from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import re
import signal
import subprocess
import sys
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import UUID

from yt_dlp import YoutubeDL
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import YoutubeDLError
from yt_dlp.version import __version__ as yt_dlp_version

from .browser_budget import HumanPauseBudget
from .douyin_extractor import DouyinPageIE
from .media import MAX_VIDEO_SECONDS, get_storage_root
from .models import SourceType, Video
from .platform_catalog import PLATFORM_SPECS, SUPPORTED_PLATFORM_TEXT
from .runtime_config import get_config_value

COLLECTOR_VERSION = "yt-dlp-link-v1"
DEFAULT_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
SUPPORTED_MEDIA_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".flv"}
PLATFORM_DOMAINS = {
    domain: SourceType(spec.key)
    for spec in PLATFORM_SPECS
    for domain in spec.link_domains
}
DOUYIN_CANONICAL_HOST = "www.douyin.com"
WORKER_IMPORT_ROOT = str(Path(__file__).resolve().parent.parent)
BROWSER_FALLBACK_CODES = {
    "link_auth_required", "link_access_denied", "link_metadata_unavailable",
    "link_download_failed", "link_browser_cookie_failed",
}
DOUYIN_VIDEO_PATH = re.compile(
    r"(?:^|/)video/(?P<video_id>[0-9]{1,30})(?:/|$)"
)
DOUYIN_VIDEO_ID = re.compile(r"^[0-9]{1,30}$")


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
        self.http_status: int | None = None

    def debug(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        self.messages = [*self.messages[-7:], message[:2000]]

    def error(self, message: str) -> None:
        self.warning(message)


class _ObservedYoutubeDL(YoutubeDL):
    """Keep the HTTP cause when an extractor replaces it with a generic Cookie error."""

    def urlopen(self, request):
        try:
            return super().urlopen(request)
        except HTTPError as exc:
            logger = self.params.get("logger")
            if isinstance(logger, _YtDlpLogger):
                logger.http_status = exc.status
            raise


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
        f"当前只支持以下平台的公开链接：{SUPPORTED_PLATFORM_TEXT}",
    )


def normalize_platform_url(url: str) -> str:
    platform = identify_platform(url)
    parsed = urlsplit(url.strip())
    if platform == SourceType.DOUYIN:
        path_match = DOUYIN_VIDEO_PATH.search(parsed.path)
        if path_match:
            return (
                f"https://{DOUYIN_CANONICAL_HOST}/video/"
                f"{path_match.group('video_id')}"
            )

        query = parse_qs(parsed.query, keep_blank_values=True)
        modal_values = [
            value.strip()
            for key in ("modal_id", "aweme_id")
            for value in query.get(key, [])
        ]
        if modal_values:
            unique_ids = set(modal_values)
            if len(unique_ids) != 1 or not DOUYIN_VIDEO_ID.fullmatch(modal_values[0]):
                raise LinkIngestionError(
                    "link_douyin_video_id_invalid",
                    "抖音弹窗链接中的视频 ID 无效，请重新复制视频分享链接",
                )
            return f"https://{DOUYIN_CANONICAL_HOST}/video/{modal_values[0]}"

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
    def __init__(
        self, credential_resolver: LinkCredentialResolver | None = None,
        *, browser_assist=None, browser_progress=None,
    ) -> None:
        self.credential_resolver = credential_resolver
        self.browser_assist = browser_assist or getattr(credential_resolver, "browser_assist", None)
        self.browser_progress = browser_progress
        self._budget: HumanPauseBudget | None = None
        self.max_download_bytes = _positive_int(
            "VIRAL_DNA_LINK_MAX_BYTES",
            DEFAULT_MAX_DOWNLOAD_BYTES,
        )
        self.socket_timeout = _positive_float("VIRAL_DNA_LINK_SOCKET_TIMEOUT", 20.0)
        self.retries = _non_negative_int("VIRAL_DNA_LINK_RETRIES", 2)
        self.timeout_seconds = configured_timeout("VIRAL_DNA_LINK_TIMEOUT_SECONDS", 120)

    async def collect(self, video: Video) -> LinkIngestionResult:
        try:
            async with HumanPauseBudget(self.timeout_seconds) as budget:
                self._budget = budget
                return await self._collect(video)
        except TimeoutError as exc:
            failure = LinkIngestionError(
                "link_download_timeout",
                f"读取或下载平台视频超过 {self.timeout_seconds:g} 秒，已停止。"
                "请检查网络和平台登录状态后重试，或直接上传视频文件。",
                retryable=True,
            )
            await self._report_failure(video.source_type, failure.code, str(failure))
            raise failure from exc
        finally:
            self._budget = None

    async def _browser_state(self, event: dict) -> None:
        if self._budget:
            self._budget.waiting(event["state"] == "waiting_user")
        if self.browser_progress:
            await self.browser_progress(event)

    async def _download_with_browser_fallback(self, url, target, platform, session):
        enabled = (
            platform == SourceType.DOUYIN and self.browser_assist
            and self.browser_assist.available()
        )
        started = asyncio.get_running_loop().time()

        async def regular():
            if session is None:
                return await self._attempt_download(url, target, None)
            return await self._download_with_credentials(url, target, platform, session)

        if not enabled:
            return await regular()
        try:
            async with asyncio.timeout(min(30, self.timeout_seconds / 3)):
                return await regular()
        except LinkIngestionError as exc:
            if exc.code not in BROWSER_FALLBACK_CODES:
                raise
        except TimeoutError:
            pass
        remaining = max(0.1, self.timeout_seconds - (asyncio.get_running_loop().time() - started))
        return await self.browser_assist.download(
            url, target, session, remaining, self.max_download_bytes, self._browser_state,
        )

    async def _collect(self, video: Video) -> LinkIngestionResult:
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

        report_success = False
        if self.credential_resolver is None:
            info = await self._download_with_browser_fallback(
                source_url, target_dir, expected_platform, None,
            )
        else:
            try:
                async with self.credential_resolver.session_for(expected_platform) as session:
                    report_success = session.configured and session.strategy != "disabled"
                    info = await self._download_with_browser_fallback(
                        source_url,
                        target_dir,
                        expected_platform,
                        session,
                    )
            except LinkCredentialError as exc:
                await self._report_failure(expected_platform, exc.code, str(exc))
                if (expected_platform == SourceType.DOUYIN and self.browser_assist
                        and self.browser_assist.available()):
                    report_success = False
                    info = await self.browser_assist.download(
                        source_url, target_dir, None, self.timeout_seconds,
                        self.max_download_bytes, self._browser_state,
                    )
                else:
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
                f"仅支持 {MAX_VIDEO_SECONDS // 60} 分钟以内的视频，请裁剪后重新导入",
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
        if report_success:
            await self._report_success(expected_platform)
        return result

    def _download_sync(
        self,
        source_url: str,
        target_dir: Path,
        logger: _YtDlpLogger,
        credential_session: LinkCredentialSession | None = None,
        *,
        use_legacy_cookie: bool = True,
        metadata_only: bool = False,
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
            # Warnings are captured in memory, not printed: they often contain the
            # actual transport failure which Douyin's generic error hides.
            "no_warnings": False,
            "logger": logger,
            "match_filter": duration_filter,
            "cachedir": False,
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
        elif self.credential_resolver is None and use_legacy_cookie:
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

        with _ObservedYoutubeDL(options) as downloader:
            downloader.add_info_extractor(DouyinPageIE())
            info = downloader.extract_info(source_url, download=not metadata_only)
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
                first_error.code in {
                    "link_auth_required", "link_access_denied", "link_metadata_unavailable",
                }
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
            return info
        return info

    async def probe_url(self, source_url: str, session: LinkCredentialSession) -> dict[str, Any]:
        """Test a real video's metadata with the same collector, without downloading it."""
        source_url = normalize_platform_url(source_url)
        seconds = min(self.timeout_seconds, 45)
        enabled = (
            identify_platform(source_url) == SourceType.DOUYIN
            and self.browser_assist and self.browser_assist.available()
        )
        try:
            async with HumanPauseBudget(seconds) as budget:
                self._budget = budget
                started = asyncio.get_running_loop().time()
                try:
                    async with asyncio.timeout(min(15, seconds / 3) if enabled else seconds):
                        return await self._download_process(
                            source_url, get_storage_root() / "temp", session, metadata_only=True,
                        )
                except LinkIngestionError as exc:
                    if not enabled or exc.code not in BROWSER_FALLBACK_CODES:
                        raise
                except TimeoutError:
                    if not enabled:
                        raise
                remaining = max(0.1, seconds - (asyncio.get_running_loop().time() - started))
                return await self.browser_assist.probe(
                    source_url, session, remaining, self._browser_state,
                )
        except TimeoutError as exc:
            raise LinkIngestionError(
                "link_probe_timeout", "视频链接测试超时，已停止；请检查网络后重试。",
                retryable=True,
            ) from exc
        finally:
            self._budget = None

    async def _attempt_download(
        self,
        source_url: str,
        target_dir: Path,
        credential_session: LinkCredentialSession | None,
    ) -> dict[str, Any]:
        logger = _YtDlpLogger()
        try:
            return await self._download_process(source_url, target_dir, credential_session)
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

    async def _download_process(
        self,
        source_url: str,
        target_dir: Path,
        credential_session: LinkCredentialSession | None,
        *,
        metadata_only: bool = False,
    ) -> dict[str, Any]:
        # A thread cannot be stopped by asyncio cancellation. Use a dedicated child
        # so the deadline also stops yt-dlp, its network retries and FFmpeg children.
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            WORKER_IMPORT_ROOT, environment.get("PYTHONPATH"),
        )))
        environment["VIRAL_DNA_WORKSPACE_ROOT"] = str(get_storage_root())
        environment["VIRAL_DNA_STORAGE_ROOT"] = str(get_storage_root())
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            sys.executable, "-m", "viral_dna_api.link_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            **({"creationflags": subprocess.CREATE_NO_WINDOW}
               if os.name == "nt" else {"start_new_session": True}),
        ))
        try:
            process = await asyncio.shield(spawn)
        except asyncio.CancelledError:
            process = await spawn
            await _stop_download_process(process)
            raise
        session = credential_session
        request = {
            "source_url": source_url,
            "target_dir": str(target_dir),
            "max_download_bytes": self.max_download_bytes,
            "socket_timeout": self.socket_timeout,
            "retries": self.retries,
            "use_legacy_cookie": self.credential_resolver is None,
            "metadata_only": metadata_only,
            "cookie_file": str(session.cookie_file) if session and session.cookie_file else None,
            "cookies_from_browser": session.cookies_from_browser if session else None,
        }
        communication = asyncio.create_task(
            process.communicate(json.dumps(request).encode("utf-8"))
        )
        try:
            stdout, _stderr = await asyncio.shield(communication)
        except BaseException:
            await _stop_download_process(process)
            with suppress(Exception):
                await communication
            raise
        try:
            response = json.loads(stdout)
            if process.returncode != 0 or not isinstance(response, dict):
                raise ValueError("worker failed")
            if "error" in response:
                error = response["error"]
                raise LinkIngestionError(
                    error["code"], error["message"], retryable=error["retryable"],
                )
            if not isinstance(response.get("info"), dict):
                raise ValueError("missing metadata")
            return response["info"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LinkIngestionError(
                "link_worker_failed", "视频读取进程异常退出，请重试或直接上传视频文件。",
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
                f"仅支持 {MAX_VIDEO_SECONDS // 60} 分钟以内的视频，请裁剪后重新导入",
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
        # A transport refusal is not evidence that a readable Cookie has expired.
        status = logger.http_status
        if status == 429 or "http error 429" in details:
            return LinkIngestionError(
                "link_rate_limited", "平台限制了请求频率（HTTP 429），已停止；请稍后重试。",
                retryable=True,
            )
        if status == 403 or "http error 403" in details:
            return LinkIngestionError(
                "link_access_denied",
                "平台拒绝视频访问（HTTP 403），不代表 Cookie 未导入或已失效。"
                "请在当前设备浏览器确认视频可播放；若出现验证，请先手动完成后重试。",
                retryable=True,
            )
        if status is not None and status >= 500:
            return LinkIngestionError(
                "link_platform_unavailable", "平台服务暂时异常，已停止；请稍后重试。",
                retryable=True,
            )
        if any(marker in details for marker in ("timed out", "timeout", "connection reset")):
            return LinkIngestionError(
                "link_download_timeout", "连接平台超时，已停止；请稍后重试。", retryable=True,
            )
        if any(marker in details for marker in (
            "certificate_verify_failed", "certificate verify failed", "name resolution",
            "getaddrinfo failed", "unable to connect", "connection refused", "proxyerror",
        )):
            return LinkIngestionError(
                "link_network_failed", "无法连接平台，请检查服务器网络、代理和证书配置。",
                retryable=True,
            )
        if any(
            marker in details
            for marker in (
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
        if status == 401:
            return LinkIngestionError(
                "link_auth_required", "平台要求登录；请到“平台连接”更新登录信息后重试。",
                retryable=True,
            )
        if "fresh cookies" in details or "link_douyin_metadata_missing" in details:
            return LinkIngestionError(
                "link_metadata_unavailable",
                "抖音未返回可解析的视频信息，可能是访问限制或采集兼容问题；"
                "不能据此判断 Cookie 失效。请确认链接可播放后重试。",
                retryable=True,
            )
        if any(marker in details for marker in ("404", "private", "unavailable", "deleted")):
            return LinkIngestionError(
                "link_unavailable",
                "视频不存在、已删除、非公开或链接已失效",
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


async def _stop_download_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill.exe", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            await asyncio.wait_for(killer.wait(), 5)
        except TimeoutError:
            killer.kill()
            await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


def configured_timeout(name: str, default: float) -> float:
    try:
        value = float(get_config_value(name, str(default)))
        return value if math.isfinite(value) and value > 0 else default
    except (TypeError, ValueError):
        return default


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
