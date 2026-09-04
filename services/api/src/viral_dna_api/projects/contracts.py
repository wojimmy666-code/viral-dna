from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectKind(StrEnum):
    ANALYSIS = "analysis"
    SKILL = "skill"


class ProjectLifecycle(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"
    ALL = "all"


class ProjectLifecycleAction(StrEnum):
    ARCHIVE = "archive"
    ACTIVATE = "activate"
    TRASH = "trash"
    RESTORE = "restore"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class ProjectStage(StrEnum):
    ANALYSIS = "analysis"
    ANALYSIS_REPORT = "analysis_report"
    CREATIVE_BRIEF = "creative_brief"
    STYLE_CONFIRMATION = "style_confirmation"
    STORYBOARD_DESIGN = "storyboard_design"
    SHOT_IMAGES = "shot_images"
    SHOT_VIDEOS = "shot_videos"
    EDITING = "editing"
    AUDIO_CAPTION = "audio_caption"
    EXPORT = "export"


class AnalysisProjectSource(BaseModel):
    kind: Literal["analysis"] = "analysis"
    record_id: UUID
    video_id: UUID
    latest_analysis_id: UUID | None = None
    source_type: str = Field(min_length=1, max_length=40)
    source_url: str | None = Field(default=None, max_length=8192)


class SkillProjectSource(BaseModel):
    kind: Literal["skill"] = "skill"
    skill_id: str = Field(min_length=3, max_length=120)
    skill_version_id: UUID
    skill_version_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    active_skill_run_id: UUID | None = None
    production_project_id: UUID | None = None


ProjectSource = Annotated[
    AnalysisProjectSource | SkillProjectSource,
    Field(discriminator="kind"),
]


class Project(BaseModel):
    schema_version: Literal["viral-dna-project/v1"] = "viral-dna-project/v1"
    id: UUID = Field(default_factory=uuid4)
    owner_account_id: UUID | None = None
    kind: ProjectKind
    name: str = Field(min_length=1, max_length=120)
    folder_id: UUID | None = None
    lifecycle: ProjectLifecycle = ProjectLifecycle.ACTIVE
    lifecycle_before_trash: ProjectLifecycle | None = None
    status: ProjectStatus = ProjectStatus.DRAFT
    active_stage: ProjectStage
    source_binding: ProjectSource
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_opened_at: datetime | None = None
    archived_at: datetime | None = None
    trashed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_source_kind(self) -> Project:
        if self.kind.value != self.source_binding.kind:
            raise ValueError("项目 kind 与 source_binding 不一致")
        if self.lifecycle == ProjectLifecycle.TRASHED and self.trashed_at is None:
            raise ValueError("回收站项目必须记录 trashed_at")
        if self.lifecycle != ProjectLifecycle.TRASHED and self.trashed_at is not None:
            raise ValueError("非回收站项目不能保留 trashed_at")
        return self


class ProjectCreate(BaseModel):
    kind: Literal["skill"]
    name: str = Field(min_length=1, max_length=120)
    skill_version_id: UUID
    folder_id: UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    folder_id: UUID | None = None


class ProjectLifecycleRequest(BaseModel):
    action: ProjectLifecycleAction


class ProjectBatchLifecycleRequest(ProjectLifecycleRequest):
    project_ids: list[UUID] = Field(min_length=1, max_length=100)


class ProjectBatchDeleteRequest(BaseModel):
    project_ids: list[UUID] = Field(min_length=1, max_length=100)


class ProjectBatchMutationResponse(BaseModel):
    affected_ids: list[UUID]
    affected_count: int = Field(ge=0)


class ProjectSummary(Project):
    source_type: str = Field(min_length=1, max_length=40)
    source_url: str | None = None
    author: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    thumbnail_url: str | None = None
    production_project_count: int = Field(default=0, ge=0)
    skill_name: str | None = None
    skill_slug: str | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)
    lifecycle_counts: dict[str, int]
