"""Authored film shots stay independent from model-generation batches."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class GroupAssetMention(BaseModel):
    reference_kind: Literal["project_asset"] = "project_asset"
    reference_id: UUID
    label: str = Field(min_length=1, max_length=260)
    role: Literal["actor_identity", "composition", "scene", "product", "wardrobe", "style"] = "composition"
    order: int = Field(default=1, ge=1, le=100)


class VideoGenerationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    shot_plan_ids: list[UUID] = Field(min_length=2, max_length=20)
    video_prompt: str = Field(default="", max_length=8000)
    video_prompt_mentions: list[GroupAssetMention] = Field(default_factory=list, max_length=50)
    transition: Literal["cut", "continuous", "dissolve"] = "cut"

    @model_serializer(mode="wrap")
    def preserve_legacy_fingerprint(self, handler):
        value = handler(self)
        if not self.video_prompt_mentions:
            value.pop("video_prompt_mentions", None)
        return value

    @model_validator(mode="after")
    def unique_members(self):
        if len(set(self.shot_plan_ids)) != len(self.shot_plan_ids):
            raise ValueError("生成组不能重复包含同一分镜")
        return self


class VideoGroupClip(BaseModel):
    group_id: UUID
    candidate_id: UUID
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    trim_in_seconds: float = Field(ge=0)
    trim_out_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.trim_out_seconds <= self.trim_in_seconds:
            raise ValueError("出点必须晚于入点")
        return self


class VideoGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_id: UUID
    groups: list[VideoGenerationGroup] = Field(default_factory=list, max_length=100)


class VideoGroupCut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot_plan_id: UUID
    trim_in_seconds: float = Field(ge=0)
    trim_out_seconds: float = Field(gt=0)


class VideoGroupAdopt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_id: UUID
    candidate_id: UUID
    cuts: list[VideoGroupCut] = Field(min_length=2, max_length=20)
    content_reviewed: Literal[True]
