from __future__ import annotations

from typing import Any

from ...errors import (
    VideoProviderError,
    VideoProviderFailure,
    classify_video_provider_failure,
    http_error_status,
)


def map_seedance_error(
    status_code: int,
    *,
    raw_code: str | None,
    message: str | None,
) -> tuple[int, VideoProviderFailure]:
    """Map both HTTP errors and terminal task failures from Seedance."""

    provider_code = str(raw_code or "").strip() or None
    technical_message = str(message or "火山方舟视频接口请求失败").strip()
    lowered = f"{provider_code or ''} {technical_message}".casefold()
    if (
        provider_code == "SetLimitExceeded"
        or "setlimitexceeded" in lowered
        or "safe experience mode" in lowered
        or "安心体验模式" in lowered
        or "安全体验模式" in lowered
    ):
        return 409, classify_video_provider_failure(
            provider="volc_ark",
            code="video_provider_inference_limit",
            message=technical_message,
            provider_code=provider_code,
        )
    if status_code in {401, 403} or any(
        token in lowered for token in ("authentication", "invalid api key", "unauthorized")
    ):
        return 401, classify_video_provider_failure(
            provider="volc_ark",
            code="video_provider_auth_invalid",
            message=technical_message,
            provider_code=provider_code,
        )
    if any(
        token in lowered
        for token in (
            "accountoverdue",
            "insufficient",
            "balance",
            "quotaexhausted",
            "quota exhausted",
        )
    ):
        return 402, classify_video_provider_failure(
            provider="volc_ark",
            code="video_provider_balance_insufficient",
            message=technical_message,
            provider_code=provider_code,
        )
    if status_code == 429 or any(
        token in lowered for token in ("ratelimit", "rate limit", "too many requests")
    ):
        return 429, classify_video_provider_failure(
            provider="volc_ark",
            code="video_provider_rate_limited",
            message=technical_message,
            retryable=True,
            provider_code=provider_code,
        )
    if any(
        token in lowered
        for token in ("content policy", "content moderation", "sensitive", "risk")
    ):
        return 422, classify_video_provider_failure(
            provider="volc_ark",
            code="video_provider_content_rejected",
            message=technical_message,
            provider_code=provider_code,
        )
    normalized_status, code, retryable = http_error_status(status_code)
    return normalized_status, classify_video_provider_failure(
        provider="volc_ark",
        code=code if status_code >= 400 else provider_code,
        message=technical_message,
        retryable=retryable,
        provider_code=provider_code,
    )


def raise_seedance_error(status_code: int, payload: dict[str, Any]) -> None:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    raw_code = str(error.get("code") or "")
    message = str(error.get("message") or "火山方舟视频接口请求失败")
    normalized_status, failure = map_seedance_error(
        status_code,
        raw_code=raw_code,
        message=message,
    )
    raise VideoProviderError(
        normalized_status,
        failure.code,
        failure.message,
        retryable=failure.retryable,
        raw_code=raw_code,
        provider="volc_ark",
        failure=failure,
    )
