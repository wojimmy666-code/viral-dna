from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from ..production_seeds.contracts import ExactOverlayInstruction


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_digest(value: Any, *, exclude: set[str] | None = None) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude=exclude or set())
    else:
        value = to_jsonable_python(value)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    STALE = "stale"
    CANCELLED = "cancelled"


class ValidationStatus(StrEnum):
    UNCHECKED = "unchecked"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"


class SkillWorkflowStage(StrEnum):
    CREATIVE_BRIEF = "creative_brief"
    STYLE_CONFIRMATION = "style_confirmation"
    STORYBOARD_DESIGN = "storyboard_design"
    SHOT_IMAGES = "shot_images"
    SHOT_VIDEOS = "shot_videos"
    EDITING = "editing"
    AUDIO_CAPTION = "audio_caption"
    EXPORT = "export"


class SkillGate(StrEnum):
    BRIEF_APPROVED = "brief_approved"
    STYLE_APPROVED = "style_approved"
    STORYBOARD_APPROVED = "storyboard_approved"
    IMAGES_APPROVED = "images_approved"
    VIDEOS_APPROVED = "videos_approved"
    PICTURE_LOCKED = "picture_locked"
    AUDIO_CAPTION_APPROVED = "audio_caption_approved"
    DELIVERY_APPROVED = "delivery_approved"


GATE_ORDER = [
    SkillGate.BRIEF_APPROVED,
    SkillGate.STYLE_APPROVED,
    SkillGate.STORYBOARD_APPROVED,
    SkillGate.IMAGES_APPROVED,
    SkillGate.VIDEOS_APPROVED,
    SkillGate.PICTURE_LOCKED,
    SkillGate.AUDIO_CAPTION_APPROVED,
    SkillGate.DELIVERY_APPROVED,
]

STAGE_BY_GATE = dict(zip(GATE_ORDER, list(SkillWorkflowStage), strict=True))


class AutomationMode(StrEnum):
    GUIDED = "guided"
    FULL_AUTO = "full_auto"


class CreativeBasis(StrEnum):
    BRAND_LED = "brand_led"
    REFERENCE_LED = "reference_led"
    HYBRID = "hybrid"


class Fidelity(StrEnum):
    EXACT = "exact"
    IDENTITY_LOCK = "identity_lock"
    STRUCTURAL = "structural"
    STYLE_ONLY = "style_only"
    LOOSE_REFERENCE = "loose_reference"


class RightsStatus(StrEnum):
    CONFIRMED = "confirmed"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"
    EXPIRED = "expired"


class ConsentStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    REVOKED = "revoked"


class ClaimStatus(StrEnum):
    APPROVED = "approved"
    RESTRICTED = "restricted"
    FORBIDDEN = "forbidden"
    UNVERIFIED = "unverified"


class BrandSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_category_profile_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    values: list[str] = Field(default_factory=list, max_length=30)
    voice: list[str] = Field(default_factory=list, max_length=30)
    visual_identity: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class BrandSnapshotCreate(BaseModel):
    source_category_profile_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    values: list[str] = Field(default_factory=list, max_length=30)
    voice: list[str] = Field(default_factory=list, max_length=30)
    visual_identity: dict[str, Any] = Field(default_factory=dict)


class AssetUsage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    asset_id: UUID
    role: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    fidelity: Fidelity
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    allowed_distribution: list[str] = Field(default_factory=list, max_length=20)
    owner_or_licensor: str | None = Field(default=None, max_length=240)
    evidence_asset_id: UUID | None = None
    territory: list[str] = Field(default_factory=list, max_length=30)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    consent_status: ConsentStatus = ConsentStatus.NOT_APPLICABLE
    allowed_transformations: list[str] = Field(default_factory=list, max_length=30)
    claim_evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)
    required_in_shot_keys: list[str] = Field(default_factory=list, max_length=100)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "allowed_distribution",
        "territory",
        "allowed_transformations",
        "required_in_shot_keys",
    )
    @classmethod
    def unique_strings(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("素材用途列表不能重复")
        return values


class AssetUsageInput(BaseModel):
    id: UUID | None = None
    asset_id: UUID
    role: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    fidelity: Fidelity
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    allowed_distribution: list[str] = Field(default_factory=list, max_length=20)
    owner_or_licensor: str | None = Field(default=None, max_length=240)
    evidence_asset_id: UUID | None = None
    territory: list[str] = Field(default_factory=list, max_length=30)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    consent_status: ConsentStatus = ConsentStatus.NOT_APPLICABLE
    allowed_transformations: list[str] = Field(default_factory=list, max_length=30)
    claim_evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)
    required_in_shot_keys: list[str] = Field(default_factory=list, max_length=100)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AssetUsageListUpdate(BaseModel):
    items: list[AssetUsageInput] = Field(default_factory=list, max_length=100)


class ClaimEvidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    claim_text: str = Field(min_length=1, max_length=1000)
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    evidence_asset_ids: list[UUID] = Field(default_factory=list, max_length=50)
    allowed_channels: list[str] = Field(default_factory=list, max_length=30)
    required_disclaimer: str | None = Field(default=None, max_length=1000)
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ClaimEvidenceInput(BaseModel):
    id: UUID | None = None
    claim_text: str = Field(min_length=1, max_length=1000)
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    evidence_asset_ids: list[UUID] = Field(default_factory=list, max_length=50)
    allowed_channels: list[str] = Field(default_factory=list, max_length=30)
    required_disclaimer: str | None = Field(default=None, max_length=1000)


class ClaimEvidenceListUpdate(BaseModel):
    items: list[ClaimEvidenceInput] = Field(default_factory=list, max_length=100)


class CreativeBriefInput(BaseModel):
    brand_snapshot_id: UUID
    objective: str = Field(min_length=1, max_length=2000)
    audience: str = Field(min_length=1, max_length=1000)
    distribution_channel: str = Field(min_length=1, max_length=80)
    target_duration_seconds: int = Field(ge=3, le=600)
    output_aspect_ratio: str = Field(pattern=r"^\d{1,5}:\d{1,5}$")
    fps: int = Field(default=30, ge=1, le=120)
    language: str = Field(default="中文", min_length=1, max_length=40)
    locale: str = Field(default="zh-CN", min_length=2, max_length=20)
    creative_basis: CreativeBasis
    call_to_action: str = Field(default="", max_length=1000)
    required_messages: list[str] = Field(default_factory=list, max_length=30)
    forbidden_messages: list[str] = Field(default_factory=list, max_length=30)
    selected_asset_usage_ids: list[UUID] = Field(default_factory=list, max_length=100)
    skill_answers: dict[str, str | list[str]] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)


class CreativeBriefRevision(CreativeBriefInput):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    target_duration_frames: int = Field(gt=0)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_by: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RunContractInput(BaseModel):
    image_provider_connection_id: str = Field(min_length=1, max_length=160)
    image_model_id: str = Field(min_length=1, max_length=200)
    image_width: int = Field(ge=256, le=8192)
    image_height: int = Field(ge=256, le=8192)
    video_provider_connection_id: str = Field(min_length=1, max_length=160)
    video_model_id: str = Field(min_length=1, max_length=200)
    video_width: int = Field(ge=256, le=8192)
    video_height: int = Field(ge=256, le=8192)
    video_resolution_label: str = Field(
        min_length=2,
        max_length=20,
        pattern=r"^(?:[0-9]{3,4}P|2K|4K)$",
    )
    video_fps: int = Field(ge=1, le=120)
    video_duration_capabilities_seconds: list[int] = Field(min_length=1, max_length=20)
    candidate_count_by_stage: dict[str, int] = Field(default_factory=dict)
    text_model_selection: str = Field(min_length=1, max_length=200)
    audio_source_strategy: Literal["candidate", "source", "muted"] = "muted"
    generate_video_audio: bool = False
    music_strategy: Literal["none", "select", "generate"] = "none"
    narration_strategy: Literal["none", "recorded", "generated"] = "none"
    subtitle_strategy: Literal["none", "final_speech", "manual"] = "none"
    automation_mode: AutomationMode = AutomationMode.GUIDED
    budget_limit_micros: int | None = Field(default=None, gt=0)
    estimated_cost_micros: int = Field(default=0, ge=0)
    estimate_status: Literal["known", "partial", "unknown"] = "unknown"
    allow_provider_fallback: Literal[False] = False
    supports_exact_overlay: bool = False

    @model_validator(mode="after")
    def validate_automation_budget(self) -> RunContractInput:
        if self.automation_mode == AutomationMode.FULL_AUTO and self.budget_limit_micros is None:
            raise ValueError("全自动模式必须设置预算上限")
        if (
            self.budget_limit_micros is not None
            and self.estimated_cost_micros > self.budget_limit_micros
        ):
            raise ValueError("预计成本已超过预算上限")
        return self


class RunContractRevision(RunContractInput):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_by: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PreflightIssue(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    severity: Literal["error", "warning"]
    message: str = Field(min_length=1, max_length=1000)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=160)


class PreflightResult(BaseModel):
    project_id: UUID
    can_start: bool
    issues: list[PreflightIssue] = Field(default_factory=list)
    estimated_cost_micros: int = Field(default=0, ge=0)
    budget_limit_micros: int | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class CreativeTreatmentRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    core_idea: str = Field(min_length=1, max_length=4000)
    narrative_structure: str = Field(min_length=1, max_length=4000)
    opening_hook: str = Field(min_length=1, max_length=2000)
    rhythm_curve: list[str] = Field(default_factory=list, max_length=30)
    visual_approach: str = Field(min_length=1, max_length=4000)
    presentation_principles: list[str] = Field(default_factory=list, max_length=30)
    sound_direction: str = Field(default="", max_length=2000)
    call_to_action: str = Field(default="", max_length=1000)
    risks: list[str] = Field(default_factory=list, max_length=30)
    source_input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class StyleBibleRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    skill_version_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    brand_snapshot_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    brief_revision_id: UUID
    reference_fact_digests: list[str] = Field(default_factory=list, max_length=100)
    palette: dict[str, Any] = Field(default_factory=dict)
    typography: dict[str, Any] = Field(default_factory=dict)
    lighting: dict[str, Any] = Field(default_factory=dict)
    composition: dict[str, Any] = Field(default_factory=dict)
    camera: dict[str, Any] = Field(default_factory=dict)
    motion: dict[str, Any] = Field(default_factory=dict)
    texture: dict[str, Any] = Field(default_factory=dict)
    rhythm: dict[str, Any] = Field(default_factory=dict)
    product_identity_lock: list[str] = Field(default_factory=list, max_length=50)
    character_identity_lock: list[str] = Field(default_factory=list, max_length=50)
    positive_lock: list[str] = Field(default_factory=list, max_length=50)
    negative_lock: list[str] = Field(default_factory=list, max_length=50)
    image_prompt_rules: list[str] = Field(default_factory=list, max_length=50)
    video_prompt_rules: list[str] = Field(default_factory=list, max_length=50)
    validation_checklist: list[str] = Field(default_factory=list, max_length=80)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class LookTestItem(BaseModel):
    shot_key: str = Field(min_length=1, max_length=160)
    requested_candidate_count: int = Field(default=1, ge=1, le=4)
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=4)
    generation_run_id: UUID | None = None
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    attempt: int = Field(default=0, ge=0, le=10)
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=300)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2000)
    retryable: bool = False


class LookTest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    style_bible_revision_id: UUID
    representative_shot_keys: list[str] = Field(min_length=1, max_length=4)
    run_contract_revision_id: UUID
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=20)
    selected_candidate_ids: list[UUID] = Field(default_factory=list, max_length=4)
    items: list[LookTestItem] = Field(default_factory=list, max_length=4)
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    validation_status: ValidationStatus = ValidationStatus.UNCHECKED
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    decision_note: str = Field(default="", max_length=1000)
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error_message: str | None = Field(default=None, max_length=2000)
    output_width: int = Field(ge=256, le=8192)
    output_height: int = Field(ge=256, le=8192)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OutlineBeat(BaseModel):
    stable_beat_key: str = Field(pattern=r"^beat_[a-z0-9]{8,64}$")
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=1000)
    target_duration_frames: int = Field(gt=0)
    message: str = Field(default="", max_length=2000)


class OutlineRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    beats: list[OutlineBeat] = Field(min_length=1, max_length=30)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class ShotManifestShot(BaseModel):
    stable_shot_key: str = Field(pattern=r"^shot_[a-z0-9]{8,64}$")
    order: int = Field(ge=1)
    narrative_role: str = Field(min_length=1, max_length=80)
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    handle_in_frames: int = Field(default=0, ge=0, le=600)
    handle_out_frames: int = Field(default=0, ge=0, le=600)
    description: str = Field(min_length=1, max_length=4000)
    image_prompt: str = Field(min_length=1, max_length=8000)
    image_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    video_prompt: str = Field(min_length=1, max_length=8000)
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    image_asset_usage_ids: list[UUID] = Field(default_factory=list, max_length=50)
    video_reference_usage_ids: list[UUID] = Field(default_factory=list, max_length=50)
    exact_overlays: list[ExactOverlayInstruction] = Field(default_factory=list, max_length=20)
    continuity_group_ids: list[str] = Field(default_factory=list, max_length=30)
    dialogue_or_voiceover: str = Field(default="", max_length=4000)
    caption_intent: str = Field(default="", max_length=2000)
    output_mode: Literal["image_to_video"] = "image_to_video"
    required_model_capabilities: list[str] = Field(default_factory=list, max_length=30)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ShotManifestRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    outline_revision_id: UUID
    style_bible_revision_id: UUID
    fps: int = Field(ge=1, le=120)
    shots: list[ShotManifestShot] = Field(min_length=1, max_length=500)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_order(self) -> ShotManifestRevision:
        orders = [item.order for item in self.shots]
        keys = [item.stable_shot_key for item in self.shots]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError("分镜顺序必须从 1 连续编号")
        if len(keys) != len(set(keys)):
            raise ValueError("stable_shot_key 不能重复")
        return self


class OutlineUpdate(BaseModel):
    beats: list[OutlineBeat] = Field(min_length=1, max_length=30)


class ShotManifestUpdate(BaseModel):
    outline_revision_id: UUID
    style_bible_revision_id: UUID
    fps: int = Field(ge=1, le=120)
    shots: list[ShotManifestShot] = Field(min_length=1, max_length=500)


class LookTestSelection(BaseModel):
    selected_candidate_ids: list[UUID] = Field(min_length=1, max_length=4)
    decision_note: str = Field(default="", max_length=1000)


class SkillRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    skill_version_snapshot_id: UUID
    run_contract_revision_id: UUID
    current_stage: SkillWorkflowStage = SkillWorkflowStage.CREATIVE_BRIEF
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    estimated_cost_micros: int = Field(default=0, ge=0)
    actual_cost_micros: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    resume_token: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=120)
    last_event_sequence: int = Field(default=0, ge=0)
    worker_lease_id: str | None = Field(default=None, max_length=120)
    worker_lease_expires_at: datetime | None = None
    provider_request_ids: dict[str, str] = Field(default_factory=dict)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=2000)


class SkillRunCreate(BaseModel):
    run_contract_revision_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class SkillStepRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    skill_run_id: UUID
    stage: SkillWorkflowStage
    operation: str = Field(min_length=1, max_length=120)
    attempt: int = Field(default=1, ge=1, le=10)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    validation_status: ValidationStatus = ValidationStatus.UNCHECKED
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    progress: int = Field(default=0, ge=0, le=100)
    queue_wait_ms: int = Field(default=0, ge=0)
    provider_ms: int = Field(default=0, ge=0)
    postprocess_ms: int = Field(default=0, ge=0)
    total_ms: int = Field(default=0, ge=0)
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=240)
    estimated_cost_micros: int = Field(default=0, ge=0)
    actual_cost_micros: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2000)
    retryable: bool = False
    output_artifact_ids: list[UUID] = Field(default_factory=list, max_length=100)


class SkillStageMetrics(BaseModel):
    stage: SkillWorkflowStage
    step_count: int = Field(ge=0)
    queue_wait_ms: int = Field(ge=0)
    provider_ms: int = Field(ge=0)
    postprocess_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)
    estimated_cost_micros: int = Field(ge=0)
    actual_cost_micros: int = Field(ge=0)
    failed_step_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)


class SkillRunMetrics(BaseModel):
    run_id: UUID
    project_id: UUID
    stages: list[SkillStageMetrics] = Field(default_factory=list)
    queue_wait_ms: int = Field(ge=0)
    provider_ms: int = Field(ge=0)
    postprocess_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)
    estimated_cost_micros: int = Field(ge=0)
    actual_cost_micros: int = Field(ge=0)


class SkillOperationMetrics(BaseModel):
    skill_id: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=120)
    run_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    revision_request_count: int = Field(ge=0)
    average_total_ms: int = Field(ge=0)
    average_actual_cost_micros: int = Field(ge=0)


class SkillOperationsSummary(BaseModel):
    total_runs: int = Field(ge=0)
    succeeded_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    blocked_runs: int = Field(ge=0)
    items: list[SkillOperationMetrics] = Field(default_factory=list)


class GateDecisionValue(StrEnum):
    APPROVE = "approve"
    REQUEST_REVISION = "request_revision"
    SKIP = "skip"


class GateActorType(StrEnum):
    USER = "user"
    PLATFORM_ADMIN = "platform_admin"
    SYSTEM = "system"


class GateDecision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    skill_run_id: UUID
    gate: SkillGate
    decision: GateDecisionValue
    actor_type: GateActorType
    actor_id: UUID | None = None
    note: str = Field(default="", max_length=1000)
    related_revision_ids: list[UUID] = Field(default_factory=list, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def system_cannot_approve(self) -> GateDecision:
        if self.actor_type == GateActorType.SYSTEM and self.decision == GateDecisionValue.APPROVE:
            raise ValueError("系统不能代替用户进行人工批准")
        return self


class GateDecisionRequest(BaseModel):
    decision: GateDecisionValue
    note: str = Field(default="", max_length=1000)
    related_revision_ids: list[UUID] = Field(default_factory=list, max_length=100)


class Artifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    stable_shot_key: str | None = Field(default=None, max_length=80)
    kind: str = Field(min_length=1, max_length=120)
    revision_number: int = Field(ge=1)
    source_step_run_id: UUID | None = None
    storage_uri: str | None = Field(default=None, max_length=4096)
    mime_type: str | None = Field(default=None, max_length=120)
    byte_size: int | None = Field(default=None, ge=0)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    producer_version: str = Field(min_length=1, max_length=120)
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    selected: bool = False
    stale: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactDependency(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID
    depends_on_type: str = Field(min_length=1, max_length=120)
    depends_on_id: str = Field(min_length=1, max_length=240)
    depends_on_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DependencyImpactRequest(BaseModel):
    depends_on_type: str = Field(min_length=1, max_length=120)
    depends_on_id: str = Field(min_length=1, max_length=240)
    next_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DependencyImpactResponse(BaseModel):
    affected_artifact_ids: list[UUID]
    affected_count: int = Field(ge=0)


class DeliveryFile(BaseModel):
    kind: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=240)
    storage_uri: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    media: dict[str, Any] = Field(default_factory=dict)


class DeliveryManifest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    skill_run_id: UUID
    production_project_id: UUID
    timeline_revision_id: UUID
    files: list[DeliveryFile] = Field(min_length=1, max_length=20)
    rights_summary: dict[str, Any]
    quality_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    exact_overlay_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class FrameRate(BaseModel):
    numerator: int = Field(default=30, gt=0, le=120_000)
    denominator: int = Field(default=1, gt=0, le=1001)


class TimelineV3Transition(BaseModel):
    kind: Literal["none", "fade", "crossfade"] = "none"
    duration_frames: int = Field(default=0, ge=0, le=600)

    @model_validator(mode="after")
    def validate_duration(self) -> TimelineV3Transition:
        if self.kind == "none" and self.duration_frames != 0:
            raise ValueError("无转场时转场帧数必须为 0")
        if self.kind != "none" and self.duration_frames <= 0:
            raise ValueError("启用转场时转场帧数必须大于 0")
        return self


class TimelineV3Clip(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    stable_shot_key: str = Field(pattern=r"^shot_[a-z0-9]{8,64}$")
    candidate_id: UUID
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    source_in_frame: int = Field(default=0, ge=0)
    source_duration_frames: int = Field(gt=0)
    handle_in_frames: int = Field(default=0, ge=0)
    handle_out_frames: int = Field(default=0, ge=0)
    audio_source: Literal["candidate", "source", "muted"] = "muted"
    candidate_audio_available: bool = False
    transition_after: TimelineV3Transition = Field(default_factory=TimelineV3Transition)


class TimelineAudioItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    asset_id: UUID
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    source_in_frame: int = Field(default=0, ge=0)
    gain_db: float = Field(default=0, ge=-60, le=12)
    fade_in_frames: int = Field(default=0, ge=0)
    fade_out_frames: int = Field(default=0, ge=0)
    loop: bool = False


class TimelineCaptionCue(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)
    speech_revision_id: UUID | None = None

    @model_validator(mode="after")
    def validate_range(self) -> TimelineCaptionCue:
        if self.end_frame <= self.start_frame:
            raise ValueError("字幕结束帧必须晚于开始帧")
        return self


class TimelineV3Revision(BaseModel):
    schema_version: Literal["viral-dna-timeline/v3"] = "viral-dna-timeline/v3"
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    production_project_id: UUID
    source_timeline_revision_id: UUID | None = None
    revision_number: int = Field(ge=1)
    parent_revision_id: UUID | None = None
    frame_rate: FrameRate = Field(default_factory=FrameRate)
    video_clips: list[TimelineV3Clip] = Field(default_factory=list, max_length=500)
    picture_lock_revision_id: UUID | None = None
    narration: list[TimelineAudioItem] = Field(default_factory=list, max_length=500)
    music: list[TimelineAudioItem] = Field(default_factory=list, max_length=20)
    sfx: list[TimelineAudioItem] = Field(default_factory=list, max_length=500)
    subtitles: list[TimelineCaptionCue] = Field(default_factory=list, max_length=5000)
    subtitle_speech_revision_id: UUID | None = None
    exact_overlays: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    mix_revision_id: UUID | None = None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class AudioAsset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    kind: Literal["music", "narration", "sfx"]
    source: Literal["uploaded", "selected", "generated", "recorded"]
    storage_uri: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_frames: int = Field(gt=0)
    sample_rate: int = Field(gt=0, le=384000)
    channels: int = Field(gt=0, le=16)
    rights_status: RightsStatus
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)


class AudioAssetCreate(BaseModel):
    kind: Literal["music", "narration", "sfx"]
    source: Literal["uploaded", "selected", "generated", "recorded"]
    storage_uri: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_frames: int = Field(gt=0)
    sample_rate: int = Field(gt=0, le=384000)
    channels: int = Field(gt=0, le=16)
    rights_status: RightsStatus
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)


class MixRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    timeline_revision_id: UUID
    revision_number: int = Field(ge=1)
    integrated_loudness_lufs: float | None = None
    true_peak_dbtp: float | None = None
    validation_status: ValidationStatus = ValidationStatus.UNCHECKED
    validation_messages: list[str] = Field(default_factory=list, max_length=100)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class PictureLockRequest(BaseModel):
    production_project_id: UUID
    clips: list[TimelineV3Clip] = Field(min_length=1, max_length=500)
    exact_overlays: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class ProductionPictureLockRequest(BaseModel):
    production_project_id: UUID
    expected_timeline_revision_id: UUID


class AudioCaptionUpdate(BaseModel):
    timeline_revision_id: UUID
    narration: list[TimelineAudioItem] = Field(default_factory=list, max_length=500)
    music: list[TimelineAudioItem] = Field(default_factory=list, max_length=20)
    sfx: list[TimelineAudioItem] = Field(default_factory=list, max_length=500)
    subtitles: list[TimelineCaptionCue] = Field(default_factory=list, max_length=5000)
    subtitle_speech_revision_id: UUID | None = None
    integrated_loudness_lufs: float | None = None
    true_peak_dbtp: float | None = None


class ProductionAudioCaptionFinalize(BaseModel):
    production_project_id: UUID
    expected_timeline_revision_id: UUID
    background_audio_kind: Literal["music", "narration", "sfx"] = "music"
    background_audio_rights_status: RightsStatus = RightsStatus.UNKNOWN
    integrated_loudness_lufs: float | None = None
    true_peak_dbtp: float | None = None


class DeliveryManifestCreate(BaseModel):
    production_project_id: UUID
    timeline_revision_id: UUID
    files: list[DeliveryFile] = Field(min_length=1, max_length=20)
    quality_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    exact_overlay_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class DeliveryFromExportRequest(BaseModel):
    production_project_id: UUID
    export_job_id: UUID
    exact_overlay_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class SkillRunDetail(BaseModel):
    run: SkillRun
    steps: list[SkillStepRun] = Field(default_factory=list)
    gates: list[GateDecision] = Field(default_factory=list)


class SkillProjectWorkspace(BaseModel):
    brand_snapshot: BrandSnapshot | None = None
    brief: CreativeBriefRevision | None = None
    asset_usages: list[AssetUsage] = Field(default_factory=list)
    claims: list[ClaimEvidence] = Field(default_factory=list)
    run_contract: RunContractRevision | None = None
    treatment: CreativeTreatmentRevision | None = None
    style_bible: StyleBibleRevision | None = None
    look_test: LookTest | None = None
    outline: OutlineRevision | None = None
    shot_manifest: ShotManifestRevision | None = None
    run: SkillRunDetail | None = None
    production_seed_id: UUID | None = None
    production_project_id: UUID | None = None
    timeline: TimelineV3Revision | None = None
    audio_assets: list[AudioAsset] = Field(default_factory=list)
    mix_revision: MixRevision | None = None
    delivery_manifest: DeliveryManifest | None = None
