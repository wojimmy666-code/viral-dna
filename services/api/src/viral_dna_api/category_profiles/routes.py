from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from .contracts import (
    CategoryProfile,
    CategoryProfileCreate,
    CategoryProfileListResponse,
    CategoryProfileRevisionRequest,
    CategoryProfileUpdate,
)
from .service import CategoryProfileService, CategoryProfileServiceError


def create_category_profile_router(service: CategoryProfileService) -> APIRouter:
    router = APIRouter(prefix="/me/category-profiles", tags=["category-profiles"])

    def http_error(exc: CategoryProfileServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        )

    @router.get("", response_model=CategoryProfileListResponse)
    async def list_profiles(
        include_deleted: bool = False,
        q: Annotated[str | None, Query(max_length=120)] = None,
    ) -> CategoryProfileListResponse:
        return await service.list(include_deleted=include_deleted, query=q)

    @router.post("", response_model=CategoryProfile, status_code=status.HTTP_201_CREATED)
    async def create_profile(payload: CategoryProfileCreate) -> CategoryProfile:
        try:
            return await service.create(payload)
        except CategoryProfileServiceError as exc:
            raise http_error(exc) from exc

    @router.get("/{profile_id}", response_model=CategoryProfile)
    async def get_profile(profile_id: UUID) -> CategoryProfile:
        try:
            return await service.get(profile_id)
        except CategoryProfileServiceError as exc:
            raise http_error(exc) from exc

    @router.put("/{profile_id}", response_model=CategoryProfile)
    async def update_profile(
        profile_id: UUID,
        payload: CategoryProfileUpdate,
    ) -> CategoryProfile:
        try:
            return await service.update(profile_id, payload)
        except CategoryProfileServiceError as exc:
            raise http_error(exc) from exc

    @router.delete("/{profile_id}", response_model=CategoryProfile)
    async def delete_profile(
        profile_id: UUID,
        payload: CategoryProfileRevisionRequest,
    ) -> CategoryProfile:
        try:
            return await service.delete(profile_id, payload.revision)
        except CategoryProfileServiceError as exc:
            raise http_error(exc) from exc

    @router.post("/{profile_id}/restore", response_model=CategoryProfile)
    async def restore_profile(
        profile_id: UUID,
        payload: CategoryProfileRevisionRequest,
    ) -> CategoryProfile:
        try:
            return await service.restore(profile_id, payload.revision)
        except CategoryProfileServiceError as exc:
            raise http_error(exc) from exc

    return router
