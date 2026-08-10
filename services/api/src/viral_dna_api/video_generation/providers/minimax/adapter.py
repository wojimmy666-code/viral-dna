from __future__ import annotations

import time
from typing import Any

import httpx

from ....models import VideoProviderTaskStatus
from ...contracts import (
    ProviderCredentialValidation,
    ProviderPollResult,
    ProviderSubmitResult,
    ProviderVideoRequest,
)
from ...errors import VideoProviderError
from .client import MiniMaxClient
from .error_mapper import raise_minimax_error
from .h3_request_mapper import build_minimax_h3_request
from .hailuo_request_mapper import build_minimax_hailuo_request


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise VideoProviderError(
            502, "video_provider_response_invalid", "MiniMax 返回了无效 JSON"
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _legacy_ok(payload: dict[str, Any]) -> bool:
    base = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
    return int(base.get("status_code") or 0) == 0


def _is_h3(provider_model: str | None) -> bool:
    return provider_model == "MiniMax-H3"


class MiniMaxVideoProvider:
    provider_id = "minimax"
    adapter_version = "minimax-video-v3"

    async def validate_credentials(
        self, api_key: str, base_url: str
    ) -> ProviderCredentialValidation:
        started = time.perf_counter()
        try:
            async with MiniMaxClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.list_h3_tasks(page_num=1, page_size=1)
            latency = round((time.perf_counter() - started) * 1000)
            if response.status_code == 401:
                return ProviderCredentialValidation(
                    False,
                    "MiniMax API Key 无效、类型不适用于视频接口，或与当前服务区域不匹配",
                    latency,
                    error_code="video_provider_auth_invalid",
                )
            if response.status_code == 403:
                return ProviderCredentialValidation(
                    False,
                    "MiniMax API Key 已被识别，但当前账号没有 H3 视频接口权限",
                    latency,
                    error_code="video_provider_permission_denied",
                )

            payload = _json(response)
            if response.status_code == 200 and isinstance(payload.get("items"), list):
                return ProviderCredentialValidation(True, "MiniMax API Key 校验通过", latency)

            try:
                raise_minimax_error(response.status_code, payload)
            except VideoProviderError as exc:
                if exc.code == "video_provider_balance_insufficient":
                    return ProviderCredentialValidation(
                        True,
                        "MiniMax API Key 有效，但账户余额不足",
                        latency,
                        balance_known=True,
                        balance_micros=0,
                        error_code=exc.code,
                    )
                return ProviderCredentialValidation(
                    False,
                    str(exc),
                    latency,
                    error_code=exc.code,
                    retryable=exc.retryable,
                )
        except VideoProviderError as exc:
            return ProviderCredentialValidation(
                False,
                str(exc),
                round((time.perf_counter() - started) * 1000),
                error_code=exc.code,
                retryable=exc.retryable,
            )
        except httpx.HTTPError:
            return ProviderCredentialValidation(
                False,
                "无法连接 MiniMax 服务，请稍后重试并检查服务区域",
                round((time.perf_counter() - started) * 1000),
                error_code="video_provider_unavailable",
                retryable=True,
            )

    async def submit(
        self,
        request: ProviderVideoRequest,
        *,
        api_key: str,
        base_url: str,
    ) -> ProviderSubmitResult:
        h3 = _is_h3(request.provider_model)
        payload = build_minimax_h3_request(request) if h3 else build_minimax_hailuo_request(request)
        try:
            async with MiniMaxClient(api_key, base_url) as client:
                response = (
                    await client.create_h3_task(payload)
                    if h3
                    else await client.create_legacy_task(payload)
                )
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503,
                "video_provider_unavailable",
                "无法连接 MiniMax 视频服务",
                retryable=True,
            ) from exc
        body = _json(response)
        task_id = str(body.get("task_id") or "").strip()
        if response.is_error or (not h3 and not _legacy_ok(body)) or not task_id:
            raise_minimax_error(response.status_code, body)
        return ProviderSubmitResult(task_id=task_id, raw=body)

    async def poll(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> ProviderPollResult:
        try:
            async with MiniMaxClient(api_key, base_url) as client:
                if _is_h3(provider_model):
                    response = await client.get_h3_task(task_id)
                    body = _json(response)
                    if response.is_error:
                        raise_minimax_error(response.status_code, body)
                    return self._h3_poll_result(body)
                response = await client.get_legacy_task(task_id)
                body = _json(response)
                if response.is_error or not _legacy_ok(body):
                    raise_minimax_error(response.status_code, body)
                return await self._legacy_poll_result(body, client)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503,
                "video_provider_unavailable",
                "无法查询 MiniMax 视频任务",
                retryable=True,
            ) from exc

    @staticmethod
    def _h3_poll_result(body: dict[str, Any]) -> ProviderPollResult:
        task = body.get("task") if isinstance(body.get("task"), dict) else {}
        raw_status = str(task.get("status") or "").lower()
        content = task.get("content") if isinstance(task.get("content"), dict) else {}
        usage = task.get("usage") if isinstance(task.get("usage"), dict) else {}
        error = task.get("error") if isinstance(task.get("error"), dict) else {}
        status = {
            "queued": VideoProviderTaskStatus.QUEUED,
            "running": VideoProviderTaskStatus.RUNNING,
            "succeeded": VideoProviderTaskStatus.SUCCEEDED,
            "failed": VideoProviderTaskStatus.FAILED,
            "cancelled": VideoProviderTaskStatus.CANCELLED,
        }.get(raw_status, VideoProviderTaskStatus.UNKNOWN)
        return ProviderPollResult(
            status=status,
            raw=body,
            output_url=str(content.get("url") or "").strip() or None,
            usage=usage,
            duration_seconds=float(task.get("duration") or 0) or None,
            error_code=str(error.get("type") or "").strip() or None,
            error_message=str(error.get("message") or "").strip() or None,
        )

    @staticmethod
    async def _legacy_poll_result(
        body: dict[str, Any], client: MiniMaxClient
    ) -> ProviderPollResult:
        raw_status = str(body.get("status") or "").lower()
        output_url: str | None = None
        if raw_status == "success" and body.get("file_id"):
            file_response = await client.retrieve_file(str(body["file_id"]))
            file_body = _json(file_response)
            if file_response.is_error or not _legacy_ok(file_body):
                raise_minimax_error(file_response.status_code, file_body)
            file_info = file_body.get("file") if isinstance(file_body.get("file"), dict) else {}
            output_url = str(file_info.get("download_url") or "").strip() or None
        status = {
            "preparing": VideoProviderTaskStatus.QUEUED,
            "queueing": VideoProviderTaskStatus.QUEUED,
            "processing": VideoProviderTaskStatus.RUNNING,
            "success": VideoProviderTaskStatus.SUCCEEDED,
            "fail": VideoProviderTaskStatus.FAILED,
        }.get(raw_status, VideoProviderTaskStatus.UNKNOWN)
        return ProviderPollResult(
            status=status,
            raw=body,
            output_url=output_url,
            usage=body.get("usage") if isinstance(body.get("usage"), dict) else {},
            width=int(body.get("video_width") or 0) or None,
            height=int(body.get("video_height") or 0) or None,
            error_code=str(body.get("base_resp", {}).get("status_code") or "").strip() or None,
            error_message=str(body.get("error_message") or "").strip() or None,
        )

    async def cancel(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> bool:
        if not _is_h3(provider_model):
            return False
        try:
            async with MiniMaxClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.cancel_h3_task(task_id)
            return response.status_code < 400
        except httpx.HTTPError:
            return False
