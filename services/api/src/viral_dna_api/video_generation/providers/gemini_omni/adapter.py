from __future__ import annotations

import base64
import binascii
import time
from typing import Any

import httpx

from ....models import VideoProviderTaskStatus
from ...contracts import (
    MAX_GENERATED_VIDEO_BYTES,
    ProviderCredentialValidation,
    ProviderPollResult,
    ProviderSubmitResult,
    ProviderVideoRequest,
)
from ...errors import VideoProviderError
from .client import GeminiOmniClient
from .error_mapper import raise_gemini_omni_error
from .request_mapper import build_gemini_omni_request


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise VideoProviderError(
            502,
            "video_provider_response_invalid",
            "Gemini Omni 返回了无效 JSON",
            provider="gemini_omni",
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _video_content(payload: dict[str, Any]) -> dict[str, Any] | None:
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for content in step.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "video":
                return content
    output = payload.get("output_video")
    return output if isinstance(output, dict) else None


def _safe_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    video = _video_content(payload)
    snapshot: dict[str, Any] = {
        key: payload[key]
        for key in ("id", "object", "model", "status", "created", "updated", "usage")
        if key in payload
    }
    if isinstance(payload.get("error"), dict):
        snapshot["error"] = payload["error"]
    if video:
        encoded = str(video.get("data") or "")
        snapshot["video_output"] = {
            "mime_type": video.get("mime_type"),
            "delivery": "inline" if encoded else "uri" if video.get("uri") else "unknown",
            "encoded_bytes": len(encoded),
        }
    return snapshot


def _decode_video(encoded: str) -> bytes:
    compact = "".join(encoded.split())
    if not compact or len(compact) > ((MAX_GENERATED_VIDEO_BYTES + 2) // 3) * 4 + 16:
        raise VideoProviderError(
            502,
            "video_provider_output_too_large",
            "Gemini Omni 返回的视频为空或超过 500MB 安全限制",
            provider="gemini_omni",
        )
    try:
        output = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VideoProviderError(
            502,
            "video_provider_response_invalid",
            "Gemini Omni 返回的视频数据无法解码",
            provider="gemini_omni",
        ) from exc
    if not output or len(output) > MAX_GENERATED_VIDEO_BYTES:
        raise VideoProviderError(
            502,
            "video_provider_output_too_large",
            "Gemini Omni 返回的视频为空或超过 500MB 安全限制",
            provider="gemini_omni",
        )
    return output


class GeminiOmniVideoProvider:
    provider_id = "gemini_omni"
    adapter_version = "gemini-omni-interactions-v1"
    provider_model = "gemini-omni-1.1-flash"

    async def validate_credentials(
        self,
        api_key: str,
        base_url: str,
    ) -> ProviderCredentialValidation:
        started = time.perf_counter()
        try:
            async with GeminiOmniClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.get_model(self.provider_model)
            latency = round((time.perf_counter() - started) * 1000)
            body = _json(response)
            if response.is_error:
                try:
                    raise_gemini_omni_error(response.status_code, body)
                except VideoProviderError as exc:
                    return ProviderCredentialValidation(
                        False,
                        str(exc),
                        latency,
                        error_code=exc.code,
                        retryable=exc.retryable,
                    )
            if str(body.get("name") or body.get("id") or "").endswith(self.provider_model):
                return ProviderCredentialValidation(True, "Gemini Omni API Key 校验通过", latency)
            return ProviderCredentialValidation(
                False,
                "该地址未返回 Gemini Omni 模型信息，请确认中转服务兼容 Gemini Interactions API",
                latency,
                error_code="video_provider_response_invalid",
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
                "无法连接 Gemini Omni 服务，请检查网络、官方地址或兼容中转地址",
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
        payload = build_gemini_omni_request(request)
        try:
            async with GeminiOmniClient(api_key, base_url) as client:
                response = await client.create_interaction(payload)
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503,
                "video_provider_unavailable",
                "无法连接 Gemini Omni 视频服务",
                retryable=True,
                provider="gemini_omni",
            ) from exc
        body = _json(response)
        task_id = str(body.get("id") or "").strip()
        if response.is_error or not task_id:
            raise_gemini_omni_error(response.status_code, body)
        return ProviderSubmitResult(task_id=task_id, raw=_safe_snapshot(body))

    async def poll(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> ProviderPollResult:
        try:
            async with GeminiOmniClient(api_key, base_url) as client:
                response = await client.get_interaction(task_id)
                body = _json(response)
                if response.is_error:
                    raise_gemini_omni_error(response.status_code, body)
                raw_status = str(body.get("status") or "").lower()
                status = {
                    "queued": VideoProviderTaskStatus.QUEUED,
                    "in_progress": VideoProviderTaskStatus.RUNNING,
                    "completed": VideoProviderTaskStatus.SUCCEEDED,
                    "failed": VideoProviderTaskStatus.FAILED,
                    "cancelled": VideoProviderTaskStatus.CANCELLED,
                    "incomplete": VideoProviderTaskStatus.FAILED,
                    "budget_exceeded": VideoProviderTaskStatus.FAILED,
                    "requires_action": VideoProviderTaskStatus.FAILED,
                }.get(raw_status, VideoProviderTaskStatus.UNKNOWN)
                output_bytes: bytes | None = None
                output_url: str | None = None
                video = _video_content(body)
                if status == VideoProviderTaskStatus.SUCCEEDED and video:
                    encoded = str(video.get("data") or "").strip()
                    output_url = str(video.get("uri") or "").strip() or None
                    if encoded:
                        output_bytes = _decode_video(encoded)
                        output_url = None
                    elif output_url:
                        download = await client.download_generated_video(output_url)
                        if download.is_error:
                            download_body = _json(download)
                            raise_gemini_omni_error(download.status_code, download_body)
                        output_bytes = download.content
                        output_url = None
                        if not output_bytes or len(output_bytes) > MAX_GENERATED_VIDEO_BYTES:
                            raise VideoProviderError(
                                502,
                                "video_provider_output_too_large",
                                "Gemini Omni 返回的视频为空或超过 500MB 安全限制",
                                provider="gemini_omni",
                            )
                if status == VideoProviderTaskStatus.SUCCEEDED and not (
                    output_bytes or output_url
                ):
                    status = VideoProviderTaskStatus.FAILED
                error = body.get("error") if isinstance(body.get("error"), dict) else {}
                return ProviderPollResult(
                    status=status,
                    raw=_safe_snapshot(body),
                    output_url=output_url,
                    output_bytes=output_bytes,
                    usage=body.get("usage") if isinstance(body.get("usage"), dict) else {},
                    error_code=str(error.get("status") or raw_status).strip() or None,
                    error_message=(
                        str(error.get("message") or "").strip()
                        or (
                            "Gemini Omni 已完成任务，但没有返回视频数据"
                            if (
                                status == VideoProviderTaskStatus.FAILED
                                and raw_status == "completed"
                            )
                            else None
                        )
                    ),
                    retryable=False,
                )
        except VideoProviderError:
            raise
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                503,
                "video_provider_unavailable",
                "无法查询 Gemini Omni 视频任务",
                retryable=True,
                provider="gemini_omni",
            ) from exc

    async def cancel(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> bool:
        try:
            async with GeminiOmniClient(api_key, base_url, timeout_seconds=30) as client:
                response = await client.cancel_interaction(task_id)
            return response.status_code < 400 or response.status_code in {404, 409}
        except httpx.HTTPError:
            return False
