from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..models import ManagedAssetKind, ManagedAssetMediaType


class ManagedAssetGroupSummary(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=1000)
    kind: ManagedAssetKind
    project_name: str = Field(min_length=1, max_length=128)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ManagedAssetSummary(BaseModel):
    provider: Literal["volc_ark"] = "volc_ark"
    id: str = Field(min_length=1, max_length=256)
    group_id: str = Field(min_length=1, max_length=256)
    group_name: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    kind: ManagedAssetKind
    media_type: ManagedAssetMediaType
    status: Literal["active", "processing", "failed"]
    preview_url: str | None = Field(default=None, max_length=8192)
    project_name: str = Field(min_length=1, max_length=128)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_inference_at: datetime | None = None


class ManagedAssetCatalogResponse(BaseModel):
    provider: Literal["volc_ark"] = "volc_ark"
    kind: ManagedAssetKind
    project_name: str
    region: Literal["cn-beijing", "cn-shanghai"]
    groups: list[ManagedAssetGroupSummary] = Field(default_factory=list)
    assets: list[ManagedAssetSummary] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class ManagedAssetCatalogStatusResponse(BaseModel):
    provider: Literal["volc_ark"] = "volc_ark"
    supported: bool = True
    credentials_configured: bool = False
    access_key_hint: str | None = None
    region: Literal["cn-beijing", "cn-shanghai"]
    project_name: str
    validation_status: Literal["not_configured", "valid", "unknown"]
    validation_message: str
