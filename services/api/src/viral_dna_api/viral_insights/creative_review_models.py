"""Shared requirements and field-based review, independent of model prose quotations."""

from typing import Literal

from pydantic import BaseModel, Field, StrictBool


class CreativeRequirementRule(BaseModel):
    requirement_index: int = Field(ge=1, le=24)
    kind: Literal["structure", "shared", "per_scene"]
    expected_scene_count: int | None = Field(default=None, ge=1, le=200)


class CreativeCommonRule(BaseModel):
    requirement_index: int = Field(ge=1, le=24)
    image_rule: str = Field(default="", max_length=500)
    video_rule: str = Field(default="", max_length=500)


class CreativeFieldReference(BaseModel):
    field: Literal["common_image", "common_video", "description", "image_prompt", "video_prompt"]
    scene_index: int | None = Field(default=None, ge=1, le=200)


class CreativeRequirementCheck(BaseModel):
    requirement_index: int = Field(ge=1, le=24)
    satisfied: StrictBool
    uncertain: StrictBool = False
    explanation: str = Field(min_length=1, max_length=500)
    references: list[CreativeFieldReference] = Field(default_factory=list, max_length=600)
    conflicting_scenes: list[int] = Field(default_factory=list, max_length=200)


class CreativeReviewIssue(BaseModel):
    requirement_index: int | None = None
    code: str
    severity: Literal["review", "revision"]
    message: str


class CreativeHumanReview(BaseModel):
    user_id: str | None = None
    reviewed_at: str
    content_fingerprint: str
    brief_text: str
    confirmed_requirements: list[int]
