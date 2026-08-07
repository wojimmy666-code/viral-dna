from __future__ import annotations

from typing import Any

from ...errors import VideoProviderError, http_error_status


def raise_seedance_error(status_code: int, payload: dict[str, Any]) -> None:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    raw_code = str(error.get("code") or "")
    message = str(error.get("message") or "火山方舟视频接口请求失败")
    lowered = f"{raw_code} {message}".lower()
    if status_code in {401, 403} or any(
        token in lowered for token in ("authentication", "invalid api key", "unauthorized")
    ):
        raise VideoProviderError(
            401, "video_provider_auth_invalid", "火山方舟 API Key 无效", raw_code=raw_code
        )
    if any(token in lowered for token in ("accountoverdue", "insufficient", "balance", "quota")):
        raise VideoProviderError(
            402,
            "video_provider_balance_insufficient",
            "火山方舟账户余额或配额不足",
            raw_code=raw_code,
        )
    normalized_status, code, retryable = http_error_status(status_code)
    raise VideoProviderError(
        normalized_status,
        code,
        f"火山方舟视频接口请求失败：{message}",
        retryable=retryable,
        raw_code=raw_code,
    )
