from __future__ import annotations

from typing import Any

from ...errors import VideoProviderError, http_error_status


def raise_bailian_error(status_code: int, payload: dict[str, Any]) -> None:
    raw_code = str(payload.get("code") or payload.get("output", {}).get("code") or "")
    message = str(
        payload.get("message") or payload.get("output", {}).get("message") or "百炼视频接口请求失败"
    )
    lowered = f"{raw_code} {message}".lower()
    if "invalidapikey" in lowered or "api-key" in lowered or status_code in {401, 403}:
        raise VideoProviderError(
            401, "video_provider_auth_invalid", "百炼 API Key 无效或地域不匹配", raw_code=raw_code
        )
    if any(
        token in lowered for token in ("arrearage", "insufficient", "balance", "quotaexhausted")
    ):
        raise VideoProviderError(
            402, "video_provider_balance_insufficient", "百炼账户余额或配额不足", raw_code=raw_code
        )
    normalized_status, code, retryable = http_error_status(status_code)
    raise VideoProviderError(
        normalized_status,
        code,
        f"百炼视频接口请求失败：{message}",
        retryable=retryable,
        raw_code=raw_code,
    )
