from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from viral_dna_api.category_profiles.contracts import CategoryProfileSnapshot
from ..visual_styles import VisualStyle
from .creative_review_models import (
    CreativeCommonRule, CreativeHumanReview, CreativeRequirementCheck,
    CreativeRequirementRule, CreativeReviewIssue,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ViralClaimKind(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"


class ViralStrategy(StrEnum):
    CREATIVE = "creative"
    FAITHFUL = "faithful"
    SCENARIO = "scenario"
    PROOF = "proof"
    # Kept so persisted v1/v2 concept sets remain readable.
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
    category_profile_id: UUID
    strategies: list[ViralStrategy] = Field(
        default_factory=lambda: [
            ViralStrategy.FAITHFUL,
            ViralStrategy.SCENARIO,
            ViralStrategy.PROOF,
        ],
        min_length=1,
        max_length=3,
    )
    replacements: list[ViralReplacementSelection] = Field(default_factory=list, max_length=30)

    @field_validator("strategies")
    @classmethod
    def unique_strategies(cls, values: list[ViralStrategy]) -> list[ViralStrategy]:
        if len(values) != len(set(values)):
            raise ValueError("复刻策略不能重复")
        current = {
            ViralStrategy.FAITHFUL,
            ViralStrategy.SCENARIO,
            ViralStrategy.PROOF,
        }
        if any(value not in current for value in values):
            raise ValueError("旧版复刻策略已停用，请使用结构迁移、场景叙事或证据说服")
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
    # A reference, never the identity, order or timing of a newly authored shot.
    source_shot_id: str | None = Field(default=None, min_length=1, max_length=120)
    index: int = Field(ge=1)
    duration_seconds: float = Field(gt=0, le=60)
    title: str = Field(min_length=1, max_length=160)
    traffic_role: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2400)
    image_prompt: str = Field(min_length=1, max_length=8000)
    video_prompt: str = Field(min_length=1, max_length=8000)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    retained_mechanisms: list[str] = Field(default_factory=list, max_length=20)


class ViralConceptContent(BaseModel):
    """Creative content, without application-owned identity or strategy metadata."""

    name: str = Field(min_length=1, max_length=160)
    one_liner: str = Field(min_length=1, max_length=500)
    thesis: str = Field(default="", max_length=1000)
    hook: str = Field(default="", max_length=1000)
    narrative_structure: str = Field(default="", max_length=1000)
    visual_memory: str = Field(default="", max_length=1000)
    payoff: str = Field(default="", max_length=1000)
    category_fit_summary: str = Field(default="", max_length=1200)
    changed_elements: list[str] = Field(default_factory=list, max_length=20)
    target_audience: str = Field(min_length=1, max_length=1000)
    why_it_can_work: str = Field(min_length=1, max_length=1600)
    difficulty: Literal["low", "medium", "high"] = "medium"
    estimated_cost_level: Literal["low", "medium", "high"] = "medium"
    retained_dna: list[str] = Field(default_factory=list, max_length=20)
    improvements: list[str] = Field(default_factory=list, max_length=20)
    required_assets: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=20)
    shots: list[ViralConceptShot] = Field(min_length=1, max_length=200)
    common_rules: list[CreativeCommonRule] = Field(default_factory=list, max_length=24)
    requirement_checks: list[CreativeRequirementCheck] = Field(default_factory=list, max_length=24)


class CreativeBriefEvidence(BaseModel):
    scene_index: int = Field(ge=1, le=200)
    quote: str = Field(min_length=2, max_length=300)


class CreativeBriefCheck(BaseModel):
    requirement_index: int = Field(ge=1, le=24)
    satisfied: StrictBool
    explanation: str = Field(min_length=8, max_length=400)
    scene_scope: Literal["selected", "all"] = "selected"
    evidence: list[CreativeBriefEvidence] = Field(default_factory=list, max_length=200)


class CreativeBriefFulfillment(CreativeBriefCheck):
    requirement: str = Field(min_length=1, max_length=2000)


class ViralConcept(ViralConceptContent):
    id: UUID = Field(default_factory=uuid4)
    strategy: ViralStrategy
    brief_checks: list[CreativeBriefFulfillment] = Field(default_factory=list, max_length=24)


CreativeSceneText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]


class CreativePlannedScene(BaseModel):
    index: int = Field(ge=1, le=200)
    description: str = Field(min_length=1, max_length=1200)
    duration_seconds: float = Field(gt=0, le=60)
    transition: Literal["cut", "continuous", "dissolve"] = "cut"


class CreativeIdeaContent(BaseModel):
    """Only the fields the creative model is responsible for authoring."""

    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=220)
    visual_memory: str = Field(min_length=1, max_length=160)
    key_scenes: list[CreativeSceneText] = Field(min_length=1, max_length=3)
    # Complete film plan, independent of the two/three illustrative highlights.
    # Empty remains valid for immutable historical batches.
    scene_plan: list[CreativePlannedScene] = Field(default_factory=list, max_length=200)
    rhythm: str = Field(default="", max_length=500)
    category_fit: str = Field(min_length=1, max_length=240)
    borrowed: str = Field(min_length=1, max_length=240)
    changed: str = Field(min_length=1, max_length=240)
    # Semantic axes, not fixed strategy names. Shared montage grammar is allowed.
    creative_intent: str = Field(min_length=1, max_length=240)
    visual_organization: str = Field(min_length=1, max_length=240)
    product_role: str = Field(min_length=1, max_length=240)
    assumptions: list[CreativeSceneText] = Field(default_factory=list, max_length=10)
    common_rules: list[CreativeCommonRule] = Field(default_factory=list, max_length=24)
    requirement_checks: list[CreativeRequirementCheck] = Field(default_factory=list, max_length=24)
    highlight_scene_indices: list[int] = Field(default_factory=list, max_length=3)


class CreativeIdea(CreativeIdeaContent):
    id: UUID = Field(default_factory=uuid4)
    # Application-owned provenance; absent on legacy records, never model-authored.
    visual_style_snapshot: dict[str, Any] | None = None
    brief_checks: list[CreativeBriefFulfillment] = Field(default_factory=list, max_length=24)
    review_issues: list[str] = Field(default_factory=list, max_length=24)
    review_state: Literal["unreviewed", "ready", "needs_review", "needs_revision"] = "unreviewed"
    review_details: list[CreativeReviewIssue] = Field(default_factory=list, max_length=100)
    review_brief: str | None = None
    human_review: CreativeHumanReview | None = None


class CreativeIdeaEdit(BaseModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    feedback: str | None = Field(default=None, max_length=2000)
    idea: CreativeIdeaContent
    requirement_rules: list[CreativeRequirementRule] = Field(default_factory=list, max_length=24)
    confirmed_requirements: list[int] = Field(default_factory=list, max_length=24)


class CreativeGenerateRequest(BaseModel):
    request_id: UUID
    category_profile_id: UUID
    feedback: str | None = Field(default=None, max_length=2000)
    replacements: list[ViralReplacementSelection] = Field(default_factory=list, max_length=30)
    visual_style: VisualStyle | None = None


class CreativeActionRequest(BaseModel):
    request_id: UUID
    feedback: str | None = Field(default=None, max_length=2000)
    revision_notes: str | None = Field(default=None, max_length=2000)
    visual_style: VisualStyle | None = None

    @field_validator("revision_notes")
    @classmethod
    def validate_revision_notes(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("请填写本条创意的修改意见")
        return value


class CreativePlanEdit(BaseModel):
    expected_revision: int = Field(ge=1)
    concept: ViralConcept


class CreativeResultRecovery(BaseModel):
    version: Literal["ellipsis-citation-v1"] = "ellipsis-citation-v1"
    recovered_at: datetime = Field(default_factory=utc_now)
    source_model_run_id: UUID
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_error_code: str
    previous_error_message: str | None = None


class ViralConceptSet(BaseModel):
    schema_version: Literal[
        "viral-dna-concepts-v1",
        "viral-dna-concepts-v2",
        "viral-dna-concepts-v3",
        "viral-dna-concepts-v4",
    ] = "viral-dna-concepts-v3"
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID
    video_id: UUID
    insight_report_id: UUID
    input_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: Literal["queued", "running", "completed", "stale", "failed", "cancelled"] = "completed"
    concepts: list[ViralConcept] = Field(default_factory=list, max_length=3)
    phase: Literal["legacy", "ideas", "expanded"] = "legacy"
    operation: Literal["generate", "regenerate", "expand", "edit", "localize"] = "generate"
    language_issues: list[str] = Field(default_factory=list, max_length=800)
    language_result: dict[str, Any] | None = None
    language_applied_revision_id: UUID | None = None
    ideas: list[CreativeIdea] = Field(default_factory=list, max_length=3)
    requirement_rules: list[CreativeRequirementRule] = Field(default_factory=list, max_length=24)
    # Read-only fingerprint for optimistic edits; never an authority supplied by the model.
    review_source_fingerprint: str | None = None
    parent_set_id: UUID | None = None
    source_idea_id: UUID | None = None
    request_id: UUID | None = None
    request_signature: str | None = None
    feedback: str = Field(default="", max_length=2000)
    revision_notes: str | None = Field(default=None, max_length=2000)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    visual_style_snapshot: dict[str, Any] = Field(default_factory=dict)
    # Editable production configuration, never part of the historical AI input.
    production_style_revision: int = 0
    production_visual_style_snapshot: dict[str, Any] | None = None
    model_runs: list[UUID] = Field(default_factory=list)
    requested_model: str | None = None
    resolved_model: str | None = None
    cost_status: Literal["not_started", "measured", "unreported"] = "not_started"
    estimated_cost_micros: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model_elapsed_ms: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = Field(default=None, max_length=500)
    recovery: CreativeResultRecovery | None = None
    revision: int = Field(default=1, ge=1)
    published_result: ViralConceptPublishResult | None = None
    generator_id: str = Field(default="replication-rules-v1", min_length=1, max_length=120)
    strategy_contract_version: str = Field(
        default="strategy-contract-v1",
        min_length=1,
        max_length=120,
    )
    source_insight_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    category_profile: CategoryProfileSnapshot | None = None
    stale_reason: str | None = Field(default=None, max_length=500)
    model_cost_micros: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_result(self) -> ViralConceptSet:
        if self.status in {"completed", "stale"}:
            if self.phase == "ideas" and len(self.ideas) != 3:
                raise ValueError("创意阶段必须有三个简短方向")
            if self.phase != "ideas" and not self.concepts:
                raise ValueError("完整方案必须包含分镜")
        return self


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


ViralConceptSet.model_rebuild()
