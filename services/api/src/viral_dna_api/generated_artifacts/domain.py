from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class GeneratedArtifactKind(StrEnum):
    IMAGE_CANDIDATE = "image_candidate"
    VIDEO_CANDIDATE = "video_candidate"
    DEPTH_CONTROL = "depth_control"


class GeneratedArtifactStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    DELETED = "deleted"


class StorageReferenceOwner(StrEnum):
    GENERATED_ARTIFACT = "generated_artifact"
    ASSET = "asset"


class StorageReferenceRole(StrEnum):
    CONTENT = "content"
    THUMBNAIL = "thumbnail"
    PREVIEW = "preview"


class GeneratedArtifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    workspace_id: UUID
    kind: GeneratedArtifactKind
    source_entity_id: UUID
    project_id: UUID
    shot_plan_id: UUID
    generation_run_id: UUID | None = None
    revision_id: UUID | None = None
    content_object_id: UUID
    thumbnail_object_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=160)
    prompt_snapshot: str | None = Field(default=None, max_length=16000)
    input_asset_ids: list[UUID] = Field(default_factory=list, max_length=100)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    codec: str | None = Field(default=None, max_length=80)
    actual_cost_micros: int | None = Field(default=None, ge=0)
    status: GeneratedArtifactStatus = GeneratedArtifactStatus.AVAILABLE
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StorageObjectReference(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    workspace_id: UUID
    storage_object_id: UUID
    owner_type: StorageReferenceOwner
    owner_id: UUID
    role: StorageReferenceRole
    created_at: datetime = Field(default_factory=utc_now)


class AssetProvenance(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    workspace_id: UUID
    asset_id: UUID
    artifact_id: UUID
    artifact_kind: GeneratedArtifactKind
    source_entity_id: UUID
    project_id: UUID
    shot_plan_id: UUID
    generation_run_id: UUID | None = None
    revision_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    prompt_snapshot: str | None = None
    input_asset_ids: list[UUID] = Field(default_factory=list)
    actual_cost_micros: int | None = None
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
