from __future__ import annotations

from typing import Any

from ...errors import VideoProviderError, http_error_status


def raise_gemini_omni_error(status_code: int, payload: dict[str, Any]) -> None:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    raw_code = str(error.get("status") or error.get("code") or payload.get("status") or "")
    message = str(error.get("message") or payload.get("message") or "Gemini Omni 视频接口请求失败")
    lowered = f"{raw_code} {message}".casefold()
    if status_code in {401, 403} or any(
        token in lowered for token in ("api key not valid", "unauthenticated", "permission_denied")
    ):
        raise VideoProviderError(
            401,
            "video_provider_auth_invalid",
            "Gemini API Key 无效，或当前项目没有 Gemini Omni 权限",
            raw_code=raw_code,
            provider="gemini_omni",
        )
    if status_code == 429 and any(
        token in lowered for token in ("quota", "billing", "resource_exhausted")
    ):
        raise VideoProviderError(
            402,
            "video_provider_balance_insufficient",
            "Gemini 项目付费额度或配额不足",
            raw_code=raw_code,
            provider="gemini_omni",
        )
    if status_code == 429:
        raise VideoProviderError(
            429,
            "video_provider_rate_limited",
            "Gemini Omni 请求频率超限",
            retryable=True,
            raw_code=raw_code,
            provider="gemini_omni",
        )
    if any(
        token in lowered
        for token in ("safety", "blocked", "prohibited", "content policy", "responsible_ai")
    ):
        raise VideoProviderError(
            422,
            "video_provider_content_rejected",
            "Gemini Omni 拒绝了当前提示词或参考画面",
            raw_code=raw_code,
            provider="gemini_omni",
        )
    if status_code == 400 or "invalid_argument" in lowered:
        raise VideoProviderError(
            422,
            "video_provider_request_failed",
            f"Gemini Omni 请求参数无效：{message}",
            raw_code=raw_code,
            provider="gemini_omni",
        )
    normalized_status, code, retryable = http_error_status(status_code)
    raise VideoProviderError(
        normalized_status,
        code,
        f"Gemini Omni 视频接口请求失败：{message}",
        retryable=retryable,
        raw_code=raw_code,
        provider="gemini_omni",
    )
