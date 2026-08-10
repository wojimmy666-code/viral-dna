from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError
from yt_dlp.version import __version__ as yt_dlp_version

from .media import MAX_VIDEO_SECONDS, get_storage_root
from .models import SourceType, Video

COLLECTOR_VERSION = "yt-dlp-link-v1"
DEFAULT_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
SUPPORTED_MEDIA_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".flv"}
PLATFORM_DOMAINS = {
    "douyin.com": SourceType.DOUYIN,
    "iesdouyin.com": SourceType.DOUYIN,
    "xiaohongshu.com": SourceType.XIAOHONGSHU,
    "xhslink.com": SourceType.XIAOHONGSHU,
    "rednote.com": SourceType.XIAOHONGSHU,
}


class LinkIngestionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LinkCredentialError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class LinkCredentialSession:
    configured: bool
    strategy: str
    source_label: str
    cookie_file: Path | None = None
    cookies_from_browser: tuple[str, str, None, None] | None = None


class LinkCredentialResolver(Protocol):
    def session_for(
        self,
        platform: SourceType,
    ) -> AbstractAsyncContextManager[LinkCredentialSession]: ...

    async def report_success(self, platform: SourceType) -> None: ...

    async def report_failure(self, platform: SourceType, code: str, message: str) -> None: ...


@dataclass(frozen=True, slots=True)
class LinkIngestionResult:
    path: Path
    platform: SourceType
    resolved_url: str
    source_video_id: str | None
    title: str | None
    author: str | None
    duration_seconds: float | None
    file_size_bytes: int


class _YtDlpLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        self.messages.append(message)

    def error(self, message: str) -> None:
        self.messages.append(message)


def identify_platform(url: str) -> SourceType:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LinkIngestionError(
            "link_invalid",
            "只支持有效的 HTTP/HTTPS 视频链接",
        )
    if parsed.username or parsed.password:
        raise LinkIngestionError(
            "link_credentials_forbidden",
            "视频链接不能包含用户名或密码",
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise LinkIngestionError("link_invalid_port", "视频链接端口无效") from exc
    if port not in {None, 80, 443}:
        raise LinkIngestionError(
            "link_port_forbidden",
            "视频链接只能使用标准 HTTP/HTTPS 端口",
        )

    hostname = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise LinkIngestionError(
            "link_ip_forbidden",
            "不允许使用 IP 地址作为视频来源",
        )

    for domain, platform in PLATFORM_DOMAINS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return platform
    raise LinkIngestionError(
        "link_platform_unsupported",
        "当前只支持抖音和小红书公开链接",
    )


def normalize_platform_url(url: str) -> str:
    identify_platform(url)
    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    include_port = port is not None and not (
        (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)
    )
    netloc = f"{hostname}:{port}" if include_port else hostname
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def get_link_storage_root(video_id: UUID, record_id: UUID | None = None) -> Path:
    if record_id is not None:
        return get_storage_root() / "records" / str(record_id) / "source"
    return get_storage_root() / "links" / str(video_id)


class LinkCollector:
    def __init__(self, credential_resolver: LinkCredentialResolver | None = None) -> None:
        self.credential_resolver = credential_resolver
        self.max_download_bytes = _positive_int(
            "VIRAL_DNA_LINK_MAX_BYTES",
            DEFAULT_MAX_DOWNLOAD_BYTES,
        )
        self.socket_timeout = _positive_float("VIRAL_DNA_LINK_SOCKET_TIMEOUT", 20.0)
        self.retries = _non_negative_int("VIRAL_DNA_LINK_RETRIES", 2)

    async def collect(self, video: Video) -> LinkIngestionResult:
        if video.source_type == SourceType.UPLOAD or not video.source_url:
            raise LinkIngestionError(
                "link_source_missing",
                "该视频记录没有可采集的平台链接",
            )

        source_url = normalize_platform_url(video.source_url)
        expected_platform = identify_platform(source_url)
        if expected_platform != video.source_type:
            raise LinkIngestionError(
                "link_platform_mismatch",
                "链接平台与视频记录不一致",
            )

        target_dir = get_link_storage_root(video.id, video.record_id)
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self._remove_partial_files, target_dir)

        if self.credential_resolver is None:
            info = await self._attempt_download(source_url, target_dir, None)
        else:
            try:
                async with self.credential_resolver.session_for(expected_platform) as session:
                    info = await self._download_with_credentials(
                        source_url,
                        target_dir,
                        expected_platform,
                        session,
                    )
            except LinkCredentialError as exc:
                await self._report_failure(expected_platform, exc.code, str(exc))
                raise LinkIngestionError(exc.code, str(exc), retryable=exc.retryable) from exc

        resolved_url = str(info.get("webpage_url") or info.get("original_url") or source_url)
        try:
            resolved_platform = identify_platform(resolved_url)
        except LinkIngestionError as exc:
            raise LinkIngestionError(
                "link_redirect_blocked",
                "平台链接跳转到了不受支持的站点，已停止采集",
            ) from exc
        if resolved_platform != expected_platform:
            raise LinkIngestionError(
                "link_redirect_blocked",
                "平台链接跳转到了其他平台，已停止采集",
            )

        media_path = self._locate_downloaded_media(target_dir, info)
        file_size = media_path.stat().st_size
        if file_size <= 0:
            raise LinkIngestionError("link_download_empty", "平台返回了空视频文件", retryable=True)
        if file_size > self.max_download_bytes:
            media_path.unlink(missing_ok=True)
            raise LinkIngestionError(
                "link_size_exceeded",
                f"链接视频不能超过 {self.max_download_bytes // 1024 // 1024} MB",
            )

        duration = _optional_float(info.get("duration"))
        if duration is not None and duration > MAX_VIDEO_SECONDS:
            media_path.unlink(missing_ok=True)
            raise LinkIngestionError(
                "link_duration_exceeded",
                f"当前只支持 {MAX_VIDEO_SECONDS // 60} 分钟以内的视频",
            )

        result = LinkIngestionResult(
            path=media_path,
            platform=expected_platform,
            resolved_url=normalize_platform_url(resolved_url),
            source_video_id=_optional_text(info.get("id")),
            title=_optional_text(info.get("title")),
            author=_first_text(
                info.get("uploader"),
                info.get("creator"),
                info.get("channel"),
                info.get("uploader_id"),
            ),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )
        await asyncio.to_thread(self._write_manifest, target_dir, result)
        return result

    def _download_sync(
        self,
        source_url: str,
        target_dir: Path,
        logger: _YtDlpLogger,
        credential_session: LinkCredentialSession | None = None,
    ) -> dict[str, Any]:
        def duration_filter(info: dict[str, Any], incomplete: bool = False) -> str | None:
            if incomplete:
                return None
            duration = _optional_float(info.get("duration"))
            if duration is not None and duration > MAX_VIDEO_SECONDS:
                return "link_duration_exceeded"
            return None

        options: dict[str, Any] = {
            "outtmpl": str(target_dir / "original.%(ext)s"),
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "playlist_items": "1",
            "max_filesize": self.max_download_bytes,
            "socket_timeout": self.socket_timeout,
            "retries": self.retries,
            "fragment_retries": self.retries,
            "extractor_retries": self.retries,
            "continuedl": True,
            "overwrites": False,
            "quiet": True,
            "no_warnings": True,
            "logger": logger,
            "match_filter": duration_filter,
            "cachedir": str(get_storage_root() / "temp" / "yt-dlp-cache"),
        }
        cookie_path = credential_session.cookie_file if credential_session else None
        if cookie_path is not None:
            cookie_path = cookie_path.expanduser().resolve()
            if not cookie_path.is_file():
                raise LinkIngestionError(
                    "link_cookie_file_missing",
                    "本机平台 Cookie 临时文件不存在，请重新配置",
                )
            options["cookiefile"] = str(cookie_path)
        elif credential_session and credential_session.cookies_from_browser is not None:
            options["cookiesfrombrowser"] = credential_session.cookies_from_browser
        elif self.credential_resolver is None:
            cookie_file = os.getenv("VIRAL_DNA_YTDLP_COOKIE_FILE", "").strip()
            if cookie_file:
                legacy_cookie_path = Path(cookie_file).expanduser().resolve()
                if not legacy_cookie_path.is_file():
                    raise LinkIngestionError(
                        "link_cookie_file_missing",
                        "配置的 yt-dlp Cookie 文件不存在",
                    )
                options["cookiefile"] = str(legacy_cookie_path)

        proxy = os.getenv("VIRAL_DNA_YTDLP_PROXY", "").strip()
        if proxy:
            options["proxy"] = proxy

        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source_url, download=True)
        if not isinstance(info, dict):
            raise LinkIngestionError(
                "link_metadata_missing",
                "平台没有返回可用的视频信息",
                retryable=True,
            )
        return info

    async def _download_with_credentials(
        self,
        source_url: str,
        target_dir: Path,
        platform: SourceType,
        session: LinkCredentialSession,
    ) -> dict[str, Any]:
        use_initially = session.configured and session.strategy == "always"
        try:
            info = await self._attempt_download(
                source_url,
                target_dir,
                session if use_initially else None,
            )
        except LinkIngestionError as first_error:
            should_retry = (
                first_error.code == "link_auth_required"
                and session.configured
                and session.strategy == "on_auth_required"
            )
            if not should_retry:
                if use_initially or first_error.code == "link_auth_required":
                    await self._report_failure(platform, first_error.code, str(first_error))
                raise
            await asyncio.to_thread(self._remove_partial_files, target_dir)
            try:
                info = await self._attempt_download(source_url, target_dir, session)
            except LinkIngestionError as credential_error:
                await self._report_failure(platform, credential_error.code, str(credential_error))
                raise
            await self._report_success(platform)
            return info
        if use_initially:
            await self._report_success(platform)
        return info

    async def _attempt_download(
        self,
        source_url: str,
        target_dir: Path,
        credential_session: LinkCredentialSession | None,
    ) -> dict[str, Any]:
        logger = _YtDlpLogger()
        try:
            if credential_session is None:
                return await asyncio.to_thread(
                    self._download_sync,
                    source_url,
                    target_dir,
                    logger,
                )
            return await asyncio.to_thread(
                self._download_sync,
                source_url,
                target_dir,
                logger,
                credential_session,
            )
        except LinkIngestionError:
            raise
        except YoutubeDLError as exc:
            raise self._translate_download_error(exc, logger) from exc
        except OSError as exc:
            raise LinkIngestionError(
                "link_storage_failed",
                "链接视频无法写入本地存储",
                retryable=True,
            ) from exc

    async def _report_success(self, platform: SourceType) -> None:
        if self.credential_resolver is None:
            return
        try:
            await self.credential_resolver.report_success(platform)
        except Exception:
            return

    async def _report_failure(self, platform: SourceType, code: str, message: str) -> None:
        if self.credential_resolver is None:
            return
        try:
            await self.credential_resolver.report_failure(platform, code, message)
        except Exception:
            return

    def _locate_downloaded_media(self, target_dir: Path, info: dict[str, Any]) -> Path:
        candidates: list[Path] = []
        for key in ("filepath", "_filename"):
            value = info.get(key)
            if isinstance(value, str):
                candidates.append(Path(value))
        requested_downloads = info.get("requested_downloads")
        if isinstance(requested_downloads, list):
            for item in requested_downloads:
                if isinstance(item, dict) and isinstance(item.get("filepath"), str):
                    candidates.append(Path(item["filepath"]))
        candidates.extend([*target_dir.glob("original.*"), *target_dir.glob("source.*")])

        target_root = target_dir.resolve()
        valid: list[Path] = []
        for candidate in candidates:
            resolved = candidate.resolve()
            try:
                resolved.relative_to(target_root)
            except ValueError:
                continue
            if resolved.is_file() and resolved.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES:
                valid.append(resolved)
        if not valid:
            raise LinkIngestionError(
                "link_download_missing",
                "平台没有生成可分析的视频文件",
                retryable=True,
            )
        unique = {path: None for path in valid}
        return max(
            unique,
            key=lambda path: (
                path.stem in {"original", "source"},
                path.stat().st_size,
                path.stat().st_mtime_ns,
            ),
        )

    def _translate_download_error(
        self,
        error: YoutubeDLError,
        logger: _YtDlpLogger,
    ) -> LinkIngestionError:
        details = " ".join([str(error), *logger.messages]).lower()
        if "link_duration_exceeded" in details:
            return LinkIngestionError(
                "link_duration_exceeded",
                f"当前只支持 {MAX_VIDEO_SECONDS // 60} 分钟以内的视频",
            )
        if "max-filesize" in details or "larger than" in details:
            return LinkIngestionError(
                "link_size_exceeded",
                f"链接视频不能超过 {self.max_download_bytes // 1024 // 1024} MB",
            )
        if "could not copy" in details or "cookie database" in details and "permission" in details:
            return LinkIngestionError(
                "platform_browser_cookie_locked",
                "浏览器 Cookie 数据库正在被占用，请关闭浏览器后台进程后重试",
                retryable=True,
            )
        if any(marker in details for marker in ("failed to decrypt", "dpapi", "app-bound")):
            return LinkIngestionError(
                "platform_browser_cookie_decryption_failed",
                "浏览器安全保护阻止了 Cookie 解密，请改用 cookies.txt 导入",
            )
        if any(
            marker in details
            for marker in (
                "fresh cookies",
                "login required",
                "sign in",
                "captcha",
                "verify you are human",
            )
        ):
            return LinkIngestionError(
                "link_auth_required",
                "平台要求登录或人机验证；请到“平台连接”更新登录状态后重试",
                retryable=True,
            )
        if any(marker in details for marker in ("404", "private", "unavailable", "deleted")):
            return LinkIngestionError(
                "link_unavailable",
                "视频不存在、已删除、非公开或链接已失效",
            )
        if any(marker in details for marker in ("timed out", "timeout", "connection reset")):
            return LinkIngestionError(
                "link_download_timeout",
                "连接平台超时，请稍后重试",
                retryable=True,
            )
        if "unsupported url" in details:
            return LinkIngestionError(
                "link_extractor_unsupported",
                "当前采集器无法解析该平台链接格式",
            )
        return LinkIngestionError(
            "link_download_failed",
            "无法从平台获取公开视频，请确认链接仍可在浏览器中播放",
            retryable=True,
        )

    @staticmethod
    def _remove_partial_files(target_dir: Path) -> None:
        for pattern in ("*.part", "*.ytdl", "*.tmp"):
            for candidate in target_dir.glob(pattern):
                if candidate.is_file():
                    candidate.unlink(missing_ok=True)

    @staticmethod
    def _write_manifest(target_dir: Path, result: LinkIngestionResult) -> None:
        payload = {
            "collector_version": COLLECTOR_VERSION,
            "yt_dlp_version": yt_dlp_version,
            "platform": result.platform.value,
            "resolved_url": result.resolved_url,
            "source_video_id": result.source_video_id,
            "title": result.title,
            "author": result.author,
            "duration_seconds": result.duration_seconds,
            "file_name": result.path.name,
            "file_size_bytes": result.file_size_bytes,
            "collected_at": datetime.now(UTC).isoformat(),
        }
        manifest_path = target_dir / "metadata.json"
        temp_path = target_dir / "metadata.json.tmp"
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(manifest_path)
        legacy_manifest = target_dir / "ingestion.json"
        if legacy_manifest != manifest_path:
            legacy_manifest.write_text(manifest_path.read_text("utf-8"), encoding="utf-8")


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是正整数") from exc
    if value <= 0:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是正整数")
    return value


def _non_negative_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是非负整数") from exc
    if value < 0:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是非负整数")
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是正数") from exc
    if value <= 0:
        raise LinkIngestionError("link_config_invalid", f"{name} 必须是正数")
    return value


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text:
            return text
    return None
