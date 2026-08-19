from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx

from ..public_media import PublicMediaStager, PublicMediaStagingError
from ..storage_objects import (
    ObjectReplica,
    ObjectReplicaKind,
    ObjectReplicaState,
    StorageManager,
    StorageObject,
    StorageObjectError,
    StorageObjectType,
)
from ..workspace import WorkspaceManager
from ..workspace_catalog import (
    AccountContextService,
    StorageProviderType,
)
from .domain import (
    MediaAccessLease,
    MediaLeaseState,
    MediaStagingConfig,
    MediaStagingProvider,
    MediaStagingSettingsResponse,
    MediaStagingSettingsUpdate,
    MediaStagingValidationResponse,
    OssCredentialMode,
    StagedMedia,
    utc_now,
)
from .oss import AliyunOssClient, OssError
from .secrets import MediaStagingSecretStore


class MediaStagingRepository(Protocol):
    async def save_media_staging_config(self, config: MediaStagingConfig) -> MediaStagingConfig: ...
    async def get_media_staging_config(self, account_id: UUID) -> MediaStagingConfig | None: ...
    async def save_media_access_lease(self, lease: MediaAccessLease) -> MediaAccessLease: ...
    async def list_media_access_leases(self) -> list[MediaAccessLease]: ...
    async def save_object_replica(self, replica: ObjectReplica) -> ObjectReplica: ...
    async def list_object_replicas(self, object_id: UUID) -> list[ObjectReplica]: ...
    async def list_storage_objects(self) -> list[StorageObject]: ...


class MediaStagingError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class MediaStagingService:
    def __init__(
        self,
        repository: MediaStagingRepository,
        workspace: WorkspaceManager,
        account_context: AccountContextService,
        storage: StorageManager,
        public_media: PublicMediaStager,
        secret_store: MediaStagingSecretStore,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.account_context = account_context
        self.storage = storage
        self.public_media = public_media
        self.secret_store = secret_store
        self._cleanup_task: asyncio.Task[None] | None = None
        self._closed = False

    async def config(self) -> MediaStagingConfig:
        context = await self.account_context.ensure_current()
        stored = await self.repository.get_media_staging_config(context.account.id)
        if stored is not None:
            return stored
        return MediaStagingConfig(account_id=context.account.id)

    async def ready(self) -> bool:
        config = await self.config()
        if config.provider == MediaStagingProvider.LOCAL_PROXY:
            return self.public_media.ready
        if config.provider != MediaStagingProvider.ALIYUN_OSS:
            return False
        if not config.bucket:
            return False
        if config.credential_mode == OssCredentialMode.ECS_RAM_ROLE:
            return True
        return await self.secret_store.read(config.account_id) is not None

    async def settings(self) -> MediaStagingSettingsResponse:
        config = await self.config()
        access_key = (
            await self.secret_store.read(config.account_id)
            if config.credential_mode == OssCredentialMode.ACCESS_KEY
            else None
        )
        ready = await self.ready()
        if config.provider == MediaStagingProvider.DISABLED:
            status = "not_configured"
            message = "尚未配置媒体暂存服务"
        elif ready:
            status = "ready"
            message = (
                "已使用 OSS 私有桶和短期签名 URL"
                if config.provider == MediaStagingProvider.ALIYUN_OSS
                else self.public_media.configuration.validation_message
            )
        else:
            status = "incomplete"
            message = "配置尚不完整，请填写 Bucket 与凭证后测试连接"
        return MediaStagingSettingsResponse(
            provider=config.provider,
            credential_mode=config.credential_mode,
            region=config.region,
            bucket=config.bucket,
            internal_endpoint=config.internal_endpoint,
            public_endpoint=config.public_endpoint,
            role_name=config.role_name,
            object_prefix=config.object_prefix,
            signed_url_ttl_seconds=config.signed_url_ttl_seconds,
            cleanup_grace_seconds=config.cleanup_grace_seconds,
            access_key_configured=access_key is not None,
            access_key_hint=(
                f"{access_key[0][:4]}...{access_key[0][-4:]}"
                if access_key and len(access_key[0]) >= 8
                else "已保存"
                if access_key
                else None
            ),
            ready=ready,
            validation_status=status,
            validation_message=message,
            updated_at=config.updated_at,
        )

    async def update_settings(
        self,
        payload: MediaStagingSettingsUpdate,
    ) -> MediaStagingSettingsResponse:
        context = await self.account_context.ensure_current()
        current = await self.repository.get_media_staging_config(context.account.id)
        now = utc_now()
        config_values = dict(
            account_id=context.account.id,
            provider=payload.provider,
            credential_mode=payload.credential_mode,
            region=payload.region.strip(),
            bucket=payload.bucket.strip(),
            internal_endpoint=(payload.internal_endpoint or "").strip() or None,
            public_endpoint=(payload.public_endpoint or "").strip() or None,
            role_name=(payload.role_name or "").strip() or None,
            object_prefix=payload.object_prefix,
            signed_url_ttl_seconds=payload.signed_url_ttl_seconds,
            cleanup_grace_seconds=payload.cleanup_grace_seconds,
            version=(current.version + 1) if current else 1,
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        if current is not None:
            config_values["id"] = current.id
        config = MediaStagingConfig(**config_values)
        if payload.clear_access_key:
            await self.secret_store.delete(context.account.id)
        elif payload.access_key_id and payload.access_key_secret:
            await self.secret_store.save(
                context.account.id,
                payload.access_key_id.get_secret_value().strip(),
                payload.access_key_secret.get_secret_value().strip(),
            )
        await self.repository.save_media_staging_config(config)
        if config.provider == MediaStagingProvider.ALIYUN_OSS:
            await self.account_context.ensure_account_storage_location(
                provider_type=StorageProviderType.OSS,
                name="阿里云 OSS 媒体暂存",
                config_reference=f"media-staging:{config.id}",
            )
        return await self.settings()

    async def validate(self) -> MediaStagingValidationResponse:
        config = await self.config()
        if config.provider == MediaStagingProvider.LOCAL_PROXY:
            if not self.public_media.ready:
                return MediaStagingValidationResponse(
                    valid=False,
                    message=(
                        self.public_media.configuration.validation_message
                        or "公网 API 地址不可用"
                    ),
                    error_code="local_proxy_not_ready",
                )
            return MediaStagingValidationResponse(valid=True, message="本机反向代理暂存可用")
        if config.provider != MediaStagingProvider.ALIYUN_OSS:
            return MediaStagingValidationResponse(
                valid=False,
                message="请先选择阿里云 OSS 或本机反向代理",
                error_code="media_staging_disabled",
            )
        client = await self._oss_client(config)
        try:
            valid, message, latency = await client.validate()
            return MediaStagingValidationResponse(
                valid=valid,
                message=message,
                latency_ms=latency,
                error_code=None if valid else "oss_validation_failed",
            )
        finally:
            await client.close()

    async def stage_path(
        self,
        path: Path,
        *,
        object_type: StorageObjectType = StorageObjectType.DEPTH_VIDEO,
        purpose: str = "video_generation",
        expected_sha256: str | None = None,
    ) -> StagedMedia:
        resolved = await asyncio.to_thread(path.resolve)
        if not await asyncio.to_thread(resolved.is_file):
            raise MediaStagingError(
                "media_source_missing",
                "需要暂存的媒体文件不存在",
                status_code=404,
            )
        config = await self.config()
        if config.provider == MediaStagingProvider.LOCAL_PROXY:
            try:
                staged = self.public_media.stage(resolved)
            except PublicMediaStagingError as exc:
                raise MediaStagingError(exc.code, str(exc), status_code=exc.status_code) from exc
            storage_object = await self._ensure_storage_object(
                resolved,
                object_type=object_type,
                expected_sha256=expected_sha256,
            )
            return StagedMedia(
                storage_object_id=storage_object.id,
                provider=config.provider,
                url=staged.url,
                expires_at=staged.expires_at,
                object_key=staged.relative_path,
            )
        if config.provider != MediaStagingProvider.ALIYUN_OSS:
            raise MediaStagingError(
                "media_staging_not_configured",
                "当前模型需要可访问的 HTTPS 媒体地址，请先配置 OSS 私有桶媒体暂存",
                status_code=409,
            )
        storage_object = await self._ensure_storage_object(
            resolved,
            object_type=object_type,
            expected_sha256=expected_sha256,
        )
        context = await self.account_context.ensure_current()
        location = await self.account_context.ensure_account_storage_location(
            provider_type=StorageProviderType.OSS,
            name="阿里云 OSS 媒体暂存",
            config_reference=f"media-staging:{config.id}",
        )
        suffix = resolved.suffix.lower() if len(resolved.suffix) <= 12 else ".bin"
        object_key = (
            f"{config.object_prefix}/{context.account.id}/{context.active_workspace.id}/"
            f"{storage_object.sha256[:2]}/{storage_object.sha256}{suffix or '.bin'}"
        )
        replicas = await self.repository.list_object_replicas(storage_object.id)
        replica = next(
            (
                item for item in replicas
                if item.storage_location_id == location.id and item.object_key == object_key
            ),
            None,
        )
        client = await self._oss_client(config)
        reused = False
        try:
            if replica and replica.state == ObjectReplicaState.AVAILABLE:
                reused = await client.object_exists(object_key)
            if not reused:
                uploading = (
                    replica.model_copy(
                        update={"state": ObjectReplicaState.UPLOADING, "updated_at": utc_now()}
                    )
                    if replica
                    else ObjectReplica(
                        account_id=context.account.id,
                        storage_object_id=storage_object.id,
                        storage_location_id=location.id,
                        object_key=object_key,
                        replica_kind=ObjectReplicaKind.PROVIDER_STAGING,
                        state=ObjectReplicaState.UPLOADING,
                        checksum=storage_object.sha256,
                        content_type=mimetypes.guess_type(resolved.name)[0]
                        or "application/octet-stream",
                        is_cache=True,
                        is_pinned=False,
                    )
                )
                replica = await self.repository.save_object_replica(uploading)
                content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                try:
                    result = await client.upload_file(
                        object_key,
                        resolved,
                        content_type=content_type,
                    )
                except OssError as exc:
                    await self.repository.save_object_replica(
                        replica.model_copy(
                            update={
                                "state": ObjectReplicaState.FAILED,
                                "error_code": exc.code,
                                "error_message": str(exc),
                                "updated_at": utc_now(),
                            }
                        )
                    )
                    raise
                replica = await self.repository.save_object_replica(
                    replica.model_copy(
                        update={
                            "state": ObjectReplicaState.AVAILABLE,
                            "etag": result.etag,
                            "remote_version": result.version_id,
                            "last_synced_at": utc_now(),
                            "last_verified_at": utc_now(),
                            "remote_last_modified_at": utc_now(),
                            "delete_after": utc_now()
                            + timedelta(seconds=config.signed_url_ttl_seconds)
                            + timedelta(seconds=config.cleanup_grace_seconds),
                            "error_code": None,
                            "error_message": None,
                            "updated_at": utc_now(),
                        }
                    )
                )
            url, expires_at = await client.presign_get(
                object_key,
                config.signed_url_ttl_seconds,
            )
            await self._probe_signed_url(url)
        except OssError as exc:
            raise MediaStagingError(exc.code, str(exc), status_code=exc.status_code) from exc
        finally:
            await client.close()
        delete_after = expires_at + timedelta(seconds=config.cleanup_grace_seconds)
        lease = await self.repository.save_media_access_lease(
            MediaAccessLease(
                account_id=context.account.id,
                workspace_id=context.active_workspace.id,
                storage_object_id=storage_object.id,
                replica_id=replica.id if replica else None,
                provider=config.provider,
                object_key=object_key,
                purpose=purpose,
                expires_at=expires_at,
                delete_after=delete_after,
            )
        )
        return StagedMedia(
            storage_object_id=storage_object.id,
            lease_id=lease.id,
            provider=config.provider,
            url=url,
            expires_at=expires_at,
            object_key=object_key,
            reused_replica=reused,
        )

    async def _ensure_storage_object(
        self,
        path: Path,
        *,
        object_type: StorageObjectType,
        expected_sha256: str | None,
    ) -> StorageObject:
        context = await self.account_context.ensure_current()
        digest = await asyncio.to_thread(_sha256_file, path)
        if expected_sha256 and expected_sha256 != digest:
            raise MediaStagingError("checksum_mismatch", "媒体文件校验和不一致", status_code=409)
        for item in await self.repository.list_storage_objects():
            if (
                item.workspace_id == context.active_workspace.id
                and item.object_type == object_type
                and item.sha256 == digest
                and item.deleted_at is None
            ):
                try:
                    await self.storage.materialize_local(item.id)
                    return item
                except StorageObjectError:
                    continue
        local_location = next(
            item for item in context.storage_locations
            if item.provider_type == StorageProviderType.LOCAL_FILESYSTEM
        )
        self.storage.bind_local_location(local_location.id)
        try:
            object_key = path.relative_to(self.workspace.root).as_posix()
        except ValueError as exc:
            raise MediaStagingError(
                "media_source_outside_workspace",
                "媒体文件必须位于当前工作区内",
                status_code=422,
            ) from exc
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            return await self.storage.register_existing_local_object(
                account_id=context.account.id,
                workspace_id=context.active_workspace.id,
                storage_location_id=local_location.id,
                object_type=object_type,
                original_filename=path.name,
                mime_type=mime_type,
                object_key=object_key,
                expected_sha256=digest,
            )
        except StorageObjectError as exc:
            raise MediaStagingError(exc.code, str(exc), status_code=exc.status_code) from exc

    async def _oss_client(self, config: MediaStagingConfig) -> AliyunOssClient:
        access_key = (
            await self.secret_store.read(config.account_id)
            if config.credential_mode == OssCredentialMode.ACCESS_KEY
            else None
        )
        return AliyunOssClient(config, access_key=access_key)

    @staticmethod
    async def _probe_signed_url(url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(url, headers={"Range": "bytes=0-0"})
        except httpx.HTTPError as exc:
            raise MediaStagingError(
                "signed_url_probe_failed",
                "OSS 签名 URL 已生成，但公网读取探测失败",
                status_code=502,
            ) from exc
        if response.status_code not in {200, 206}:
            raise MediaStagingError(
                "signed_url_not_readable",
                f"OSS 签名 URL 无法读取（HTTP {response.status_code}）",
                status_code=502,
            )

    def start_cleanup(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._closed = False
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def shutdown(self) -> None:
        self._closed = True
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(900)
            try:
                await self.cleanup_expired()
            except Exception:
                # Cleanup is best effort; upload/generation paths must remain available.
                continue

    async def cleanup_expired(self) -> int:
        now = datetime.now(UTC)
        leases = await self.repository.list_media_access_leases()
        expired = [
            item
            for item in leases
            if item.state == MediaLeaseState.ACTIVE and item.expires_at <= now
        ]
        for lease in expired:
            await self.repository.save_media_access_lease(
                lease.model_copy(update={"state": MediaLeaseState.EXPIRED})
            )
        active_replica_ids = {
            item.replica_id
            for item in leases
            if item.state == MediaLeaseState.ACTIVE
            and item.expires_at > now
            and item.replica_id is not None
        }
        config = await self.config()
        if config.provider != MediaStagingProvider.ALIYUN_OSS:
            return len(expired)
        context = await self.account_context.ensure_current()
        client = await self._oss_client(config)
        deleted = 0
        try:
            for storage_object in await self.repository.list_storage_objects():
                for replica in await self.repository.list_object_replicas(storage_object.id):
                    if (
                        replica.account_id != context.account.id
                        or replica.replica_kind != ObjectReplicaKind.PROVIDER_STAGING
                        or replica.state != ObjectReplicaState.AVAILABLE
                        or replica.is_pinned
                        or replica.delete_after is None
                        or replica.delete_after > now
                        or replica.id in active_replica_ids
                    ):
                        continue
                    deleting = await self.repository.save_object_replica(
                        replica.model_copy(
                            update={
                                "state": ObjectReplicaState.DELETING,
                                "updated_at": utc_now(),
                            }
                        )
                    )
                    try:
                        await client.delete(deleting.object_key)
                    except OssError as exc:
                        await self.repository.save_object_replica(
                            deleting.model_copy(
                                update={
                                    "state": ObjectReplicaState.FAILED,
                                    "error_code": exc.code,
                                    "error_message": str(exc),
                                    "updated_at": utc_now(),
                                }
                            )
                        )
                        continue
                    await self.repository.save_object_replica(
                        deleting.model_copy(
                            update={
                                "state": ObjectReplicaState.DELETED,
                                "last_verified_at": utc_now(),
                                "error_code": None,
                                "error_message": None,
                                "updated_at": utc_now(),
                            }
                        )
                    )
                    deleted += 1
        finally:
            await client.close()
        return len(expired) + deleted
