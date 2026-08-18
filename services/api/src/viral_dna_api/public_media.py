from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .runtime_config import get_config_value
from .workspace import WorkspaceManager

PUBLIC_MEDIA_BASE_URL_ENV = "VIRAL_DNA_PUBLIC_MEDIA_BASE_URL"
PUBLIC_MEDIA_TTL_SECONDS_ENV = "VIRAL_DNA_PUBLIC_MEDIA_TTL_SECONDS"
DEFAULT_PUBLIC_MEDIA_TTL_SECONDS = 3600
MIN_PUBLIC_MEDIA_TTL_SECONDS = 900
MAX_PUBLIC_MEDIA_TTL_SECONDS = 604800
MAX_PUBLIC_MEDIA_BYTES = 100 * 1024 * 1024
PUBLIC_MEDIA_PATH = "/api/v1/public-media"
_STAGED_FILENAME = re.compile(
    r"^(?P<expires>[0-9]{10})-(?P<id>[0-9a-f]{32})(?P<suffix>\.[a-z0-9]{2,8})$"
)
_ALLOWED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
    "video/quicktime",
}


class PublicMediaStagingError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class PublicMediaConfiguration:
    base_url: str | None
    ttl_seconds: int
    ready: bool
    validation_message: str


@dataclass(frozen=True, slots=True)
class PublicMediaLease:
    url: str
    media_type: str
    expires_at: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PublishedMedia:
    path: Path
    media_type: str
    expires_at: int


def _b64encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload + padding)


def normalize_public_media_base_url(value: str | None) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise PublicMediaStagingError(
            422,
            "public_media_base_url_invalid",
            "公网媒体地址格式无效",
        ) from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if (
        parts.scheme.lower() != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or parts.query
        or parts.fragment
    ):
        raise PublicMediaStagingError(
            422,
            "public_media_base_url_not_allowed",
            "公网媒体地址必须是无凭据、无查询参数的 HTTPS 地址",
        )
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise PublicMediaStagingError(
            422,
            "public_media_base_url_not_public",
            "公网媒体地址不能使用 localhost 或本地域名",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise PublicMediaStagingError(
            422,
            "public_media_base_url_not_public",
            "公网媒体地址不能使用内网、回环或保留 IP",
        )
    path = parts.path.rstrip("/")
    if path.endswith("/api/v1"):
        path = path[: -len("/api/v1")]
    return urlunsplit(("https", parts.netloc, path, "", "")).rstrip("/")


def public_media_configuration() -> PublicMediaConfiguration:
    raw = get_config_value(PUBLIC_MEDIA_BASE_URL_ENV, "").strip()
    try:
        ttl = int(
            get_config_value(
                PUBLIC_MEDIA_TTL_SECONDS_ENV,
                str(DEFAULT_PUBLIC_MEDIA_TTL_SECONDS),
            )
        )
    except ValueError:
        ttl = DEFAULT_PUBLIC_MEDIA_TTL_SECONDS
    ttl = min(MAX_PUBLIC_MEDIA_TTL_SECONDS, max(MIN_PUBLIC_MEDIA_TTL_SECONDS, ttl))
    if not raw:
        return PublicMediaConfiguration(
            base_url=None,
            ttl_seconds=ttl,
            ready=False,
            validation_message=(
                "未配置公网 HTTPS 地址；需要全场景深度视频的模型将无法提交生成"
            ),
        )
    try:
        base_url = normalize_public_media_base_url(raw)
    except PublicMediaStagingError as exc:
        return PublicMediaConfiguration(
            base_url=raw,
            ttl_seconds=ttl,
            ready=False,
            validation_message=str(exc),
        )
    return PublicMediaConfiguration(
        base_url=base_url,
        ttl_seconds=ttl,
        ready=True,
        validation_message="已配置；生成时会签发短期、只读的 Provider 媒体地址",
    )


class PublicMediaStager:
    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    @property
    def configuration(self) -> PublicMediaConfiguration:
        return public_media_configuration()

    @property
    def ready(self) -> bool:
        return self.configuration.ready

    @property
    def readiness_message(self) -> str:
        return self.configuration.validation_message

    @property
    def root(self) -> Path:
        return self.workspace.paths.temporary / "public-media"

    @property
    def secret_path(self) -> Path:
        return self.workspace.paths.metadata_dir / "public-media-signing.key"

    def _secret(self) -> bytes:
        path = self.secret_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            payload = secrets.token_bytes(32)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(payload)
                try:
                    os.replace(temporary, path)
                except OSError:
                    if not path.exists():
                        raise
            finally:
                temporary.unlink(missing_ok=True)
        if len(payload) < 32:
            raise PublicMediaStagingError(
                500,
                "public_media_signing_key_invalid",
                "工作区公网媒体签名密钥无效",
            )
        return payload

    def _cleanup_expired(self, now: int) -> None:
        root = self.root
        if not root.is_dir():
            return
        for item in root.iterdir():
            match = _STAGED_FILENAME.fullmatch(item.name)
            if match and int(match.group("expires")) < now:
                item.unlink(missing_ok=True)

    def _validate_source(self, path: Path) -> tuple[Path, str, int]:
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.workspace.root.resolve())
        except (OSError, ValueError) as exc:
            raise PublicMediaStagingError(
                404,
                "public_media_source_missing",
                "待发布的参考素材不存在或不属于当前工作区",
            ) from exc
        if not resolved.is_file():
            raise PublicMediaStagingError(
                404,
                "public_media_source_missing",
                "待发布的参考素材不存在",
            )
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_PUBLIC_MEDIA_BYTES:
            raise PublicMediaStagingError(
                422,
                "public_media_source_size_invalid",
                "参考素材为空或超过 100MB 的安全限制",
            )
        media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if media_type not in _ALLOWED_MEDIA_TYPES:
            raise PublicMediaStagingError(
                422,
                "public_media_source_format_invalid",
                "公网暂存仅支持 JPEG、PNG、WebP、MP4、WebM 或 MOV",
            )
        return resolved, media_type, size

    def stage(self, path: Path, *, ttl_seconds: int | None = None) -> PublicMediaLease:
        config = self.configuration
        if not config.ready or not config.base_url:
            raise PublicMediaStagingError(
                409,
                "video_public_media_transport_required",
                config.validation_message,
            )
        source, media_type, size = self._validate_source(path)
        ttl = ttl_seconds if ttl_seconds is not None else config.ttl_seconds
        ttl = min(MAX_PUBLIC_MEDIA_TTL_SECONDS, max(MIN_PUBLIC_MEDIA_TTL_SECONDS, int(ttl)))
        now = int(time.time())
        expires_at = now + ttl
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired(now)
        suffix = source.suffix.lower() or mimetypes.guess_extension(media_type) or ".bin"
        filename = f"{expires_at:010d}-{uuid4().hex}{suffix}"
        destination = self.root / filename
        temporary = self.root / f".{filename}.tmp"
        try:
            try:
                os.link(source, temporary)
            except OSError:
                shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        payload = {
            "v": 1,
            "f": filename,
            "e": expires_at,
            "s": size,
            "m": media_type,
        }
        encoded = _b64encode(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        )
        signature = _b64encode(
            hmac.new(self._secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        token = f"{encoded}.{signature}"
        return PublicMediaLease(
            url=f"{config.base_url}{PUBLIC_MEDIA_PATH}/{token}",
            media_type=media_type,
            expires_at=expires_at,
            size_bytes=size,
        )

    def resolve(self, token: str) -> PublishedMedia:
        try:
            encoded, signature = token.split(".", 1)
            expected = _b64encode(
                hmac.new(self._secret(), encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = json.loads(_b64decode(encoded).decode("utf-8"))
            filename = str(payload["f"])
            expires_at = int(payload["e"])
            expected_size = int(payload["s"])
            media_type = str(payload["m"])
            if int(payload["v"]) != 1 or not _STAGED_FILENAME.fullmatch(filename):
                raise ValueError("payload")
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise PublicMediaStagingError(
                404,
                "public_media_token_invalid",
                "公网媒体地址无效",
            ) from exc
        if expires_at < int(time.time()):
            raise PublicMediaStagingError(
                410,
                "public_media_token_expired",
                "公网媒体地址已过期",
            )
        if media_type not in _ALLOWED_MEDIA_TYPES:
            raise PublicMediaStagingError(404, "public_media_token_invalid", "公网媒体地址无效")
        path = (self.root / filename).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise PublicMediaStagingError(
                404,
                "public_media_token_invalid",
                "公网媒体地址无效",
            ) from exc
        if not path.is_file() or path.stat().st_size != expected_size:
            raise PublicMediaStagingError(
                404,
                "public_media_object_missing",
                "公网媒体对象不存在",
            )
        return PublishedMedia(path=path, media_type=media_type, expires_at=expires_at)


def create_public_media_router(stager: PublicMediaStager) -> APIRouter:
    router = APIRouter(prefix="/public-media", tags=["public-media"])

    @router.api_route("/{token}", methods=["GET", "HEAD"], response_class=FileResponse)
    async def get_public_media(token: str) -> FileResponse:
        try:
            published = stager.resolve(token)
        except PublicMediaStagingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        remaining = max(0, published.expires_at - int(time.time()))
        return FileResponse(
            path=published.path,
            media_type=published.media_type,
            headers={
                "Cache-Control": f"public, max-age={remaining}, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
