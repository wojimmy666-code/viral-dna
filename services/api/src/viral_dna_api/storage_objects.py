from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .workspace import WorkspaceManager


def utc_now() -> datetime:
    return datetime.now(UTC)


class StorageObjectType(StrEnum):
    SOURCE_VIDEO = "source_video"
    THUMBNAIL = "thumbnail"
    ASSET_IMAGE = "asset_image"
    GENERATED_IMAGE = "generated_image"
    GENERATED_VIDEO = "generated_video"
    DEPTH_VIDEO = "depth_video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    ANALYSIS_FILE = "analysis_file"
    EXPORT_FILE = "export_file"


class ObjectReplicaState(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    AVAILABLE = "available"
    MISSING = "missing"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class ObjectReplicaKind(StrEnum):
    LOCAL_PRIMARY = "local_primary"
    CLOUD_DURABLE = "cloud_durable"
    PROVIDER_STAGING = "provider_staging"


class StorageSyncState(StrEnum):
    LOCAL_ONLY = "local_only"
    CLOUD_ONLY = "cloud_only"
    SYNCING = "syncing"
    SYNCED = "synced"
    DOWNLOAD_REQUIRED = "download_required"
    UPLOAD_FAILED = "upload_failed"
    UNAVAILABLE = "unavailable"


class StorageObject(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    object_type: StorageObjectType
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id: UUID | None = None
    origin_workspace_id: UUID | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = None


class ObjectReplica(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    storage_object_id: UUID
    storage_location_id: UUID
    account_id: UUID | None = None
    object_key: str = Field(min_length=1, max_length=1024)
    replica_kind: ObjectReplicaKind = ObjectReplicaKind.LOCAL_PRIMARY
    state: ObjectReplicaState = ObjectReplicaState.PENDING
    content_type: str | None = Field(default=None, max_length=160)
    etag: str | None = Field(default=None, max_length=160)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    is_cache: bool = False
    is_pinned: bool = True
    last_verified_at: datetime | None = None
    last_synced_at: datetime | None = None
    remote_version: str | None = Field(default=None, max_length=300)
    upload_session_id: str | None = Field(default=None, max_length=500)
    remote_last_modified_at: datetime | None = None
    delete_after: datetime | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StorageAvailability(BaseModel):
    local: bool = False
    cloud: bool = False


class ObjectReplicaResponse(BaseModel):
    id: UUID
    storage_object_id: UUID
    storage_location_id: UUID
    account_id: UUID | None = None
    state: ObjectReplicaState
    checksum: str | None = None
    is_cache: bool
    is_pinned: bool
    last_verified_at: datetime | None = None
    last_synced_at: datetime | None = None
    remote_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StorageObjectResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID | None = None
    origin_workspace_id: UUID | None = None
    object_type: StorageObjectType
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    version: int
    created_at: datetime
    deleted_at: datetime | None = None
    availability: StorageAvailability
    sync_state: StorageSyncState
    content_url: str


class StorageObjectError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500, code: str = "storage_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class StoredFileInfo:
    path: Path
    size_bytes: int
    sha256: str
    etag: str


class StorageRepository(Protocol):
    async def save_storage_bundle(
        self,
        storage_object: StorageObject,
        replica: ObjectReplica,
    ) -> tuple[StorageObject, ObjectReplica]: ...

    async def save_storage_object(self, storage_object: StorageObject) -> StorageObject: ...

    async def get_storage_object(self, object_id: UUID) -> StorageObject | None: ...

    async def list_storage_objects(self) -> list[StorageObject]: ...

    async def save_object_replica(self, replica: ObjectReplica) -> ObjectReplica: ...

    async def get_object_replica(self, replica_id: UUID) -> ObjectReplica | None: ...

    async def list_object_replicas(self, object_id: UUID) -> list[ObjectReplica]: ...


class StorageDriver(Protocol):
    is_local: bool

    async def put(
        self,
        object_key: str,
        payload: bytes,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo: ...

    async def stat(self, object_key: str) -> StoredFileInfo: ...

    async def link_existing(
        self,
        source_object_key: str,
        target_object_key: str,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo: ...

    async def open_read(self, object_key: str) -> Path: ...

    async def delete_replica(self, object_key: str) -> None: ...

    async def test_connection(self) -> bool: ...


class LocalFileStorageDriver:
    is_local = True

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve_key(self, object_key: str) -> Path:
        normalized = str(object_key or "").strip().replace("\\", "/")
        if not normalized or "\x00" in normalized:
            raise StorageObjectError(
                "存储对象键不能为空",
                status_code=422,
                code="invalid_object_key",
            )
        relative = Path(normalized)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise StorageObjectError(
                "存储对象键必须是安全的相对路径",
                status_code=422,
                code="invalid_object_key",
            )
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise StorageObjectError(
                "存储对象路径越界",
                status_code=422,
                code="object_key_escape",
            ) from exc
        if target == self.root:
            raise StorageObjectError(
                "存储对象键不能指向存储根目录",
                status_code=422,
                code="invalid_object_key",
            )
        return target

    async def put(
        self,
        object_key: str,
        payload: bytes,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo:
        return await asyncio.to_thread(
            self._put_sync,
            object_key,
            payload,
            expected_sha256,
        )

    def _put_sync(
        self,
        object_key: str,
        payload: bytes,
        expected_sha256: str,
    ) -> StoredFileInfo:
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected_sha256:
            raise StorageObjectError(
                "写入内容校验和不一致",
                status_code=422,
                code="checksum_mismatch",
            )
        target = self.resolve_key(object_key)
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except StorageObjectError:
            raise
        except OSError as exc:
            raise StorageObjectError(
                "无法写入本地存储对象",
                status_code=507,
                code="local_write_failed",
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return StoredFileInfo(
            path=target,
            size_bytes=len(payload),
            sha256=digest,
            etag=digest,
        )

    async def stat(self, object_key: str) -> StoredFileInfo:
        return await asyncio.to_thread(self._stat_sync, object_key)

    async def link_existing(
        self,
        source_object_key: str,
        target_object_key: str,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo:
        return await asyncio.to_thread(
            self._link_existing_sync,
            source_object_key,
            target_object_key,
            expected_sha256,
        )

    def _link_existing_sync(
        self,
        source_object_key: str,
        target_object_key: str,
        expected_sha256: str,
    ) -> StoredFileInfo:
        source = self.resolve_key(source_object_key)
        target = self.resolve_key(target_object_key)
        if not source.is_file():
            raise StorageObjectError(
                "生成产物文件不存在",
                status_code=409,
                code="generated_artifact_missing",
            )
        source_info = self._stat_sync(source_object_key)
        if source_info.sha256 != expected_sha256:
            raise StorageObjectError(
                "生成产物校验和不一致",
                status_code=409,
                code="checksum_mismatch",
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target_info = self._stat_sync(target_object_key)
                if target_info.sha256 == expected_sha256:
                    return target_info
                raise StorageObjectError(
                    "目标对象路径已被其他内容占用",
                    status_code=409,
                    code="object_key_conflict",
                )
            os.link(source, target)
        except StorageObjectError:
            raise
        except OSError as exc:
            raise StorageObjectError(
                "当前文件系统不支持无复制加入资产库",
                status_code=409,
                code="zero_copy_unavailable",
            ) from exc
        return StoredFileInfo(
            path=target,
            size_bytes=source_info.size_bytes,
            sha256=source_info.sha256,
            etag=source_info.etag,
        )

    def _stat_sync(self, object_key: str) -> StoredFileInfo:
        target = self.resolve_key(object_key)
        if not target.is_file():
            raise StorageObjectError(
                "本地文件副本不存在",
                status_code=409,
                code="replica_missing",
            )
        try:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            size_bytes = target.stat().st_size
        except OSError as exc:
            raise StorageObjectError(
                "无法读取本地文件副本",
                status_code=409,
                code="replica_read_failed",
            ) from exc
        return StoredFileInfo(
            path=target,
            size_bytes=size_bytes,
            sha256=digest,
            etag=digest,
        )

    async def open_read(self, object_key: str) -> Path:
        info = await self.stat(object_key)
        return info.path

    async def delete_replica(self, object_key: str) -> None:
        target = self.resolve_key(object_key)
        try:
            await asyncio.to_thread(target.unlink, missing_ok=True)
        except OSError as exc:
            raise StorageObjectError(
                "无法删除本地文件副本",
                status_code=409,
                code="replica_delete_failed",
            ) from exc

    async def test_connection(self) -> bool:
        def probe() -> bool:
            probe_dir = self.root / ".viraldna"
            probe_file = probe_dir / f".storage-probe-{uuid4().hex}.tmp"
            try:
                probe_dir.mkdir(parents=True, exist_ok=True)
                probe_file.write_bytes(b"ok")
                return probe_file.read_bytes() == b"ok"
            except OSError:
                return False
            finally:
                probe_file.unlink(missing_ok=True)

        return await asyncio.to_thread(probe)


class FakeCloudStorageDriver:
    """Filesystem-backed cloud double used only by tests and local contract checks."""

    is_local = False

    def __init__(self, root: Path) -> None:
        self._delegate = LocalFileStorageDriver(root)

    async def put(
        self,
        object_key: str,
        payload: bytes,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo:
        return await self._delegate.put(
            object_key,
            payload,
            expected_sha256=expected_sha256,
        )

    async def stat(self, object_key: str) -> StoredFileInfo:
        return await self._delegate.stat(object_key)

    async def link_existing(
        self,
        source_object_key: str,
        target_object_key: str,
        *,
        expected_sha256: str,
    ) -> StoredFileInfo:
        raise StorageObjectError(
            "云端存储不支持本地硬链接",
            status_code=409,
            code="zero_copy_unavailable",
        )

    async def open_read(self, object_key: str) -> Path:
        return await self._delegate.open_read(object_key)

    async def delete_replica(self, object_key: str) -> None:
        await self._delegate.delete_replica(object_key)

    async def test_connection(self) -> bool:
        return await self._delegate.test_connection()


def build_object_key(object_id: UUID, original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower()
    if (
        not suffix
        or len(suffix) > 12
        or not all(character.isalnum() or character == "." for character in suffix)
    ):
        suffix = ".bin"
    identifier = object_id.hex
    return f"objects/{identifier[:2]}/{object_id}/content{suffix}"


class StorageManager:
    def __init__(
        self,
        repository: StorageRepository,
        workspace: WorkspaceManager,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self._drivers: dict[UUID, StorageDriver] = {}

    def bind_local_location(self, storage_location_id: UUID) -> None:
        self.register_driver(storage_location_id, LocalFileStorageDriver(self.workspace.root))

    def register_driver(self, storage_location_id: UUID, driver: StorageDriver) -> None:
        self._drivers[storage_location_id] = driver

    async def replicate_object(
        self,
        object_id: UUID,
        target_location_id: UUID,
    ) -> ObjectReplica:
        storage_object = await self.get_object(object_id)
        target_driver = self._drivers.get(target_location_id)
        if target_driver is None:
            raise StorageObjectError(
                "目标存储位置在当前设备不可用",
                status_code=409,
                code="storage_location_unavailable",
            )
        replicas = await self.repository.list_object_replicas(object_id)
        existing = next(
            (item for item in replicas if item.storage_location_id == target_location_id),
            None,
        )
        if existing is not None and existing.state == ObjectReplicaState.AVAILABLE:
            try:
                info = await target_driver.stat(existing.object_key)
                if (
                    info.sha256 == storage_object.sha256
                    and info.size_bytes == storage_object.size_bytes
                ):
                    return existing
            except StorageObjectError:
                pass

        source = next(
            (
                (item, self._drivers[item.storage_location_id])
                for item in replicas
                if item.state == ObjectReplicaState.AVAILABLE
                and item.storage_location_id in self._drivers
                and item.storage_location_id != target_location_id
            ),
            None,
        )
        if source is None:
            raise StorageObjectError(
                "没有可用于复制的源副本",
                status_code=409,
                code="replica_source_unavailable",
            )
        source_replica, source_driver = source
        source_path = await source_driver.open_read(source_replica.object_key)
        payload = await asyncio.to_thread(source_path.read_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != storage_object.sha256:
            raise StorageObjectError(
                "源副本校验和不一致",
                status_code=409,
                code="checksum_mismatch",
            )
        object_key = source_replica.object_key
        replica = (
            existing.model_copy(
                update={
                    "object_key": object_key,
                    "state": ObjectReplicaState.UPLOADING,
                    "checksum": digest,
                    "updated_at": utc_now(),
                }
            )
            if existing is not None
            else ObjectReplica(
                storage_object_id=object_id,
                storage_location_id=target_location_id,
                object_key=object_key,
                state=ObjectReplicaState.UPLOADING,
                checksum=digest,
            )
        )
        await self.repository.save_object_replica(replica)
        try:
            info = await target_driver.put(
                object_key,
                payload,
                expected_sha256=digest,
            )
        except Exception:
            failed = replica.model_copy(
                update={"state": ObjectReplicaState.FAILED, "updated_at": utc_now()}
            )
            await self.repository.save_object_replica(failed)
            raise
        available = replica.model_copy(
            update={
                "state": ObjectReplicaState.AVAILABLE,
                "etag": info.etag,
                "last_verified_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_object_replica(available)
        return available

    async def register_existing_local_object(
        self,
        *,
        account_id: UUID | None = None,
        workspace_id: UUID,
        storage_location_id: UUID,
        object_type: StorageObjectType,
        original_filename: str,
        mime_type: str,
        object_key: str,
        expected_sha256: str | None = None,
    ) -> StorageObject:
        """Adopt an existing workspace file via a durable local hard link."""

        driver = self._drivers.get(storage_location_id)
        if driver is None or not driver.is_local:
            raise StorageObjectError(
                "现有文件只能登记到当前设备的本地存储位置",
                status_code=409,
                code="local_storage_location_required",
            )
        info = await driver.stat(object_key)
        if expected_sha256 is not None and info.sha256 != expected_sha256:
            raise StorageObjectError(
                "现有文件校验和与旧资产记录不一致",
                status_code=409,
                code="checksum_mismatch",
            )
        filename = Path(original_filename or "file.bin").name.strip()[:255] or "file.bin"
        storage_object = StorageObject(
            account_id=account_id,
            workspace_id=workspace_id,
            origin_workspace_id=workspace_id,
            object_type=object_type,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=info.size_bytes,
            sha256=info.sha256,
        )
        canonical_object_key = build_object_key(storage_object.id, filename)
        adopted_info = await driver.link_existing(
            object_key,
            canonical_object_key,
            expected_sha256=info.sha256,
        )
        replica = ObjectReplica(
            account_id=account_id,
            storage_object_id=storage_object.id,
            storage_location_id=storage_location_id,
            object_key=canonical_object_key,
            state=ObjectReplicaState.AVAILABLE,
            etag=adopted_info.etag,
            checksum=adopted_info.sha256,
            last_verified_at=utc_now(),
        )
        await self.repository.save_storage_bundle(storage_object, replica)
        return storage_object


    async def save_object(
        self,
        *,
        account_id: UUID | None = None,
        workspace_id: UUID,
        storage_location_id: UUID,
        object_type: StorageObjectType,
        original_filename: str,
        mime_type: str,
        payload: bytes,
    ) -> StorageObject:
        driver = self._drivers.get(storage_location_id)
        if driver is None:
            raise StorageObjectError(
                "目标存储位置在当前设备不可用",
                status_code=409,
                code="storage_location_unavailable",
            )
        filename = Path(original_filename or "file.bin").name.strip()[:255] or "file.bin"
        digest = hashlib.sha256(payload).hexdigest()
        storage_object = StorageObject(
            account_id=account_id,
            workspace_id=workspace_id,
            origin_workspace_id=workspace_id,
            object_type=object_type,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(payload),
            sha256=digest,
        )
        object_key = build_object_key(storage_object.id, filename)
        replica = ObjectReplica(
            account_id=account_id,
            storage_object_id=storage_object.id,
            storage_location_id=storage_location_id,
            object_key=object_key,
            state=ObjectReplicaState.UPLOADING,
            checksum=digest,
        )
        try:
            info = await driver.put(object_key, payload, expected_sha256=digest)
            replica = replica.model_copy(
                update={
                    "state": ObjectReplicaState.AVAILABLE,
                    "etag": info.etag,
                    "last_verified_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_storage_bundle(storage_object, replica)
        except Exception:
            await driver.delete_replica(object_key)
            raise
        return storage_object

    async def get_object(self, object_id: UUID) -> StorageObject:
        storage_object = await self.repository.get_storage_object(object_id)
        if storage_object is None or storage_object.deleted_at is not None:
            raise StorageObjectError(
                "存储对象不存在",
                status_code=404,
                code="storage_object_not_found",
            )
        return storage_object

    async def list_replicas(self, object_id: UUID) -> list[ObjectReplica]:
        await self.get_object(object_id)
        return await self.repository.list_object_replicas(object_id)

    async def materialize_local(self, object_id: UUID) -> Path:
        storage_object = await self.get_object(object_id)
        replicas = await self.repository.list_object_replicas(object_id)
        candidates = sorted(
            (
                replica
                for replica in replicas
                if replica.state == ObjectReplicaState.AVAILABLE
                and self._drivers.get(replica.storage_location_id) is not None
                and self._drivers[replica.storage_location_id].is_local
            ),
            key=lambda replica: (replica.is_cache, replica.created_at),
        )
        for replica in candidates:
            driver = self._drivers[replica.storage_location_id]
            try:
                info = await driver.stat(replica.object_key)
            except StorageObjectError as exc:
                state = (
                    ObjectReplicaState.MISSING
                    if exc.code == "replica_missing"
                    else ObjectReplicaState.FAILED
                )
                await self.repository.save_object_replica(
                    replica.model_copy(update={"state": state, "updated_at": utc_now()})
                )
                continue
            if (
                info.size_bytes != storage_object.size_bytes
                or info.sha256 != storage_object.sha256
                or (replica.checksum is not None and info.sha256 != replica.checksum)
            ):
                await self.repository.save_object_replica(
                    replica.model_copy(
                        update={
                            "state": ObjectReplicaState.FAILED,
                            "last_verified_at": utc_now(),
                            "updated_at": utc_now(),
                        }
                    )
                )
                continue
            if replica.etag != info.etag or replica.last_verified_at is None:
                await self.repository.save_object_replica(
                    replica.model_copy(
                        update={
                            "etag": info.etag,
                            "last_verified_at": utc_now(),
                            "updated_at": utc_now(),
                        }
                    )
                )
            return info.path
        cloud_available = any(
            replica.state == ObjectReplicaState.AVAILABLE
            and (driver := self._drivers.get(replica.storage_location_id)) is not None
            and not driver.is_local
            for replica in replicas
        )
        raise StorageObjectError(
            (
                "对象仅有云端副本，需要先下载到本机"
                if cloud_available
                else "当前设备没有可读取的本地副本"
            ),
            status_code=409,
            code="download_required" if cloud_available else "local_replica_unavailable",
        )

    async def availability(self, object_id: UUID) -> tuple[StorageAvailability, StorageSyncState]:
        await self.get_object(object_id)
        replicas = await self.repository.list_object_replicas(object_id)
        available = [item for item in replicas if item.state == ObjectReplicaState.AVAILABLE]
        local = any(
            (driver := self._drivers.get(item.storage_location_id)) is not None and driver.is_local
            for item in available
        )
        cloud = any(
            (driver := self._drivers.get(item.storage_location_id)) is not None
            and not driver.is_local
            for item in available
        )
        if local and cloud:
            sync_state = StorageSyncState.SYNCED
        elif local:
            sync_state = StorageSyncState.LOCAL_ONLY
        elif cloud:
            sync_state = StorageSyncState.CLOUD_ONLY
        elif any(
            item.state in {ObjectReplicaState.PENDING, ObjectReplicaState.UPLOADING}
            for item in replicas
        ):
            sync_state = StorageSyncState.SYNCING
        elif any(item.state == ObjectReplicaState.FAILED for item in replicas):
            sync_state = StorageSyncState.UPLOAD_FAILED
        elif available:
            sync_state = StorageSyncState.DOWNLOAD_REQUIRED
        else:
            sync_state = StorageSyncState.UNAVAILABLE
        return StorageAvailability(local=local, cloud=cloud), sync_state

    async def response(self, object_id: UUID) -> StorageObjectResponse:
        storage_object = await self.get_object(object_id)
        availability, sync_state = await self.availability(object_id)
        return StorageObjectResponse(
            **storage_object.model_dump(),
            availability=availability,
            sync_state=sync_state,
            content_url=f"/api/v1/storage-objects/{object_id}/content",
        )

    async def replica_responses(self, object_id: UUID) -> list[ObjectReplicaResponse]:
        replicas = await self.list_replicas(object_id)
        return [
            ObjectReplicaResponse.model_validate(replica.model_dump(exclude={"object_key", "etag"}))
            for replica in replicas
        ]


class ContentResolver:
    def __init__(self, storage: StorageManager) -> None:
        self.storage = storage

    async def resolve_local(self, object_id: UUID) -> tuple[Path, StorageObject]:
        storage_object = await self.storage.get_object(object_id)
        path = await self.storage.materialize_local(object_id)
        return path, storage_object
