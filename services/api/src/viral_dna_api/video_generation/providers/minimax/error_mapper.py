from __future__ import annotations

from typing import Any

from ...errors import VideoProviderError, http_error_status


def raise_minimax_error(status_code: int, payload: dict[str, Any]) -> None:
    base = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    raw_code = str(
        base.get("status_code")
        or payload.get("status_code")
        or error.get("http_code")
        or error.get("type")
        or ""
    )
    message = str(
        base.get("status_msg")
        or payload.get("error_message")
        or error.get("message")
        or "MiniMax 视频接口请求失败"
    )
    lowered = f"{raw_code} {message}".lower()
    if status_code == 402 or "1008" in lowered or "insufficient_balance" in lowered:
        raise VideoProviderError(
            402, "video_provider_balance_insufficient", "MiniMax 账户余额不足", raw_code=raw_code
        )
    if raw_code in {"1004", "2049"} or status_code in {401, 403} or "authorized_error" in lowered:
        raise VideoProviderError(
            401, "video_provider_auth_invalid", "MiniMax API Key 无效", raw_code=raw_code
        )
    if raw_code == "1002" or status_code == 429 or "rate_limit_error" in lowered:
        raise VideoProviderError(
            429,
            "video_provider_rate_limited",
            "MiniMax 请求频率超限",
            retryable=True,
            raw_code=raw_code,
        )
    normalized_status, code, retryable = http_error_status(status_code)
    raise VideoProviderError(
        normalized_status,
        code,
        f"MiniMax 视频接口请求失败：{message}",
        retryable=retryable,
        raw_code=raw_code,
    )
