from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .asset_library import Asset, AssetType, normalize_tags
from .chinese import to_simplified
from .models import (
    ProductionProject,
    ProjectAssetLink,
    ReferenceAsset,
    ReferenceAssetCreate,
    ReferenceAssetType,
    ReferenceAssetUpdate,
)
from .production import ProductionServiceError, inspect_reference_image
from .storage_objects import StorageManager, StorageObjectError, StorageObjectType
from .workspace import WorkspaceManager
from .workspace_catalog import (
    AccountContextService,
    StoragePolicy,
    StorageProviderType,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


REFERENCE_TO_ASSET_TYPE = {
    ReferenceAssetType.PERSON: AssetType.PERSON,
    ReferenceAssetType.WARDROBE: AssetType.CLOTHING,
    ReferenceAssetType.PRODUCT: AssetType.PRODUCT,
    ReferenceAssetType.SCENE: AssetType.SCENE,
    ReferenceAssetType.PROP: AssetType.OTHER,
    ReferenceAssetType.STYLE: AssetType.OTHER,
}

ASSET_TO_REFERENCE_TYPE = {
    AssetType.PERSON: ReferenceAssetType.PERSON,
    AssetType.CLOTHING: ReferenceAssetType.WARDROBE,
    AssetType.PRODUCT: ReferenceAssetType.PRODUCT,
    AssetType.SCENE: ReferenceAssetType.SCENE,
    AssetType.LOGO: ReferenceAssetType.PROP,
    AssetType.OTHER: ReferenceAssetType.PROP,
}


class ProjectAssetRepository(Protocol):
    async def get_asset(self, asset_id: UUID) -> Asset | None: ...

    async def save_asset(self, asset: Asset) -> Asset: ...

    async def list_assets(self) -> list[Asset]: ...

    async def save_project_asset_link(self, link: ProjectAssetLink) -> ProjectAssetLink: ...

    async def list_project_asset_links(
        self,
        project_id: UUID | None = None,
    ) -> list[ProjectAssetLink]: ...

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]: ...

    async def list_reference_assets(self, project_id: UUID) -> list[ReferenceAsset]: ...


class ProjectAssetService:
    """Bridges workspace assets into projects without copying their content."""

    def __init__(
        self,
        repository: ProjectAssetRepository,
        workspace: WorkspaceManager,
        storage: StorageManager,
        account_context: AccountContextService,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.storage = storage
        self.account_context = account_context
        self._lock = asyncio.Lock()

    async def _active_context(self):
        context = await self.account_context.ensure_current()
        local_location = next(
            (
                item
                for item in context.storage_locations
                if item.provider_type == StorageProviderType.LOCAL_FILESYSTEM
            ),
            None,
        )
        if local_location is None:
            raise ProductionServiceError(
                409,
                "local_storage_unavailable",
                "当前工作区没有可用的本地存储位置",
            )
        self.storage.bind_local_location(local_location.id)
        return context, local_location

    async def bootstrap_legacy_references(self) -> dict[str, object]:
        """Idempotently register legacy project references as workspace assets."""

        context, local_location = await self._active_context()
        migrated = 0
        linked = 0
        skipped = 0
        failures: list[dict[str, str]] = []
        async with self._lock:
            projects = await self.repository.list_production_projects()
            for project in projects:
                for legacy in await self.repository.list_reference_assets(project.id):
                    try:
                        asset = await self.repository.get_asset(legacy.id)
                        if asset is None:
                            original_path = self.workspace.resolve(legacy.relative_path)
                            if not original_path.is_file():
                                raise FileNotFoundError(str(original_path))
                            payload = await asyncio.to_thread(original_path.read_bytes)
                            image = await asyncio.to_thread(
                                inspect_reference_image,
                                payload,
                                legacy.mime_type,
                            )
                            thumbnail_payload = image.thumbnail
                            thumbnail_path: Path | None = None
                            if legacy.thumbnail_relative_path:
                                thumbnail_path = self.workspace.resolve(
                                    legacy.thumbnail_relative_path
                                )
                                if thumbnail_path.is_file():
                                    thumbnail_payload = await asyncio.to_thread(
                                        thumbnail_path.read_bytes
                                    )
                            content_object = await self.storage.register_existing_local_object(
                                workspace_id=context.active_workspace.id,
                                storage_location_id=local_location.id,
                                object_type=StorageObjectType.ASSET_IMAGE,
                                original_filename=original_path.name,
                                mime_type=image.mime_type,
                                object_key=legacy.relative_path,
                                expected_sha256=legacy.sha256,
                            )
                            if thumbnail_path is not None and thumbnail_path.is_file():
                                thumbnail_object = (
                                    await self.storage.register_existing_local_object(
                                        workspace_id=context.active_workspace.id,
                                        storage_location_id=local_location.id,
                                        object_type=StorageObjectType.THUMBNAIL,
                                        original_filename=thumbnail_path.name,
                                        mime_type="image/webp",
                                        object_key=legacy.thumbnail_relative_path or "",
                                    )
                                )
                            else:
                                thumbnail_object = await self.storage.save_object(
                                    workspace_id=context.active_workspace.id,
                                    storage_location_id=local_location.id,
                                    object_type=StorageObjectType.THUMBNAIL,
                                    original_filename=f"{legacy.id}-thumbnail.webp",
                                    mime_type="image/webp",
                                    payload=thumbnail_payload,
                                )
                            asset = Asset(
                                id=legacy.id,
                                workspace_id=context.active_workspace.id,
                                content_object_id=content_object.id,
                                thumbnail_object_id=thumbnail_object.id,
                                type=REFERENCE_TO_ASSET_TYPE[legacy.type],
                                name=legacy.name,
                                description=legacy.description,
                                tags=legacy.tags,
                                rights_confirmed=legacy.rights_confirmed,
                                rights_note=legacy.rights_note,
                                storage_policy=StoragePolicy.LOCAL_ONLY,
                                width=legacy.width,
                                height=legacy.height,
                                created_at=legacy.created_at,
                                updated_at=legacy.created_at,
                                archived_at=None,
                            )
                            await self.repository.save_asset(asset)
                            migrated += 1
                        created = await self._ensure_link(
                            project,
                            asset,
                            legacy.type,
                            removed_at=legacy.archived_at,
                        )
                        linked += int(created)
                        skipped += int(not created and asset.id == legacy.id)
                    except Exception as exc:  # one damaged legacy file must not block startup
                        failures.append(
                            {
                                "project_id": str(project.id),
                                "asset_id": str(legacy.id),
                                "error": str(exc),
                            }
                        )
        return {
            "migrated": migrated,
            "linked": linked,
            "skipped": skipped,
            "failures": failures,
        }

    async def create_reference(
        self,
        project: ProductionProject,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> ReferenceAsset:
        context, local_location = await self._active_context()
        if not payload.rights_confirmed:
            raise ProductionServiceError(
                422,
                "rights_confirmation_required",
                "请先确认拥有该参考图片的使用权",
            )
        image = await asyncio.to_thread(
            inspect_reference_image,
            file_payload,
            declared_mime_type,
        )
        stem = Path(filename or payload.name or "asset").stem.strip()[:180] or "asset"
        content_object = await self.storage.save_object(
            workspace_id=context.active_workspace.id,
            storage_location_id=local_location.id,
            object_type=StorageObjectType.ASSET_IMAGE,
            original_filename=f"{stem}{image.extension}",
            mime_type=image.mime_type,
            payload=file_payload,
        )
        thumbnail_object = await self.storage.save_object(
            workspace_id=context.active_workspace.id,
            storage_location_id=local_location.id,
            object_type=StorageObjectType.THUMBNAIL,
            original_filename=f"{content_object.id}-thumbnail.webp",
            mime_type="image/webp",
            payload=image.thumbnail,
        )
        asset = Asset(
            workspace_id=context.active_workspace.id,
            content_object_id=content_object.id,
            thumbnail_object_id=thumbnail_object.id,
            type=REFERENCE_TO_ASSET_TYPE[payload.type],
            name=self._text(payload.name),
            description=self._text(payload.description, allow_empty=True),
            tags=normalize_tags(payload.tags),
            rights_confirmed=True,
            rights_note=(
                self._text(payload.rights_note, allow_empty=True)
                if payload.rights_note is not None
                else None
            ),
            storage_policy=StoragePolicy.LOCAL_ONLY,
            width=image.width,
            height=image.height,
        )
        async with self._lock:
            await self.repository.save_asset(asset)
            await self._ensure_link(project, asset, payload.type)
        return await self._projection(project.id, asset, payload.type)

    async def link_asset(
        self,
        project: ProductionProject,
        asset_id: UUID,
        reference_type: ReferenceAssetType | None = None,
    ) -> ReferenceAsset:
        context, _ = await self._active_context()
        asset = await self.repository.get_asset(asset_id)
        if asset is None or asset.archived_at is not None:
            raise ProductionServiceError(404, "asset_not_found", "资产不存在或已归档")
        if asset.workspace_id != context.active_workspace.id:
            raise ProductionServiceError(409, "asset_workspace_mismatch", "资产不属于当前工作区")
        if not asset.rights_confirmed:
            raise ProductionServiceError(
                422,
                "reference_rights_required",
                "资产尚未完成使用权确认",
            )
        resolved_type = reference_type or ASSET_TO_REFERENCE_TYPE[asset.type]
        async with self._lock:
            await self._ensure_link(project, asset, resolved_type)
        return await self._projection(project.id, asset, resolved_type)

    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]:
        links = await self.repository.list_project_asset_links(project_id)
        output: list[ReferenceAsset] = []
        for link in links:
            if link.removed_at is not None and not include_archived:
                continue
            asset = await self.repository.get_asset(link.asset_id)
            if asset is None:
                continue
            if asset.archived_at is not None and not include_archived:
                continue
            output.append(await self._projection(project_id, asset, link.reference_type, link))
        return sorted(output, key=lambda item: item.created_at)

    async def get_reference(
        self,
        asset_id: UUID,
        project_id: UUID | None = None,
        *,
        include_archived: bool = True,
    ) -> ReferenceAsset | None:
        links = await self.repository.list_project_asset_links(project_id)
        link = next(
            (
                item
                for item in links
                if item.asset_id == asset_id
                and (include_archived or item.removed_at is None)
            ),
            None,
        )
        if link is None:
            return None
        asset = await self.repository.get_asset(asset_id)
        if asset is None:
            return None
        return await self._projection(link.project_id, asset, link.reference_type, link)

    async def update_reference(
        self,
        project_id: UUID,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
    ) -> ReferenceAsset:
        reference = await self.get_reference(asset_id, project_id)
        if reference is None or reference.archived_at is not None:
            raise ProductionServiceError(404, "reference_asset_not_found", "项目参考资产不存在")
        asset = await self.repository.get_asset(asset_id)
        assert asset is not None
        fields = payload.model_fields_set - {"expected_revision_id", "confirm_stale"}
        updates: dict[str, object] = {"version": asset.version + 1, "updated_at": utc_now()}
        if "name" in fields:
            updates["name"] = self._text(payload.name)
        if "description" in fields:
            updates["description"] = self._text(payload.description, allow_empty=True)
        if "tags" in fields:
            updates["tags"] = normalize_tags(payload.tags or [])
        if "rights_confirmed" in fields:
            updates["rights_confirmed"] = bool(payload.rights_confirmed)
        if "rights_note" in fields:
            updates["rights_note"] = (
                self._text(payload.rights_note, allow_empty=True)
                if payload.rights_note is not None
                else None
            )
        updated = asset.model_copy(update=updates)
        await self.repository.save_asset(updated)
        return await self._projection(project_id, updated, reference.type)

    async def unlink_reference(self, project_id: UUID, asset_id: UUID) -> ReferenceAsset:
        links = await self.repository.list_project_asset_links(project_id)
        link = next((item for item in links if item.asset_id == asset_id), None)
        if link is None:
            raise ProductionServiceError(404, "reference_asset_not_found", "项目参考资产不存在")
        if link.removed_at is None:
            link = link.model_copy(update={"removed_at": utc_now(), "updated_at": utc_now()})
            await self.repository.save_project_asset_link(link)
        asset = await self.repository.get_asset(asset_id)
        if asset is None:
            raise ProductionServiceError(404, "asset_not_found", "资产不存在")
        return await self._projection(project_id, asset, link.reference_type, link)

    async def resolve_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool,
    ) -> tuple[Path, str]:
        asset = await self.repository.get_asset(asset_id)
        if asset is None:
            raise ProductionServiceError(404, "asset_not_found", "资产不存在")
        object_id = asset.thumbnail_object_id if thumbnail else asset.content_object_id
        try:
            storage_object = await self.storage.get_object(object_id)
            path = await self.storage.materialize_local(object_id)
        except StorageObjectError as exc:
            raise ProductionServiceError(exc.status_code, exc.code, str(exc)) from exc
        return path, storage_object.mime_type

    async def snapshot_reference(
        self,
        project_id: UUID,
        reference: ReferenceAsset,
    ) -> dict[str, object]:
        links = await self.repository.list_project_asset_links(project_id)
        link = next((item for item in links if item.asset_id == reference.id), None)
        asset = await self.repository.get_asset(reference.id)
        if link is None or asset is None:
            raise ProductionServiceError(409, "reference_asset_not_found", "项目参考资产不存在")
        content = await self.storage.get_object(asset.content_object_id)
        thumbnail = await self.storage.get_object(asset.thumbnail_object_id)
        return {
            "asset_id": str(asset.id),
            "workspace_id": str(asset.workspace_id),
            "reference_type": link.reference_type.value,
            "content_object_id": str(content.id),
            "content_sha256": content.sha256,
            "thumbnail_object_id": str(thumbnail.id),
            "thumbnail_sha256": thumbnail.sha256,
            "name": asset.name,
            "description": asset.description,
            "tags": list(asset.tags),
            "rights_confirmed": asset.rights_confirmed,
            "rights_note": asset.rights_note,
            "width": asset.width,
            "height": asset.height,
            "created_at": asset.created_at.isoformat(),
            "removed_at": link.removed_at.isoformat() if link.removed_at else None,
        }

    async def link_snapshot_reference(
        self,
        project: ProductionProject,
        payload: dict[str, object],
    ) -> ReferenceAsset:
        raw_id = payload.get("asset_id") or payload.get("id")
        if raw_id is None:
            raise ProductionServiceError(409, "invalid_revision_snapshot", "版本资产标识缺失")
        asset_id = UUID(str(raw_id))
        raw_type = payload.get("reference_type") or payload.get("type")
        reference_type = ReferenceAssetType(str(raw_type)) if raw_type else None
        return await self.link_asset(project, asset_id, reference_type)

    async def _ensure_link(
        self,
        project: ProductionProject,
        asset: Asset,
        reference_type: ReferenceAssetType,
        *,
        removed_at: datetime | None = None,
    ) -> bool:
        links = await self.repository.list_project_asset_links(project.id)
        existing = next((item for item in links if item.asset_id == asset.id), None)
        if existing is not None:
            updates: dict[str, object] = {}
            if existing.reference_type != reference_type:
                updates["reference_type"] = reference_type
            if existing.removed_at != removed_at:
                updates["removed_at"] = removed_at
            if updates:
                updates["updated_at"] = utc_now()
                await self.repository.save_project_asset_link(existing.model_copy(update=updates))
            return False
        await self.repository.save_project_asset_link(
            ProjectAssetLink(
                workspace_id=asset.workspace_id,
                project_id=project.id,
                asset_id=asset.id,
                reference_type=reference_type,
                removed_at=removed_at,
            )
        )
        return True

    async def _projection(
        self,
        project_id: UUID,
        asset: Asset,
        reference_type: ReferenceAssetType,
        link: ProjectAssetLink | None = None,
    ) -> ReferenceAsset:
        content = await self.storage.get_object(asset.content_object_id)
        thumbnail = await self.storage.get_object(asset.thumbnail_object_id)
        try:
            content_path = await self.storage.materialize_local(asset.content_object_id)
            relative_path = self.workspace.relative(content_path)
        except (StorageObjectError, ValueError):
            relative_path = f"objects/{content.id}/{content.original_filename}"
        try:
            thumbnail_path = await self.storage.materialize_local(asset.thumbnail_object_id)
            thumbnail_relative_path = self.workspace.relative(thumbnail_path)
        except (StorageObjectError, ValueError):
            thumbnail_relative_path = f"objects/{thumbnail.id}/{thumbnail.original_filename}"
        return ReferenceAsset(
            id=asset.id,
            project_id=project_id,
            type=reference_type,
            name=asset.name,
            description=asset.description,
            relative_path=relative_path,
            thumbnail_relative_path=thumbnail_relative_path,
            mime_type=content.mime_type,
            width=asset.width,
            height=asset.height,
            sha256=content.sha256,
            tags=asset.tags,
            rights_confirmed=asset.rights_confirmed,
            rights_note=asset.rights_note,
            created_at=asset.created_at,
            archived_at=(link.removed_at if link else asset.archived_at),
        )

    @staticmethod
    def _text(value: str | None, *, allow_empty: bool = False) -> str:
        normalized = (to_simplified(value or "") or "").strip()
        if not normalized and not allow_empty:
            raise ProductionServiceError(422, "invalid_text", "资产名称不能为空")
        return normalized
