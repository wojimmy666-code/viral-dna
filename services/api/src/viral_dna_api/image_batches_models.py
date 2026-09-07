from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .models import ImageGenerationOverrides


class ImageBatchRequest(ImageGenerationOverrides):
    request_id: UUID = Field(default_factory=uuid4)
    expected_revision_id: UUID
    mode: Literal["missing", "all"] = "all"


class ImageBatchItem(BaseModel):
    shot_plan_id: UUID
    visual_beat_id: UUID
    shot_index: int
    beat_index: int
    input_fingerprint: str
    prompt_snapshot: dict | None = None
    status: Literal[
        "pending", "running", "completed", "skipped", "failed", "cancelled", "unknown"
    ] = "pending"
    run_id: UUID | None = None
    candidate_ids: list[UUID] = Field(default_factory=list)
    error_message: str = ""
    retryable: bool = False


class ImageBatch(BaseModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    mode: Literal["missing", "all"]
    model_alias: str
    model_label: str
    execution_mode: Literal["local_tool", "remote_api"] = "remote_api"
    concurrency_limit: int = 3
    allow_unknown_cost: bool = False
    image_tool_snapshot: dict = Field(default_factory=dict)
    width: int
    height: int
    candidate_count: int = 1
    estimated_cost_micros: int | None = None
    actual_cost_micros: int = 0
    status: Literal["running", "stopping", "completed", "partial", "cancelled", "interrupted"] = (
        "running"
    )
    items: list[ImageBatchItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_heartbeat_at: datetime
    completed_at: datetime | None = None
