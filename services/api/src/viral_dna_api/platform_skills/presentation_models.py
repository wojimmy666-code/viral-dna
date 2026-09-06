from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class PresentationItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    image_asset_id: UUID | None = None
    video_asset_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_media(self):
        if self.image_asset_id is None and self.video_asset_id is None:
            raise ValueError("展示项至少需要一张图片或一个视频")
        return self


class PresentationItem(PresentationItemInput):
    poster_asset_id: UUID | None = None


class SkillPresentation(BaseModel):
    schema_version: Literal["viraldna.skill-presentation/v1"] = "viraldna.skill-presentation/v1"
    revision: int = 0
    primary_item_id: UUID | None = None
    items: list[PresentationItem] = Field(default_factory=list)

    @property
    def primary(self):
        return next((item for item in self.items if item.id == self.primary_item_id), None)

    @computed_field
    @property
    def cover_url(self) -> str | None:
        item = self.primary
        asset_id = (item.image_asset_id or item.poster_asset_id) if item else None
        return f"/api/v1/skill-media/{asset_id}/content" if asset_id else None

    @computed_field
    @property
    def poster_url(self) -> str | None:
        asset_id = self.primary.poster_asset_id if self.primary else None
        return f"/api/v1/skill-media/{asset_id}/content" if asset_id else None

    @computed_field
    @property
    def video_url(self) -> str | None:
        asset_id = self.primary.video_asset_id if self.primary else None
        return f"/api/v1/skill-media/{asset_id}/content" if asset_id else None


class PresentationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    primary_item_id: UUID | None = None
    # Array contract is intentional; multi-item editing is a future release.
    items: list[PresentationItemInput] = Field(default_factory=list, max_length=1)

    @model_validator(mode="after")
    def validate_primary(self):
        if self.items and self.primary_item_id != self.items[0].id:
            raise ValueError("主展示项必须指向已提交的展示项")
        if not self.items and self.primary_item_id is not None:
            raise ValueError("清空展示素材时不能保留主展示项")
        return self


class SkillMediaAsset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    skill_id: str
    kind: Literal["image", "video"]
    original_filename: str
    source_size: int = 0
    source_sha256: str = ""
    status: Literal["uploaded", "processing", "ready", "failed"] = "uploaded"
    phase: str = "等待处理"
    progress: int = Field(default=0, ge=0, le=100)
    error_message: str | None = None
    retryable: bool = False
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    poster_asset_id: UUID | None = None
    parent_asset_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def content_url(self) -> str | None:
        return f"/api/v1/admin/skill-media/{self.id}/content" if self.status == "ready" else None

    @computed_field
    @property
    def poster_url(self) -> str | None:
        return (
            f"/api/v1/admin/skill-media/{self.poster_asset_id}/content"
            if self.poster_asset_id
            else None
        )
