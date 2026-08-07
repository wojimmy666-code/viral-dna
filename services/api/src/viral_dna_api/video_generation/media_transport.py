from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .contracts import MAX_GENERATED_VIDEO_BYTES
from .errors import VideoProviderError

MAX_PROVIDER_IMAGE_BYTES = 10 * 1024 * 1024


def image_data_url(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise VideoProviderError(
            409, "video_start_frame_missing", "已确认的起始帧文件不存在"
        ) from exc
    if not payload or len(payload) > MAX_PROVIDER_IMAGE_BYTES:
        raise VideoProviderError(
            422,
            "video_start_frame_size_invalid",
            "起始帧为空或超过远程视频模型允许的 10MB 安全限制",
        )
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise VideoProviderError(
            422, "video_start_frame_format_invalid", "起始帧必须是 JPEG、PNG 或 WebP"
        )
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


async def download_provider_video(
    url: str,
    destination: Path,
    *,
    timeout_seconds: float = 120,
) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise VideoProviderError(
            502, "video_provider_output_url_invalid", "Provider 返回了不安全的视频地址"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.download"
    size = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=30),
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not (
                    content_type.startswith("video/")
                    or content_type.startswith("application/octet-stream")
                ):
                    raise VideoProviderError(
                        502,
                        "video_provider_output_type_invalid",
                        "Provider 返回的下载内容不是视频",
                    )
                with temporary.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_GENERATED_VIDEO_BYTES:
                            raise VideoProviderError(
                                502,
                                "video_provider_output_too_large",
                                "Provider 视频超过工作区 500MB 安全限制",
                            )
                        output.write(chunk)
        if size <= 0:
            raise VideoProviderError(502, "video_provider_output_empty", "Provider 返回了空视频")
        temporary.replace(destination)
    except httpx.HTTPError as exc:
        raise VideoProviderError(
            502,
            "video_provider_download_failed",
            "无法下载 Provider 生成的视频",
            retryable=True,
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
