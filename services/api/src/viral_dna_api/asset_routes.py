from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from .asset_library import (
    MAX_ASSET_IMAGE_BYTES,
    AssetFolderCreate,
    AssetFolderResponse,
    AssetFolderUpdate,
    AssetLibraryError,
    AssetLibraryService,
    AssetListResponse,
    AssetResponse,
    AssetType,
    AssetUpdate,
    AssetUploadInput,
)
from .storage_objects import (
    ObjectReplicaResponse,
    StorageObjectError,
    StorageObjectResponse,
    StorageSyncState,
)
from .workspace_catalog import StoragePolicy


def _tags(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    return [item.strip() for item in re.split(r"[,，\n]", value) if item.strip()]


def _raise_http(exc: AssetLibraryError | StorageObjectError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def create_asset_router(service: AssetLibraryService) -> APIRouter:
    router = APIRouter(tags=["assets"])

    @router.get(
        "/workspaces/{workspace_id}/asset-folders",
        response_model=list[AssetFolderResponse],
    )
    async def list_asset_folders(workspace_id: UUID) -> list[AssetFolderResponse]:
        try:
            return await service.list_folders(workspace_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.post(
        "/workspaces/{workspace_id}/asset-folders",
        response_model=AssetFolderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_asset_folder(
        workspace_id: UUID,
        payload: AssetFolderCreate,
    ) -> AssetFolderResponse:
        try:
            return await service.create_folder(workspace_id, payload)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.patch(
        "/asset-folders/{folder_id}",
        response_model=AssetFolderResponse,
    )
    async def update_asset_folder(
        folder_id: UUID,
        payload: AssetFolderUpdate,
    ) -> AssetFolderResponse:
        try:
            return await service.update_folder(folder_id, payload)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.delete(
        "/asset-folders/{folder_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_asset_folder(
        folder_id: UUID,
        move_assets_to_unfiled: Annotated[bool, Query()] = False,
    ) -> Response:
        try:
            await service.delete_folder(
                folder_id,
                move_assets_to_unfiled=move_assets_to_unfiled,
            )
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/workspaces/{workspace_id}/assets",
        response_model=AssetListResponse,
    )
    async def list_assets(
        workspace_id: UUID,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        folder_id: Annotated[str | None, Query()] = None,
        asset_type: Annotated[AssetType | None, Query(alias="type")] = None,
        query: Annotated[str | None, Query(max_length=120)] = None,
        storage_state: Annotated[StorageSyncState | None, Query()] = None,
        include_archived: Annotated[bool, Query()] = False,
    ) -> AssetListResponse:
        try:
            return await service.list_assets(
                workspace_id,
                page=page,
                page_size=page_size,
                folder_id=folder_id,
                asset_type=asset_type,
                query=query,
                storage_state=storage_state,
                include_archived=include_archived,
            )
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.post(
        "/workspaces/{workspace_id}/assets",
        response_model=AssetResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_asset(
        workspace_id: UUID,
        file: Annotated[UploadFile, File()],
        asset_type: Annotated[AssetType, Form(alias="type")],
        folder_id: Annotated[UUID | None, Form()] = None,
        target_location_id: Annotated[UUID | None, Form()] = None,
        storage_policy: Annotated[StoragePolicy, Form()] = StoragePolicy.LOCAL_ONLY,
        name: Annotated[str | None, Form()] = None,
        description: Annotated[str, Form()] = "",
        tags: Annotated[str | None, Form()] = None,
        rights_confirmed: Annotated[bool, Form()] = False,
        rights_note: Annotated[str | None, Form()] = None,
    ) -> AssetResponse:
        content = bytearray()
        try:
            while chunk := await file.read(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_ASSET_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="资产图片不能超过 15 MB")
        finally:
            await file.close()
        try:
            return await service.upload_asset(
                workspace_id,
                AssetUploadInput(
                    folder_id=folder_id,
                    target_location_id=target_location_id,
                    storage_policy=storage_policy,
                    type=asset_type,
                    name=name,
                    description=description,
                    tags=_tags(tags),
                    rights_confirmed=rights_confirmed,
                    rights_note=rights_note,
                ),
                bytes(content),
                file.filename or "asset",
                file.content_type,
            )
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.get("/assets/{asset_id}", response_model=AssetResponse)
    async def get_asset(asset_id: UUID) -> AssetResponse:
        try:
            return await service.get_asset(asset_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.patch("/assets/{asset_id}", response_model=AssetResponse)
    async def update_asset(asset_id: UUID, payload: AssetUpdate) -> AssetResponse:
        try:
            return await service.update_asset(asset_id, payload)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.delete("/assets/{asset_id}", response_model=AssetResponse)
    async def archive_asset(asset_id: UUID) -> AssetResponse:
        try:
            return await service.archive_asset(asset_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.post("/assets/{asset_id}/restore", response_model=AssetResponse)
    async def restore_asset(asset_id: UUID) -> AssetResponse:
        try:
            return await service.restore_asset(asset_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.get("/assets/{asset_id}/content")
    async def get_asset_content(asset_id: UUID) -> FileResponse:
        try:
            path, storage_object = await service.resolve_asset_content(
                asset_id,
                thumbnail=False,
            )
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)
        return FileResponse(
            path,
            media_type=storage_object.mime_type,
            filename=storage_object.original_filename,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/assets/{asset_id}/thumbnail")
    async def get_asset_thumbnail(asset_id: UUID) -> FileResponse:
        try:
            path, storage_object = await service.resolve_asset_content(
                asset_id,
                thumbnail=True,
            )
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)
        return FileResponse(
            path,
            media_type=storage_object.mime_type,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get(
        "/storage-objects/{object_id}",
        response_model=StorageObjectResponse,
    )
    async def get_storage_object(object_id: UUID) -> StorageObjectResponse:
        try:
            return await service.storage_object_response(object_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    @router.get("/storage-objects/{object_id}/content")
    async def get_storage_object_content(object_id: UUID) -> FileResponse:
        try:
            path, storage_object = await service.resolve_storage_object(object_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)
        return FileResponse(
            path,
            media_type=storage_object.mime_type,
            filename=storage_object.original_filename,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get(
        "/storage-objects/{object_id}/replicas",
        response_model=list[ObjectReplicaResponse],
    )
    async def list_storage_object_replicas(
        object_id: UUID,
    ) -> list[ObjectReplicaResponse]:
        try:
            return await service.replica_responses(object_id)
        except (AssetLibraryError, StorageObjectError) as exc:
            _raise_http(exc)

    return router
