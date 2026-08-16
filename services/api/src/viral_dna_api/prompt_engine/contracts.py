from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


TransitionKind = Literal[
    "none",
    "hard_cut",
    "crossfade",
    "foreground_occlusion",
    "wipe",
    "whip_pan",
    "match_cut",
    "other",
    "uncertain",
]


class PromptVisualDraft(BaseModel):
    subjects: str = Field(default="", max_length=2400)
    scene: str = Field(default="", max_length=2400)
    composition: str = Field(default="", max_length=2400)
    lighting: str = Field(default="", max_length=1600)
    color: str = Field(default="", max_length=1600)


class PromptMotionPhaseDraft(BaseModel):
    id: str = Field(default_factory=lambda: f"phase_{uuid4().hex[:12]}", max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    subject_motion: str = Field(default="", max_length=2400)
    camera_motion: str = Field(default="", max_length=1600)
    foreground_motion: str = Field(default="", max_length=1600)
    focus_change: str = Field(default="", max_length=1600)

    @model_validator(mode="after")
    def validate_time_range(self) -> PromptMotionPhaseDraft:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("阶段结束时间必须晚于开始时间")
        return self


class PromptTransitionDraft(BaseModel):
    kind: TransitionKind = "none"
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    instruction: str = Field(default="", max_length=2400)
    mask_object: str = Field(default="", max_length=500)
    direction: str = Field(default="", max_length=500)
    terminal_frame: str = Field(default="", max_length=1200)

    @model_validator(mode="after")
    def validate_time_range(self) -> PromptTransitionDraft:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("转场结束时间不能早于开始时间")
        return self


class PromptShotDraft(BaseModel):
    schema_version: Literal["prompt-shot-draft-v2"] = "prompt-shot-draft-v2"
    visual: PromptVisualDraft = Field(default_factory=PromptVisualDraft)
    phases: list[PromptMotionPhaseDraft] = Field(min_length=1, max_length=20)
    transition: PromptTransitionDraft = Field(default_factory=PromptTransitionDraft)
    continuity_refs: list[str] = Field(default_factory=list, max_length=40)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    custom_notes: str = Field(default="", max_length=2400)


class PromptShotDraftUpdate(BaseModel):
    shot_id: str = Field(min_length=1, max_length=160)
    draft: PromptShotDraft


class PromptDraftUpdateRequest(BaseModel):
    expected_revision_id: UUID
    shots: list[PromptShotDraftUpdate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_shots(self) -> PromptDraftUpdateRequest:
        shot_ids = [item.shot_id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("同一分镜不能在一次保存中重复出现")
        return self


class PromptCompileRequest(BaseModel):
    target_model: str = Field(default="seedance", min_length=1, max_length=120)
    draft: PromptShotDraft


class PromptCompileResponse(BaseModel):
    target_model: str
    compiled_prompt: str
    character_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
