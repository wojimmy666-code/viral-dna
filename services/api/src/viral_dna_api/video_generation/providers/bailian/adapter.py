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
from .client import BailianClient
from .error_mapper import raise_bailian_error
from .request_mapper import build_bailian_request


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise VideoProviderError(
            502, "video_provider_response_invalid", "百炼返回了无效 JSON"
        ) from exc
    return payload if isinstance(payload, dict) else {}


class BailianVideoProvider:
    provider_id = "bailian"
    adapter_version = "bailian-wan27-v1"

    async def validate_credentials(
        self,
        api_key: str,
        base_url: str,
    ) -> ProviderCredentialValidation:
        started = time.perf_counter()
        try:
            async with BailianClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.get_task("viral-dna-credential-probe")
            payload = _json(response)
            if (
                response.status_code in {401, 403}
                or str(payload.get("code", "")) == "InvalidApiKey"
            ):
                return ProviderCredentialValidation(
                    False,
                    "百炼 API Key 无效或与当前地域不匹配",
                    round((time.perf_counter() - started) * 1000),
                )
            return ProviderCredentialValidation(
                True, "百炼 API Key 校验通过", round((time.perf_counter() - started) * 1000)
            )
        except httpx.HTTPError:
            return ProviderCredentialValidation(
                False,
                "无法连接百炼服务，请检查网络与服务地址",
                round((time.perf_counter() - started) * 1000),
            )

    async def submit(
        self,
        request: ProviderVideoRequest,
        *,
        api_key: str,
        base_url: str,
    ) -> ProviderSubmitResult:
        payload = build_bailian_request(request)
        try:
            async with BailianClient(api_key, base_url) as client:
                response = await client.create_task(payload)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503, "video_provider_unavailable", "无法连接百炼视频服务", retryable=True
            ) from exc
        body = _json(response)
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        task_id = str(output.get("task_id") or "").strip()
        if response.is_error or not task_id:
            raise_bailian_error(response.status_code, body)
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
            async with BailianClient(api_key, base_url) as client:
                response = await client.get_task(task_id)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503, "video_provider_unavailable", "无法查询百炼视频任务", retryable=True
            ) from exc
        body = _json(response)
        if response.is_error:
            raise_bailian_error(response.status_code, body)
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        raw_status = str(output.get("task_status") or "UNKNOWN").upper()
        status = {
            "PENDING": VideoProviderTaskStatus.QUEUED,
            "RUNNING": VideoProviderTaskStatus.RUNNING,
            "SUCCEEDED": VideoProviderTaskStatus.SUCCEEDED,
            "FAILED": VideoProviderTaskStatus.FAILED,
            "CANCELED": VideoProviderTaskStatus.CANCELLED,
            "CANCELLED": VideoProviderTaskStatus.CANCELLED,
        }.get(raw_status, VideoProviderTaskStatus.UNKNOWN)
        return ProviderPollResult(
            status=status,
            raw=body,
            output_url=str(output.get("video_url") or "").strip() or None,
            usage=usage,
            duration_seconds=float(usage.get("output_video_duration") or usage.get("duration") or 0)
            or None,
            error_code=str(output.get("code") or "").strip() or None,
            error_message=str(output.get("message") or "").strip() or None,
            retryable=False,
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
            async with BailianClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.cancel_task(task_id)
            return response.status_code < 400 or response.status_code in {404, 409}
        except httpx.HTTPError:
            return False
