from __future__ import annotations

from .contracts import VideoGenerationError


class VideoProviderError(VideoGenerationError):
    """Normalized error raised by a concrete remote video provider."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        raw_code: str | int | None = None,
    ) -> None:
        super().__init__(status_code, code, message, retryable=retryable)
        self.raw_code = str(raw_code) if raw_code is not None else None


def http_error_status(status_code: int) -> tuple[int, str, bool]:
    if status_code in {401, 403}:
        return 401, "video_provider_auth_invalid", False
    if status_code == 402:
        return 402, "video_provider_balance_insufficient", False
    if status_code == 429:
        return 429, "video_provider_rate_limited", True
    if status_code >= 500:
        return 503, "video_provider_unavailable", True
    return 502, "video_provider_request_failed", False
