from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class QualityFindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ContinuityDimension(StrEnum):
    IDENTITY = "identity"
    WARDROBE = "wardrobe"
    PRODUCT = "product"
    SCENE = "scene"
    ACTION = "action"
    SCREEN_POSITION = "screen_position"
    MOTION_DIRECTION = "motion_direction"
    CAMERA_AXIS = "camera_axis"
    LIGHTING = "lighting"
    COLOR = "color"


class ContinuityFindingSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class ContinuityFindingState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    WAIVED = "waived"


class ContinuityReportStatus(StrEnum):
    COMPLETED = "completed"
    STALE = "stale"
    FAILED = "failed"


class ContinuityVerificationState(StrEnum):
    RULE_ONLY = "rule_only"
    PARTIAL = "partial"
    VERIFIED = "verified"


class ContinuityBoundaryStatus(StrEnum):
    PASSED = "passed"
    UNVERIFIED = "unverified"
    WARNING = "warning"
    BLOCKED = "blocked"
    STALE = "stale"


class ContinuityDecision(StrEnum):
    RESOLVE = "resolve"
    WAIVE = "waive"
    REOPEN = "reopen"


class ContinuitySnapshot(BaseModel):
    shot_plan_id: UUID
    shot_index: int = Field(ge=1)
    approved_video_candidate_id: UUID | None = None
    generation_run_id: UUID | None = None
    generation_provider: str | None = Field(default=None, max_length=80)
    generation_model: str | None = Field(default=None, max_length=160)
    generation_model_snapshot: str | None = Field(default=None, max_length=160)
    candidate_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    reference_asset_ids: dict[str, list[UUID]] = Field(default_factory=dict)
    locks: list[str] = Field(default_factory=list)
    prompt_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    observed_facts: dict[str, str] = Field(default_factory=dict)
    evidence_source: Literal["rule_only", "candidate_metadata", "vlm"] = "rule_only"
    fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class ContinuityFinding(BaseModel):
    key: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    code: str = Field(min_length=1, max_length=120)
    dimension: ContinuityDimension
    severity: ContinuityFindingSeverity
    state: ContinuityFindingState = ContinuityFindingState.OPEN
    boundary_key: str = Field(min_length=1, max_length=120)
    left_shot_plan_id: UUID
    right_shot_plan_id: UUID
    message: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(default="", max_length=1000)
    expected: Any | None = None
    actual: Any | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    decision_reason: str | None = Field(default=None, max_length=1000)
    decided_at: datetime | None = None


class ContinuityBoundaryResult(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    left_shot_plan_id: UUID
    right_shot_plan_id: UUID
    left_shot_index: int = Field(ge=1)
    right_shot_index: int = Field(ge=1)
    status: ContinuityBoundaryStatus
    verification_state: ContinuityVerificationState
    findings: list[ContinuityFinding] = Field(default_factory=list)


class ContinuityReport(BaseModel):
    schema_version: Literal["viral-dna-continuity-report-v1"] = "viral-dna-continuity-report-v1"
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_id: UUID
    rule_version: Literal["continuity-rules-v1"] = "continuity-rules-v1"
    status: ContinuityReportStatus = ContinuityReportStatus.COMPLETED
    verification_state: ContinuityVerificationState
    input_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    snapshots: list[ContinuitySnapshot] = Field(default_factory=list)
    boundaries: list[ContinuityBoundaryResult] = Field(default_factory=list)
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    open_finding_count: int = Field(default=0, ge=0)
    score: int = Field(default=100, ge=0, le=100)
    stale_boundary_keys: list[str] = Field(default_factory=list)
    invalidated_by_revision_id: UUID | None = None
    model_cost_micros: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContinuityReportRunRequest(BaseModel):
    expected_revision_id: UUID


class ContinuityFindingDecisionRequest(BaseModel):
    expected_revision_id: UUID
    decision: ContinuityDecision
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_decision_reason(self) -> ContinuityFindingDecisionRequest:
        if self.decision in {ContinuityDecision.RESOLVE, ContinuityDecision.WAIVE}:
            if not self.reason or not self.reason.strip():
                raise ValueError("解决或豁免连续性问题时必须填写说明")
        return self


GoldenTransitionKind = Literal[
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


class GoldenShotExpectation(BaseModel):
    shot_index: int = Field(ge=1)
    expected_start_seconds: float | None = Field(default=None, ge=0)
    expected_end_seconds: float | None = Field(default=None, gt=0)
    time_tolerance_seconds: float = Field(default=0.25, ge=0, le=5)
    required_prompt_terms: list[str] = Field(default_factory=list, max_length=40)
    forbidden_prompt_terms: list[str] = Field(default_factory=list, max_length=40)
    required_motion_terms: list[str] = Field(default_factory=list, max_length=40)
    min_visual_beat_count: int = Field(default=0, ge=0, le=20)
    max_visual_beat_count: int | None = Field(default=None, ge=0, le=20)
    min_motion_phase_count: int = Field(default=0, ge=0, le=20)
    expected_transition_kind: GoldenTransitionKind | None = None

    @field_validator(
        "required_prompt_terms",
        "forbidden_prompt_terms",
        "required_motion_terms",
    )
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("黄金样本关键词不能重复")
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self) -> GoldenShotExpectation:
        if (
            self.expected_start_seconds is not None
            and self.expected_end_seconds is not None
            and self.expected_end_seconds <= self.expected_start_seconds
        ):
            raise ValueError("黄金样本分镜结束时间必须晚于开始时间")
        if (
            self.max_visual_beat_count is not None
            and self.max_visual_beat_count < self.min_visual_beat_count
        ):
            raise ValueError("最大画面数量不能小于最小画面数量")
        overlap = set(self.required_prompt_terms) & set(self.forbidden_prompt_terms)
        if overlap:
            raise ValueError("同一提示词关键词不能同时设为必须和禁止")
        return self


class GoldenAnalysisExpectation(BaseModel):
    schema_version: Literal["viral-dna-golden-analysis-v1"] = "viral-dna-golden-analysis-v1"
    sample_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    source_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_shot_count: int = Field(ge=1, le=200)
    max_boundary_gap_seconds: float = Field(default=0.5, ge=0, le=10)
    max_boundary_overlap_seconds: float = Field(default=0.05, ge=0, le=10)
    minimum_score: int = Field(default=100, ge=0, le=100)
    shots: list[GoldenShotExpectation] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_shot_expectations(self) -> GoldenAnalysisExpectation:
        indices = [item.shot_index for item in self.shots]
        if len(indices) != len(set(indices)):
            raise ValueError("黄金样本不能重复定义同一个分镜")
        if max(indices) > self.expected_shot_count:
            raise ValueError("黄金样本分镜序号不能超过预期分镜总数")
        return self


class GoldenRegressionFinding(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    severity: QualityFindingSeverity
    scope: Literal["analysis", "shot"]
    shot_index: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=1000)
    expected: str | int | float | None = None
    actual: str | int | float | None = None


class GoldenRegressionResult(BaseModel):
    schema_version: Literal["viral-dna-golden-result-v1"] = "viral-dna-golden-result-v1"
    sample_id: str
    sample_name: str
    passed: bool
    score: int = Field(ge=0, le=100)
    finding_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    expectation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    report_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    findings: list[GoldenRegressionFinding] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
