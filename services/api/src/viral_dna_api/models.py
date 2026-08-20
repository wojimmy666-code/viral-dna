from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)

from .control_assets.domain import DepthControlAsset
from .prompt_engine.contracts import PromptShotDraft
from .reference_routes.domain import VideoReferenceRouteCapability
from .schema import WORKSPACE_SCHEMA_VERSION
from .video_references.domain import (
    PersonReferenceCapability,
    VideoReferenceBinding,
)


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


class AnalysisRecordLifecycle(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"


class AnalysisRecordLifecycleAction(StrEnum):
    ARCHIVE = "archive"
    ACTIVATE = "activate"
    TRASH = "trash"
    RESTORE = "restore"


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
    IMAGE_CANDIDATES_ARCHIVED = "image_candidates_archived"
    IMAGE_CANDIDATES_RESTORED = "image_candidates_restored"
    IMAGE_APPROVED = "image_approved"
    IMAGE_APPROVAL_REVOKED = "image_approval_revoked"
    IMAGE_REJECTED = "image_rejected"
    VIDEO_CANDIDATES_CREATED = "video_candidates_created"
    VIDEO_CANDIDATES_ARCHIVED = "video_candidates_archived"
    VIDEO_CANDIDATES_RESTORED = "video_candidates_restored"
    VIDEO_CANDIDATE_SELECTED = "video_candidate_selected"
    VIDEO_APPROVED = "video_approved"
    VIDEO_APPROVAL_REVOKED = "video_approval_revoked"
    VIDEO_REJECTED = "video_rejected"
    VIDEO_PREPARATION_CHANGED = "video_preparation_changed"
    ANALYSIS_PROMPTS_SYNCED = "analysis_prompts_synced"
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


class VideoGenerationInputMode(StrEnum):
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    MULTI_IMAGE_TO_VIDEO = "multi_image_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    HYBRID_REFERENCE_TO_VIDEO = "hybrid_reference_to_video"


class VideoGenerationInputSource(StrEnum):
    """Optional generation inputs. Prompt text is always present and is not a toggle."""

    APPROVED_IMAGES = "approved_images"
    PROJECT_ASSETS = "project_assets"
    PROVIDER_MANAGED_ASSETS = "provider_managed_assets"
    REFERENCE_VIDEO = "reference_video"
    DEPTH_CONTROL = "depth_control"


class VideoPromptReferenceKind(StrEnum):
    """Stable source categories used by generation inputs and prompt mentions."""

    PROJECT_ASSET = "project_asset"
    APPROVED_IMAGE = "approved_image"
    PROVIDER_MANAGED_ASSET = "provider_managed_asset"
    REFERENCE_VIDEO = "reference_video"
    DEPTH_CONTROL = "depth_control"


class VideoPromptReferenceRole(StrEnum):
    ACTOR_IDENTITY = "actor_identity"
    COMPOSITION = "composition"
    SCENE = "scene"
    PRODUCT = "product"
    WARDROBE = "wardrobe"
    MOTION = "motion"
    CAMERA = "camera"
    DEPTH = "depth"


class VideoGenerationReference(BaseModel):
    """A concrete media input selected for one video generation request."""

    reference_kind: VideoPromptReferenceKind
    reference_id: UUID
    label: str = Field(min_length=1, max_length=260)
    role: VideoPromptReferenceRole
    order: int = Field(default=1, ge=1, le=100)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lstrip("@").strip()
        if not normalized:
            raise ValueError("视频生成参考名称不能为空")
        return normalized


class VideoGenerationInputPlan(BaseModel):
    schema_version: Literal["viral-dna-video-input-plan/v1"] = (
        "viral-dna-video-input-plan/v1"
    )
    sources: list[VideoGenerationInputSource] = Field(default_factory=list, max_length=5)
    references: list[VideoGenerationReference] = Field(default_factory=list, max_length=100)

    @field_validator("sources")
    @classmethod
    def require_unique_sources(
        cls,
        values: list[VideoGenerationInputSource],
    ) -> list[VideoGenerationInputSource]:
        if len(values) != len(set(values)):
            raise ValueError("视频生成输入不能重复")
        return values

    @field_validator("references")
    @classmethod
    def require_unique_references(
        cls,
        values: list[VideoGenerationReference],
    ) -> list[VideoGenerationReference]:
        keys = [(item.reference_kind, item.reference_id) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("视频生成参考不能重复")
        return values

    def includes(self, source: VideoGenerationInputSource) -> bool:
        return source in self.sources

    @property
    def input_mode(self) -> VideoGenerationInputMode:
        image_sources = {
            VideoGenerationInputSource.APPROVED_IMAGES,
            VideoGenerationInputSource.PROJECT_ASSETS,
            VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS,
        }
        control_sources = {
            VideoGenerationInputSource.REFERENCE_VIDEO,
            VideoGenerationInputSource.DEPTH_CONTROL,
        }
        image_count = sum(source in image_sources for source in self.sources)
        control_count = sum(source in control_sources for source in self.sources)
        if image_count == 0 and control_count == 0:
            return VideoGenerationInputMode.TEXT_TO_VIDEO
        if image_count and control_count:
            return VideoGenerationInputMode.HYBRID_REFERENCE_TO_VIDEO
        if control_count:
            return VideoGenerationInputMode.VIDEO_TO_VIDEO
        if image_count == 1 and VideoGenerationInputSource.APPROVED_IMAGES in self.sources:
            return VideoGenerationInputMode.IMAGE_TO_VIDEO
        return VideoGenerationInputMode.MULTI_IMAGE_TO_VIDEO


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


class VideoProviderTaskStatus(StrEnum):
    PENDING_SUBMISSION = "pending_submission"
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class GenerationCandidateStatus(StrEnum):
    READY = "ready"
    SELECTED = "selected"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class GenerationCandidateArchiveReason(StrEnum):
    USER_DELETED = "user_deleted"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REVOKED = "revoked"
    REJECTED = "rejected"


class VideoClipAudioMode(StrEnum):
    SOURCE = "source"
    MUTED = "muted"


class VideoClipPreparationStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"


class VideoQualityStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class TimelineTransitionKind(StrEnum):
    NONE = "none"
    FADE = "fade"
    CROSSFADE = "crossfade"


class TimelineChangeKind(StrEnum):
    INITIALIZED = "initialized"
    HANDOFF_SYNCED = "handoff_synced"
    CLIPS_UPDATED = "clips_updated"
    TRACKS_UPDATED = "tracks_updated"
    RESTORED = "restored"


class TimelineRenderStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TimelineRenderKind(StrEnum):
    PREVIEW = "preview"
    FINAL = "final"


class TimelineExportResolution(StrEnum):
    PROJECT = "project"
    P720 = "720p"
    P1080 = "1080p"


class TimelineExportSubtitleMode(StrEnum):
    BURNED = "burned"
    EMBEDDED = "embedded"
    NONE = "none"


class TimelineExportQuality(StrEnum):
    STANDARD = "standard"
    HIGH = "high"


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


class ManagedAssetKind(StrEnum):
    VIRTUAL_PERSON = "virtual_person"
    VERIFIED_PERSON = "verified_person"


class ManagedAssetRole(StrEnum):
    ACTOR_IDENTITY = "actor_identity"


class ManagedAssetMediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class ProviderManagedAssetCapability(BaseModel):
    supported: bool = False
    provider: str | None = Field(default=None, max_length=80)
    catalog_browsing: bool = False
    asset_kinds: list[ManagedAssetKind] = Field(default_factory=list, max_length=20)
    roles: list[ManagedAssetRole] = Field(default_factory=list, max_length=20)
    maximum_bindings: int = Field(default=0, ge=0, le=20)
    reference_transport: Literal["none", "asset_uri"] = "none"
    requires_same_project: bool = False

    @model_validator(mode="after")
    def validate_supported_capability(self) -> ProviderManagedAssetCapability:
        if not self.supported:
            return self
        if not self.provider or not self.catalog_browsing:
            raise ValueError("供应商托管资产能力必须声明目录 Provider")
        if not self.asset_kinds or not self.roles or self.maximum_bindings < 1:
            raise ValueError("供应商托管资产能力必须声明类型、角色和数量上限")
        if self.reference_transport == "none":
            raise ValueError("供应商托管资产能力必须声明请求传输协议")
        return self


class VideoGenerationCapability(BaseModel):
    text_to_video: bool = False
    image_to_video: bool = True
    reference_video: bool = False
    depth_control_video: bool = False
    multi_image_reference: bool = False
    ordered_reference_images: bool = False
    minimum_reference_images: int = Field(default=1, ge=0, le=20)
    maximum_reference_images: int = Field(default=1, ge=1, le=20)
    start_frame: bool = True
    end_frame: bool = False
    max_candidates: int = Field(default=4, ge=1, le=20)
    minimum_duration_seconds: float = Field(default=0.1, gt=0, le=60)
    maximum_duration_seconds: float = Field(default=60, gt=0, le=600)
    duration_step_seconds: float = Field(default=1, gt=0, le=60)
    default_duration_seconds: float | None = Field(default=None, gt=0, le=600)
    supported_durations: list[float] = Field(default_factory=list, max_length=30)
    maximum_width: int = Field(default=1920, ge=256, le=8192)
    maximum_height: int = Field(default=1920, ge=256, le=8192)
    native_audio: bool = False
    supports_negative_prompt: bool = True
    supports_seed: bool = True
    supports_camera_constraints: bool = True
    supported_resolutions: list[str] = Field(default_factory=list, max_length=20)
    supported_aspect_ratios: list[str] = Field(default_factory=list, max_length=20)
    maximum_prompt_characters: int = Field(default=2000, ge=1, le=100_000)
    managed_assets: ProviderManagedAssetCapability = Field(
        default_factory=ProviderManagedAssetCapability
    )
    person_references: PersonReferenceCapability = Field(
        default_factory=PersonReferenceCapability
    )
    reference_route: VideoReferenceRouteCapability = Field(
        default_factory=VideoReferenceRouteCapability
    )

    @model_validator(mode="after")
    def validate_reference_image_limits(self) -> VideoGenerationCapability:
        if self.maximum_reference_images < self.minimum_reference_images:
            raise ValueError("最大参考图数量不能小于最小参考图数量")
        if self.multi_image_reference and self.maximum_reference_images < 2:
            raise ValueError("多图参考模型必须至少支持两张参考图")
        if self.ordered_reference_images and not self.multi_image_reference:
            raise ValueError("有序参考图能力依赖多图参考能力")
        return self

    @computed_field(return_type=list[VideoGenerationInputSource])
    @property
    def supported_input_sources(self) -> list[VideoGenerationInputSource]:
        """Return the optional media inputs accepted by this model.

        Prompt text is deliberately omitted because it is always submitted.
        Audio is deliberately omitted because it belongs to the editing stage.
        """
        values: list[VideoGenerationInputSource] = []
        if self.image_to_video:
            values.extend(
                [
                    VideoGenerationInputSource.APPROVED_IMAGES,
                    VideoGenerationInputSource.PROJECT_ASSETS,
                ]
            )
        if self.managed_assets.supported:
            values.append(VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS)
        if self.reference_video:
            values.append(VideoGenerationInputSource.REFERENCE_VIDEO)
        if self.depth_control_video or self.reference_route.supports_depth_control_video:
            values.append(VideoGenerationInputSource.DEPTH_CONTROL)
        return values


class VideoGenerationModelOption(BaseModel):
    alias: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    provider: Literal["bailian", "volc_ark", "minimax"]
    model: str | None = Field(default=None, max_length=160)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    available: bool = True
    availability_note: str | None = Field(default=None, max_length=500)
    recommended: bool = False
    pricing_version: str = Field(min_length=1, max_length=80)
    pricing: dict[str, Any] = Field(default_factory=dict)
    capabilities: VideoGenerationCapability


class VideoProviderCredentialUpdate(BaseModel):
    provider: Literal["bailian", "volc_ark", "minimax"]
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    base_url: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    managed_asset_access_key: SecretStr | None = Field(default=None, max_length=256)
    managed_asset_secret_key: SecretStr | None = Field(default=None, max_length=512)
    managed_asset_region: Literal["cn-beijing", "cn-shanghai"] | None = None
    managed_asset_project_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    clear_managed_asset_credentials: bool = False

    @model_validator(mode="after")
    def validate_managed_asset_fields(self) -> VideoProviderCredentialUpdate:
        managed_fields_set = bool(
            self.managed_asset_access_key
            or self.managed_asset_secret_key
            or self.managed_asset_region
            or self.managed_asset_project_name
            or self.clear_managed_asset_credentials
        )
        if managed_fields_set and self.provider != "volc_ark":
            raise ValueError("只有火山方舟 Provider 支持托管资产目录配置")
        return self

class VideoGenerationSettingsUpdate(BaseModel):
    enabled: bool = True
    default_model_alias: str = Field(
        default="bailian_wan_2_7_r2v",
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    default_resolution: str = Field(default="720P", pattern=r"^(?:[0-9]{3,4}P|2K)$")
    poll_interval_seconds: float = Field(default=5, ge=0.2, le=60)
    task_timeout_seconds: int = Field(default=900, ge=30, le=7200)
    public_media_base_url: str | None = Field(default=None, max_length=1000)
    public_media_ttl_seconds: int = Field(default=3600, ge=900, le=604800)
    providers: list[VideoProviderCredentialUpdate] = Field(default_factory=list, max_length=3)

    @field_validator("providers")
    @classmethod
    def validate_unique_video_providers(
        cls,
        values: list[VideoProviderCredentialUpdate],
    ) -> list[VideoProviderCredentialUpdate]:
        providers = [item.provider for item in values]
        if len(providers) != len(set(providers)):
            raise ValueError("同一视频 Provider 不能重复配置")
        return values


class VideoProviderSettingsResponse(BaseModel):
    provider: Literal["bailian", "volc_ark", "minimax"]
    label: str
    api_key_configured: bool = False
    api_key_hint: str | None = None
    base_url: str
    last_validated_at: datetime | None = None
    validation_status: Literal["not_configured", "valid", "invalid", "unknown"] = "not_configured"
    validation_message: str | None = None
    balance_known: bool = False
    balance_micros: int | None = Field(default=None, ge=0)
    currency: str = "CNY"
    managed_asset_catalog_supported: bool = False
    managed_asset_credentials_configured: bool = False
    managed_asset_access_key_hint: str | None = None
    managed_asset_region: Literal["cn-beijing", "cn-shanghai"] | None = None
    managed_asset_project_name: str | None = None
    managed_asset_validation_status: Literal[
        "not_supported",
        "not_configured",
        "valid",
        "invalid",
        "unknown",
    ] = "not_supported"
    managed_asset_validation_message: str | None = None


class VideoGenerationSettingsResponse(BaseModel):
    enabled: bool = True
    default_model_alias: str
    default_resolution: str = "720P"
    poll_interval_seconds: float = 5
    task_timeout_seconds: int = 900
    public_media_base_url: str | None = None
    public_media_ttl_seconds: int = 3600
    public_media_transport_ready: bool = False
    public_media_validation_message: str | None = None
    catalog_version: str
    pricing_version: str
    providers: list[VideoProviderSettingsResponse] = Field(default_factory=list)
    models: list[VideoGenerationModelOption] = Field(default_factory=list)


class VideoProviderValidationRequest(BaseModel):
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    base_url: str | None = Field(default=None, max_length=500)


class VideoProviderValidationResponse(BaseModel):
    provider: Literal["bailian", "volc_ark", "minimax"]
    valid: bool
    message: str
    latency_ms: int | None = Field(default=None, ge=0)
    balance_known: bool = False
    balance_micros: int | None = Field(default=None, ge=0)
    currency: str = "CNY"
    error_code: str | None = Field(default=None, max_length=120)
    retryable: bool = False


class VideoCostEstimateRequest(BaseModel):
    model_alias: str = Field(min_length=1, max_length=80)
    duration_seconds: float = Field(gt=0, le=60)
    resolution: str = Field(default="720P", pattern=r"^(?:[0-9]{3,4}P|2K)$")
    candidate_count: int = Field(default=1, ge=1, le=4)


class VideoCostEstimateResponse(BaseModel):
    model_alias: str
    provider: str
    model: str | None = None
    duration_seconds: float
    resolution: str
    candidate_count: int
    estimate_known: bool
    estimated_cost_micros: int | None = Field(default=None, ge=0)
    currency: str = "CNY"
    pricing_version: str
    explanation: str


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
    local_model_policy: Literal["latest_flagship", "pinned", "balanced"] = "latest_flagship"
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
    model_policy: Literal["latest_flagship", "pinned", "balanced"] = "latest_flagship"
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


class ShotVisualBeatFact(BaseModel):
    """A time-bound visual fact that belongs only to the current shot content."""

    index: int = Field(ge=1, le=20)
    title: str = Field(default="画面", min_length=1, max_length=120)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    source_timestamp_seconds: float = Field(ge=0)
    image_prompt: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_time_range(self) -> ShotVisualBeatFact:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("画面结束时间必须晚于开始时间")
        if not self.start_seconds <= self.source_timestamp_seconds <= self.end_seconds:
            raise ValueError("画面来源时间必须位于画面时间范围内")
        return self


class ShotMotionPhaseFact(BaseModel):
    """Observable motion state for one time-bound phase inside a shot."""

    index: int = Field(ge=1, le=20)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    description: str = Field(min_length=1, max_length=1600)
    camera_motion: str = Field(default="无法确认", max_length=800)
    subject_motion: str = Field(default="无法确认", max_length=800)
    foreground_motion: str = Field(default="无明显前景运动", max_length=800)
    focus_change: str = Field(default="无法确认", max_length=800)
    foreground_occupancy_start_percent: int | None = Field(default=None, ge=0, le=100)
    foreground_occupancy_end_percent: int | None = Field(default=None, ge=0, le=100)
    occlusion_start_percent: int | None = Field(default=None, ge=0, le=100)
    occlusion_end_percent: int | None = Field(default=None, ge=0, le=100)
    observed: bool = True
    confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_time_range(self) -> ShotMotionPhaseFact:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("运镜阶段结束时间必须晚于开始时间")
        return self


class ShotTransitionFact(BaseModel):
    """Outgoing transition facts kept separate from the current shot content."""

    kind: Literal[
        "none",
        "hard_cut",
        "crossfade",
        "foreground_occlusion",
        "wipe",
        "whip_pan",
        "match_cut",
        "other",
        "uncertain",
    ] = "none"
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    description: str = Field(default="无出场转场", max_length=1600)
    mask_object: str | None = Field(default=None, max_length=300)
    direction: str | None = Field(default=None, max_length=300)
    terminal_frame: str = Field(default="", max_length=800)
    continuity_anchor: str | None = Field(default=None, max_length=800)
    generation_prompt: str = Field(default="", max_length=2000)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_time_range(self) -> ShotTransitionFact:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("出场转场结束时间不能早于开始时间")
        return self


class Shot(BaseModel):
    id: str
    index: int
    start_seconds: float
    end_seconds: float
    content_start_seconds: float | None = Field(default=None, ge=0)
    content_end_seconds: float | None = Field(default=None, gt=0)
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
    visual_beats: list[ShotVisualBeatFact] = Field(default_factory=list, max_length=20)
    motion_phases: list[ShotMotionPhaseFact] = Field(default_factory=list, max_length=20)
    continuous_take: bool | None = None
    motion_confidence: float = Field(default=0, ge=0, le=1)
    outgoing_transition: ShotTransitionFact = Field(default_factory=ShotTransitionFact)

    @model_validator(mode="after")
    def validate_content_range(self) -> Shot:
        content_start = (
            self.content_start_seconds
            if self.content_start_seconds is not None
            else self.start_seconds
        )
        content_end = (
            self.content_end_seconds if self.content_end_seconds is not None else self.end_seconds
        )
        if content_start < self.start_seconds or content_end > self.end_seconds:
            raise ValueError("分镜有效内容必须位于剪辑时间范围内")
        if content_end <= content_start:
            raise ValueError("分镜有效内容结束时间必须晚于开始时间")
        return self


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
    visual_beats: list[ShotVisualBeatFact] = Field(min_length=1, max_length=20)
    motion_phases: list[ShotMotionPhaseFact] = Field(default_factory=list, max_length=20)
    continuous_take: bool | None = None
    motion_confidence: float = Field(default=0, ge=0, le=1)
    outgoing_transition: ShotTransitionFact = Field(default_factory=ShotTransitionFact)


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
    transition_start_seconds: float | None = Field(default=None, ge=0)
    stable_new_scene_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_transition_window(self) -> ShotBoundaryDecision:
        if (
            self.transition_start_seconds is not None
            and self.stable_new_scene_seconds is not None
            and self.stable_new_scene_seconds < self.transition_start_seconds
        ):
            raise ValueError("新场景稳定时间不能早于转场开始时间")
        return self


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
    draft: PromptShotDraft | None = None
    source_draft: PromptShotDraft | None = None
    language_issues: list[str] = Field(default_factory=list, max_length=40)


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
    compiler_version: str = "prompt-ir-v2"
    revision_id: UUID | None = None
    revision_number: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
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
    content_start_seconds: float | None = Field(default=None, ge=0)
    content_end_seconds: float | None = Field(default=None, gt=0)
    incoming_transition_start_seconds: float | None = Field(default=None, ge=0)
    incoming_transition_end_seconds: float | None = Field(default=None, ge=0)
    outgoing_transition_start_seconds: float | None = Field(default=None, ge=0)
    outgoing_transition_end_seconds: float | None = Field(default=None, ge=0)
    analysis_clip_url: str | None = None
    analysis_clip_start_seconds: float | None = Field(default=None, ge=0)
    analysis_clip_end_seconds: float | None = Field(default=None, gt=0)
    representative_timestamp: float = Field(ge=0)
    keyframe_url: str
    evidence_frame_urls: list[str] = Field(default_factory=list)
    evidence_timestamps: list[float] = Field(default_factory=list, max_length=20)
    motion_frame_urls: list[str] = Field(default_factory=list, max_length=20)
    motion_timestamps: list[float] = Field(default_factory=list, max_length=20)
    detection_method: str

    boundary_method: str | None = Field(default=None, max_length=80)
    boundary_confidence: float | None = Field(default=None, ge=0, le=1)
    source_candidate_ids: list[str] = Field(default_factory=list)
    semantic_group: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_content_range(self) -> ShotEvidence:
        content_start = (
            self.content_start_seconds
            if self.content_start_seconds is not None
            else self.start_seconds
        )
        content_end = (
            self.content_end_seconds if self.content_end_seconds is not None else self.end_seconds
        )
        if content_start < self.start_seconds or content_end > self.end_seconds:
            raise ValueError("镜头证据有效内容必须位于剪辑时间范围内")
        if content_end <= content_start:
            raise ValueError("镜头证据有效内容结束时间必须晚于开始时间")
        if self.evidence_timestamps and any(
            timestamp < content_start or timestamp > content_end
            for timestamp in self.evidence_timestamps
        ):
            raise ValueError("镜头证据帧必须位于有效内容范围内")
        if (
            self.analysis_clip_start_seconds is not None
            and self.analysis_clip_end_seconds is not None
            and self.analysis_clip_end_seconds <= self.analysis_clip_start_seconds
        ):
            raise ValueError("分析视频片段结束时间必须晚于开始时间")
        if self.motion_timestamps and self.analysis_clip_start_seconds is not None:
            analysis_end = (
                self.analysis_clip_end_seconds or self.content_end_seconds or self.end_seconds
            )
            if any(
                timestamp < self.analysis_clip_start_seconds or timestamp > analysis_end
                for timestamp in self.motion_timestamps
            ):
                raise ValueError("运动证据帧必须位于分析视频片段范围内")
        return self


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
    transition_start_seconds: float | None = Field(default=None, ge=0)
    stable_new_scene_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_transition_window(self) -> SceneBoundaryCandidate:
        if (
            self.transition_start_seconds is not None
            and self.stable_new_scene_seconds is not None
            and self.stable_new_scene_seconds < self.transition_start_seconds
        ):
            raise ValueError("候选新场景稳定时间不能早于转场开始时间")
        return self


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
    prompt_source_analysis_id: UUID | None = None
    source_prompt_package_id: UUID
    source_project_id: UUID | None = None
    source_revision_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    status: ProductionProjectStatus = ProductionProjectStatus.DRAFT
    active_step: ProductionStep = ProductionStep.SHOT_IMAGES
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
    folder_id: UUID | None = None
    folder_name: str | None = Field(default=None, min_length=1, max_length=120)
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
    label: str = Field(min_length=1, max_length=260)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lstrip("@").strip()
        if not normalized:
            raise ValueError("提示词资产名称不能为空")
        return normalized


class VideoPromptMention(VideoGenerationReference):
    """A human-readable prompt token bound to one concrete generation input."""

    reference_kind: VideoPromptReferenceKind
    reference_id: UUID
    label: str = Field(min_length=1, max_length=260)
    role: VideoPromptReferenceRole
    order: int = Field(default=1, ge=1, le=100)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().lstrip("@").strip()
        if not normalized:
            raise ValueError("视频提示词引用名称不能为空")
        return normalized


class ShotVisualBeat(BaseModel):
    """Ordered visual node inside one model-generated shot video."""

    id: UUID = Field(default_factory=uuid4)
    index: int = Field(ge=1, le=20)
    title: str = Field(default="画面", min_length=1, max_length=120)
    start_ratio: float = Field(default=0, ge=0, le=1)
    end_ratio: float = Field(default=1, ge=0, le=1)
    source_frame_url: str | None = Field(default=None, min_length=1, max_length=2048)
    source_frame_relative_path: str | None = Field(default=None, max_length=2048)
    source_timestamp_seconds: float | None = Field(default=None, ge=0)
    source_frame_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_frame_warning: (
        Literal[
            "duplicate_frame",
            "frame_extract_failed",
            "timestamp_mismatch",
        ]
        | None
    ) = None
    source_origin: Literal[
        "analysis",
        "auto_extract",
        "video_selection",
        "duplicate",
        "blank",
        "legacy",
    ] = "analysis"
    image_prompt: str = Field(default="", max_length=8000)
    image_prompt_mentions: list[PromptAssetMention] = Field(
        default_factory=list,
        max_length=20,
    )
    image_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    required: bool = True
    image_status: WorkflowItemStatus = WorkflowItemStatus.DRAFT
    approved_image_candidate_id: UUID | None = None
    transition_to_next_type: Literal[
        "cut",
        "dissolve",
        "match_action",
        "model_generated",
    ] = "model_generated"
    transition_to_next_duration_seconds: float = Field(default=0.5, ge=0, le=5)
    transition_to_next_prompt: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("source_frame_relative_path")
    @classmethod
    def validate_source_frame_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None

    @field_validator("image_prompt_mentions")
    @classmethod
    def require_unique_mentions(
        cls,
        values: list[PromptAssetMention],
    ) -> list[PromptAssetMention]:
        ids = [item.reference_asset_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("同一参考资产不能在一个画面提示词中重复关联")
        return values

    @field_validator("image_negative_constraints")
    @classmethod
    def require_unique_constraints(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("画面负面约束不能重复")
        return values

    @model_validator(mode="after")
    def validate_ratio_range(self) -> ShotVisualBeat:
        if self.end_ratio <= self.start_ratio:
            raise ValueError("画面结束位置必须晚于开始位置")
        return self


class ProviderManagedAssetBinding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    asset_id: str = Field(min_length=1, max_length=256)
    group_id: str | None = Field(default=None, max_length=256)
    kind: ManagedAssetKind
    role: ManagedAssetRole = ManagedAssetRole.ACTOR_IDENTITY
    name: str = Field(min_length=1, max_length=120)
    group_name: str | None = Field(default=None, max_length=120)
    media_type: ManagedAssetMediaType
    project_name: str = Field(min_length=1, max_length=128)
    status: Literal["active"] = "active"
    preview_url: str | None = Field(default=None, max_length=8192)
    bound_at: datetime = Field(default_factory=utc_now)
    last_verified_at: datetime = Field(default_factory=utc_now)


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
        "auto_extract",
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
    video_prompt_mentions: list[VideoPromptMention] = Field(
        default_factory=list,
        max_length=40,
    )
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    managed_asset_bindings: list[ProviderManagedAssetBinding] = Field(
        default_factory=list,
        max_length=20,
    )
    video_reference_bindings: list[VideoReferenceBinding] = Field(
        default_factory=list,
        max_length=100,
    )
    depth_control_assets: list[DepthControlAsset] = Field(
        default_factory=list,
        max_length=20,
    )
    reference_policy_version: str = Field(
        default="video-reference-policy/v3-depth-only",
        min_length=1,
        max_length=80,
    )
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
    visual_beats: list[ShotVisualBeat] = Field(default_factory=list, max_length=20)
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

    @field_validator("managed_asset_bindings")
    @classmethod
    def require_unique_managed_asset_roles(
        cls,
        values: list[ProviderManagedAssetBinding],
    ) -> list[ProviderManagedAssetBinding]:
        keys = [(item.provider, item.role) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一 Provider 的托管资产角色不能重复绑定")
        return values

    @field_validator("video_prompt_mentions")
    @classmethod
    def require_unique_video_prompt_mentions(
        cls,
        values: list[VideoPromptMention],
    ) -> list[VideoPromptMention]:
        keys = [(item.reference_kind, item.reference_id) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一视频输入不能在提示词中重复关联")
        orders = [item.order for item in values]
        if len(orders) != len(set(orders)):
            raise ValueError("视频提示词引用顺序不能重复")
        return values

    @field_validator("video_reference_bindings")
    @classmethod
    def require_unique_video_reference_ids(
        cls,
        values: list[VideoReferenceBinding],
    ) -> list[VideoReferenceBinding]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("视频参考绑定 ID 不能重复")
        return values

    @field_validator("depth_control_assets")
    @classmethod
    def require_unique_depth_control_asset_ids(
        cls,
        values: list[DepthControlAsset],
    ) -> list[DepthControlAsset]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("深度控制资产 ID 不能重复")
        if sum(item.enabled for item in values) > 1:
            raise ValueError("一个分镜只能启用一个深度控制资产")
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
        if not self.visual_beats:
            self.visual_beats = [
                ShotVisualBeat(
                    id=uuid5(NAMESPACE_URL, f"viral-dna:shot:{self.id}:visual-beat:1"),
                    index=1,
                    title="画面 1",
                    start_ratio=0,
                    end_ratio=1,
                    source_frame_url=self.source_keyframe_url,
                    source_frame_relative_path=self.source_keyframe_relative_path,
                    source_timestamp_seconds=self.source_keyframe_timestamp_seconds,
                    source_origin=(
                        "legacy"
                        if self.source_keyframe_origin == "analysis"
                        else self.source_keyframe_origin
                    ),
                    image_prompt=self.image_prompt,
                    image_prompt_mentions=self.image_prompt_mentions,
                    image_negative_constraints=self.image_negative_constraints,
                    required=self.required,
                    image_status=self.image_status,
                    approved_image_candidate_id=self.approved_image_candidate_id,
                    created_at=self.created_at,
                    updated_at=self.updated_at,
                )
            ]
        ordered = sorted(self.visual_beats, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("分镜画面序号必须从 1 开始且连续")
        if len({item.id for item in ordered}) != len(ordered):
            raise ValueError("分镜画面不能包含重复 ID")
        previous_end = 0.0
        for beat in ordered:
            if beat.start_ratio + 0.0001 < previous_end:
                raise ValueError("分镜画面时间范围不能重叠")
            if (
                beat.source_timestamp_seconds is not None
                and not self.start_seconds <= beat.source_timestamp_seconds <= self.end_seconds
            ):
                raise ValueError("画面源帧时间必须位于当前分镜范围内")
            previous_end = beat.end_ratio
        return self


class GenerationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    shot_plan_id: UUID
    visual_beat_id: UUID | None = None
    revision_id: UUID
    kind: GenerationKind
    input_mode: ImageGenerationInputMode | VideoGenerationInputMode = (
        ImageGenerationInputMode.KEYFRAME_EDIT
    )
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    model_snapshot: str = Field(min_length=1, max_length=160)
    model_alias: str | None = Field(default=None, max_length=80)
    model_display_name: str | None = Field(default=None, max_length=160)
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
    actual_cost_known: bool = True
    cost_currency: str = Field(default="CNY", min_length=3, max_length=8)
    pricing_snapshot: dict[str, Any] = Field(default_factory=dict)
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
    provider_error_code: str | None = Field(default=None, max_length=120)
    error_category: str | None = Field(default=None, max_length=80)
    error_title: str | None = Field(default=None, max_length=160)
    error_technical_message: str | None = Field(default=None, max_length=4000)
    error_retryable: bool = False
    error_action: str | None = Field(default=None, max_length=80)
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


class VideoProviderTask(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    generation_run_id: UUID
    project_id: UUID
    shot_plan_id: UUID
    ordinal: int = Field(ge=1, le=20)
    provider: Literal["bailian", "volc_ark", "minimax"]
    model_alias: str = Field(min_length=1, max_length=80)
    provider_model: str = Field(min_length=1, max_length=160)
    provider_task_id: str | None = Field(default=None, max_length=500)
    status: VideoProviderTaskStatus = VideoProviderTaskStatus.PENDING_SUBMISSION
    submission_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    request_snapshot: dict[str, Any] = Field(default_factory=dict)
    response_snapshot: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    output_url: str | None = Field(default=None, max_length=4096)
    output_relative_path: str | None = Field(default=None, max_length=2048)
    estimated_cost_micros: int | None = Field(default=None, ge=0)
    actual_cost_micros: int | None = Field(default=None, ge=0)
    cost_known: bool = False
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=2000)
    retryable: bool = False
    provider_error_code: str | None = Field(default=None, max_length=120)
    error_category: str | None = Field(default=None, max_length=80)
    error_title: str | None = Field(default=None, max_length=160)
    error_technical_message: str | None = Field(default=None, max_length=4000)
    error_action: str | None = Field(default=None, max_length=80)
    submitted_at: datetime | None = None
    last_polled_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("output_relative_path")
    @classmethod
    def validate_provider_output_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None


class VideoProviderTaskResponse(BaseModel):
    id: UUID
    generation_run_id: UUID
    ordinal: int
    provider: str
    model_alias: str
    provider_model: str
    provider_task_id: str | None = None
    status: VideoProviderTaskStatus
    estimated_cost_micros: int | None = None
    actual_cost_micros: int | None = None
    cost_known: bool = False
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    provider_error_code: str | None = None
    error_category: str | None = None
    error_title: str | None = None
    error_technical_message: str | None = None
    error_action: str | None = None
    submitted_at: datetime | None = None
    last_polled_at: datetime | None = None
    completed_at: datetime | None = None


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
    archived_at: datetime | None = None
    archived_by_account_id: UUID | None = None
    archive_reason: GenerationCandidateArchiveReason | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "relative_path",
        "thumbnail_relative_path",
        "metadata_relative_path",
    )
    @classmethod
    def validate_candidate_paths(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None


class VideoMappedTextCue(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    kind: Literal["transcript", "subtitle"]
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    clip_start_seconds: float = Field(ge=0)
    clip_end_seconds: float = Field(gt=0)
    clipped: bool = False

    @model_validator(mode="after")
    def validate_ranges(self) -> VideoMappedTextCue:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("字幕或对白源时间范围无效")
        if self.clip_end_seconds <= self.clip_start_seconds:
            raise ValueError("字幕或对白片段时间范围无效")
        return self


class VideoClipPreparation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_id: UUID
    shot_plan_id: UUID
    candidate_id: UUID
    trim_in_seconds: float = Field(default=0, ge=0)
    trim_out_seconds: float = Field(gt=0)
    prepared_duration_seconds: float = Field(gt=0)
    timeline_duration_seconds: float = Field(gt=0)
    video_playback_rate: float = Field(gt=0, le=8)
    duration_alignment: Literal["exact", "retime", "outside_safe_range"]
    cover_timestamp_seconds: float = Field(ge=0)
    cover_relative_path: str = Field(min_length=1, max_length=2048)
    audio_mode: VideoClipAudioMode = VideoClipAudioMode.SOURCE
    audio_mapping_strategy: Literal[
        "preserve_source_timeline",
        "muted",
        "source_audio_unavailable",
    ]
    source_audio_url: str | None = Field(default=None, max_length=2048)
    source_audio_start_seconds: float = Field(ge=0)
    source_audio_end_seconds: float = Field(gt=0)
    transcript_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    subtitle_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    quality_status: VideoQualityStatus
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: VideoClipPreparationStatus
    blocker_messages: list[str] = Field(default_factory=list, max_length=20)
    warning_messages: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("cover_relative_path")
    @classmethod
    def validate_cover_path(cls, value: str) -> str:
        return _normalize_workspace_relative_path(value)

    @model_validator(mode="after")
    def validate_preparation_ranges(self) -> VideoClipPreparation:
        if self.trim_out_seconds <= self.trim_in_seconds:
            raise ValueError("视频出点必须晚于入点")
        if not self.trim_in_seconds <= self.cover_timestamp_seconds <= self.trim_out_seconds:
            raise ValueError("封面帧必须位于当前视频裁剪范围内")
        expected_duration = self.trim_out_seconds - self.trim_in_seconds
        if abs(expected_duration - self.prepared_duration_seconds) > 0.01:
            raise ValueError("视频裁剪时长与入点、出点不一致")
        if self.source_audio_end_seconds <= self.source_audio_start_seconds:
            raise ValueError("原音轨映射范围无效")
        return self


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
    folder_id: UUID | None = None
    folder_name: str | None = None
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


class ShotVisualBeatCreate(BaseModel):
    expected_revision_id: UUID
    insert_after_visual_beat_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    start_ratio: float | None = Field(default=None, ge=0, le=1)
    end_ratio: float | None = Field(default=None, ge=0, le=1)
    source_timestamp_seconds: float | None = Field(default=None, ge=0)
    image_prompt: str = Field(default="", max_length=8000)
    required: bool = True

    @model_validator(mode="after")
    def validate_optional_ratio_range(self) -> ShotVisualBeatCreate:
        if (
            self.start_ratio is not None
            and self.end_ratio is not None
            and self.end_ratio <= self.start_ratio
        ):
            raise ValueError("画面结束位置必须晚于开始位置")
        return self


class ProductionPromptSyncChoice(StrEnum):
    USE_LATEST = "use_latest"
    KEEP_CURRENT = "keep_current"


class ProductionPromptFieldDiff(BaseModel):
    field_key: str = Field(min_length=1, max_length=120)
    field_kind: Literal["image_prompt", "video_prompt"]
    label: str = Field(min_length=1, max_length=120)
    visual_beat_index: int | None = Field(default=None, ge=1, le=20)
    base_value: str = Field(default="", max_length=8000)
    current_value: str = Field(default="", max_length=8000)
    latest_value: str = Field(default="", max_length=8000)
    manually_edited: bool = False
    suggested_choice: ProductionPromptSyncChoice


class ProductionShotPromptDiff(BaseModel):
    shot_plan_id: UUID
    source_shot_id: str = Field(min_length=1, max_length=120)
    index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    fields: list[ProductionPromptFieldDiff] = Field(default_factory=list)


class ProductionAnalysisUpdatePreview(BaseModel):
    project_id: UUID
    current_revision_id: UUID
    base_analysis_id: UUID
    prompt_source_analysis_id: UUID
    target_analysis_id: UUID
    target_prompt_package_id: UUID
    target_generated_at: datetime
    update_available: bool = False
    compatible: bool = True
    structural_change_detected: bool = False
    structural_change_messages: list[str] = Field(default_factory=list, max_length=100)
    changed_field_count: int = Field(default=0, ge=0)
    automatic_field_count: int = Field(default=0, ge=0)
    conflict_field_count: int = Field(default=0, ge=0)
    shots: list[ProductionShotPromptDiff] = Field(default_factory=list)


class ProductionPromptSyncDecision(BaseModel):
    shot_plan_id: UUID
    field_key: str = Field(min_length=1, max_length=120)
    choice: ProductionPromptSyncChoice


class ProductionPromptSyncRequest(BaseModel):
    expected_revision_id: UUID
    target_analysis_id: UUID
    decisions: list[ProductionPromptSyncDecision] = Field(default_factory=list)

    @field_validator("decisions")
    @classmethod
    def require_unique_prompt_decisions(
        cls,
        values: list[ProductionPromptSyncDecision],
    ) -> list[ProductionPromptSyncDecision]:
        keys = [(item.shot_plan_id, item.field_key) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一个提示词字段不能重复选择同步策略")
        return values


class ShotVisualBeatUpdate(BaseModel):
    expected_revision_id: UUID
    confirm_stale: bool = False
    title: str | None = Field(default=None, min_length=1, max_length=120)
    start_ratio: float | None = Field(default=None, ge=0, le=1)
    end_ratio: float | None = Field(default=None, ge=0, le=1)
    image_prompt: str | None = Field(default=None, max_length=8000)
    image_prompt_mentions: list[PromptAssetMention] | None = Field(
        default=None,
        max_length=20,
    )
    image_negative_constraints: list[str] | None = Field(default=None, max_length=40)
    required: bool | None = None
    transition_to_next_type: (
        Literal[
            "cut",
            "dissolve",
            "match_action",
            "model_generated",
        ]
        | None
    ) = None
    transition_to_next_duration_seconds: float | None = Field(default=None, ge=0, le=5)
    transition_to_next_prompt: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_visual_beat_change(self) -> ShotVisualBeatUpdate:
        changed = self.model_fields_set - {"expected_revision_id", "confirm_stale"}
        if not changed:
            raise ValueError("至少需要提供一个要修改的画面字段")
        if (
            self.start_ratio is not None
            and self.end_ratio is not None
            and self.end_ratio <= self.start_ratio
        ):
            raise ValueError("画面结束位置必须晚于开始位置")
        return self


class ShotVisualBeatReorder(BaseModel):
    expected_revision_id: UUID
    ordered_visual_beat_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("ordered_visual_beat_ids")
    @classmethod
    def require_unique_visual_beats(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("画面排序不能包含重复项")
        return values


class ShotVisualBeatDelete(BaseModel):
    expected_revision_id: UUID
    confirm_stale: bool = False


class ShotPlanFieldsUpdate(BaseModel):
    image_prompt: str | None = Field(default=None, max_length=8000)
    image_prompt_mentions: list[PromptAssetMention] | None = Field(
        default=None,
        max_length=20,
    )
    image_negative_constraints: list[str] | None = Field(default=None, max_length=40)
    video_prompt: str | None = Field(default=None, max_length=8000)
    video_prompt_mentions: list[VideoPromptMention] | None = Field(
        default=None,
        max_length=40,
    )
    video_negative_constraints: list[str] | None = Field(default=None, max_length=40)
    managed_asset_bindings: list[ProviderManagedAssetBinding] | None = Field(
        default=None,
        max_length=20,
    )
    video_reference_bindings: list[VideoReferenceBinding] | None = Field(
        default=None,
        max_length=100,
    )
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

    @field_validator("managed_asset_bindings")
    @classmethod
    def require_unique_managed_binding_roles(
        cls,
        values: list[ProviderManagedAssetBinding] | None,
    ) -> list[ProviderManagedAssetBinding] | None:
        if values is None:
            return values
        keys = [(item.provider, item.role) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一 Provider 的托管资产角色不能重复绑定")
        return values

    @field_validator("video_prompt_mentions")
    @classmethod
    def require_unique_video_mentions(
        cls,
        values: list[VideoPromptMention] | None,
    ) -> list[VideoPromptMention] | None:
        if values is None:
            return values
        keys = [(item.reference_kind, item.reference_id) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("同一视频输入不能在提示词中重复关联")
        orders = [item.order for item in values]
        if len(orders) != len(set(orders)):
            raise ValueError("视频提示词引用顺序不能重复")
        return values

    @field_validator("video_reference_bindings")
    @classmethod
    def require_unique_video_reference_binding_ids(
        cls,
        values: list[VideoReferenceBinding] | None,
    ) -> list[VideoReferenceBinding] | None:
        if values is None:
            return values
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("视频参考绑定 ID 不能重复")
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


class ShotMediaPreview(BaseModel):
    thumbnail_url: str = Field(min_length=1, max_length=2048)
    kind: Literal[
        "candidate_image",
        "selected_image",
        "approved_image",
        "candidate_video",
        "selected_video",
        "approved_video",
    ]
    candidate_id: UUID
    updated_at: datetime


class ShotPlanResponse(BaseModel):
    plan: ShotPlan
    reference_bindings: list[ReferenceBinding] = Field(default_factory=list)
    current_revision_id: UUID
    image_preview: ShotMediaPreview | None = None
    video_preview: ShotMediaPreview | None = None


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
    visual_beat_id: UUID | None = None
    candidate_count: int = Field(default=1, ge=1, le=4)
    input_mode: ImageGenerationInputMode = ImageGenerationInputMode.KEYFRAME_EDIT
    execution_mode: Literal["remote_api", "local_tool"] | None = None
    model_alias: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    allow_unknown_cost: bool = False
    generation_intent: Literal["standard", "new_variation"] = "standard"
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)


class VideoGenerationCreate(BaseModel):
    expected_revision_id: UUID
    candidate_count: int = Field(default=1, ge=1, le=4)
    input_mode: VideoGenerationInputMode = VideoGenerationInputMode.MULTI_IMAGE_TO_VIDEO
    input_plan: VideoGenerationInputPlan = Field(
        default_factory=lambda: VideoGenerationInputPlan(
            sources=[VideoGenerationInputSource.APPROVED_IMAGES]
        )
    )
    execution_mode: Literal["simulated", "remote_api"] = "simulated"
    model_alias: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    resolution: str | None = Field(default=None, pattern=r"^(?:[0-9]{3,4}P|2K)$")
    duration_seconds: float | None = Field(default=None, ge=0.1, le=60)
    allow_unknown_cost: bool = False
    generation_intent: Literal["standard", "new_variation"] = "standard"
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)


class ShotVideoGenerationDraft(BaseModel):
    schema_version: Literal["viral-dna-shot-video-draft/v1"] = (
        "viral-dna-shot-video-draft/v1"
    )
    project_id: UUID
    shot_plan_id: UUID
    model_alias: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    resolution: str = Field(pattern=r"^(?:[0-9]{3,4}P|2K)$")
    duration_seconds: float = Field(ge=0.1, le=60)
    candidate_count: int = Field(default=1, ge=1, le=4)
    input_plan: VideoGenerationInputPlan = Field(default_factory=VideoGenerationInputPlan)
    draft_version: int = Field(default=1, ge=1)
    origin: Literal["global_default", "latest_run", "user"] = "global_default"
    updated_by_account_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ShotVideoGenerationDraftUpdate(BaseModel):
    expected_draft_version: int = Field(ge=1)
    model_alias: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    resolution: str = Field(pattern=r"^(?:[0-9]{3,4}P|2K)$")
    duration_seconds: float = Field(ge=0.1, le=60)
    candidate_count: int = Field(default=1, ge=1, le=4)
    input_plan: VideoGenerationInputPlan = Field(default_factory=VideoGenerationInputPlan)


class ShotKeyframeSelectRequest(BaseModel):
    expected_revision_id: UUID
    visual_beat_id: UUID | None = None
    timestamp_seconds: float = Field(ge=0)
    confirm_stale: bool = False


class ShotSourceFrameApprovalRequest(BaseModel):
    expected_revision_id: UUID
    visual_beat_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)
    confirm_downstream_stale: bool = False


class ShotImageApprovalRevokeRequest(BaseModel):
    expected_revision_id: UUID
    visual_beat_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)
    confirm_downstream_stale: bool = False


class ShotVideoApprovalRevokeRequest(BaseModel):
    expected_revision_id: UUID
    reason: str | None = Field(default=None, max_length=1000)
    confirm_downstream_stale: bool = False


class VideoClipPreparationUpdate(BaseModel):
    expected_revision_id: UUID
    trim_in_seconds: float | None = Field(default=None, ge=0, le=3600)
    trim_out_seconds: float | None = Field(default=None, gt=0, le=3600)
    cover_timestamp_seconds: float | None = Field(default=None, ge=0, le=3600)
    audio_mode: VideoClipAudioMode | None = None


class VideoClipPreparationResponse(BaseModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    shot_plan_id: UUID
    candidate_id: UUID
    trim_in_seconds: float
    trim_out_seconds: float
    prepared_duration_seconds: float
    timeline_duration_seconds: float
    video_playback_rate: float
    duration_alignment: Literal["exact", "retime", "outside_safe_range"]
    cover_timestamp_seconds: float
    cover_url: str
    audio_mode: VideoClipAudioMode
    audio_mapping_strategy: str
    source_audio_available: bool
    source_audio_start_seconds: float
    source_audio_end_seconds: float
    transcript_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    subtitle_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    quality_status: VideoQualityStatus
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: VideoClipPreparationStatus
    blocker_messages: list[str] = Field(default_factory=list)
    warning_messages: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


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
    archived_at: datetime | None = None
    archived_by_account_id: UUID | None = None
    archive_reason: GenerationCandidateArchiveReason | None = None
    content_url: str
    thumbnail_url: str
    created_at: datetime


class GenerationRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    shot_plan_id: UUID
    visual_beat_id: UUID | None = None
    revision_id: UUID
    kind: GenerationKind
    input_mode: ImageGenerationInputMode | VideoGenerationInputMode
    provider: str
    model: str
    model_snapshot: str
    model_alias: str | None = None
    model_display_name: str | None = None
    execution_mode: ImageExecutionMode
    adapter_id: str
    adapter_version: str
    protocol_version: str | None = None
    provider_request_id: str | None = None
    capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
    cost_source: GenerationCostSource
    cost_estimate_known: bool
    actual_cost_known: bool = True
    cost_currency: str = "CNY"
    pricing_snapshot: dict[str, Any] = Field(default_factory=dict)
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
    provider_error_code: str | None = None
    error_category: str | None = None
    error_title: str | None = None
    error_technical_message: str | None = None
    error_retryable: bool = False
    error_action: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    last_heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    candidates: list[GenerationCandidateResponse] = Field(default_factory=list)
    provider_tasks: list[VideoProviderTaskResponse] = Field(default_factory=list)


class ShotPlanDetailResponse(ShotPlanResponse):
    generation_runs: list[GenerationRunResponse] = Field(default_factory=list)
    approval_events: list[ApprovalEvent] = Field(default_factory=list)
    video_preparation: VideoClipPreparationResponse | None = None


class CandidateSelectRequest(BaseModel):
    expected_revision_id: UUID


class CandidateApprovalRequest(BaseModel):
    expected_revision_id: UUID
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)
    confirm_downstream_stale: bool = False
    confirm_stale_input: bool = False

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
    prepared_shot_count: int = Field(default=0, ge=0)
    quality_warning_shot_count: int = Field(default=0, ge=0)
    stale_shot_count: int = Field(ge=0)
    continuity_status: Literal["not_run", "completed", "stale", "failed"] = "not_run"
    continuity_verification_state: Literal["rule_only", "partial", "verified"] | None = None
    continuity_blocker_count: int = Field(default=0, ge=0)
    continuity_warning_count: int = Field(default=0, ge=0)
    blocker_messages: list[str] = Field(default_factory=list)


class ProductionAdvanceRequest(BaseModel):
    expected_revision_id: UUID
    target_step: ProductionStep


class EditingHandoffClip(BaseModel):
    shot_plan_id: UUID
    shot_index: int = Field(ge=1)
    candidate_id: UUID
    candidate_content_url: str
    cover_url: str
    cover_timestamp_seconds: float | None = Field(default=None, ge=0)
    timeline_start_seconds: float = Field(ge=0)
    timeline_end_seconds: float = Field(gt=0)
    timeline_duration_seconds: float = Field(gt=0)
    trim_in_seconds: float = Field(ge=0)
    trim_out_seconds: float = Field(gt=0)
    video_playback_rate: float = Field(gt=0)
    audio_mode: VideoClipAudioMode
    source_audio_start_seconds: float = Field(ge=0)
    source_audio_end_seconds: float = Field(gt=0)
    transcript_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    subtitle_cues: list[VideoMappedTextCue] = Field(default_factory=list)
    quality_status: VideoQualityStatus
    quality_report: dict[str, Any] = Field(default_factory=dict)
    blocker_messages: list[str] = Field(default_factory=list, max_length=20)
    warning_messages: list[str] = Field(default_factory=list)


class EditingHandoffManifest(BaseModel):
    schema_version: Literal["viral-dna-editing-handoff/v1"] = "viral-dna-editing-handoff/v1"
    project_id: UUID
    revision_id: UUID
    source_analysis_id: UUID
    source_audio_url: str | None = None
    audio_strategy: Literal["continuous_source_track", "per_shot", "muted"]
    timeline_duration_seconds: float = Field(gt=0)
    clips: list[EditingHandoffClip] = Field(min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)


class TimelineTransition(BaseModel):
    kind: TimelineTransitionKind = TimelineTransitionKind.NONE
    duration_seconds: float = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_duration(self) -> TimelineTransition:
        if self.kind == TimelineTransitionKind.NONE and self.duration_seconds != 0:
            raise ValueError("无转场时转场时长必须为 0")
        if self.kind != TimelineTransitionKind.NONE and self.duration_seconds <= 0:
            raise ValueError("启用转场时必须设置大于 0 的转场时长")
        return self


class CandidateBatchLifecycleRequest(BaseModel):
    expected_revision_id: UUID
    candidate_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("candidate_ids")
    @classmethod
    def require_unique_candidate_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("候选 ID 不能重复")
        return value


class CandidateBatchLifecycleResponse(BaseModel):
    project_id: UUID
    shot_plan_id: UUID
    current_revision_id: UUID
    candidates: list[GenerationCandidateResponse]
    affected_count: int = Field(ge=1)


class TimelineClip(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    shot_plan_id: UUID
    shot_index: int = Field(ge=1)
    candidate_id: UUID
    candidate_content_url: str = Field(min_length=1, max_length=2048)
    cover_url: str = Field(min_length=1, max_length=2048)
    cover_relative_path: str | None = Field(default=None, max_length=2048)
    cover_timestamp_seconds: float | None = Field(default=None, ge=0)
    order: int = Field(ge=1)
    enabled: bool = True
    candidate_duration_seconds: float = Field(gt=0)
    trim_in_seconds: float = Field(ge=0)
    trim_out_seconds: float = Field(gt=0)
    playback_rate: float = Field(gt=0, le=8)
    timeline_start_seconds: float = Field(ge=0)
    timeline_end_seconds: float = Field(gt=0)
    timeline_duration_seconds: float = Field(gt=0)
    audio_mode: VideoClipAudioMode = VideoClipAudioMode.SOURCE
    audio_volume: float = Field(default=1, ge=0, le=2)
    source_audio_start_seconds: float = Field(ge=0)
    source_audio_end_seconds: float = Field(gt=0)
    transition_after: TimelineTransition = Field(default_factory=TimelineTransition)
    quality_status: VideoQualityStatus = VideoQualityStatus.WARNING
    quality_report: dict[str, Any] = Field(default_factory=dict)
    blocker_messages: list[str] = Field(default_factory=list, max_length=20)
    warning_messages: list[str] = Field(default_factory=list)

    @field_validator("cover_relative_path")
    @classmethod
    def validate_cover_relative_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_clip_ranges(self) -> TimelineClip:
        if self.trim_out_seconds <= self.trim_in_seconds:
            raise ValueError("片段出点必须晚于入点")
        if self.trim_out_seconds > self.candidate_duration_seconds + 0.05:
            raise ValueError("片段出点不能超过候选视频时长")
        if (
            self.cover_timestamp_seconds is not None
            and not self.trim_in_seconds <= self.cover_timestamp_seconds <= self.trim_out_seconds
        ):
            raise ValueError("封面帧必须位于当前片段裁剪范围内")
        if self.timeline_end_seconds <= self.timeline_start_seconds:
            raise ValueError("时间线片段结束时间必须晚于开始时间")
        if self.source_audio_end_seconds <= self.source_audio_start_seconds:
            raise ValueError("原音轨结束时间必须晚于开始时间")
        return self


class TimelineSubtitleCue(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    source_cue_id: str | None = Field(default=None, max_length=120)
    clip_id: UUID | None = None
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    clip_start_seconds: float | None = Field(default=None, ge=0)
    clip_end_seconds: float | None = Field(default=None, gt=0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_cue_range(self) -> TimelineSubtitleCue:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("字幕结束时间必须晚于开始时间")
        if (self.clip_start_seconds is None) != (self.clip_end_seconds is None):
            raise ValueError("字幕片段相对时间必须同时设置")
        if (
            self.clip_start_seconds is not None
            and self.clip_end_seconds is not None
            and self.clip_end_seconds <= self.clip_start_seconds
        ):
            raise ValueError("字幕片段相对结束时间必须晚于开始时间")
        return self


class TimelineAudioTrack(BaseModel):
    strategy: Literal["continuous_source_track", "per_shot", "muted"]
    source_audio_url: str | None = Field(default=None, max_length=2048)
    enabled: bool = True
    volume: float = Field(default=1, ge=0, le=2)
    normalize_loudness: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> TimelineAudioTrack:
        if self.strategy != "muted" and not self.source_audio_url:
            raise ValueError("启用原音轨时必须存在音频来源")
        return self


class TimelineBackgroundAudioTrack(BaseModel):
    source_relative_path: str | None = Field(default=None, max_length=2048)
    source_url: str | None = Field(default=None, max_length=2048)
    name: str | None = Field(default=None, max_length=240)
    enabled: bool = False
    volume: float = Field(default=0.35, ge=0, le=2)
    loop: bool = True

    @field_validator("source_relative_path")
    @classmethod
    def validate_source_relative_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_source(self) -> TimelineBackgroundAudioTrack:
        if self.enabled and (not self.source_relative_path or not self.source_url):
            raise ValueError("启用附加音轨时必须先上传音频文件")
        return self


class ProductionTimeline(BaseModel):
    schema_version: Literal["viral-dna-timeline/v1"] = "viral-dna-timeline/v1"
    project_id: UUID
    source_handoff_revision_id: UUID
    revision_id: UUID
    revision_number: int = Field(ge=1)
    output_aspect_ratio: str = Field(min_length=3, max_length=20)
    output_width: int = Field(ge=256, le=8192)
    output_height: int = Field(ge=256, le=8192)
    fps: int = Field(default=30, ge=12, le=60)
    duration_seconds: float = Field(gt=0)
    clips: list[TimelineClip] = Field(min_length=1)
    audio_track: TimelineAudioTrack
    background_audio_track: TimelineBackgroundAudioTrack = Field(
        default_factory=TimelineBackgroundAudioTrack
    )
    subtitle_cues: list[TimelineSubtitleCue] = Field(default_factory=list)
    validation_messages: list[str] = Field(default_factory=list)
    warning_messages: list[str] = Field(default_factory=list)
    last_preview_job_id: UUID | None = None
    last_export_job_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TimelineClipUpdate(BaseModel):
    clip_id: UUID
    enabled: bool | None = None
    trim_in_seconds: float | None = Field(default=None, ge=0)
    trim_out_seconds: float | None = Field(default=None, gt=0)
    cover_timestamp_seconds: float | None = Field(default=None, ge=0)
    timeline_duration_seconds: float | None = Field(default=None, gt=0, le=300)
    audio_mode: VideoClipAudioMode | None = None
    audio_volume: float | None = Field(default=None, ge=0, le=2)
    transition_after: TimelineTransition | None = None


class TimelineUpdateRequest(BaseModel):
    expected_revision_id: UUID
    clip_order: list[UUID] | None = Field(default=None, min_length=1)
    clip_updates: list[TimelineClipUpdate] = Field(default_factory=list)
    audio_track: TimelineAudioTrack | None = None
    background_audio_track: TimelineBackgroundAudioTrack | None = None
    subtitle_cues: list[TimelineSubtitleCue] | None = None
    summary: str = Field(default="更新时间线", min_length=1, max_length=240)


class TimelineClipInspectionRequest(BaseModel):
    expected_revision_id: UUID


class TimelineValidationResponse(BaseModel):
    project_id: UUID
    revision_id: UUID
    valid: bool
    duration_seconds: float = Field(gt=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TimelineRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision_number: int = Field(ge=1)
    change_kind: TimelineChangeKind
    summary: str = Field(min_length=1, max_length=240)
    snapshot_relative_path: str = Field(min_length=1, max_length=2048)
    source_revision_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("snapshot_relative_path")
    @classmethod
    def validate_snapshot_path(cls, value: str) -> str:
        return _normalize_workspace_relative_path(value)


class TimelineRevisionList(BaseModel):
    items: list[TimelineRevision] = Field(default_factory=list)


class TimelineRestoreRequest(BaseModel):
    expected_revision_id: UUID


class TimelinePreviewCreate(BaseModel):
    expected_revision_id: UUID


class TimelineFinalRenderCreate(BaseModel):
    expected_revision_id: UUID
    resolution: TimelineExportResolution = TimelineExportResolution.P1080
    subtitle_mode: TimelineExportSubtitleMode = TimelineExportSubtitleMode.BURNED
    quality: TimelineExportQuality = TimelineExportQuality.HIGH


class TimelineExportValidationSummary(BaseModel):
    valid: bool
    expected_duration_seconds: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(ge=0)
    video_codec: str = Field(min_length=1, max_length=80)
    audio_codec: str | None = Field(default=None, max_length=80)
    has_audio: bool
    has_subtitles: bool
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TimelineRenderJob(BaseModel):
    schema_version: Literal["viral-dna-render-job/v1"] = "viral-dna-render-job/v1"
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    timeline_revision_id: UUID
    kind: TimelineRenderKind = TimelineRenderKind.PREVIEW
    status: TimelineRenderStatus = TimelineRenderStatus.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    preview_width: int = Field(ge=2, le=8192)
    preview_height: int = Field(ge=2, le=8192)
    resolution: TimelineExportResolution | None = None
    subtitle_mode: TimelineExportSubtitleMode | None = None
    quality: TimelineExportQuality | None = None
    request_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    output_filename: str | None = Field(default=None, max_length=240)
    output_relative_path: str | None = Field(default=None, max_length=2048)
    subtitle_relative_path: str | None = Field(default=None, max_length=2048)
    cover_relative_path: str | None = Field(default=None, max_length=2048)
    manifest_relative_path: str | None = Field(default=None, max_length=2048)
    output_url: str | None = Field(default=None, max_length=2048)
    subtitle_url: str | None = Field(default=None, max_length=2048)
    cover_url: str | None = Field(default=None, max_length=2048)
    manifest_url: str | None = Field(default=None, max_length=2048)
    file_size_bytes: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    validation_summary: TimelineExportValidationSummary | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1000)
    cancellation_requested: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator(
        "output_relative_path",
        "subtitle_relative_path",
        "cover_relative_path",
        "manifest_relative_path",
    )
    @classmethod
    def validate_optional_relative_path(cls, value: str | None) -> str | None:
        return _normalize_workspace_relative_path(value) if value is not None else None


class TimelineRenderJobList(BaseModel):
    items: list[TimelineRenderJob] = Field(default_factory=list)


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
    archived_at: datetime | None = None
    trashed_at: datetime | None = None
    purged_at: datetime | None = None


class AnalysisRecordUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    folder_id: UUID | None = None


class AnalysisRecordLifecycleUpdate(BaseModel):
    action: AnalysisRecordLifecycleAction


class AnalysisRecordBatchLifecycleUpdate(AnalysisRecordLifecycleUpdate):
    record_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("record_ids")
    @classmethod
    def unique_record_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("分析记录不能重复")
        return value


class AnalysisRecordBatchDelete(BaseModel):
    record_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("record_ids")
    @classmethod
    def unique_record_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("分析记录不能重复")
        return value


class AnalysisRecordMutationResult(BaseModel):
    affected_ids: list[UUID]
    affected_count: int = Field(ge=0)


class AnalysisRecordLifecycleCounts(BaseModel):
    active: int = Field(default=0, ge=0)
    archived: int = Field(default=0, ge=0)
    trashed: int = Field(default=0, ge=0)


class AnalysisRecordSummary(AnalysisRecord):
    thumbnail_url: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    production_project_count: int = Field(default=0, ge=0)


class AnalysisRecordList(BaseModel):
    items: list[AnalysisRecordSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int = Field(ge=0)
    lifecycle_counts: AnalysisRecordLifecycleCounts = Field(
        default_factory=AnalysisRecordLifecycleCounts
    )


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
    workspace_schema_version: int = WORKSPACE_SCHEMA_VERSION
    process_started_at: datetime
    analyzer_mode: str


class ApiMessage(BaseModel):
    message: str
    details: dict[str, Any] | None = None
