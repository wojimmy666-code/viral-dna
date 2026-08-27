from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..models import ShotVideoGenerationDraft, VideoPromptMention


class VideoIntentCompileRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)
    intent_text: str = Field(min_length=1, max_length=4000)
    intent_mentions: list[VideoPromptMention] = Field(default_factory=list, max_length=40)
    merge_strategy: Literal["preserve_manual", "replace_all"] = "preserve_manual"

    @model_validator(mode="after")
    def validate_mentions(self) -> VideoIntentCompileRequest:
        keys = [(item.reference_kind, item.reference_id) for item in self.intent_mentions]
        if len(keys) != len(set(keys)):
            raise ValueError("创作意图不能重复引用同一资产")
        missing = [
            f"@{item.label}"
            for item in self.intent_mentions
            if f"@{item.label}" not in self.intent_text
        ]
        if missing:
            raise ValueError("创作意图引用与正文不一致，请重新选择资产")
        unbound_text = self.intent_text
        for item in self.intent_mentions:
            unbound_text = unbound_text.replace(f"@{item.label}", "")
        if "@" in unbound_text:
            raise ValueError("创作意图包含尚未选择完成的 @ 引用")
        return self


class IntentUnderstandingSummary(BaseModel):
    preserved: list[str] = Field(default_factory=list, max_length=20)
    replaced: list[str] = Field(default_factory=list, max_length=20)
    redesigned: list[str] = Field(default_factory=list, max_length=20)
    removed: list[str] = Field(default_factory=list, max_length=20)
    reference_count: int = Field(default=0, ge=0)


class UnresolvedIntentRequirement(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    dimension: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    candidates: list[str] = Field(default_factory=list, max_length=20)


class VideoIntentCompileResponse(BaseModel):
    draft: ShotVideoGenerationDraft
    summary: IntentUnderstandingSummary
    unresolved_requirements: list[UnresolvedIntentRequirement] = Field(
        default_factory=list,
        max_length=40,
    )
    warnings: list[str] = Field(default_factory=list, max_length=40)
    recommended_model_alias: str | None = Field(default=None, max_length=80)
    route_explanation: str = Field(default="", max_length=500)
    transition_evidence: Literal[
        "source_clip",
        "analyzed_facts",
        "user_instruction",
        "free",
        "none",
    ] = "none"


class VideoIntentRestoreRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)
    parts: list[Literal["prompt", "references", "negative_constraints"]] = Field(
        min_length=1,
        max_length=3,
    )
