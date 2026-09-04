from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status

from ..workspace_catalog import AccountContextService
from .contracts import (
    AccountSkillFavorite,
    PlatformSkillVersion,
    SkillCatalogItem,
    SkillCatalogListResponse,
    SkillCatalogState,
    SkillLifecycle,
    SkillValidationResult,
    SkillVersionCreate,
)
from .service import MAX_SKILL_PACKAGE_BYTES, PlatformSkillCatalogService, PlatformSkillError


class SkillFavoriteRepository(Protocol):
    async def save_skill_favorite(
        self,
        favorite: AccountSkillFavorite,
    ) -> AccountSkillFavorite: ...

    async def list_skill_favorites(
        self,
        account_id: UUID,
    ) -> list[AccountSkillFavorite]: ...

    async def delete_skill_favorite(self, account_id: UUID, skill_id: str) -> None: ...


def _raise_http(exc: PlatformSkillError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


async def _favorite_ids(
    repository: SkillFavoriteRepository,
    account_context: AccountContextService,
) -> tuple[UUID, set[str]]:
    account = await account_context.current_account()
    favorites = await repository.list_skill_favorites(account.id)
    return account.id, {item.skill_id for item in favorites}


def create_platform_skill_router(
    service: PlatformSkillCatalogService,
    repository: SkillFavoriteRepository,
    account_context: AccountContextService,
) -> APIRouter:
    router = APIRouter(tags=["platform-skills"])

    @router.get("/skills", response_model=SkillCatalogListResponse)
    async def list_skills(
        query: Annotated[str | None, Query(max_length=120)] = None,
        category: Annotated[str | None, Query(max_length=60)] = None,
        favorites_only: Annotated[bool, Query()] = False,
    ) -> SkillCatalogListResponse:
        _, favorites = await _favorite_ids(repository, account_context)
        payload = await service.list_catalog(
            query=query,
            category=category,
            favorite_skill_ids=favorites,
        )
        if favorites_only:
            payload.items = [item for item in payload.items if item.favorited]
            payload.total = len(payload.items)
        return payload

    @router.get("/skills/{slug}", response_model=SkillCatalogItem)
    async def get_skill(slug: str) -> SkillCatalogItem:
        _, favorites = await _favorite_ids(repository, account_context)
        try:
            return await service.get_catalog_item(slug, favorite_skill_ids=favorites)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.get(
        "/skills/{slug}/versions/{version_id}",
        response_model=PlatformSkillVersion,
    )
    async def get_skill_version(slug: str, version_id: UUID) -> PlatformSkillVersion:
        try:
            item = await service.get_catalog_item(slug)
            version = await service.get_version(version_id)
        except PlatformSkillError as exc:
            _raise_http(exc)
        if version.skill_id != item.id:
            raise HTTPException(status_code=404, detail="Skill 版本不存在")
        return version

    @router.post("/skills/{skill_id}/favorite", response_model=AccountSkillFavorite)
    async def favorite_skill(skill_id: str) -> AccountSkillFavorite:
        account_id, favorites = await _favorite_ids(repository, account_context)
        state = await service.list_admin()
        if not any(
            item.id == skill_id and item.lifecycle == SkillLifecycle.PUBLISHED
            for item in state.skills
        ):
            raise HTTPException(status_code=404, detail="Skill 不存在")
        if skill_id in favorites:
            existing = await repository.list_skill_favorites(account_id)
            return next(item for item in existing if item.skill_id == skill_id)
        return await repository.save_skill_favorite(
            AccountSkillFavorite(account_id=account_id, skill_id=skill_id)
        )

    @router.delete("/skills/{skill_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
    async def unfavorite_skill(skill_id: str) -> Response:
        account = await account_context.current_account()
        await repository.delete_skill_favorite(account.id, skill_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def create_platform_skill_admin_router(
    service: PlatformSkillCatalogService,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["platform-skill-admin"])

    @router.get("/skills", response_model=SkillCatalogState)
    async def list_admin_skills() -> SkillCatalogState:
        return await service.list_admin()

    @router.post(
        "/skill-versions",
        response_model=PlatformSkillVersion,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_version(payload: SkillVersionCreate) -> PlatformSkillVersion:
        try:
            return await service.create_version(payload)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.put("/skill-versions/{version_id}", response_model=PlatformSkillVersion)
    async def update_version(
        version_id: UUID,
        payload: SkillVersionCreate,
    ) -> PlatformSkillVersion:
        try:
            return await service.update_draft(version_id, payload)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-versions/import",
        response_model=PlatformSkillVersion,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_version(
        package: Annotated[UploadFile, File()],
        changelog: Annotated[str, Query(max_length=1000)] = "",
    ) -> PlatformSkillVersion:
        payload = await package.read(MAX_SKILL_PACKAGE_BYTES + 1)
        try:
            return await service.import_package(payload, changelog=changelog)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-versions/{version_id}/validate",
        response_model=SkillValidationResult,
    )
    async def validate_version(version_id: UUID) -> SkillValidationResult:
        try:
            return await service.validate_version(version_id)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-versions/{version_id}/publish",
        response_model=PlatformSkillVersion,
    )
    async def publish_version(version_id: UUID) -> PlatformSkillVersion:
        try:
            return await service.publish(version_id, None)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-versions/{version_id}/deprecate",
        response_model=PlatformSkillVersion,
    )
    async def deprecate_version(version_id: UUID) -> PlatformSkillVersion:
        try:
            return await service.set_version_status(
                version_id,
                SkillLifecycle.DEPRECATED,
            )
        except PlatformSkillError as exc:
            _raise_http(exc)

    @router.post(
        "/skill-versions/{version_id}/block",
        response_model=PlatformSkillVersion,
    )
    async def block_version(version_id: UUID) -> PlatformSkillVersion:
        try:
            return await service.set_version_status(version_id, SkillLifecycle.BLOCKED)
        except PlatformSkillError as exc:
            _raise_http(exc)

    return router
