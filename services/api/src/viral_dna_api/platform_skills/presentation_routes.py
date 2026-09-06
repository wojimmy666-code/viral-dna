from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from .presentation_models import PresentationUpdate, SkillMediaAsset, SkillPresentation
from .routes import _raise_http
from .service import PlatformSkillError


def create_skill_presentation_router(service, require_admin):
    router = APIRouter(tags=["skill-presentation"])
    admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

    @admin.get("/skills/{skill_id}/presentation")
    async def get_presentation(skill_id: str):
        try:
            return await service.presentation(skill_id)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @admin.put("/skills/{skill_id}/presentation", response_model=SkillPresentation)
    async def save_presentation(skill_id: str, payload: PresentationUpdate):
        try:
            return await service.save(skill_id, payload)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @admin.post("/skills/{skill_id}/media", response_model=SkillMediaAsset, status_code=202)
    async def upload_media(
        skill_id: str,
        kind: Annotated[Literal["image", "video"], Form()],
        file: Annotated[UploadFile, File()],
    ):
        try:
            return await service.upload(skill_id, kind, file)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @admin.get("/skill-media/{asset_id}", response_model=SkillMediaAsset)
    async def get_media(asset_id: UUID):
        try:
            return await service.get(asset_id)
        except PlatformSkillError as exc:
            _raise_http(exc)

    @admin.post("/skill-media/{asset_id}/retry", response_model=SkillMediaAsset, status_code=202)
    async def retry_media(asset_id: UUID):
        try:
            return await service.retry(asset_id)
        except PlatformSkillError as exc:
            _raise_http(exc)

    async def response(asset_id, admin=False):
        try:
            path, mime = await service.content(asset_id, admin=admin)
            return FileResponse(
                path,
                media_type=mime,
                headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
            )
        except PlatformSkillError as exc:
            _raise_http(exc)

    @admin.get("/skill-media/{asset_id}/content")
    async def admin_content(asset_id: UUID):
        return await response(asset_id, admin=True)

    @router.get("/skill-media/{asset_id}/content")
    async def public_content(asset_id: UUID):
        return await response(asset_id)

    router.include_router(admin)
    return router
