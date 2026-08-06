from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator, model_validator

from .schema import WORKSPACE_SCHEMA_VERSION


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_workspace_relative_path(value: str) -> str:
    normalized = value.strip().replace(chr(92), "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and ":" in path.parts[0])
    ):
        raise ValueError("工作区文件路径必须是安全的相对路径")
    return path.as_posix()


class SourceType(StrEnum):
    UPLOAD = "upload"
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"


class VideoStatus(StrEnum):
    READY = "ready"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportKind(StrEnum):
    REPORT_JSON = "report_json"
    REPORT_MARKDOWN = "report_markdown"
    PROMPT_PACKAGE = "prompt_package"
    TRANSCRIPT = "transcript"
    SUBTITLES = "subtitles"


class AnalysisMode(StrEnum):
    SIMULATED = "simulated"
    MEDIA_EVIDENCE = "media_evidence"
    MODEL = "model"


class AnalysisStage(StrEnum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    PREPROCESSING = "preprocessing"
    SEGMENTING = "segmenting"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    REASONING = "reasoning"
    COMPILING_PROMPTS = "compiling_prompts"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisProfile(StrEnum):
    QUALITY = "quality"
    BALANCED = "balanced"
    ECONOMY = "economy"


class ModelTask(StrEnum):
    SHOT_SEGMENTATION = "shot_segmentation"
    SHOT_FACTS = "shot_facts"
    ENTITY_RESOLUTION = "entity_resolution"
    VIRAL_REASONING = "viral_reasoning"
    PROMPT_GENERATION = "prompt_generation"
    IMAGE_QUALITY_QA = "image_quality_qa"


class ModelRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"
    BLOCKED = "blocked"


class CostStatus(StrEnum):
    ESTIMATED = "estimated"
    MEASURED = "measured"
    RECONCILED = "reconciled"


class ProductionProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProductionStep(StrEnum):
    PROJECT_SETUP = "project_setup"
    REFERENCE_ASSETS = "reference_assets"
    SHOT_IMAGES = "shot_images"
    SHOT_VIDEOS = "shot_videos"
    EDITING = "editing"
    EXPORT = "export"


class WorkflowItemStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    GENERATING = "generating"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    STALE = "stale"
    FAILED = "failed"


class ShotLifecycleStatus(StrEnum):
    ACTIVE = "active"
    DISCARDED = "discarded"


class ShotSourceKind(StrEnum):
    ANALYSIS = "analysis"
    VIDEO_RANGE = "video_range"
    DUPLICATE = "duplicate"
    BLANK = "blank"


class ProductionChangeKind(StrEnum):
    PROJECT_CREATED = "project_created"
    PROJECT_SETTINGS_CHANGED = "project_settings_changed"
    REFERENCE_CHANGED = "reference_changed"
    SHOT_PLAN_CHANGED = "shot_plan_changed"
    SHOT_STRUCTURE_CHANGED = "shot_structure_changed"
    SOURCE_KEYFRAME_CHANGED = "source_keyframe_changed"
    IMAGE_CANDIDATE_SELECTED = "image_candidate_selected"
    IMAGE_APPROVED = "image_approved"
    IMAGE_APPROVAL_REVOKED = "image_approval_revoked"
    IMAGE_REJECTED = "image_rejected"
    WORKFLOW_ADVANCED = "workflow_advanced"
    BRANCH_CREATED = "branch_created"


class ReferenceAssetType(StrEnum):
    PERSON = "person"
    WARDROBE = "wardrobe"
    PRODUCT = "product"
    SCENE = "scene"
    PROP = "prop"
    STYLE = "style"


class ReferenceRole(StrEnum):
    IDENTITY = "identity"
    PRODUCT = "product"
    SCENE = "scene"
    WARDROBE = "wardrobe"
    STYLE = "style"
    LAYOUT = "layout"


class ShotLock(StrEnum):
    TIMING = "timing"
    CAMERA = "camera"
    COMPOSITION = "composition"
    ACTION = "action"
    LIGHTING = "lighting"
    AUDIO = "audio"


class GenerationKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class ImageExecutionMode(StrEnum):
    REMOTE_API = "remote_api"
    LOCAL_TOOL = "local_tool"
    SIMULATED = "simulated"
    SOURCE_FRAME = "source_frame"


class ImageGenerationInputMode(StrEnum):
    KEYFRAME_EDIT = "keyframe_edit"
    TEXT_TO_IMAGE = "text_to_image"


class GenerationCostSource(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    CONFIGURED_RATE = "configured_rate"
    UNMETERED = "unmetered"
    SUBSCRIPTION_QUOTA = "subscription_quota"
    UNKNOWN = "unknown"


class ProductionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"
    BLOCKED = "blocked"


class GenerationCandidateStatus(StrEnum):
    READY = "ready"
    SELECTED = "selected"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REVOKED = "revoked"
    REJECTED = "rejected"


class ModelProviderOption(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)


class ModelOption(BaseModel):
    alias: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class ModelSettingsUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    model_alias: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    api_key: SecretStr | None = Field(default=None, max_length=512)
    base_url: HttpUrl | None = None


class ModelSettingsResponse(BaseModel):
    provider: str
    model_alias: str
    model: str | None = None
    base_url: str
    api_key_configured: bool = False
    api_key_hint: str | None = None
    last_validated_at: datetime | None = None
    validation_latency_ms: int | None = Field(default=None, ge=0)
    catalog_version: str
    pricing_version: str
    providers: list[ModelProviderOption]
    models: list[ModelOption]


class ImageGenerationCapability(BaseModel):
    text_to_image: bool = False
    image_to_image: bool = True
    multi_reference: bool = True
    max_reference_images: int = Field(default=2, ge=0, le=20)
    max_input_images: int = Field(default=3, ge=1, le=20)
    max_candidates: int = Field(default=4, ge=1, le=20)
    maximum_width: int = Field(default=2048, ge=256, le=32768)
    maximum_height: int = Field(default=2048, ge=256, le=32768)
    maximum_pixels: int = Field(default=4_194_304, ge=65_536)
    supported_formats: list[str] = Field(default_factory=lambda: ["jpeg", "png", "webp"])
    supports_negative_prompt: bool = True
    supports_seed: bool = True


class ImageGenerationModelOption(BaseModel):
    alias: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    unit_cost_micros: int = Field(ge=0)
    pricing_version: str = Field(min_length=1, max_length=80)
    recommended: bool = False
    capabilities: ImageGenerationCapability


class ImageGenerationSettingsUpdate(BaseModel):
    execution_mode: Literal["remote_api", "local_tool"]
    default_candidate_count: int = Field(default=1, ge=1, le=4)
    remote_provider: str = Field(default="dashscope", min_length=1, max_length=80)
    remote_model_alias: str = Field(
        default="qwen_image_2_pro",
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    remote_api_key: SecretStr | None = Field(default=None, max_length=512)
    remote_base_url: str | None = Field(default=None, max_length=500)
    local_adapter_id: str = Field(
        default="viral_dna_json_v1",
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    local_executable_path: str | None = Field(default=None, max_length=2048)
    local_fixed_args: list[str] = Field(default_factory=list, max_length=20)
    local_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    local_concurrency: int = Field(default=1, ge=1, le=8)
    local_protocol_version: str = Field(
        default="viral-dna-image-tool/v1",
        min_length=1,
        max_length=80,
    )
    local_cost_source: Literal[
        "configured_rate",
        "unmetered",
        "subscription_quota",
        "unknown",
    ] = "unknown"
    local_unit_cost_micros: int | None = Field(default=None, ge=0)
    local_model_policy: Literal["latest_flagship", "pinned", "balanced"] = (
        "latest_flagship"
    )
    local_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[a-zA-Z0-9_./:-]+$",
    )
    local_reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "xhigh"
    local_proxy_mode: Literal["system", "manual", "disabled"] = "system"
    local_proxy_url: str | None = Field(default=None, max_length=500)
    local_windows_sandbox_mode: Literal["auto", "elevated", "unelevated"] = "auto"
    semantic_quality_enabled: bool = False

    @field_validator("local_fixed_args")
    @classmethod
    def validate_local_fixed_args(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 500 or "\x00" in item or "\r" in item or "\n" in item:
                raise ValueError("本机工具固定参数格式无效")
            normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def validate_selected_mode(self) -> ImageGenerationSettingsUpdate:
        if self.execution_mode == "remote_api" and not (self.remote_base_url or "").strip():
            raise ValueError("国内 API 模式必须填写服务地址")
        if self.execution_mode == "local_tool" and not (self.local_executable_path or "").strip():
            raise ValueError("本机工具模式必须填写可执行文件路径")
        if self.local_cost_source == "configured_rate" and self.local_unit_cost_micros is None:
            raise ValueError("按配置费率计费时必须填写单张成本")
        if self.local_proxy_mode == "manual" and not (self.local_proxy_url or "").strip():
            raise ValueError("手动代理模式必须填写代理地址")
        return self


class ImageGenerationSettingsResponse(BaseModel):
    enabled: bool = False
    execution_mode: ImageExecutionMode = ImageExecutionMode.REMOTE_API
    default_candidate_count: int = Field(default=1, ge=1, le=4)
    remote_provider: str = "dashscope"
    remote_model_alias: str = "qwen_image_2_pro"
    remote_model: str | None = None
    remote_base_url: str
    api_key_configured: bool = False
    api_key_hint: str | None = None
    local_adapter_id: str = "viral_dna_json_v1"
    local_executable_path: str | None = None
    local_fixed_args: list[str] = Field(default_factory=list)
    local_timeout_seconds: int = 300
    local_concurrency: int = 1
    local_protocol_version: str = "viral-dna-image-tool/v1"
    local_tool_id: str | None = None
    local_tool_version: str | None = None
    local_cost_source: GenerationCostSource = GenerationCostSource.UNKNOWN
    local_unit_cost_micros: int | None = None
    semantic_quality_enabled: bool = False
    local_model_policy: str = "latest_flagship"
    local_model: str | None = None
    local_reasoning_effort: str = "xhigh"
    local_windows_sandbox_mode: Literal["auto", "elevated", "unelevated"] = "auto"
    local_proxy_mode: Literal["system", "manual", "disabled"] = "system"
    local_proxy_url: str | None = None
    local_proxy_detected_url: str | None = None
    local_proxy_effective_url: str | None = None
    local_proxy_delivery: Literal["codex_native", "environment", "direct"] = "direct"
    local_proxy_source: Literal[
        "manual",
        "windows_user_proxy",
        "environment",
        "disabled",
        "none",
    ] = "none"
    last_validated_at: datetime | None = None
    validation_latency_ms: int | None = Field(default=None, ge=0)
    catalog_version: str
    pricing_version: str
    selected_capabilities: ImageGenerationCapability | None = None
    models: list[ImageGenerationModelOption]


class LocalImageToolDetectRequest(BaseModel):
    adapter_id: str = Field(
        default="viral_dna_json_v1",
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    executable_path: str = Field(min_length=1, max_length=2048)
    fixed_args: list[str] = Field(default_factory=list, max_length=20)
    protocol_version: str = Field(
        default="viral-dna-image-tool/v1",
        min_length=1,
        max_length=80,
    )
    timeout_seconds: int = Field(default=20, ge=3, le=120)
    proxy_mode: Literal["system", "manual", "disabled"] = "system"
    proxy_url: str | None = Field(default=None, max_length=500)


class LocalImageToolDetectResponse(BaseModel):
    tool_id: str
    tool_version: str
    protocol_version: str
    capabilities: ImageGenerationCapability
    latency_ms: int = Field(ge=0)


class LocalCodexDiscoveryResponse(BaseModel):
    codex_found: bool = False
    codex_executable_path: str | None = None
    codex_version: str | None = None
    auth_status: Literal["authenticated", "not_authenticated", "unknown"] = "unknown"
    desktop_app_found: bool = False
    imagegen_status: Literal["installed_unverified", "not_found"] = "not_found"
    imagegen_skill_path: str | None = None
    recommended_adapter_id: str = "codex_imagegen_v1"
    recommended_model_policy: Literal["latest_flagship"] = "latest_flagship"
    recommended_model: str = "gpt-5.6-sol"
    recommended_reasoning_effort: Literal["xhigh"] = "xhigh"
    model_catalog_version: str
    wrapper_path: str
    can_auto_configure: bool = False
    requires_smoke_test: bool = True
    warnings: list[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=utc_now)


class LocalCodexAutoConfigureRequest(BaseModel):
    model_policy: Literal["latest_flagship", "pinned", "balanced"] = (
        "latest_flagship"
    )
    model: str | None = Field(default=None, max_length=160)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "xhigh"
    default_candidate_count: int = Field(default=1, ge=1, le=4)
    proxy_mode: Literal["system", "manual", "disabled"] = "system"
    proxy_url: str | None = Field(default=None, max_length=500)
    windows_sandbox_mode: Literal["auto", "elevated", "unelevated"] = "auto"


class LocalCodexNetworkTestRequest(BaseModel):
    proxy_mode: Literal["system", "manual", "disabled"] = "system"
    proxy_url: str | None = Field(default=None, max_length=500)
    timeout_seconds: int = Field(default=15, ge=3, le=60)

    @model_validator(mode="after")
    def validate_proxy(self) -> LocalCodexNetworkTestRequest:
        if self.proxy_mode == "manual" and not (self.proxy_url or "").strip():
            raise ValueError("手动代理模式必须填写代理地址")
        return self


class LocalCodexNetworkTestResponse(BaseModel):
    reachable: bool
    auth_status: Literal["authenticated", "not_authenticated", "unknown"]
    endpoint_host: str = "chatgpt.com"
    http_status: int | None = None
    proxy_source: Literal[
        "manual",
        "windows_user_proxy",
        "environment",
        "disabled",
        "none",
    ]
    effective_proxy_url: str | None = None
    latency_ms: int = Field(ge=0)
    message: str


class LocalCodexSandboxTestRequest(BaseModel):
    proxy_mode: Literal["system", "manual", "disabled"] = "system"
    proxy_url: str | None = Field(default=None, max_length=500)
    windows_sandbox_mode: Literal["auto", "elevated", "unelevated"] = "auto"
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def validate_proxy(self) -> LocalCodexSandboxTestRequest:
        if self.proxy_mode == "manual" and not (self.proxy_url or "").strip():
            raise ValueError("手动代理模式必须填写代理地址")
        return self


class LocalCodexSandboxTestResponse(BaseModel):
    ready: bool = True
    sandbox_mode: Literal["auto", "elevated", "unelevated"]
    proxy_delivery: Literal["codex_native", "environment", "direct"]
    latency_ms: int = Field(ge=0)
    message: str


class LinkVideoCreate(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=120)
    target_model: str = Field(default="seedance", max_length=40)
    rights_confirmed: bool


class Video(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    record_id: UUID | None = None
    source_type: SourceType
    source_url: str | None = None
    resolved_source_url: str | None = None
    source_video_id: str | None = None
    source_author: str | None = None
    ingested_at: datetime | None = None
    original_filename: str | None = None
    stored_path: str | None = Field(default=None, exclude=True)
    stored_relative_path: str | None = Field(default=None, exclude=True)
    title: str
    target_model: str = "seedance"
    status: VideoStatus = VideoStatus.READY
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sha256: str | None = None
    has_audio: bool | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AnalysisCreate(BaseModel):
    granularity: Literal["standard", "fine"] = "fine"
    include_audio: bool = True
    include_ocr: bool = True
    analysis_profile: AnalysisProfile = AnalysisProfile.BALANCED
    max_cost_cny: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=6)


class ModelTargetSnapshot(BaseModel):
    alias: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    region: str = Field(default="cn-beijing", min_length=1, max_length=80)
    endpoint: str = Field(default="default", min_length=1, max_length=80)
    thinking: bool = False
    prompt_version: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(min_length=1, max_length=80)


class ModelRouteSnapshot(BaseModel):
    task: ModelTask
    targets: list[ModelTargetSnapshot] = Field(min_length=1)


class ModelPlanSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    profile: AnalysisProfile
    catalog_version: str = Field(min_length=1, max_length=80)
    pricing_version: str = Field(min_length=1, max_length=80)
    routes: list[ModelRouteSnapshot]
    created_at: datetime = Field(default_factory=utc_now)

    def targets_for(self, task: ModelTask) -> list[ModelTargetSnapshot]:
        route = next((item for item in self.routes if item.task == task), None)
        return list(route.targets) if route else []


class AnalysisError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AnalysisJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    record_id: UUID | None = None
    video_id: UUID
    analysis_version: str = "phase1-simulated-v1"
    analysis_mode: AnalysisMode = AnalysisMode.SIMULATED
    granularity: Literal["standard", "fine"] = "fine"
    include_audio: bool = True
    include_ocr: bool = True
    analysis_profile: AnalysisProfile = AnalysisProfile.BALANCED
    max_cost_micros: int | None = Field(default=None, gt=0)
    model_plan: ModelPlanSnapshot | None = None
    estimated_cost_micros: int = Field(default=0, ge=0)
    measured_cost_micros: int = Field(default=0, ge=0)
    stage: AnalysisStage = AnalysisStage.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    message: str = "等待分析"
    simulated: bool = True
    error: AnalysisError | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class Shot(BaseModel):
    id: str
    index: int
    start_seconds: float
    end_seconds: float
    title: str
    subjects: list[str]
    action: str
    scene: str
    camera: str
    composition: str
    lighting: str
    color: str
    dialogue: str | None = None
    subtitle_text: str | None = None
    ocr_text: str | None = None
    audio: str
    transition: str
    narrative_role: str
    prompt: str
    confidence: float = Field(ge=0, le=1)
    keyframe_url: str | None = None
    evidence_frame_urls: list[str] = Field(default_factory=list)
    evidence_kind: Literal["simulated", "measured", "model"] = "simulated"

    boundary_method: str | None = Field(default=None, max_length=80)
    boundary_confidence: float | None = Field(default=None, ge=0, le=1)
    source_candidate_ids: list[str] = Field(default_factory=list)
    semantic_group: str | None = Field(default=None, max_length=120)


class ShotVisualFacts(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subjects: list[str] = Field(default_factory=list, max_length=20)
    action: str = Field(min_length=1, max_length=1200)
    scene: str = Field(min_length=1, max_length=1200)
    camera: str = Field(min_length=1, max_length=1200)
    composition: str = Field(min_length=1, max_length=1200)
    lighting: str = Field(min_length=1, max_length=1200)
    color: str = Field(min_length=1, max_length=1200)
    transition: str = Field(min_length=1, max_length=800)
    narrative_role: str = Field(min_length=1, max_length=800)
    replication_prompt: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1)
    contains_multiple_scenes: bool = False
    multiple_scenes_reason: str | None = Field(default=None, max_length=800)


SemanticShotGroup = Literal[
    "情境/钩子",
    "产品/主体演示",
    "结果/生活方式",
    "知识/观点",
    "行动引导/结尾",
    "其他",
]


class ShotBoundaryDecision(BaseModel):
    candidate_id: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^candidate_[0-9]{3}$",
    )
    before_description: str = Field(min_length=1, max_length=500)
    after_description: str = Field(min_length=1, max_length=500)
    decision: Literal["keep", "reject"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=800)
    semantic_group_before: SemanticShotGroup
    semantic_group_after: SemanticShotGroup
    progressive_motion: bool


class ShotSegmentationSelection(BaseModel):
    candidate_reviews: list[ShotBoundaryDecision] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)


class Entity(BaseModel):
    id: str
    type: Literal["person", "wardrobe", "scene", "product", "prop", "style"]
    name: str
    description: str
    occurrence_shot_ids: list[str]
    replaceable_fields: list[str]
    confidence: float = Field(ge=0, le=1)


class ViralFinding(BaseModel):
    id: str
    type: str
    title: str
    score: int = Field(ge=0, le=100)
    start_seconds: float
    end_seconds: float
    observation: str
    mechanism: str
    expected_effect: str
    recommendation: str
    confidence: float = Field(ge=0, le=1)


class PromptShot(BaseModel):
    shot_id: str
    duration_seconds: float
    prompt: str
    negative_constraints: list[str]


class PromptPackage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    version: int = 1
    target_model: str
    aspect_ratio: str = "9:16"
    global_prompt: str
    continuity_locks: list[str]
    entities: dict[str, str]
    shots: list[PromptShot]
    negative_constraints: list[str]
    created_at: datetime = Field(default_factory=utc_now)


class VideoOverview(BaseModel):
    summary: str
    content_type: str
    narrative_structure: str
    audience_inference: str
    visual_style: str
    duration_seconds: float
    aspect_ratio: str
    viral_potential_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)


class SubtitleStream(BaseModel):
    index: int = Field(ge=0)
    codec_name: str = Field(min_length=1, max_length=80)
    language: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=200)
    extractable: bool = False


class MediaMetadata(BaseModel):
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation: int = 0
    fps: float = Field(ge=0)
    format_name: str
    video_codec: str
    audio_codec: str | None = None
    has_audio: bool
    size_bytes: int = Field(gt=0)
    bit_rate: int | None = Field(default=None, ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    aspect_ratio: str
    subtitle_streams: list[SubtitleStream] = Field(default_factory=list)


class ShotEvidence(BaseModel):
    shot_id: str
    index: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    representative_timestamp: float = Field(ge=0)
    keyframe_url: str
    evidence_frame_urls: list[str] = Field(default_factory=list)
    detection_method: str

    boundary_method: str | None = Field(default=None, max_length=80)
    boundary_confidence: float | None = Field(default=None, ge=0, le=1)
    source_candidate_ids: list[str] = Field(default_factory=list)
    semantic_group: str | None = Field(default=None, max_length=120)


class SceneBoundaryCandidate(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^candidate_[0-9]{3}$")
    timestamp_seconds: float = Field(gt=0)
    score: float = Field(ge=0, le=1)
    methods: list[str] = Field(min_length=1)
    hard_boundary: bool = False
    evidence_frame_urls: list[str] = Field(default_factory=list, max_length=2)
    evidence_timestamps: list[float] = Field(default_factory=list, max_length=4)
    comparison_image_url: str | None = None
    selected_by_model: bool = False
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    model_before_description: str | None = Field(default=None, max_length=500)
    model_after_description: str | None = Field(default=None, max_length=500)
    model_reason: str | None = Field(default=None, max_length=800)
    model_decision: Literal["keep", "reject"] | None = None
    model_progressive_motion: bool | None = None
    model_consistency_adjusted: bool = False
    semantic_group_before: str | None = Field(default=None, max_length=120)
    semantic_group_after: str | None = Field(default=None, max_length=120)


class SegmentationMetadata(BaseModel):
    strategy: str = "hybrid_candidate_vlm"
    detector_version: str
    candidate_count: int = Field(default=0, ge=0)
    candidates: list[SceneBoundaryCandidate] = Field(default_factory=list)
    context_sheet_url: str | None = None
    context_timestamps: list[float] = Field(default_factory=list)
    program_boundaries: list[float] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    final_boundaries: list[float] = Field(default_factory=list)
    final_shot_count: int = Field(default=0, ge=0)
    verified_by_model: bool = False
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    model_summary: str | None = Field(default=None, max_length=1200)
    fallback_reason: str | None = Field(default=None, max_length=500)


class MediaEvidence(BaseModel):
    processor_version: str
    metadata: MediaMetadata
    proxy_url: str
    audio_url: str | None = None
    subtitle_url: str | None = None
    subtitle_extraction_message: str | None = Field(default=None, max_length=500)
    contact_sheet_url: str | None = None
    manifest_url: str
    shots: list[ShotEvidence]
    segmentation: SegmentationMetadata | None = None


class EvidenceProviderStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class EvidenceProviderRun(BaseModel):
    kind: Literal["asr", "ocr", "subtitle"]
    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    status: EvidenceProviderStatus
    item_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    message: str | None = Field(default=None, max_length=500)


class TranscriptWord(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def end_after_start(self) -> TranscriptWord:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("词级转写结束时间必须晚于开始时间")
        return self


class TranscriptSegment(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[TranscriptWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def end_after_start(self) -> TranscriptSegment:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("转写片段结束时间必须晚于开始时间")
        return self


class SubtitleCue(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    stream_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def end_after_start(self) -> SubtitleCue:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("字幕结束时间必须晚于开始时间")
        return self


class OCRObservation(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    timestamp_seconds: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: list[float] | None = Field(default=None, min_length=4, max_length=4)
    shot_id: str | None = Field(default=None, max_length=80)
    frame_url: str | None = None


class ShotTimelineEvidence(BaseModel):
    shot_id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    transcript_segment_ids: list[str] = Field(default_factory=list)
    transcript_text: str | None = None
    subtitle_cue_ids: list[str] = Field(default_factory=list)
    subtitle_text: str | None = None
    ocr_observation_ids: list[str] = Field(default_factory=list)
    ocr_text: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> ShotTimelineEvidence:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("镜头时间线结束时间必须晚于开始时间")
        return self


class EvidenceTimeline(BaseModel):
    timeline_version: str = "phase1-evidence-timeline-v2"
    duration_seconds: float = Field(gt=0)
    language: str | None = Field(default=None, max_length=20)
    provider_runs: list[EvidenceProviderRun]
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    subtitle_cues: list[SubtitleCue] = Field(default_factory=list)
    ocr_observations: list[OCRObservation] = Field(default_factory=list)
    shots: list[ShotTimelineEvidence]
    warnings: list[str] = Field(default_factory=list)
    artifact_url: str


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    video_seconds: float = Field(default=0, ge=0)


class PriceSnapshot(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    catalog_version: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    region: str = Field(min_length=1, max_length=80)
    input_tokens_above: int = Field(default=0, ge=0)
    input_tokens_at_most: int = Field(gt=0)
    input_cny_per_million: Decimal = Field(ge=0)
    cached_input_cny_per_million: Decimal | None = Field(default=None, ge=0)
    output_cny_per_million: Decimal = Field(ge=0)
    currency: Literal["CNY"] = "CNY"
    effective_from: datetime
    source_url: str


class ModelRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID
    video_id: UUID
    task: ModelTask
    shot_id: str | None = Field(default=None, max_length=80)
    attempt: int = Field(default=1, ge=1)
    retry_of_run_id: UUID | None = None
    cache_source_run_id: UUID | None = None
    provider: str = Field(min_length=1, max_length=80)
    requested_model: str = Field(min_length=1, max_length=160)
    resolved_model: str | None = Field(default=None, max_length=160)
    prompt_version: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(min_length=1, max_length=80)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    provider_request_id: str | None = Field(default=None, max_length=200)
    status: ModelRunStatus = ModelRunStatus.RUNNING
    usage: ModelUsage = Field(default_factory=ModelUsage)
    price_snapshot_id: str | None = Field(default=None, max_length=160)
    estimated_cost_micros: int = Field(default=0, ge=0)
    measured_cost_micros: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    raw_response_ref: str | None = Field(default=None, max_length=500)
    result_payload: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class ModelCostBreakdown(BaseModel):
    provider: str
    model: str
    run_count: int = Field(default=0, ge=0)
    measured_cost_micros: int = Field(default=0, ge=0)


class AnalysisCostSummary(BaseModel):
    analysis_id: UUID
    currency: Literal["CNY"] = "CNY"
    status: CostStatus = CostStatus.ESTIMATED
    estimated_cost_micros: int = Field(default=0, ge=0)
    measured_cost_micros: int = Field(default=0, ge=0)
    run_count: int = Field(default=0, ge=0)
    completed_run_count: int = Field(default=0, ge=0)
    failed_run_count: int = Field(default=0, ge=0)
    cached_run_count: int = Field(default=0, ge=0)
    breakdown: list[ModelCostBreakdown] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    video_id: UUID
    analysis_id: UUID
    analysis_mode: AnalysisMode = AnalysisMode.SIMULATED
    overview: VideoOverview
    shots: list[Shot]
    entities: list[Entity]
    viral_findings: list[ViralFinding]
    prompt_package: PromptPackage
    media_evidence: MediaEvidence | None = None
    evidence_timeline: EvidenceTimeline | None = None
    model_warnings: list[str] = Field(default_factory=list)
    model_cost_summary: AnalysisCostSummary | None = None
    generated_at: datetime = Field(default_factory=utc_now)


class ReplacementItem(BaseModel):
    entity_id: str
    description: str = Field(min_length=2, max_length=500)


class ReplacementCreate(BaseModel):
    replacements: list[ReplacementItem] = Field(min_length=1, max_length=10)
    locks: list[Literal["timing", "camera", "composition", "action", "lighting", "audio"]] = Field(
        default_factory=lambda: ["timing", "camera", "composition", "action"]
    )

    @model_validator(mode="after")
    def unique_entities(self) -> ReplacementCreate:
        ids = [item.entity_id for item in self.replacements]
        if len(ids) != len(set(ids)):
            raise ValueError("同一元素不能重复替换")
        return self


class ReplacementDiff(BaseModel):
    entity_id: str
    before: str
    after: str
    affected_shot_ids: list[str]


class ReplacementVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    source_prompt_package_id: UUID
    prompt_package: PromptPackage
    diffs: list[ReplacementDiff]
    locks: list[str]
    created_at: datetime = Field(default_factory=utc_now)


class ProductionProject(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    record_id: UUID
    video_id: UUID
    base_analysis_id: UUID
    source_prompt_package_id: UUID
    source_project_id: UUID | None = None
    source_revision_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    status: ProductionProjectStatus = ProductionProjectStatus.DRAFT
    active_step: ProductionStep = ProductionStep.PROJECT_SETUP
    current_revision_id: UUID | None = None
    output_aspect_ratio: str = Field(
        default="9:16",
        min_length=3,
        max_length=20,
        pattern=r"^\d{1,5}:\d{1,5}$",
    )
    output_width: int = Field(default=1080, ge=256, le=8192)
    output_height: int = Field(default=1920, ge=256, le=8192)
    budget_limit_micros: int | None = Field(default=None, gt=0)
    estimated_cost_micros: int = Field(default=0, ge=0)
    actual_cost_micros: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("output_aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value: str) -> str:
        width, height = (int(part) for part in value.split(":"))
        if width <= 0 or height <= 0:
            raise ValueError("输出画面比例必须大于零")
        return f"{width}:{height}"


class ProductionRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    parent_revision_id: UUID | None = None
    revision_number: int = Field(ge=1)
    change_kind: ProductionChangeKind
    change_summary: str = Field(min_length=1, max_length=500)
    snapshot_relative_path: str = Field(min_length=1, max_length=2048)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("snapshot_relative_path")
    @classmethod
    def validate_snapshot_path(cls, value: str) -> str:
        return _normalize_workspace_relative_path(value)


class ReferenceAsset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    type: ReferenceAssetType
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    relative_path: str = Field(min_length=1, max_length=2048)
    thumbnail_relative_path: str | None = Field(default=None, max_length=2048)
    mime_type: str = Field(min_length=1, max_length=120)
    width: int = Field(gt=0, le=32768)
    height: int = Field(gt=0, le=32768)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    tags: list[str] = Field(default_factory=list, max_length=20)
    rights_confirmed: bool = False
    rights_note: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _normalize_workspace_relative_path(value)

    @field_validator("thumbnail_relative_path")
    @classmethod
    def validate_thumbnail_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("参考资产标签不能重复")
        return normalized


class ProjectAssetLink(BaseModel):
    """Stable association between a project and a workspace-level asset."""

    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    project_id: UUID
    asset_id: UUID
    reference_type: ReferenceAssetType
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    removed_at: datetime | None = None


class ReferenceBinding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    shot_plan_id: UUID
    reference_asset_id: UUID
    role: ReferenceRole
    weight: float = Field(default=1, ge=0, le=2)
    crop_hint: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class PromptAssetMention(BaseModel):
    reference_asset_id: UUID
    label: str = Field(min_length=1, max_length=120)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lstrip("@").strip()
        if not normalized:
            raise ValueError("提示词资产名称不能为空")
        return normalized


class ShotPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_id: UUID
    source_shot_id: str = Field(min_length=1, max_length=120)
    index: int = Field(ge=1)
    lifecycle_status: ShotLifecycleStatus = ShotLifecycleStatus.ACTIVE
    source_kind: ShotSourceKind = ShotSourceKind.ANALYSIS
    source_keyframe_url: str | None = Field(default=None, min_length=1, max_length=2048)
    source_keyframe_relative_path: str | None = Field(default=None, max_length=2048)
    source_keyframe_timestamp_seconds: float | None = Field(default=None, ge=0)
    source_keyframe_origin: Literal[
        "analysis",
        "video_selection",
        "duplicate",
        "blank",
    ] = "analysis"
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    image_prompt: str = Field(default="", max_length=8000)
    image_prompt_mentions: list[PromptAssetMention] = Field(
        default_factory=list,
        max_length=20,
    )
    image_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    video_prompt: str = Field(default="", max_length=8000)
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    locks: list[ShotLock] = Field(
        default_factory=lambda: [
            ShotLock.TIMING,
            ShotLock.CAMERA,
            ShotLock.COMPOSITION,
            ShotLock.ACTION,
        ],
        max_length=6,
    )
    required: bool = True
    image_status: WorkflowItemStatus = WorkflowItemStatus.DRAFT
    video_status: WorkflowItemStatus = WorkflowItemStatus.DRAFT
    approved_image_candidate_id: UUID | None = None
    approved_video_candidate_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "image_negative_constraints",
        "video_negative_constraints",
        "locks",
    )
    @classmethod
    def require_unique_items(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("分镜约束和锁定项不能重复")
        return values

    @field_validator("image_prompt_mentions")
    @classmethod
    def require_unique_prompt_mentions(
        cls,
        values: list[PromptAssetMention],
    ) -> list[PromptAssetMention]:
        ids = [item.reference_asset_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("同一参考资产不能在提示词中重复关联")
        return values

    @field_validator("source_keyframe_relative_path")
    @classmethod
    def validate_source_keyframe_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_timeline(self) -> ShotPlan:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("分镜结束时间必须晚于开始时间")
        if (
            self.source_keyframe_timestamp_seconds is not None
            and not self.start_seconds <= self.source_keyframe_timestamp_seconds <= self.end_seconds
        ):
            raise ValueError("分镜关键帧时间必须位于当前分镜范围内")
        return self


class GenerationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    shot_plan_id: UUID
    revision_id: UUID
    kind: GenerationKind
    input_mode: ImageGenerationInputMode = ImageGenerationInputMode.KEYFRAME_EDIT
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    model_snapshot: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(min_length=1, max_length=80)
    pricing_version: str = Field(min_length=1, max_length=80)
    request_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    input_snapshot_relative_path: str = Field(min_length=1, max_length=2048)
    execution_mode: ImageExecutionMode = ImageExecutionMode.SIMULATED
    adapter_id: str = Field(default="simulated", min_length=1, max_length=120)
    adapter_version: str = Field(default="batch4.1", min_length=1, max_length=120)
    protocol_version: str | None = Field(default=None, max_length=120)
    provider_request_id: str | None = Field(default=None, max_length=300)
    capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
    cost_source: GenerationCostSource = GenerationCostSource.UNMETERED
    cost_estimate_known: bool = True
    usage: dict[str, Any] = Field(default_factory=dict)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    retry_of_run_id: UUID | None = None
    cancellation_requested: bool = False
    output_manifest_relative_path: str | None = Field(default=None, max_length=2048)
    status: ProductionRunStatus = ProductionRunStatus.QUEUED
    estimated_cost_micros: int = Field(default=0, ge=0)
    actual_cost_micros: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("input_snapshot_relative_path")
    @classmethod
    def validate_input_snapshot_path(cls, value: str) -> str:
        return _normalize_workspace_relative_path(value)

    @field_validator("output_manifest_relative_path")
    @classmethod
    def validate_output_manifest_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None


class GenerationCandidate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    generation_run_id: UUID
    ordinal: int = Field(ge=1)
    kind: GenerationKind
    relative_path: str = Field(min_length=1, max_length=2048)
    thumbnail_relative_path: str | None = Field(default=None, max_length=2048)
    width: int | None = Field(default=None, gt=0, le=32768)
    height: int | None = Field(default=None, gt=0, le=32768)
    duration_seconds: float | None = Field(default=None, gt=0)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    metadata_relative_path: str = Field(min_length=1, max_length=2048)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: GenerationCandidateStatus = GenerationCandidateStatus.READY
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "relative_path",
        "thumbnail_relative_path",
        "metadata_relative_path",
    )
    @classmethod
    def validate_candidate_paths(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None


class ApprovalEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_id: UUID
    shot_plan_id: UUID
    candidate_id: UUID
    target_kind: GenerationKind
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> ApprovalEvent:
        if self.decision == ApprovalDecision.REJECTED and not (self.reason or "").strip():
            raise ValueError("退回候选时必须填写原因")
        return self


class ProductionProjectCreate(BaseModel):
    base_analysis_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    output_aspect_ratio: str | None = Field(
        default=None,
        min_length=3,
        max_length=20,
        pattern=r"^\d{1,5}:\d{1,5}$",
    )
    output_width: int | None = Field(default=None, ge=256, le=8192)
    output_height: int | None = Field(default=None, ge=256, le=8192)
    budget_limit_micros: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_complete_dimensions(self) -> ProductionProjectCreate:
        if (self.output_width is None) != (self.output_height is None):
            raise ValueError("输出宽度和高度必须同时设置")
        return self


class ProductionProjectUpdate(BaseModel):
    expected_revision_id: UUID
    confirm_stale: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=120)
    output_aspect_ratio: str | None = Field(
        default=None,
        min_length=3,
        max_length=20,
        pattern=r"^\d{1,5}:\d{1,5}$",
    )
    output_width: int | None = Field(default=None, ge=256, le=8192)
    output_height: int | None = Field(default=None, ge=256, le=8192)
    budget_limit_micros: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_project_change(self) -> ProductionProjectUpdate:
        changed_fields = self.model_fields_set - {"expected_revision_id", "confirm_stale"}
        if not changed_fields:
            raise ValueError("至少需要提供一个要修改的创作方案字段")
        if ("output_width" in changed_fields) != ("output_height" in changed_fields):
            raise ValueError("输出宽度和高度必须同时设置")
        return self


class ProductionBranchCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source_revision_id: UUID | None = None


class ProductionRevisionResponse(BaseModel):
    id: UUID
    project_id: UUID
    parent_revision_id: UUID | None = None
    revision_number: int = Field(ge=1)
    change_kind: ProductionChangeKind
    change_summary: str
    created_at: datetime


class ProductionRevisionDetail(ProductionRevisionResponse):
    snapshot: dict[str, Any]


class ProductionProjectDetail(BaseModel):
    project: ProductionProject
    current_revision: ProductionRevisionResponse | None = None
    revision_count: int = Field(default=0, ge=0)
    reference_count: int = Field(default=0, ge=0)
    shot_count: int = Field(default=0, ge=0)
    discarded_shot_count: int = Field(default=0, ge=0)
    approved_image_count: int = Field(default=0, ge=0)
    stale_image_count: int = Field(default=0, ge=0)


class ReferenceAssetCreate(BaseModel):
    expected_revision_id: UUID
    type: ReferenceAssetType
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    rights_confirmed: bool = False
    rights_note: str | None = Field(default=None, max_length=1000)


class ProjectAssetLinkCreate(BaseModel):
    expected_revision_id: UUID
    type: ReferenceAssetType | None = None


class ReferenceAssetUpdate(BaseModel):
    expected_revision_id: UUID
    confirm_stale: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)
    rights_confirmed: bool | None = None
    rights_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_asset_change(self) -> ReferenceAssetUpdate:
        if not (self.model_fields_set - {"expected_revision_id", "confirm_stale"}):
            raise ValueError("至少需要提供一个要修改的参考资产字段")
        return self


class ReferenceAssetResponse(BaseModel):
    id: UUID
    project_id: UUID
    type: ReferenceAssetType
    name: str
    description: str
    mime_type: str
    width: int
    height: int
    sha256: str
    tags: list[str]
    rights_confirmed: bool
    rights_note: str | None = None
    content_url: str
    thumbnail_url: str
    current_revision_id: UUID
    created_at: datetime
    archived_at: datetime | None = None


class ReferenceBindingInput(BaseModel):
    reference_asset_id: UUID
    role: ReferenceRole
    weight: float = Field(default=1, ge=0, le=2)
    crop_hint: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)


class ShotPlanFieldsUpdate(BaseModel):
    image_prompt: str | None = Field(default=None, max_length=8000)
    image_prompt_mentions: list[PromptAssetMention] | None = Field(
        default=None,
        max_length=20,
    )
    image_negative_constraints: list[str] | None = Field(default=None, max_length=40)
    video_prompt: str | None = Field(default=None, max_length=8000)
    video_negative_constraints: list[str] | None = Field(default=None, max_length=40)
    locks: list[ShotLock] | None = Field(default=None, max_length=6)
    required: bool | None = None
    reference_bindings: list[ReferenceBindingInput] | None = Field(default=None, max_length=20)

    @field_validator(
        "image_negative_constraints",
        "video_negative_constraints",
        "locks",
    )
    @classmethod
    def require_unique_update_items(cls, values: list[Any] | None) -> list[Any] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("分镜约束和锁定项不能重复")
        return values

    @field_validator("reference_bindings")
    @classmethod
    def require_unique_bindings(
        cls,
        values: list[ReferenceBindingInput] | None,
    ) -> list[ReferenceBindingInput] | None:
        if values is None:
            return values
        keys = [(item.reference_asset_id, item.role) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一参考资产和角色不能重复绑定")
        return values

    @field_validator("image_prompt_mentions")
    @classmethod
    def require_unique_mentions(
        cls,
        values: list[PromptAssetMention] | None,
    ) -> list[PromptAssetMention] | None:
        if values is None:
            return values
        ids = [item.reference_asset_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("同一参考资产不能在提示词中重复关联")
        return values


class ShotPlanUpdate(ShotPlanFieldsUpdate):
    expected_revision_id: UUID
    confirm_stale: bool = False

    @model_validator(mode="after")
    def require_shot_change(self) -> ShotPlanUpdate:
        if not (self.model_fields_set - {"expected_revision_id", "confirm_stale"}):
            raise ValueError("至少需要提供一个要修改的分镜字段")
        return self


class ShotPlanBulkItem(ShotPlanFieldsUpdate):
    shot_plan_id: UUID

    @model_validator(mode="after")
    def require_bulk_item_change(self) -> ShotPlanBulkItem:
        if not (self.model_fields_set - {"shot_plan_id"}):
            raise ValueError("至少需要提供一个要修改的分镜字段")
        return self


class ShotPlanBulkUpdate(BaseModel):
    expected_revision_id: UUID
    confirm_stale: bool = False
    updates: list[ShotPlanBulkItem] = Field(min_length=1, max_length=100)

    @field_validator("updates")
    @classmethod
    def require_unique_shot_updates(
        cls,
        values: list[ShotPlanBulkItem],
    ) -> list[ShotPlanBulkItem]:
        ids = [item.shot_plan_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("同一分镜不能重复更新")
        return values


class ShotPlanCreate(BaseModel):
    expected_revision_id: UUID
    mode: Literal["duplicate", "video_range", "blank"] = "duplicate"
    insert_after_shot_plan_id: UUID | None = None
    source_shot_plan_id: UUID | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    source_keyframe_timestamp_seconds: float | None = Field(default=None, ge=0)
    image_prompt: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def validate_create_mode(self) -> ShotPlanCreate:
        if self.mode == "duplicate" and self.source_shot_plan_id is None:
            raise ValueError("复制分镜时必须指定源分镜")
        if self.mode == "video_range":
            if self.start_seconds is None or self.end_seconds is None:
                raise ValueError("视频选段必须提供开始和结束时间")
            if self.end_seconds <= self.start_seconds:
                raise ValueError("分镜结束时间必须晚于开始时间")
            if (
                self.source_keyframe_timestamp_seconds is not None
                and not self.start_seconds
                <= self.source_keyframe_timestamp_seconds
                <= self.end_seconds
            ):
                raise ValueError("关键帧时间必须位于视频选段范围内")
        return self


class ShotLifecycleUpdate(BaseModel):
    expected_revision_id: UUID
    insert_after_shot_plan_id: UUID | None = None


class ShotPlanReorder(BaseModel):
    expected_revision_id: UUID
    ordered_shot_plan_ids: list[UUID] = Field(min_length=1, max_length=200)

    @field_validator("ordered_shot_plan_ids")
    @classmethod
    def require_unique_order(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("分镜排序不能包含重复项")
        return values


class ShotPlanResponse(BaseModel):
    plan: ShotPlan
    reference_bindings: list[ReferenceBinding] = Field(default_factory=list)
    current_revision_id: UUID


class ChangeImpactRequest(BaseModel):
    expected_revision_id: UUID
    change_type: Literal[
        "project_settings",
        "reference_asset",
        "shot_plan",
        "candidate_selection",
        "image_approval_revoke",
    ]
    shot_plan_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reference_asset_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ChangeImpactResponse(BaseModel):
    impacted_shot_plan_ids: list[UUID] = Field(default_factory=list)
    impacted_shot_ids: list[str] = Field(default_factory=list)
    stale_candidate_ids: list[UUID] = Field(default_factory=list)
    stale_stage_ids: list[ProductionStep] = Field(default_factory=list)
    requires_confirmation: bool = False
    summary: str


class ImageGenerationCreate(BaseModel):
    expected_revision_id: UUID
    candidate_count: int = Field(default=1, ge=1, le=4)
    input_mode: ImageGenerationInputMode = ImageGenerationInputMode.KEYFRAME_EDIT
    execution_mode: Literal["remote_api", "local_tool"] | None = None
    allow_unknown_cost: bool = False
    generation_intent: Literal["standard", "new_variation"] = "standard"
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)


class ShotKeyframeSelectRequest(BaseModel):
    expected_revision_id: UUID
    timestamp_seconds: float = Field(ge=0)
    confirm_stale: bool = False


class ShotSourceFrameApprovalRequest(BaseModel):
    expected_revision_id: UUID
    reason: str | None = Field(default=None, max_length=1000)


class ShotImageApprovalRevokeRequest(BaseModel):
    expected_revision_id: UUID
    reason: str | None = Field(default=None, max_length=1000)
    confirm_downstream_stale: bool = False


class GenerationCandidateResponse(BaseModel):
    id: UUID
    generation_run_id: UUID
    ordinal: int
    kind: GenerationKind
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    sha256: str
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: GenerationCandidateStatus
    content_url: str
    thumbnail_url: str
    created_at: datetime


class GenerationRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    shot_plan_id: UUID
    revision_id: UUID
    kind: GenerationKind
    input_mode: ImageGenerationInputMode
    provider: str
    model: str
    model_snapshot: str
    execution_mode: ImageExecutionMode
    adapter_id: str
    adapter_version: str
    protocol_version: str | None = None
    provider_request_id: str | None = None
    capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    cost_source: GenerationCostSource
    cost_estimate_known: bool
    usage: dict[str, Any] = Field(default_factory=dict)
    status: ProductionRunStatus
    estimated_cost_micros: int
    actual_cost_micros: int
    latency_ms: int | None = None
    retry_count: int = 0
    retry_of_run_id: UUID | None = None
    cancellation_requested: bool = False
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    last_heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    candidates: list[GenerationCandidateResponse] = Field(default_factory=list)


class ShotPlanDetailResponse(ShotPlanResponse):
    generation_runs: list[GenerationRunResponse] = Field(default_factory=list)
    approval_events: list[ApprovalEvent] = Field(default_factory=list)


class CandidateSelectRequest(BaseModel):
    expected_revision_id: UUID


class CandidateApprovalRequest(BaseModel):
    expected_revision_id: UUID
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_candidate_rejection_reason(self) -> CandidateApprovalRequest:
        if self.decision == ApprovalDecision.REJECTED and not (self.reason or "").strip():
            raise ValueError("退回候选时必须填写原因")
        return self


class CandidateActionResponse(BaseModel):
    shot: ShotPlanResponse
    candidate: GenerationCandidateResponse
    approval_event: ApprovalEvent | None = None


class ProductionGateStatus(BaseModel):
    project_id: UUID
    current_step: ProductionStep
    next_step: ProductionStep | None = None
    allowed: bool
    required_shot_count: int = Field(ge=0)
    approved_shot_count: int = Field(ge=0)
    stale_shot_count: int = Field(ge=0)
    blocker_messages: list[str] = Field(default_factory=list)


class ProductionAdvanceRequest(BaseModel):
    expected_revision_id: UUID
    target_step: ProductionStep


class WorkspacePathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class WorkspaceValidationResponse(BaseModel):
    valid: bool
    normalized_path: str
    exists: bool
    writable: bool
    error: str | None = None


class WorkspaceInfo(BaseModel):
    root_path: str
    database_path: str
    initialized: bool = True
    writable: bool = True
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    record_count: int = Field(default=0, ge=0)
    folder_count: int = Field(default=0, ge=0)


class RecordFolder(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class FolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AnalysisRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    folder_id: UUID | None = None
    video_id: UUID
    source_type: SourceType
    source_url: str | None = None
    latest_analysis_id: UUID | None = None
    status: VideoStatus = VideoStatus.READY
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_opened_at: datetime | None = None


class AnalysisRecordUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    folder_id: UUID | None = None


class AnalysisRecordSummary(AnalysisRecord):
    thumbnail_url: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)


class AnalysisRecordList(BaseModel):
    items: list[AnalysisRecordSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int = Field(ge=0)


class AnalysisRecordDetail(BaseModel):
    record: AnalysisRecord
    video: Video
    analyses: list[AnalysisJob]
    latest_report: AnalysisReport | None = None


class ExportCreate(BaseModel):
    kinds: list[ExportKind] = Field(
        default_factory=lambda: [
            ExportKind.REPORT_JSON,
            ExportKind.REPORT_MARKDOWN,
            ExportKind.PROMPT_PACKAGE,
            ExportKind.TRANSCRIPT,
            ExportKind.SUBTITLES,
        ],
        min_length=1,
        max_length=5,
    )
    analysis_id: UUID | None = None
    replacement_version_id: UUID | None = None

    @model_validator(mode="after")
    def unique_kinds(self) -> ExportCreate:
        if len(self.kinds) != len(set(self.kinds)):
            raise ValueError("导出类型不能重复")
        return self


class ExportArtifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    record_id: UUID
    analysis_id: UUID
    kind: ExportKind
    filename: str = Field(min_length=1, max_length=240)
    relative_path: str = Field(exclude=True)
    media_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "viral-dna-api"
    version: str = "0.1.0"
    analyzer_mode: str


class ApiMessage(BaseModel):
    message: str
    details: dict[str, Any] | None = None
