from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from ..asset_library import AssetResponse, AssetType
from ..generated_artifacts.domain import AssetProvenance, GeneratedArtifactKind


class GeneratedArtifactPromotionRequest(BaseModel):
    kind: GeneratedArtifactKind
    source_entity_id: UUID
    shot_plan_id: UUID | None = None
    folder_id: UUID | None = None
    asset_type: AssetType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class GeneratedArtifactBatchPromotionRequest(BaseModel):
    items: list[GeneratedArtifactPromotionRequest] = Field(min_length=1, max_length=50)


class GeneratedArtifactPromotionStatusRequest(BaseModel):
    kind: GeneratedArtifactKind
    source_entity_id: UUID


class GeneratedArtifactPromotionStatus(BaseModel):
    registered: bool
    artifact_id: UUID | None = None
    promoted: bool
    asset_id: UUID | None = None


class GeneratedArtifactPromotionResponse(BaseModel):
    artifact_id: UUID
    asset: AssetResponse
    provenance: AssetProvenance
    already_existed: bool = False


class GeneratedArtifactBatchPromotionResponse(BaseModel):
    items: list[GeneratedArtifactPromotionResponse]
