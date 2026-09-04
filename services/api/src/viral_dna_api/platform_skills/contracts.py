from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillLifecycle(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    BLOCKED = "blocked"


class SkillResource(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    type: Literal["image", "video", "font", "palette", "text", "example"]
    path: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(min_length=3, max_length=120)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: str = Field(min_length=1, max_length=80)
    fidelity: Literal[
        "exact",
        "identity_lock",
        "structural",
        "style_only",
        "loose_reference",
    ] = "style_only"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip("/")
        if not normalized.startswith("resources/") or ".." in normalized.split("/"):
            raise ValueError("Skill 资源必须位于 resources/ 内")
        return normalized


class SkillMetadata(StrictModel):
    id: str = Field(pattern=r"^platform\.[a-z0-9][a-z0-9.-]{2,99}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$")
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=60)
    tags: list[str] = Field(default_factory=list, max_length=20)
    locale: str = Field(default="zh-CN", min_length=2, max_length=20)
    cover_resource: str | None = Field(default=None, max_length=64)
    cover_url: str | None = Field(default=None, max_length=2048)


class SkillDurationRange(StrictModel):
    min: int = Field(ge=3, le=600)
    max: int = Field(ge=3, le=600)

    @model_validator(mode="after")
    def validate_range(self) -> SkillDurationRange:
        if self.max < self.min:
            raise ValueError("Skill 最大时长不能小于最小时长")
        return self


class SkillIntentSpec(StrictModel):
    supported_goals: list[str] = Field(min_length=1, max_length=30)
    supported_channels: list[str] = Field(min_length=1, max_length=30)
    duration_seconds: SkillDurationRange
    aspect_ratios: list[str] = Field(min_length=1, max_length=10)

    @field_validator("aspect_ratios")
    @classmethod
    def validate_ratios(cls, value: list[str]) -> list[str]:
        for ratio in value:
            parts = ratio.split(":")
            if len(parts) != 2 or not all(part.isdigit() and int(part) > 0 for part in parts):
                raise ValueError(f"无效画幅：{ratio}")
        return list(dict.fromkeys(value))


class SkillCreativeBasis(StrictModel):
    allowed: list[Literal["brand_led", "reference_led", "hybrid"]] = Field(
        min_length=1,
        max_length=3,
    )
    recommended: Literal["brand_led", "reference_led", "hybrid"]

    @model_validator(mode="after")
    def validate_recommended(self) -> SkillCreativeBasis:
        if self.recommended not in self.allowed:
            raise ValueError("推荐创作依据必须包含在 allowed 中")
        return self


class SkillAssetRole(StrictModel):
    role: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=80)
    media_types: list[Literal["image", "video", "audio", "document"]] = Field(
        min_length=1,
        max_length=4,
    )
    min_count: int = Field(default=0, ge=0, le=50)
    max_count: int = Field(default=10, ge=1, le=100)
    fidelity: Literal[
        "exact",
        "identity_lock",
        "structural",
        "style_only",
        "loose_reference",
    ] = "loose_reference"

    @model_validator(mode="after")
    def validate_counts(self) -> SkillAssetRole:
        if self.max_count < self.min_count:
            raise ValueError("素材角色 max_count 不能小于 min_count")
        return self


class SkillQuestion(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=160)
    type: Literal["short_text", "long_text", "single_select", "multi_select"]
    required: bool = False
    max_length: int | None = Field(default=None, ge=1, le=4000)
    options: list[str] = Field(default_factory=list, max_length=30)


class SkillIntakeSpec(StrictModel):
    required_fields: list[str] = Field(min_length=1, max_length=30)
    creative_basis: SkillCreativeBasis
    asset_roles: list[SkillAssetRole] = Field(default_factory=list, max_length=30)
    questions: list[SkillQuestion] = Field(default_factory=list, max_length=30)


class SkillOutlineBeat(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    target_duration_ratio: float = Field(gt=0, le=1)
    purpose: str = Field(min_length=1, max_length=500)


class SkillCountRange(StrictModel):
    min: int = Field(ge=1, le=100)
    max: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> SkillCountRange:
        if self.max < self.min:
            raise ValueError("最大数量不能小于最小数量")
        return self


class SkillNarrativeSpec(StrictModel):
    outline_pattern: list[SkillOutlineBeat] = Field(min_length=1, max_length=20)
    shot_count: SkillCountRange

    @model_validator(mode="after")
    def validate_ratios(self) -> SkillNarrativeSpec:
        total = sum(item.target_duration_ratio for item in self.outline_pattern)
        if abs(total - 1) > 0.02:
            raise ValueError("叙事段落时长比例之和必须约等于 1")
        return self


class SkillStyleSpec(StrictModel):
    visual_keywords: list[str] = Field(min_length=1, max_length=40)
    palette_policy: dict[str, Any] = Field(default_factory=dict)
    composition: dict[str, Any] = Field(default_factory=dict)
    lighting: dict[str, Any] = Field(default_factory=dict)
    camera: dict[str, Any] = Field(default_factory=dict)
    rhythm: dict[str, Any] = Field(default_factory=dict)
    typography: dict[str, Any] = Field(default_factory=dict)
    positive_lock: list[str] = Field(default_factory=list, max_length=50)
    negative_lock: list[str] = Field(default_factory=list, max_length=50)


class SkillPromptRules(StrictModel):
    template_language: Literal["viraldna-template/v1"] = "viraldna-template/v1"
    allowed_variables: list[str] = Field(default_factory=list, max_length=50)
    image_sections: list[str] = Field(min_length=1, max_length=20)
    video_sections: list[str] = Field(min_length=1, max_length=20)


class SkillLookTestSpec(StrictModel):
    required: bool = True
    representative_count: int = Field(default=2, ge=1, le=4)
    use_output_aspect_ratio: bool = True


class SkillWorkflowSpec(StrictModel):
    automation_default: Literal["guided", "full_auto"] = "guided"
    automation_allowed: list[Literal["guided", "full_auto"]] = Field(
        default_factory=lambda: ["guided"],
        min_length=1,
        max_length=2,
    )
    look_test: SkillLookTestSpec = Field(default_factory=SkillLookTestSpec)
    gates: list[str] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def validate_workflow(self) -> SkillWorkflowSpec:
        required = [
            "brief_approved",
            "style_approved",
            "storyboard_approved",
            "images_approved",
            "videos_approved",
            "picture_locked",
            "audio_caption_approved",
            "delivery_approved",
        ]
        if self.gates != required:
            raise ValueError("Skill gates 必须使用平台支持的 G0-G7 固定顺序")
        if self.automation_default not in self.automation_allowed:
            raise ValueError("automation_default 必须包含在 automation_allowed 中")
        return self


class SkillGenerationPolicy(StrictModel):
    user_must_select: list[str] = Field(min_length=4, max_length=10)
    allow_silent_provider_fallback: Literal[False] = False
    image_capabilities: list[str] = Field(default_factory=list, max_length=30)
    video_capabilities: list[str] = Field(default_factory=list, max_length=30)
    recommended_candidate_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_user_choices(self) -> SkillGenerationPolicy:
        required = {
            "image_model",
            "image_resolution",
            "video_model",
            "video_resolution",
        }
        if not required.issubset(self.user_must_select):
            raise ValueError("Skill 必须要求用户选择图片／视频模型和分辨率")
        return self


class SkillSpec(StrictModel):
    intent: SkillIntentSpec
    intake: SkillIntakeSpec
    narrative: SkillNarrativeSpec
    style: SkillStyleSpec
    prompt_rules: SkillPromptRules
    continuity: dict[str, Any] = Field(default_factory=dict)
    workflow: SkillWorkflowSpec
    generation_policy: SkillGenerationPolicy
    audio: dict[str, Any] = Field(default_factory=dict)
    captions: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    delivery: dict[str, Any] = Field(default_factory=dict)


FORBIDDEN_MANIFEST_KEYS = frozenset(
    {
        "api_key",
        "base_url",
        "callback_url",
        "command",
        "environment",
        "executable",
        "script",
        "shell",
        "webhook",
    }
)


def _scan_forbidden(value: Any, path: str = "manifest") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            next_path = f"{path}.{key}"
            if normalized in FORBIDDEN_MANIFEST_KEYS:
                issues.append(f"{next_path} 不允许出现在 Skill 清单中")
            issues.extend(_scan_forbidden(item, next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(_scan_forbidden(item, f"{path}[{index}]"))
    return issues


class SkillManifest(StrictModel):
    api_version: Literal["viraldna.video-skill/v1"]
    kind: Literal["VideoSkill"]
    metadata: SkillMetadata
    resources: list[SkillResource] = Field(default_factory=list, max_length=100)
    spec: SkillSpec

    @model_validator(mode="after")
    def validate_manifest(self) -> SkillManifest:
        keys = [item.key for item in self.resources]
        if len(keys) != len(set(keys)):
            raise ValueError("Skill 资源 key 不能重复")
        if self.metadata.cover_resource and self.metadata.cover_resource not in keys:
            raise ValueError("cover_resource 必须引用已声明资源")
        issues = _scan_forbidden(self.model_dump(mode="python"))
        if issues:
            raise ValueError("；".join(issues))
        return self


class PlatformSkillVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    skill_id: str = Field(min_length=3, max_length=120)
    version: str = Field(min_length=5, max_length=40)
    revision_number: int = Field(ge=1)
    manifest: SkillManifest
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    changelog: str = Field(default="", max_length=1000)
    status: SkillLifecycle = SkillLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    published_by: UUID | None = None


class PlatformSkill(BaseModel):
    id: str = Field(min_length=3, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=60)
    tags: list[str] = Field(default_factory=list, max_length=20)
    cover_url: str | None = None
    lifecycle: SkillLifecycle = SkillLifecycle.DRAFT
    current_published_version_id: UUID | None = None
    usage_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillCatalogItem(PlatformSkill):
    current_version: PlatformSkillVersion
    favorited: bool = False
    supported_channels: list[str] = Field(default_factory=list)
    aspect_ratios: list[str] = Field(default_factory=list)
    duration_seconds: SkillDurationRange
    asset_roles: list[SkillAssetRole] = Field(default_factory=list)


class SkillCatalogListResponse(BaseModel):
    items: list[SkillCatalogItem]
    total: int = Field(ge=0)
    categories: list[str]


class SkillVersionSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    skill_id: str
    skill_version_id: UUID
    version: str
    manifest: SkillManifest
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    resource_digest_map: dict[str, str] = Field(default_factory=dict)
    copied_at: datetime = Field(default_factory=utc_now)


class AccountSkillFavorite(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    skill_id: str
    created_at: datetime = Field(default_factory=utc_now)


class SkillVersionCreate(BaseModel):
    manifest: SkillManifest
    changelog: str = Field(default="", max_length=1000)


class SkillValidationResult(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)
    content_digest: str | None = None
    resource_count: int = Field(default=0, ge=0)


class SkillCatalogState(BaseModel):
    schema_version: Literal["viral-dna-platform-skill-catalog/v1"] = (
        "viral-dna-platform-skill-catalog/v1"
    )
    skills: list[PlatformSkill] = Field(default_factory=list)
    versions: list[PlatformSkillVersion] = Field(default_factory=list)
