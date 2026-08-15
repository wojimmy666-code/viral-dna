from __future__ import annotations

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import RedirectResponse

from ..models import ManagedAssetKind
from .models import ManagedAssetCatalogResponse, ManagedAssetCatalogStatusResponse
from .service import ManagedAssetCatalogService, ManagedAssetServiceError


def _raise_http(exc: ManagedAssetServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "provider_code": exc.provider_code,
            "retryable": exc.retryable,
        },
    ) from exc


def create_managed_asset_router(service: ManagedAssetCatalogService) -> APIRouter:
    router = APIRouter(prefix="/managed-assets", tags=["managed-assets"])

    @router.get(
        "/providers/{provider}/status",
        response_model=ManagedAssetCatalogStatusResponse,
    )
    async def get_status(
        provider: Literal["volc_ark"],
    ) -> ManagedAssetCatalogStatusResponse:
        return service.status()

    @router.get(
        "/providers/{provider}/catalog",
        response_model=ManagedAssetCatalogResponse,
    )
    async def get_catalog(
        provider: Literal["volc_ark"],
        kind: Annotated[ManagedAssetKind, Query()] = ManagedAssetKind.VIRTUAL_PERSON,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 24,
        group_id: Annotated[str | None, Query(max_length=256)] = None,
        query: Annotated[str | None, Query(max_length=120)] = None,
    ) -> ManagedAssetCatalogResponse:
        try:
            return await service.catalog(
                kind=kind,
                page=page,
                page_size=page_size,
                group_id=group_id,
                query=query,
            )
        except ManagedAssetServiceError as exc:
            _raise_http(exc)

    @router.get("/providers/{provider}/assets/{asset_id}/preview")
    async def get_asset_preview(
        provider: Literal["volc_ark"],
        asset_id: Annotated[str, Path(min_length=1, max_length=256)],
    ) -> RedirectResponse:
        try:
            preview_url = await service.preview_url(asset_id)
        except ManagedAssetServiceError as exc:
            _raise_http(exc)
        return RedirectResponse(
            preview_url,
            status_code=307,
            headers={"Cache-Control": "private, max-age=300"},
        )

    return router
