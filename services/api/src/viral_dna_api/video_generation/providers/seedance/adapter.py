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
from .client import SeedanceClient
from .error_mapper import map_seedance_error, raise_seedance_error
from .request_mapper import build_seedance_request


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise VideoProviderError(
            502, "video_provider_response_invalid", "火山方舟返回了无效 JSON"
        ) from exc
    return payload if isinstance(payload, dict) else {}


class SeedanceVideoProvider:
    provider_id = "volc_ark"
    adapter_version = "seedance-content-task-v2"

    async def validate_credentials(
        self, api_key: str, base_url: str
    ) -> ProviderCredentialValidation:
        started = time.perf_counter()
        try:
            async with SeedanceClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.list_tasks()
            payload = _json(response)
            if response.status_code in {401, 403}:
                return ProviderCredentialValidation(
                    False, "火山方舟 API Key 无效", round((time.perf_counter() - started) * 1000)
                )
            if response.is_error and response.status_code not in {400, 404, 405}:
                try:
                    raise_seedance_error(response.status_code, payload)
                except VideoProviderError as exc:
                    return ProviderCredentialValidation(
                        False, str(exc), round((time.perf_counter() - started) * 1000)
                    )
            return ProviderCredentialValidation(
                True, "火山方舟 API Key 校验通过", round((time.perf_counter() - started) * 1000)
            )
        except httpx.HTTPError:
            return ProviderCredentialValidation(
                False, "无法连接火山方舟服务", round((time.perf_counter() - started) * 1000)
            )

    async def submit(
        self,
        request: ProviderVideoRequest,
        *,
        api_key: str,
        base_url: str,
    ) -> ProviderSubmitResult:
        payload = build_seedance_request(request)
        try:
            async with SeedanceClient(api_key, base_url) as client:
                response = await client.create_task(payload)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503, "video_provider_unavailable", "无法连接火山方舟视频服务", retryable=True
            ) from exc
        body = _json(response)
        task_id = str(body.get("id") or body.get("task_id") or "").strip()
        if response.is_error or not task_id:
            raise_seedance_error(response.status_code, body)
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
            async with SeedanceClient(api_key, base_url) as client:
                response = await client.get_task(task_id)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503, "video_provider_unavailable", "无法查询火山方舟视频任务", retryable=True
            ) from exc
        body = _json(response)
        if response.is_error:
            raise_seedance_error(response.status_code, body)
        raw_status = str(body.get("status") or "unknown").lower()
        status = {
            "pending": VideoProviderTaskStatus.QUEUED,
            "queued": VideoProviderTaskStatus.QUEUED,
            "running": VideoProviderTaskStatus.RUNNING,
            "processing": VideoProviderTaskStatus.RUNNING,
            "succeeded": VideoProviderTaskStatus.SUCCEEDED,
            "success": VideoProviderTaskStatus.SUCCEEDED,
            "failed": VideoProviderTaskStatus.FAILED,
            "cancelled": VideoProviderTaskStatus.CANCELLED,
            "canceled": VideoProviderTaskStatus.CANCELLED,
        }.get(raw_status, VideoProviderTaskStatus.UNKNOWN)
        content = body.get("content") if isinstance(body.get("content"), dict) else {}
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        video_url = content.get("video_url") or output.get("video_url") or body.get("video_url")
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raw_error_code = str(error.get("code") or "").strip() or None
        raw_error_message = str(error.get("message") or "").strip() or None
        failure = None
        if status == VideoProviderTaskStatus.FAILED:
            _, failure = map_seedance_error(
                response.status_code,
                raw_code=raw_error_code,
                message=raw_error_message,
            )
        return ProviderPollResult(
            status=status,
            raw=body,
            output_url=str(video_url or "").strip() or None,
            usage=usage,
            width=int(output.get("width") or 0) or None,
            height=int(output.get("height") or 0) or None,
            duration_seconds=float(output.get("duration") or 0) or None,
            error_code=failure.code if failure else raw_error_code,
            error_message=failure.message if failure else raw_error_message,
            retryable=failure.retryable if failure else False,
            provider_error_code=failure.provider_code if failure else raw_error_code,
            error_category=failure.category if failure else None,
            error_title=failure.title if failure else None,
            error_technical_message=failure.technical_message if failure else None,
            error_action=failure.suggested_action if failure else None,
        )

    async def cancel(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> bool:
        try:
            async with SeedanceClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.cancel_task(task_id)
            return response.status_code < 400 or response.status_code in {404, 409}
        except httpx.HTTPError:
            return False
