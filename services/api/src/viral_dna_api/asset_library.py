from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from .chinese import to_simplified
from .production import ProductionServiceError, inspect_reference_image
from .storage_objects import (
    ContentResolver,
    ObjectReplicaResponse,
    StorageAvailability,
    StorageManager,
    StorageObject,
    StorageObjectResponse,
    StorageObjectType,
    StorageSyncState,
)
from .workspace_catalog import (
    AccountContextService,
    StoragePolicy,
    StorageProviderType,
)

MAX_ASSET_IMAGE_BYTES = 15 * 1024 * 1024


def utc_now() -> datetime:
    return datetime.now(UTC)


class AssetType(StrEnum):
    PERSON = "person"
    PRODUCT = "product"
    CLOTHING = "clothing"
    SCENE = "scene"
    LOGO = "logo"
    MOTION_REFERENCE = "motion_reference"
    SPATIAL_DEPTH = "spatial_depth"
    OTHER = "other"


class AssetMediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DEPTH_VIDEO = "depth_video"


class AssetOriginKind(StrEnum):
    USER_UPLOAD = "user_upload"
    GENERATED_IMAGE = "generated_image"
    GENERATED_VIDEO = "generated_video"
    GENERATED_DEPTH = "generated_depth"
    IMPORTED_PLATFORM = "imported_platform"


class AssetRightsBasis(StrEnum):
    USER_CONFIRMED = "user_confirmed"
    SYSTEM_GENERATED = "system_generated"
    PENDING_REVIEW = "pending_review"


class AssetScope(StrEnum):
    WORKSPACE = "workspace"
    ACCOUNT = "account"


class AssetFolder(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    account_id: UUID | None = None
    scope: AssetScope = AssetScope.WORKSPACE
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)
    cover_asset_id: UUID | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = None


class Asset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    folder_id: UUID | None = None
    content_object_id: UUID
    thumbnail_object_id: UUID
    type: AssetType
    account_id: UUID | None = None
    scope: AssetScope = AssetScope.WORKSPACE
    media_kind: AssetMediaKind = AssetMediaKind.IMAGE
    content_type: AssetType | None = None
    origin_kind: AssetOriginKind = AssetOriginKind.USER_UPLOAD
    origin_artifact_id: UUID | None = None
    rights_basis: AssetRightsBasis = AssetRightsBasis.USER_CONFIRMED
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    rights_confirmed: bool = False
    rights_note: str | None = Field(default=None, max_length=1000)
    storage_policy: StoragePolicy = StoragePolicy.LOCAL_ONLY
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    codec: str | None = Field(default=None, max_length=80)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None


class AssetFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)


class AssetFolderUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=-10_000, le=10_000)
    cover_asset_id: UUID | None = None

    @model_validator(mode="after")
    def require_change(self) -> AssetFolderUpdate:
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("至少需要修改一个目录字段")
        return self


class AssetFolderCoverResponse(BaseModel):
    asset_id: UUID | None = None
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    source: Literal["manual", "automatic", "empty"]


class AssetFolderResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID | None = None
    scope: AssetScope = AssetScope.WORKSPACE
    name: str
    sort_order: int
    version: int
    asset_count: int = 0
    cover: AssetFolderCoverResponse
    created_at: datetime
    updated_at: datetime


class AssetUploadInput(BaseModel):
    folder_id: UUID | None = None
    target_location_id: UUID | None = None
    storage_policy: StoragePolicy = StoragePolicy.LOCAL_ONLY
    type: AssetType
    name: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    rights_confirmed: bool = False
    rights_note: str | None = Field(default=None, max_length=1000)


class AssetUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    folder_id: UUID | None = None
    type: AssetType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)
    rights_confirmed: bool | None = None
    rights_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_change(self) -> AssetUpdate:
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("至少需要修改一个资产字段")
        return self


class AssetResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    folder_id: UUID | None = None
    folder_name: str | None = None
    content_object_id: UUID
    thumbnail_object_id: UUID
    type: AssetType
    account_id: UUID | None = None
    scope: AssetScope = AssetScope.WORKSPACE
    media_kind: AssetMediaKind = AssetMediaKind.IMAGE
    content_type: AssetType | None = None
    origin_kind: AssetOriginKind = AssetOriginKind.USER_UPLOAD
    origin_artifact_id: UUID | None = None
    rights_basis: AssetRightsBasis = AssetRightsBasis.USER_CONFIRMED
    name: str
    description: str
    tags: list[str]
    rights_confirmed: bool
    rights_note: str | None = None
    storage_policy: StoragePolicy
    availability: StorageAvailability
    sync_state: StorageSyncState
    mime_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    duration_seconds: float | None = None
    fps: float | None = None
    codec: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    content_url: str
    thumbnail_url: str


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class AssetLibraryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        code: str = "asset_library_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class AssetRepository(Protocol):
    async def save_asset_folder(self, folder: AssetFolder) -> AssetFolder: ...

    async def get_asset_folder(self, folder_id: UUID) -> AssetFolder | None: ...

    async def list_asset_folders(self) -> list[AssetFolder]: ...

    async def save_asset(self, asset: Asset) -> Asset: ...

    async def get_asset(self, asset_id: UUID) -> Asset | None: ...

    async def list_assets(self) -> list[Asset]: ...


def _text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    normalized = " ".join((to_simplified(value or "") or "").split()).strip()
    if not normalized and not allow_empty:
        raise AssetLibraryError(
            f"{field_name}不能为空",
            status_code=422,
            code="invalid_text",
        )
    if len(normalized) > max_length:
        raise AssetLibraryError(
            f"{field_name}不能超过 {max_length} 个字符",
            status_code=422,
            code="invalid_text",
        )
    return normalized


def normalize_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = _text(
            value,
            field_name="标签",
            max_length=80,
            allow_empty=True,
        )
        if tag and tag not in normalized:
            normalized.append(tag)
    if len(normalized) > 20:
        raise AssetLibraryError(
            "资产标签不能超过 20 个",
            status_code=422,
            code="too_many_tags",
        )
    return normalized


class AssetLibraryService:
    def __init__(
        self,
        repository: AssetRepository,
        storage: StorageManager,
        account_context: AccountContextService,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.content = ContentResolver(storage)
        self.account_context = account_context
        self._lock = asyncio.Lock()

    async def _active_context(self, workspace_id: UUID | None = None):
        context = await self.account_context.ensure_current()
        active_workspace = context.active_workspace
        if workspace_id is not None and active_workspace.id != workspace_id:
            raise AssetLibraryError(
                "请先切换到该工作区再管理资产",
                status_code=409,
                code="workspace_not_active",
            )
        local_location = next(
            (
                location
                for location in context.storage_locations
                if location.provider_type == StorageProviderType.LOCAL_FILESYSTEM
            ),
            None,
        )
        if local_location is None:
            raise AssetLibraryError(
                "当前工作区没有可写的本地存储位置",
                status_code=409,
                code="local_storage_unavailable",
            )
        self.storage.bind_local_location(local_location.id)
        return context, local_location

    async def list_folders(self, workspace_id: UUID) -> list[AssetFolderResponse]:
        await self._active_context(workspace_id)
        folders = [
            item
            for item in await self.repository.list_asset_folders()
            if item.workspace_id == workspace_id and item.deleted_at is None
        ]
        assets = [
            item
            for item in await self.repository.list_assets()
            if item.workspace_id == workspace_id and item.archived_at is None
        ]
        assets_by_folder: dict[UUID, list[Asset]] = {}
        for asset in assets:
            if asset.folder_id is not None:
                assets_by_folder.setdefault(asset.folder_id, []).append(asset)
        return [
            self._folder_response(folder, assets_by_folder.get(folder.id, []))
            for folder in sorted(
                folders,
                key=lambda item: (item.sort_order, item.name.casefold(), str(item.id)),
            )
        ]

    async def create_folder(
        self,
        workspace_id: UUID,
        payload: AssetFolderCreate,
    ) -> AssetFolderResponse:
        context, _ = await self._active_context(workspace_id)
        name = _text(payload.name, field_name="目录名称", max_length=120)
        async with self._lock:
            await self._require_unique_folder_name(workspace_id, name)
            folder = AssetFolder(
                workspace_id=workspace_id,
                account_id=context.account.id,
                name=name,
                sort_order=payload.sort_order,
            )
            await self.repository.save_asset_folder(folder)
        return self._folder_response(folder, [])

    async def update_folder(
        self,
        folder_id: UUID,
        payload: AssetFolderUpdate,
    ) -> AssetFolderResponse:
        async with self._lock:
            folder = await self._require_folder(folder_id)
            await self._active_context(folder.workspace_id)
            if folder.version != payload.expected_version:
                raise AssetLibraryError(
                    "目录已被其他操作更新，请刷新后重试",
                    status_code=409,
                    code="folder_version_conflict",
                )
            updates: dict[str, object] = {
                "version": folder.version + 1,
                "updated_at": utc_now(),
            }
            if "name" in payload.model_fields_set:
                name = _text(payload.name, field_name="目录名称", max_length=120)
                await self._require_unique_folder_name(
                    folder.workspace_id,
                    name,
                    exclude_id=folder.id,
                )
                updates["name"] = name
            if "sort_order" in payload.model_fields_set:
                updates["sort_order"] = payload.sort_order
            if "cover_asset_id" in payload.model_fields_set:
                if payload.cover_asset_id is not None:
                    cover_asset = await self._require_asset(payload.cover_asset_id)
                    if cover_asset.archived_at is not None:
                        raise AssetLibraryError(
                            "已归档资产不能设为目录封面",
                            status_code=409,
                            code="folder_cover_asset_archived",
                        )
                    if (
                        cover_asset.workspace_id != folder.workspace_id
                        or cover_asset.folder_id != folder.id
                    ):
                        raise AssetLibraryError(
                            "目录封面必须使用当前目录中的资产",
                            status_code=409,
                            code="folder_cover_asset_mismatch",
                        )
                updates["cover_asset_id"] = payload.cover_asset_id
            updated = folder.model_copy(update=updates)
            await self.repository.save_asset_folder(updated)
        active_assets = [
            item
            for item in await self.repository.list_assets()
            if item.folder_id == folder_id and item.archived_at is None
        ]
        return self._folder_response(updated, active_assets)

    async def delete_folder(
        self,
        folder_id: UUID,
        *,
        move_assets_to_unfiled: bool,
    ) -> None:
        async with self._lock:
            folder = await self._require_folder(folder_id)
            await self._active_context(folder.workspace_id)
            assets = [
                item
                for item in await self.repository.list_assets()
                if item.workspace_id == folder.workspace_id and item.folder_id == folder.id
            ]
            if assets and not move_assets_to_unfiled:
                raise AssetLibraryError(
                    "目录中仍有资产，请先移动资产或选择移到未分类",
                    status_code=409,
                    code="folder_not_empty",
                )
            now = utc_now()
            for asset in assets:
                await self.repository.save_asset(
                    asset.model_copy(
                        update={
                            "folder_id": None,
                            "version": asset.version + 1,
                            "updated_at": now,
                        }
                    )
                )
            await self.repository.save_asset_folder(
                folder.model_copy(
                    update={
                        "deleted_at": now,
                        "version": folder.version + 1,
                        "updated_at": now,
                    }
                )
            )

    async def upload_asset(
        self,
        workspace_id: UUID,
        payload: AssetUploadInput,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> AssetResponse:
        context, local_location = await self._active_context(workspace_id)
        if payload.storage_policy != StoragePolicy.LOCAL_ONLY:
            raise AssetLibraryError(
                "当前版本只支持仅本地存储策略",
                status_code=422,
                code="storage_policy_not_supported",
            )
        if payload.target_location_id not in {None, local_location.id}:
            raise AssetLibraryError(
                "当前版本只能上传到默认本地存储位置",
                status_code=422,
                code="storage_location_not_supported",
            )
        if not payload.rights_confirmed:
            raise AssetLibraryError(
                "请先确认拥有该资产的使用权",
                status_code=422,
                code="rights_confirmation_required",
            )
        if payload.folder_id is not None:
            folder = await self._require_folder(payload.folder_id)
            if folder.workspace_id != workspace_id:
                raise AssetLibraryError(
                    "资产目录不属于当前工作区",
                    status_code=409,
                    code="folder_workspace_mismatch",
                )
        try:
            image = await asyncio.to_thread(
                inspect_reference_image,
                file_payload,
                declared_mime_type,
            )
        except ProductionServiceError as exc:
            raise AssetLibraryError(
                str(exc),
                status_code=exc.status_code,
                code=exc.code,
            ) from exc

        asset_id = uuid4()
        original_stem = Path(filename or "asset").stem.strip()[:180] or "asset"
        original_filename = f"{original_stem}{image.extension}"
        name = _text(
            payload.name or original_stem,
            field_name="资产名称",
            max_length=120,
        )
        description = _text(
            payload.description,
            field_name="资产说明",
            max_length=2000,
            allow_empty=True,
        )
        rights_note = (
            _text(
                payload.rights_note,
                field_name="权利说明",
                max_length=1000,
                allow_empty=True,
            )
            if payload.rights_note is not None
            else None
        )
        content_object = await self.storage.save_object(
            account_id=context.account.id,
            workspace_id=context.active_workspace.id,
            storage_location_id=local_location.id,
            object_type=StorageObjectType.ASSET_IMAGE,
            original_filename=original_filename,
            mime_type=image.mime_type,
            payload=file_payload,
        )
        thumbnail_object = await self.storage.save_object(
            account_id=context.account.id,
            workspace_id=context.active_workspace.id,
            storage_location_id=local_location.id,
            object_type=StorageObjectType.THUMBNAIL,
            original_filename=f"{asset_id}-thumbnail.webp",
            mime_type="image/webp",
            payload=image.thumbnail,
        )
        asset = Asset(
            id=asset_id,
            workspace_id=workspace_id,
            account_id=context.account.id,
            folder_id=payload.folder_id,
            content_object_id=content_object.id,
            thumbnail_object_id=thumbnail_object.id,
            type=payload.type,
            content_type=payload.type,
            name=name,
            description=description,
            tags=normalize_tags(payload.tags),
            rights_confirmed=True,
            rights_note=rights_note,
            storage_policy=StoragePolicy.LOCAL_ONLY,
            width=image.width,
            height=image.height,
        )
        await self.repository.save_asset(asset)
        folders = await self._folder_map(workspace_id)
        return await self._response(asset, folders)

    async def list_assets(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        folder_id: str | None,
        asset_type: AssetType | None,
        query: str | None,
        storage_state: StorageSyncState | None,
        include_archived: bool,
    ) -> AssetListResponse:
        await self._active_context(workspace_id)
        assets = [
            item
            for item in await self.repository.list_assets()
            if item.workspace_id == workspace_id and (include_archived or item.archived_at is None)
        ]
        if folder_id == "unfiled":
            assets = [item for item in assets if item.folder_id is None]
        elif folder_id:
            try:
                selected_folder_id = UUID(folder_id)
            except ValueError as exc:
                raise AssetLibraryError(
                    "资产目录筛选值无效",
                    status_code=422,
                    code="invalid_folder_filter",
                ) from exc
            assets = [item for item in assets if item.folder_id == selected_folder_id]
        if asset_type is not None:
            assets = [item for item in assets if item.type == asset_type]
        normalized_query = _text(
            query,
            field_name="搜索词",
            max_length=120,
            allow_empty=True,
        ).casefold()
        if normalized_query:
            assets = [
                item
                for item in assets
                if normalized_query
                in " ".join([item.name, item.description, *item.tags]).casefold()
            ]
        folders = await self._folder_map(workspace_id)
        responses = await asyncio.gather(*(self._response(item, folders) for item in assets))
        if storage_state is not None:
            responses = [item for item in responses if item.sync_state == storage_state]
        responses.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
        total = len(responses)
        total_pages = (total + page_size - 1) // page_size
        if total_pages:
            page = min(page, total_pages)
        else:
            page = 1
        start = (page - 1) * page_size
        return AssetListResponse(
            items=responses[start : start + page_size],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )

    async def get_asset(self, asset_id: UUID) -> AssetResponse:
        asset = await self._require_asset(asset_id)
        await self._active_context(asset.workspace_id)
        return await self._response(asset, await self._folder_map(asset.workspace_id))

    async def update_asset(self, asset_id: UUID, payload: AssetUpdate) -> AssetResponse:
        async with self._lock:
            asset = await self._require_asset(asset_id)
            await self._active_context(asset.workspace_id)
            if asset.archived_at is not None:
                raise AssetLibraryError(
                    "已归档资产需要先恢复后才能编辑",
                    status_code=409,
                    code="asset_archived",
                )
            if asset.version != payload.expected_version:
                raise AssetLibraryError(
                    "资产已被其他操作更新，请刷新后重试",
                    status_code=409,
                    code="asset_version_conflict",
                )
            now = utc_now()
            updates: dict[str, object] = {
                "version": asset.version + 1,
                "updated_at": now,
            }
            fields = payload.model_fields_set - {"expected_version"}
            if "folder_id" in fields:
                if payload.folder_id is not None:
                    folder = await self._require_folder(payload.folder_id)
                    if folder.workspace_id != asset.workspace_id:
                        raise AssetLibraryError(
                            "资产目录不属于当前工作区",
                            status_code=409,
                            code="folder_workspace_mismatch",
                        )
                if payload.folder_id != asset.folder_id:
                    await self._clear_manual_cover(asset.folder_id, asset.id, now)
                updates["folder_id"] = payload.folder_id
            if "type" in fields:
                updates["type"] = payload.type
            if "name" in fields:
                updates["name"] = _text(
                    payload.name,
                    field_name="资产名称",
                    max_length=120,
                )
            if "description" in fields:
                updates["description"] = _text(
                    payload.description,
                    field_name="资产说明",
                    max_length=2000,
                    allow_empty=True,
                )
            if "tags" in fields:
                updates["tags"] = normalize_tags(payload.tags or [])
            if "rights_confirmed" in fields:
                updates["rights_confirmed"] = bool(payload.rights_confirmed)
            if "rights_note" in fields:
                updates["rights_note"] = (
                    _text(
                        payload.rights_note,
                        field_name="权利说明",
                        max_length=1000,
                        allow_empty=True,
                    )
                    if payload.rights_note is not None
                    else None
                )
            updated = asset.model_copy(update=updates)
            await self.repository.save_asset(updated)
        return await self._response(updated, await self._folder_map(asset.workspace_id))

    async def archive_asset(self, asset_id: UUID) -> AssetResponse:
        async with self._lock:
            asset = await self._require_asset(asset_id)
            await self._active_context(asset.workspace_id)
            if asset.archived_at is None:
                now = utc_now()
                await self._clear_manual_cover(asset.folder_id, asset.id, now)
                asset = asset.model_copy(
                    update={
                        "archived_at": now,
                        "updated_at": now,
                        "version": asset.version + 1,
                    }
                )
                await self.repository.save_asset(asset)
        return await self._response(asset, await self._folder_map(asset.workspace_id))

    async def restore_asset(self, asset_id: UUID) -> AssetResponse:
        async with self._lock:
            asset = await self._require_asset(asset_id)
            await self._active_context(asset.workspace_id)
            if asset.archived_at is not None:
                asset = asset.model_copy(
                    update={
                        "archived_at": None,
                        "updated_at": utc_now(),
                        "version": asset.version + 1,
                    }
                )
                await self.repository.save_asset(asset)
        return await self._response(asset, await self._folder_map(asset.workspace_id))

    async def resolve_asset_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool,
    ) -> tuple[Path, StorageObject]:
        asset = await self._require_asset(asset_id)
        await self._active_context(asset.workspace_id)
        object_id = asset.thumbnail_object_id if thumbnail else asset.content_object_id
        return await self.content.resolve_local(object_id)

    async def resolve_storage_object(self, object_id: UUID) -> tuple[Path, StorageObject]:
        storage_object = await self.storage.get_object(object_id)
        await self._active_context(storage_object.workspace_id)
        return await self.content.resolve_local(object_id)

    async def storage_object_response(self, object_id: UUID) -> StorageObjectResponse:
        storage_object = await self.storage.get_object(object_id)
        await self._active_context(storage_object.workspace_id)
        return await self.storage.response(object_id)

    async def replica_responses(self, object_id: UUID) -> list[ObjectReplicaResponse]:
        storage_object = await self.storage.get_object(object_id)
        await self._active_context(storage_object.workspace_id)
        return await self.storage.replica_responses(object_id)

    async def _require_folder(self, folder_id: UUID) -> AssetFolder:
        folder = await self.repository.get_asset_folder(folder_id)
        if folder is None or folder.deleted_at is not None:
            raise AssetLibraryError(
                "资产目录不存在",
                status_code=404,
                code="asset_folder_not_found",
            )
        return folder

    async def _require_asset(self, asset_id: UUID) -> Asset:
        asset = await self.repository.get_asset(asset_id)
        if asset is None:
            raise AssetLibraryError(
                "资产不存在",
                status_code=404,
                code="asset_not_found",
            )
        return asset

    async def _require_unique_folder_name(
        self,
        workspace_id: UUID,
        name: str,
        *,
        exclude_id: UUID | None = None,
    ) -> None:
        duplicate = next(
            (
                folder
                for folder in await self.repository.list_asset_folders()
                if folder.workspace_id == workspace_id
                and folder.deleted_at is None
                and folder.id != exclude_id
                and folder.name.casefold() == name.casefold()
            ),
            None,
        )
        if duplicate is not None:
            raise AssetLibraryError(
                "同名资产目录已存在",
                status_code=409,
                code="asset_folder_name_conflict",
            )

    async def _folder_map(self, workspace_id: UUID) -> dict[UUID, AssetFolder]:
        return {
            item.id: item
            for item in await self.repository.list_asset_folders()
            if item.workspace_id == workspace_id and item.deleted_at is None
        }

    @staticmethod
    def _folder_response(
        folder: AssetFolder,
        active_assets: list[Asset],
    ) -> AssetFolderResponse:
        manual_cover = next(
            (item for item in active_assets if item.id == folder.cover_asset_id),
            None,
        )
        automatic_cover = max(
            active_assets,
            key=lambda item: (item.updated_at, item.created_at, str(item.id)),
            default=None,
        )
        cover_asset = manual_cover or automatic_cover
        source: Literal["manual", "automatic", "empty"] = (
            "manual"
            if manual_cover is not None
            else "automatic"
            if automatic_cover is not None
            else "empty"
        )
        cover = AssetFolderCoverResponse(source=source)
        if cover_asset is not None:
            cover = AssetFolderCoverResponse(
                asset_id=cover_asset.id,
                thumbnail_url=f"/api/v1/assets/{cover_asset.id}/thumbnail?v={cover_asset.version}",
                width=cover_asset.width,
                height=cover_asset.height,
                source=source,
            )
        return AssetFolderResponse(
            **folder.model_dump(
                exclude={"parent_id", "deleted_at", "cover_asset_id"},
            ),
            asset_count=len(active_assets),
            cover=cover,
        )

    async def _clear_manual_cover(
        self,
        folder_id: UUID | None,
        asset_id: UUID,
        updated_at: datetime,
    ) -> None:
        if folder_id is None:
            return
        folder = await self.repository.get_asset_folder(folder_id)
        if (
            folder is None
            or folder.deleted_at is not None
            or folder.cover_asset_id != asset_id
        ):
            return
        await self.repository.save_asset_folder(
            folder.model_copy(
                update={
                    "cover_asset_id": None,
                    "version": folder.version + 1,
                    "updated_at": updated_at,
                }
            )
        )

    async def _response(
        self,
        asset: Asset,
        folders: dict[UUID, AssetFolder],
    ) -> AssetResponse:
        content_object = await self.storage.get_object(asset.content_object_id)
        availability, sync_state = await self.storage.availability(asset.content_object_id)
        folder = folders.get(asset.folder_id) if asset.folder_id is not None else None
        return AssetResponse(
            **asset.model_dump(),
            folder_name=folder.name if folder else None,
            availability=availability,
            sync_state=sync_state,
            mime_type=content_object.mime_type,
            size_bytes=content_object.size_bytes,
            sha256=content_object.sha256,
            content_url=f"/api/v1/assets/{asset.id}/content",
            thumbnail_url=f"/api/v1/assets/{asset.id}/thumbnail?v={asset.version}",
        )
