from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import httpx

from .domain import MediaStagingConfig, OssCredentialMode


class OssError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class OssCredentials:
    access_key_id: str
    access_key_secret: str
    security_token: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OssUploadResult:
    etag: str | None
    version_id: str | None
    size_bytes: int


def _endpoint(value: str | None, region: str) -> str:
    raw = (value or f"https://{region}.aliyuncs.com").strip().rstrip("/")
    if not raw.startswith(("https://", "http://")):
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.netloc or parts.path not in {"", "/"}:
        raise OssError(
            "oss_endpoint_invalid",
            "OSS Endpoint 必须是只包含主机名的 HTTPS 地址",
            status_code=422,
        )
    return f"https://{parts.netloc}"


class AliyunOssClient:
    """Small OSS REST adapter with private upload and signed GET support."""

    def __init__(
        self,
        config: MediaStagingConfig,
        *,
        access_key: tuple[str, str] | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.access_key = access_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, read=600))
        self._owns_client = client is None
        self._cached_credentials: OssCredentials | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def credentials(self) -> OssCredentials:
        cached = self._cached_credentials
        if cached and (
            cached.expires_at is None
            or cached.expires_at > datetime.now(UTC) + timedelta(minutes=5)
        ):
            return cached
        if self.config.credential_mode == OssCredentialMode.ACCESS_KEY:
            if not self.access_key or not all(self.access_key):
                raise OssError("oss_credentials_missing", "尚未配置 OSS AccessKey", status_code=409)
            value = OssCredentials(self.access_key[0], self.access_key[1])
        else:
            value = await self._ecs_role_credentials()
        self._cached_credentials = value
        return value

    async def _ecs_role_credentials(self) -> OssCredentials:
        role = (self.config.role_name or "").strip()
        headers: dict[str, str] = {}
        try:
            token_response = await self.client.put(
                "http://100.100.100.200/latest/api/token",
                headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "21600"},
                timeout=2,
            )
            if token_response.is_success and token_response.text.strip():
                headers["X-aliyun-ecs-metadata-token"] = token_response.text.strip()
            if not role:
                role_response = await self.client.get(
                    "http://100.100.100.200/latest/meta-data/ram/security-credentials/",
                    headers=headers,
                    timeout=2,
                )
                role_response.raise_for_status()
                role = role_response.text.strip().splitlines()[0]
            response = await self.client.get(
                "http://100.100.100.200/latest/meta-data/ram/security-credentials/"
                + quote(role, safe=""),
                headers=headers,
                timeout=3,
            )
            response.raise_for_status()
            payload = response.json()
            expiration = datetime.fromisoformat(str(payload["Expiration"]).replace("Z", "+00:00"))
            return OssCredentials(
                str(payload["AccessKeyId"]),
                str(payload["AccessKeySecret"]),
                str(payload["SecurityToken"]),
                expiration,
            )
        except Exception as exc:
            raise OssError(
                "oss_ecs_role_unavailable",
                "无法从 ECS 实例 RAM 角色读取临时凭证；请确认服务运行在 ECS 且角色已授权 OSS",
                status_code=409,
            ) from exc

    def _object_url(self, object_key: str, *, public: bool = False) -> str:
        endpoint = _endpoint(
            self.config.public_endpoint if public else self.config.internal_endpoint,
            self.config.region,
        )
        host = urlsplit(endpoint).netloc
        return f"https://{self.config.bucket}.{host}/{quote(object_key, safe='/~-_.')}"

    @staticmethod
    def _signature(secret: str, canonical: str) -> str:
        digest = hmac.new(secret.encode(), canonical.encode(), hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    def _resource(self, object_key: str) -> str:
        return f"/{self.config.bucket}/{object_key}"

    async def upload_file(
        self,
        object_key: str,
        path: Path,
        *,
        content_type: str,
    ) -> OssUploadResult:
        credentials = await self.credentials()
        size_bytes = (await asyncio.to_thread(path.stat)).st_size
        date = format_datetime(datetime.now(UTC), usegmt=True)
        oss_headers = ""
        headers = {
            "Date": date,
            "Content-Length": str(size_bytes),
            "Content-Type": content_type,
        }
        if credentials.security_token:
            headers["x-oss-security-token"] = credentials.security_token
            oss_headers = f"x-oss-security-token:{credentials.security_token}\n"
        canonical = f"PUT\n\n{content_type}\n{date}\n{oss_headers}{self._resource(object_key)}"
        headers["Authorization"] = (
            f"OSS {credentials.access_key_id}:"
            f"{self._signature(credentials.access_key_secret, canonical)}"
        )

        async def chunks():
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk

        try:
            response = await self.client.put(
                self._object_url(object_key),
                headers=headers,
                content=chunks(),
            )
        except httpx.HTTPError as exc:
            raise OssError("oss_upload_network_failed", "上传到 OSS 时网络连接失败") from exc
        if not response.is_success:
            raise OssError(
                "oss_upload_failed",
                f"OSS 上传失败（HTTP {response.status_code}）",
                status_code=502,
            )
        return OssUploadResult(
            etag=response.headers.get("etag", "").strip('"') or None,
            version_id=response.headers.get("x-oss-version-id"),
            size_bytes=size_bytes,
        )

    async def object_exists(self, object_key: str) -> bool:
        credentials = await self.credentials()
        date = format_datetime(datetime.now(UTC), usegmt=True)
        oss_headers = ""
        headers = {"Date": date}
        if credentials.security_token:
            headers["x-oss-security-token"] = credentials.security_token
            oss_headers = f"x-oss-security-token:{credentials.security_token}\n"
        canonical = f"HEAD\n\n\n{date}\n{oss_headers}{self._resource(object_key)}"
        headers["Authorization"] = (
            f"OSS {credentials.access_key_id}:"
            f"{self._signature(credentials.access_key_secret, canonical)}"
        )
        response = await self.client.head(self._object_url(object_key), headers=headers)
        if response.status_code == 404:
            return False
        if not response.is_success:
            raise OssError("oss_stat_failed", f"OSS 对象检查失败（HTTP {response.status_code}）")
        return True

    async def presign_get(self, object_key: str, ttl_seconds: int) -> tuple[str, datetime]:
        credentials = await self.credentials()
        expires = int(time.time()) + ttl_seconds
        canonical = f"GET\n\n\n{expires}\n{self._resource(object_key)}"
        query = {
            "OSSAccessKeyId": credentials.access_key_id,
            "Expires": str(expires),
            "Signature": self._signature(credentials.access_key_secret, canonical),
        }
        if credentials.security_token:
            query["security-token"] = credentials.security_token
        url = f"{self._object_url(object_key, public=True)}?{urlencode(query)}"
        return url, datetime.fromtimestamp(expires, UTC)

    async def delete(self, object_key: str) -> None:
        credentials = await self.credentials()
        date = format_datetime(datetime.now(UTC), usegmt=True)
        oss_headers = ""
        headers = {"Date": date}
        if credentials.security_token:
            headers["x-oss-security-token"] = credentials.security_token
            oss_headers = f"x-oss-security-token:{credentials.security_token}\n"
        canonical = f"DELETE\n\n\n{date}\n{oss_headers}{self._resource(object_key)}"
        headers["Authorization"] = (
            f"OSS {credentials.access_key_id}:"
            f"{self._signature(credentials.access_key_secret, canonical)}"
        )
        response = await self.client.delete(self._object_url(object_key), headers=headers)
        if response.status_code not in {204, 404}:
            raise OssError("oss_delete_failed", f"OSS 删除失败（HTTP {response.status_code}）")

    async def validate(self) -> tuple[bool, str, int]:
        started = time.perf_counter()
        probe_key = f"{self.config.object_prefix}/.viraldna-probes/{uuid4().hex}.txt"
        probe_path: Path | None = None
        try:
            payload = f"viraldna-oss-probe:{uuid4().hex}".encode()
            descriptor, raw_path = tempfile.mkstemp(prefix="viraldna-oss-probe-", suffix=".txt")
            probe_path = Path(raw_path)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            await self.upload_file(probe_key, probe_path, content_type="text/plain")
            if not await self.object_exists(probe_key):
                raise OssError("oss_probe_missing", "OSS 测试对象上传后无法读取", status_code=502)
            url, _ = await self.presign_get(probe_key, 900)
            response = await self.client.get(url, headers={"Range": "bytes=0-0"})
            if response.status_code not in {200, 206}:
                raise OssError(
                    "oss_signed_url_probe_failed",
                    f"OSS 签名 URL 公网读取失败（HTTP {response.status_code}）",
                    status_code=502,
                )
        except OssError as exc:
            return False, str(exc), int((time.perf_counter() - started) * 1000)
        except httpx.HTTPError as exc:
            return (
                False,
                f"OSS 签名 URL 公网读取失败：{exc}",
                int((time.perf_counter() - started) * 1000),
            )
        finally:
            try:
                await self.delete(probe_key)
            except OssError:
                pass
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)
        return (
            True,
            "OSS 私有上传、签名 URL 公网读取与删除链路均可用",
            int((time.perf_counter() - started) * 1000),
        )
