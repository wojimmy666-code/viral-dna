from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ViralClaimKind(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"


class ViralStrategy(StrEnum):
    FAITHFUL = "faithful"
    DIFFERENTIATED = "differentiated"
    ENHANCED = "enhanced"


class ViralEvidenceRef(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    kind: Literal["frame", "shot", "subtitle", "dialogue", "ocr", "metric"]
    shot_id: str | None = Field(default=None, max_length=160)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    frame_url: str | None = Field(default=None, max_length=2048)
    text: str = Field(default="", max_length=2000)
    source_label: str = Field(min_length=1, max_length=120)


class ViralMechanism(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    type: Literal[
        "hook",
        "retention",
        "payoff",
        "emotion",
        "visual_memory",
        "interaction",
        "share",
        "platform_fit",
    ]
    title: str = Field(min_length=1, max_length=160)
    claim_kind: ViralClaimKind = ViralClaimKind.INFERRED
    observation: str = Field(min_length=1, max_length=2000)
    mechanism: str = Field(min_length=1, max_length=2000)
    expected_effect: str = Field(min_length=1, max_length=1200)
    impact_dimensions: list[
        Literal["click", "retention", "like", "comment", "share", "conversion"]
    ] = Field(
        default_factory=list,
        max_length=6,
    )
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    recommendation: str = Field(min_length=1, max_length=1600)
    evidence: list[ViralEvidenceRef] = Field(default_factory=list, max_length=20)


class ViralShotRole(BaseModel):
    shot_id: str = Field(min_length=1, max_length=160)
    shot_index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    role: Literal["hook", "setup", "retention", "proof", "payoff", "cta"]
    contribution: str = Field(min_length=1, max_length=1200)
    contribution_score: int = Field(ge=0, le=100)
    must_keep: list[str] = Field(default_factory=list, max_length=12)
    replaceable: list[str] = Field(default_factory=list, max_length=12)
    improvements: list[str] = Field(default_factory=list, max_length=12)
    keyframe_url: str | None = Field(default=None, max_length=2048)
    evidence: list[ViralEvidenceRef] = Field(default_factory=list, max_length=20)


class ViralDNA(BaseModel):
    invariants: list[str] = Field(default_factory=list, max_length=20)
    recommended_locks: list[str] = Field(default_factory=list, max_length=20)
    variables: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=20)


class ViralReplacementOpportunity(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    current_description: str = Field(min_length=1, max_length=2000)
    must_preserve: list[str] = Field(default_factory=list, max_length=12)
    suggested_alternatives: list[str] = Field(default_factory=list, max_length=8)
    affected_shot_ids: list[str] = Field(default_factory=list, max_length=100)
    risk: Literal["low", "medium", "high"] = "medium"


class ViralImprovement(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1600)
    priority: Literal["high", "medium", "low"]
    expected_gain: str = Field(min_length=1, max_length=800)
    affected_shot_ids: list[str] = Field(default_factory=list, max_length=100)


class ViralInsightReport(BaseModel):
    schema_version: Literal["viral-dna-insight-v1"] = "viral-dna-insight-v1"
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID
    video_id: UUID
    status: Literal["completed", "stale", "failed"] = "completed"
    source_analysis_generated_at: datetime
    input_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    headline: str = Field(min_length=1, max_length=300)
    content_value: str = Field(min_length=1, max_length=1200)
    audience: str = Field(min_length=1, max_length=1200)
    data_basis: Literal["content_inference", "performance_supported"] = "content_inference"
    evidence_coverage: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    strongest_hook: str = Field(min_length=1, max_length=1000)
    replication_difficulty: Literal["low", "medium", "high"] = "medium"
    mechanisms: list[ViralMechanism] = Field(default_factory=list, max_length=30)
    shot_roles: list[ViralShotRole] = Field(default_factory=list, max_length=200)
    dna: ViralDNA
    replacement_opportunities: list[ViralReplacementOpportunity] = Field(
        default_factory=list, max_length=100
    )
    improvements: list[ViralImprovement] = Field(default_factory=list, max_length=30)
    generator_id: str = Field(default="evidence-rules-v1", min_length=1, max_length=120)
    model_cost_micros: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ViralReplacementSelection(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)
    replacement: str = Field(min_length=1, max_length=800)


class ViralConceptGenerateRequest(BaseModel):
    strategies: list[ViralStrategy] = Field(
        default_factory=lambda: list(ViralStrategy), min_length=1, max_length=3
    )
    replacements: list[ViralReplacementSelection] = Field(default_factory=list, max_length=30)

    @field_validator("strategies")
    @classmethod
    def unique_strategies(cls, values: list[ViralStrategy]) -> list[ViralStrategy]:
        if len(values) != len(set(values)):
            raise ValueError("复刻策略不能重复")
        return values

    @field_validator("replacements")
    @classmethod
    def unique_replacements(
        cls, values: list[ViralReplacementSelection]
    ) -> list[ViralReplacementSelection]:
        ids = [item.entity_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("同一元素只能设置一个替换值")
        return values


class ViralConceptShot(BaseModel):
    source_shot_id: str = Field(min_length=1, max_length=160)
    index: int = Field(ge=1)
    duration_seconds: float = Field(gt=0, le=60)
    title: str = Field(min_length=1, max_length=160)
    traffic_role: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2400)
    image_prompt: str = Field(min_length=1, max_length=8000)
    video_prompt: str = Field(min_length=1, max_length=8000)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    retained_mechanisms: list[str] = Field(default_factory=list, max_length=20)


class ViralConcept(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    strategy: ViralStrategy
    name: str = Field(min_length=1, max_length=160)
    one_liner: str = Field(min_length=1, max_length=500)
    target_audience: str = Field(min_length=1, max_length=1000)
    why_it_can_work: str = Field(min_length=1, max_length=1600)
    difficulty: Literal["low", "medium", "high"] = "medium"
    estimated_cost_level: Literal["low", "medium", "high"] = "medium"
    retained_dna: list[str] = Field(default_factory=list, max_length=20)
    improvements: list[str] = Field(default_factory=list, max_length=20)
    required_assets: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=20)
    shots: list[ViralConceptShot] = Field(min_length=1, max_length=200)


class ViralConceptSet(BaseModel):
    schema_version: Literal["viral-dna-concepts-v1"] = "viral-dna-concepts-v1"
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID
    video_id: UUID
    insight_report_id: UUID
    input_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed", "failed"] = "completed"
    concepts: list[ViralConcept] = Field(min_length=1, max_length=3)
    generator_id: str = Field(default="replication-rules-v1", min_length=1, max_length=120)
    model_cost_micros: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ViralConceptPublishRequest(BaseModel):
    record_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=120)
    output_aspect_ratio: str | None = Field(default=None, pattern=r"^\d{1,5}:\d{1,5}$")
    budget_limit_micros: int | None = Field(default=None, gt=0)


class ViralConceptPublishResult(BaseModel):
    project_id: UUID
    project_name: str
    concept_id: UUID
    shot_count: int = Field(ge=1)
