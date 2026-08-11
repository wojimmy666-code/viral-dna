from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from ...models import ModelUsage
from ...runtime_config import get_config_value
from ..contracts import (
    ModelProviderError,
    ModelProviderUnavailable,
    ModelRequest,
    ProviderResult,
    ResultT,
)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class CredentialValidationResult:
    requested_model: str
    resolved_model: str
    provider_request_id: str | None
    latency_ms: int
    usage: ModelUsage


def _safe_message(value: object) -> str:
    message = " ".join(str(value or "").replace("\x00", "").split())
    message = re.sub(
        r"(?i)(api[_ -]?key|token|authorization)(\s*[:=]\s*)\S+",
        r"\1\2[REDACTED]",
        message,
    )
    return message[:500] or "模型服务返回未知错误"


def _json_content(value: object) -> str:
    if isinstance(value, str):
        content = value.strip()
    elif isinstance(value, list):
        content = "".join(
            str(item.get("text") or "")
            for item in value
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    else:
        content = ""
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    return content.strip()


async def _data_url(path: Path) -> str:
    payload = await asyncio.to_thread(path.read_bytes)
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _usage_from_payload(
    payload: object,
    image_count: int,
    video_seconds: float = 0.0,
) -> ModelUsage:
    def non_negative_int(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    usage_payload = payload.get("usage") if isinstance(payload, dict) else {}
    usage_payload = usage_payload if isinstance(usage_payload, dict) else {}
    prompt_details = usage_payload.get("prompt_tokens_details") or {}
    completion_details = usage_payload.get("completion_tokens_details") or {}
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    input_tokens = non_negative_int(usage_payload.get("prompt_tokens"))
    output_tokens = non_negative_int(usage_payload.get("completion_tokens"))
    return ModelUsage(
        input_tokens=input_tokens,
        cached_input_tokens=non_negative_int(prompt_details.get("cached_tokens")),
        output_tokens=output_tokens,
        reasoning_tokens=non_negative_int(completion_details.get("reasoning_tokens")),
        total_tokens=(
            non_negative_int(usage_payload.get("total_tokens")) or input_tokens + output_tokens
        ),
        image_count=image_count,
        video_seconds=max(0.0, video_seconds),
    )


class DashScopeProvider:
    provider_id = "dashscope"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else get_config_value("DASHSCOPE_API_KEY", "")
        self.base_url = (
            base_url
            if base_url is not None
            else get_config_value("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            get_config_value("VIRAL_DNA_MODEL_TIMEOUT_SECONDS", "90")
        )

    async def _request_json(
        self,
        payload: dict[str, Any],
        *,
        image_count: int = 0,
        video_seconds: float = 0.0,
    ) -> tuple[dict[str, Any], int, str | None, ModelUsage]:
        if not self.api_key.strip():
            raise ModelProviderUnavailable("未配置百炼 API Key")

        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "model_timeout",
                "百炼模型请求超时",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "model_transport_error",
                _safe_message(exc),
                retryable=True,
            ) from exc

        latency_ms = max(0, round((perf_counter() - started_at) * 1000))
        header_request_id = response.headers.get("x-request-id")
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                "model_response_invalid",
                "百炼模型返回了非 JSON 响应",
                retryable=response.status_code in RETRYABLE_STATUS_CODES,
                provider_request_id=header_request_id,
                status_code=response.status_code,
                latency_ms=latency_ms,
            ) from exc
        if not isinstance(response_payload, dict):
            raise ModelProviderError(
                "model_response_invalid",
                "百炼模型返回的 JSON 结构无效",
                retryable=False,
                provider_request_id=header_request_id,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

        usage = _usage_from_payload(response_payload, image_count, video_seconds)
        resolved_model = str(response_payload.get("model") or payload.get("model") or "")
        request_id = str(response_payload.get("id") or header_request_id or "").strip() or None
        if response.status_code >= 400:
            error = response_payload.get("error")
            raw_message = error.get("message") if isinstance(error, dict) else response_payload
            raise ModelProviderError(
                "model_http_error",
                _safe_message(raw_message),
                retryable=response.status_code in RETRYABLE_STATUS_CODES,
                provider_request_id=request_id,
                status_code=response.status_code,
                usage=usage if usage.total_tokens else None,
                resolved_model=resolved_model or None,
                latency_ms=latency_ms,
            )
        return response_payload, latency_ms, request_id, usage

    async def validate_credentials(self, model: str) -> CredentialValidationResult:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "只回复 OK，用于验证模型连接。"}],
            "enable_thinking": False,
            "temperature": 0,
            "max_tokens": 1,
        }
        response_payload, latency_ms, request_id, usage = await self._request_json(payload)
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelProviderError(
                "model_validation_invalid",
                "API Key 已连接，但模型没有返回有效响应",
                retryable=False,
                provider_request_id=request_id,
                latency_ms=latency_ms,
                usage=usage if usage.total_tokens else None,
                resolved_model=str(response_payload.get("model") or model),
            )
        return CredentialValidationResult(
            requested_model=model,
            resolved_model=str(response_payload.get("model") or model),
            provider_request_id=request_id,
            latency_ms=latency_ms,
            usage=usage,
        )

    async def generate(
        self,
        request: ModelRequest,
        response_schema: type[ResultT],
    ) -> ProviderResult[ResultT]:
        image_urls: tuple[str, ...] | list[str] = ()
        video_seconds = 0.0
        if request.video_path is not None:
            video_url = await _data_url(request.video_path)
            user_content: list[dict[str, Any]] = [
                {
                    "type": "video_url",
                    "video_url": {"url": video_url},
                    "fps": min(10.0, max(0.1, request.video_fps)),
                },
                {"type": "text", "text": request.user_prompt},
            ]
            video_seconds = max(0.0, request.video_duration_seconds)
        else:
            image_urls = await asyncio.gather(*(_data_url(path) for path in request.image_paths))
            user_content = [{"type": "text", "text": request.user_prompt}]
            if request.image_labels and len(request.image_labels) == len(image_urls):
                for label, image_url in zip(request.image_labels, image_urls, strict=True):
                    user_content.append({"type": "text", "text": label})
                    user_content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                user_content.extend(
                    {"type": "image_url", "image_url": {"url": image_url}}
                    for image_url in image_urls
                )
        payload = {
            "model": request.target.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": request.target.thinking,
            "temperature": 0.1,
        }
        response_payload, latency_ms, request_id, usage = await self._request_json(
            payload,
            image_count=0 if request.video_path is not None else len(request.image_paths),
            video_seconds=video_seconds,
        )
        resolved_model = str(response_payload.get("model") or request.target.model)
        content = ""
        try:
            choice = response_payload["choices"][0]
            content = _json_content(choice["message"]["content"])
            parsed = json.loads(content)
            data = response_schema.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ModelProviderError(
                "model_schema_invalid",
                _safe_message(exc),
                retryable=True,
                provider_request_id=request_id,
                usage=usage if usage.total_tokens else None,
                resolved_model=resolved_model,
                latency_ms=latency_ms,
                raw_content=content or None,
            ) from exc

        return ProviderResult(
            data=data,
            usage=usage,
            requested_model=request.target.model,
            resolved_model=resolved_model,
            provider_request_id=request_id,
            latency_ms=latency_ms,
            raw_content=content,
        )
