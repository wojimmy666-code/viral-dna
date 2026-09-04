from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import ValidationError

from .contracts import (
    PlatformSkill,
    PlatformSkillVersion,
    SkillCatalogItem,
    SkillCatalogListResponse,
    SkillCatalogState,
    SkillLifecycle,
    SkillManifest,
    SkillValidationResult,
    SkillVersionCreate,
    utc_now,
)

MAX_SKILL_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_SKILL_PACKAGE_ENTRIES = 100
MAX_SKILL_RESOURCE_BYTES = 25 * 1024 * 1024
BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
}


class PlatformSkillError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def manifest_digest(manifest: SkillManifest) -> str:
    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _default_manifest(
    *,
    skill_id: str,
    version: str,
    name: str,
    summary: str,
    category: str,
    cover_url: str,
    keywords: list[str],
    channels: list[str],
    goals: list[str],
    asset_role: str,
    asset_label: str,
    fidelity: str,
    camera_motion: list[str],
) -> SkillManifest:
    return SkillManifest.model_validate(
        {
            "api_version": "viraldna.video-skill/v1",
            "kind": "VideoSkill",
            "metadata": {
                "id": skill_id,
                "version": version,
                "name": name,
                "summary": summary,
                "category": category,
                "tags": keywords[:6],
                "locale": "zh-CN",
                "cover_url": cover_url,
            },
            "resources": [],
            "spec": {
                "intent": {
                    "supported_goals": goals,
                    "supported_channels": channels,
                    "duration_seconds": {"min": 10, "max": 60},
                    "aspect_ratios": ["9:16", "16:9", "1:1", "4:5"],
                },
                "intake": {
                    "required_fields": [
                        "brand",
                        "objective",
                        "audience",
                        "distribution_channel",
                        "target_duration",
                        "output_aspect_ratio",
                    ],
                    "creative_basis": {
                        "allowed": ["brand_led", "reference_led", "hybrid"],
                        "recommended": "hybrid",
                    },
                    "asset_roles": [
                        {
                            "role": asset_role,
                            "label": asset_label,
                            "media_types": ["image"],
                            "min_count": 1,
                            "max_count": 8,
                            "fidelity": fidelity,
                        },
                        {
                            "role": "logo",
                            "label": "品牌 Logo",
                            "media_types": ["image"],
                            "min_count": 0,
                            "max_count": 2,
                            "fidelity": "exact",
                        },
                        {
                            "role": "reference_video",
                            "label": "风格参考视频",
                            "media_types": ["video"],
                            "min_count": 0,
                            "max_count": 3,
                            "fidelity": "style_only",
                        },
                    ],
                    "questions": [
                        {
                            "key": "primary_message",
                            "label": "观众看完后最应记住什么？",
                            "type": "long_text",
                            "required": True,
                            "max_length": 500,
                        }
                    ],
                },
                "narrative": {
                    "outline_pattern": [
                        {
                            "key": "hook",
                            "target_duration_ratio": 0.15,
                            "purpose": "首屏建立清晰悬念或利益点",
                        },
                        {
                            "key": "reveal",
                            "target_duration_ratio": 0.25,
                            "purpose": "揭示主体和真实使用情境",
                        },
                        {
                            "key": "proof",
                            "target_duration_ratio": 0.40,
                            "purpose": "用已批准事实解释核心价值",
                        },
                        {
                            "key": "resolution",
                            "target_duration_ratio": 0.20,
                            "purpose": "收束情绪并给出行动指引",
                        },
                    ],
                    "shot_count": {"min": 4, "max": 12},
                },
                "style": {
                    "visual_keywords": keywords,
                    "palette_policy": {"source": "brand_then_reference"},
                    "composition": {
                        "principles": [
                            "one dominant subject per shot",
                            "reserve safe area for deterministic typography",
                        ]
                    },
                    "lighting": {"principles": ["controlled motivated lighting"]},
                    "camera": {
                        "allowed_motion": camera_motion,
                        "avoid_motion": ["random_handheld", "unmotivated_whip_pan"],
                    },
                    "rhythm": {"cut_density": "medium"},
                    "typography": {
                        "render_mode": "deterministic_overlay",
                        "max_lines": 2,
                    },
                    "positive_lock": [
                        "preserve subject identity and material detail",
                        "keep one coherent visual language",
                    ],
                    "negative_lock": [
                        "no invented certifications or claims",
                        "no generated logo or unreadable packaging text",
                        "no unexplained identity changes",
                    ],
                },
                "prompt_rules": {
                    "template_language": "viraldna-template/v1",
                    "allowed_variables": [
                        "brand.name",
                        "brief.objective",
                        "brief.audience",
                        "shot.description",
                        "shot.narrative_role",
                    ],
                    "image_sections": [
                        "subject_and_action",
                        "environment",
                        "composition",
                        "lighting_and_color",
                        "asset_fidelity",
                        "negative_constraints",
                    ],
                    "video_sections": [
                        "accepted_frame_binding",
                        "action_progression",
                        "camera_motion",
                        "temporal_continuity",
                        "audio_intent",
                        "negative_constraints",
                    ],
                },
                "continuity": {
                    "default_locks": [
                        "subject_identity",
                        "screen_direction",
                        "palette",
                    ],
                    "allow_intentional_change_with_reason": True,
                },
                "workflow": {
                    "automation_default": "guided",
                    "automation_allowed": ["guided", "full_auto"],
                    "look_test": {
                        "required": True,
                        "representative_count": 2,
                        "use_output_aspect_ratio": True,
                    },
                    "gates": [
                        "brief_approved",
                        "style_approved",
                        "storyboard_approved",
                        "images_approved",
                        "videos_approved",
                        "picture_locked",
                        "audio_caption_approved",
                        "delivery_approved",
                    ],
                },
                "generation_policy": {
                    "user_must_select": [
                        "image_model",
                        "image_resolution",
                        "video_model",
                        "video_resolution",
                    ],
                    "allow_silent_provider_fallback": False,
                    "image_capabilities": [
                        "text_to_image",
                        "image_to_image",
                        "aspect_ratio_control",
                    ],
                    "video_capabilities": ["image_to_video", "duration_control"],
                    "recommended_candidate_counts": {
                        "look_test": 2,
                        "shot_image": 2,
                        "shot_video": 1,
                    },
                },
                "audio": {
                    "music": {
                        "timing": "after_picture_lock",
                        "strategy": "coherent_full_timeline_track",
                    },
                    "voiceover": {"enabled": "optional"},
                    "sound_effects": {"enabled": "optional"},
                },
                "captions": {
                    "source": "final_speech_track",
                    "deterministic_render": True,
                    "safe_area_required": True,
                },
                "quality": {
                    "hard_rules": [
                        "exact_assets_not_redrawn",
                        "no_unverified_claims",
                        "rights_confirmed_before_public_export",
                    ]
                },
                "delivery": {
                    "require_manifest": True,
                    "require_content_hashes": True,
                    "require_media_probe": True,
                },
            },
        }
    )


def _seed_state() -> SkillCatalogState:
    now = utc_now()
    definitions = [
        (
            "platform.cinematic-product-story",
            "cinematic-product-story",
            "电影感产品故事",
            "以克制电影摄影、材质细节和清晰叙事呈现产品价值。",
            "商业广告",
            "/skill-covers/cinematic-product.svg",
            ["产品", "电影感", "品牌", "材质细节"],
            ["douyin", "xiaohongshu", "wechat_channels"],
            ["product_launch", "product_education", "brand_story"],
            "product_hero",
            "产品主图",
            "identity_lock",
            ["locked", "slow_push", "slow_orbit", "macro_slide"],
        ),
        (
            "platform.creator-explainer",
            "creator-explainer",
            "自媒体分步讲解",
            "用真人讲解、步骤演示和证据画面完成清楚可信的短视频。",
            "自媒体创作",
            "/skill-covers/creator-explainer.svg",
            ["讲解", "真人", "步骤", "可信"],
            ["douyin", "xiaohongshu", "bilibili"],
            ["product_education", "tutorial", "creator_content"],
            "presenter",
            "出镜人物",
            "identity_lock",
            ["locked", "gentle_follow", "detail_insert"],
        ),
        (
            "platform.rhythmic-sports-short",
            "rhythmic-sports-short",
            "节奏运动短片",
            "以动作阶段、方向连续和音乐节拍组织有冲击力的运动短片。",
            "专业影视",
            "/skill-covers/rhythmic-sports.svg",
            ["运动", "节奏", "动作连续", "高能"],
            ["douyin", "bilibili", "wechat_channels"],
            ["event_recap", "sports_promo", "brand_story"],
            "athlete",
            "人物或队伍",
            "identity_lock",
            ["tracking", "low_angle_follow", "controlled_whip"],
        ),
    ]
    skills: list[PlatformSkill] = []
    versions: list[PlatformSkillVersion] = []
    for (
        skill_id,
        slug,
        name,
        summary,
        category,
        cover_url,
        keywords,
        channels,
        goals,
        role,
        role_label,
        fidelity,
        camera_motion,
    ) in definitions:
        manifest = _default_manifest(
            skill_id=skill_id,
            version="1.0.0",
            name=name,
            summary=summary,
            category=category,
            cover_url=cover_url,
            keywords=keywords,
            channels=channels,
            goals=goals,
            asset_role=role,
            asset_label=role_label,
            fidelity=fidelity,
            camera_motion=camera_motion,
        )
        version_id = uuid5(NAMESPACE_URL, f"viraldna:{skill_id}:1.0.0")
        version = PlatformSkillVersion(
            id=version_id,
            skill_id=skill_id,
            version="1.0.0",
            revision_number=1,
            manifest=manifest,
            content_digest=manifest_digest(manifest),
            changelog="平台首发版本",
            status=SkillLifecycle.PUBLISHED,
            created_at=now,
            published_at=now,
        )
        versions.append(version)
        skills.append(
            PlatformSkill(
                id=skill_id,
                slug=slug,
                name=name,
                summary=summary,
                category=category,
                tags=keywords,
                cover_url=cover_url,
                lifecycle=SkillLifecycle.PUBLISHED,
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
    return SkillCatalogState(skills=skills, versions=versions)


class PlatformSkillCatalogService:
    def __init__(self, state_path: Path | None = None, resource_root: Path | None = None) -> None:
        self.state_path = state_path.resolve() if state_path else None
        self.resource_root = (
            resource_root.resolve()
            if resource_root
            else (self.state_path.parent / "platform-skill-resources" if self.state_path else None)
        )
        self._lock = asyncio.Lock()
        self._memory_state: SkillCatalogState | None = None

    def _read_state(self) -> SkillCatalogState:
        if self.state_path is None:
            if self._memory_state is None:
                self._memory_state = _seed_state()
            return self._memory_state.model_copy(deep=True)
        if not self.state_path.is_file():
            state = _seed_state()
            self._write_state(state)
            return state
        try:
            return SkillCatalogState.model_validate_json(
                self.state_path.read_text("utf-8-sig")
            )
        except (OSError, ValidationError) as exc:
            raise PlatformSkillError(
                500,
                "skill_catalog_invalid",
                "平台 Skill 目录损坏，已停止读取",
            ) from exc

    def _write_state(self, state: SkillCatalogState) -> None:
        if self.state_path is None:
            self._memory_state = state.model_copy(deep=True)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json(indent=2)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            dir=self.state_path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    async def list_catalog(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        favorite_skill_ids: set[str] | None = None,
    ) -> SkillCatalogListResponse:
        state = await asyncio.to_thread(self._read_state)
        favorites = favorite_skill_ids or set()
        normalized_query = (query or "").strip().casefold()
        items: list[SkillCatalogItem] = []
        for skill in state.skills:
            if skill.lifecycle != SkillLifecycle.PUBLISHED:
                continue
            version = next(
                (
                    item
                    for item in state.versions
                    if item.id == skill.current_published_version_id
                    and item.status == SkillLifecycle.PUBLISHED
                ),
                None,
            )
            if version is None:
                continue
            searchable = " ".join(
                [skill.name, skill.summary, skill.category, *skill.tags]
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            if category and skill.category != category:
                continue
            spec = version.manifest.spec
            items.append(
                SkillCatalogItem(
                    **skill.model_dump(mode="python"),
                    current_version=version,
                    favorited=skill.id in favorites,
                    supported_channels=spec.intent.supported_channels,
                    aspect_ratios=spec.intent.aspect_ratios,
                    duration_seconds=spec.intent.duration_seconds,
                    asset_roles=spec.intake.asset_roles,
                )
            )
        items.sort(key=lambda item: (-item.usage_count, item.name.casefold()))
        categories = sorted(
            {
                skill.category
                for skill in state.skills
                if skill.lifecycle == SkillLifecycle.PUBLISHED
            }
        )
        return SkillCatalogListResponse(
            items=items,
            total=len(items),
            categories=categories,
        )

    async def get_catalog_item(
        self,
        slug: str,
        *,
        favorite_skill_ids: set[str] | None = None,
    ) -> SkillCatalogItem:
        state = await asyncio.to_thread(self._read_state)
        skill = next(
            (
                item
                for item in state.skills
                if item.slug == slug and item.lifecycle == SkillLifecycle.PUBLISHED
            ),
            None,
        )
        if skill is None or skill.current_published_version_id is None:
            raise PlatformSkillError(404, "skill_not_found", "Skill 不存在或尚未发布")
        version = next(
            (
                item
                for item in state.versions
                if item.id == skill.current_published_version_id
            ),
            None,
        )
        if version is None:
            raise PlatformSkillError(409, "skill_version_missing", "Skill 发布版本不存在")
        spec = version.manifest.spec
        return SkillCatalogItem(
            **skill.model_dump(mode="python"),
            current_version=version,
            favorited=skill.id in (favorite_skill_ids or set()),
            supported_channels=spec.intent.supported_channels,
            aspect_ratios=spec.intent.aspect_ratios,
            duration_seconds=spec.intent.duration_seconds,
            asset_roles=spec.intake.asset_roles,
        )

    async def get_version(self, version_id: UUID) -> PlatformSkillVersion:
        state = await asyncio.to_thread(self._read_state)
        version = next((item for item in state.versions if item.id == version_id), None)
        if version is None:
            raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
        return version

    async def require_usable_version(self, version_id: UUID) -> PlatformSkillVersion:
        version = await self.get_version(version_id)
        if version.status != SkillLifecycle.PUBLISHED:
            raise PlatformSkillError(
                409,
                "skill_version_not_available",
                "该 Skill 版本当前不能用于新建项目",
            )
        return version

    async def list_admin(self) -> SkillCatalogState:
        return await asyncio.to_thread(self._read_state)

    async def create_version(self, payload: SkillVersionCreate) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            skill = next(
                (item for item in state.skills if item.id == payload.manifest.metadata.id),
                None,
            )
            now = utc_now()
            if skill is None:
                slug = payload.manifest.metadata.id.removeprefix("platform.").replace(".", "-")
                skill = PlatformSkill(
                    id=payload.manifest.metadata.id,
                    slug=slug,
                    name=payload.manifest.metadata.name,
                    summary=payload.manifest.metadata.summary,
                    category=payload.manifest.metadata.category,
                    tags=payload.manifest.metadata.tags,
                    cover_url=payload.manifest.metadata.cover_url,
                    lifecycle=SkillLifecycle.DRAFT,
                    created_at=now,
                    updated_at=now,
                )
                state.skills.append(skill)
            if any(
                item.skill_id == skill.id and item.version == payload.manifest.metadata.version
                for item in state.versions
            ):
                raise PlatformSkillError(
                    409,
                    "skill_version_exists",
                    "该 Skill 版本号已经存在",
                )
            revision_number = max(
                (
                    item.revision_number
                    for item in state.versions
                    if item.skill_id == skill.id
                ),
                default=0,
            ) + 1
            version = PlatformSkillVersion(
                skill_id=skill.id,
                version=payload.manifest.metadata.version,
                revision_number=revision_number,
                manifest=payload.manifest,
                content_digest=manifest_digest(payload.manifest),
                changelog=payload.changelog,
            )
            state.versions.append(version)
            skill.name = payload.manifest.metadata.name
            skill.summary = payload.manifest.metadata.summary
            skill.category = payload.manifest.metadata.category
            skill.tags = payload.manifest.metadata.tags
            skill.cover_url = payload.manifest.metadata.cover_url
            skill.updated_at = now
            await asyncio.to_thread(self._write_state, state)
            return version

    async def update_draft(
        self,
        version_id: UUID,
        payload: SkillVersionCreate,
    ) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            current = state.versions[index]
            if current.status != SkillLifecycle.DRAFT:
                raise PlatformSkillError(
                    409,
                    "published_skill_immutable",
                    "已发布的 Skill 版本不可修改，请创建新版本",
                )
            if payload.manifest.metadata.id != current.skill_id:
                raise PlatformSkillError(422, "skill_id_immutable", "Skill ID 不可修改")
            updated = current.model_copy(
                update={
                    "version": payload.manifest.metadata.version,
                    "manifest": payload.manifest,
                    "content_digest": manifest_digest(payload.manifest),
                    "changelog": payload.changelog,
                }
            )
            state.versions[index] = updated
            await asyncio.to_thread(self._write_state, state)
            return updated

    async def validate_version(self, version_id: UUID) -> SkillValidationResult:
        version = await self.get_version(version_id)
        issues: list[str] = []
        resource_keys = {item.key for item in version.manifest.resources}
        if (
            version.manifest.metadata.cover_resource
            and version.manifest.metadata.cover_resource not in resource_keys
        ):
            issues.append("封面资源不存在")
        if version.content_digest != manifest_digest(version.manifest):
            issues.append("清单内容摘要不一致")
        return SkillValidationResult(
            valid=not issues,
            issues=issues,
            content_digest=manifest_digest(version.manifest),
            resource_count=len(version.manifest.resources),
        )

    async def publish(self, version_id: UUID, admin_id: UUID | None) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            version_index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if version_index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            current = state.versions[version_index]
            if current.status == SkillLifecycle.BLOCKED:
                raise PlatformSkillError(409, "skill_version_blocked", "已阻断版本不能发布")
            validation = await self.validate_version(version_id)
            if not validation.valid:
                raise PlatformSkillError(
                    422,
                    "skill_validation_failed",
                    "；".join(validation.issues),
                )
            now = utc_now()
            published = current.model_copy(
                update={
                    "status": SkillLifecycle.PUBLISHED,
                    "published_at": current.published_at or now,
                    "published_by": admin_id,
                }
            )
            state.versions[version_index] = published
            skill = next(item for item in state.skills if item.id == current.skill_id)
            skill.lifecycle = SkillLifecycle.PUBLISHED
            skill.current_published_version_id = published.id
            skill.updated_at = now
            await asyncio.to_thread(self._write_state, state)
            return published

    async def set_version_status(
        self,
        version_id: UUID,
        status: SkillLifecycle,
    ) -> PlatformSkillVersion:
        if status not in {SkillLifecycle.DEPRECATED, SkillLifecycle.BLOCKED}:
            raise PlatformSkillError(422, "skill_status_invalid", "只支持弃用或阻断版本")
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            updated = state.versions[index].model_copy(update={"status": status})
            state.versions[index] = updated
            skill = next(item for item in state.skills if item.id == updated.skill_id)
            if skill.current_published_version_id == updated.id:
                skill.lifecycle = status
                skill.updated_at = utc_now()
            await asyncio.to_thread(self._write_state, state)
            return updated

    async def import_package(
        self,
        payload: bytes,
        *,
        changelog: str = "",
    ) -> PlatformSkillVersion:
        if not payload:
            raise PlatformSkillError(422, "skill_package_empty", "Skill 包不能为空")
        if len(payload) > MAX_SKILL_PACKAGE_BYTES:
            raise PlatformSkillError(413, "skill_package_too_large", "Skill 包不能超过 50 MB")
        with tempfile.TemporaryDirectory(prefix="viraldna-skill-") as directory:
            archive_path = Path(directory) / "skill.zip"
            archive_path.write_bytes(payload)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    entries = archive.infolist()
                    if len(entries) > MAX_SKILL_PACKAGE_ENTRIES:
                        raise PlatformSkillError(
                            422,
                            "skill_package_too_many_entries",
                            "Skill 包文件数量超过限制",
                        )
                    by_name: dict[str, zipfile.ZipInfo] = {}
                    for entry in entries:
                        normalized = PurePosixPath(entry.filename.replace("\\", "/"))
                        if (
                            normalized.is_absolute()
                            or ".." in normalized.parts
                            or entry.is_dir()
                        ):
                            if entry.is_dir():
                                continue
                            raise PlatformSkillError(
                                422,
                                "skill_package_path_invalid",
                                "Skill 包包含不安全路径",
                            )
                        if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise PlatformSkillError(
                                422,
                                "skill_package_symlink_forbidden",
                                "Skill 包不能包含符号链接",
                            )
                        if normalized.suffix.casefold() in BLOCKED_EXTENSIONS:
                            raise PlatformSkillError(
                                422,
                                "skill_package_executable_forbidden",
                                "Skill 包不能包含可执行文件或脚本",
                            )
                        if entry.file_size > MAX_SKILL_RESOURCE_BYTES:
                            raise PlatformSkillError(
                                413,
                                "skill_resource_too_large",
                                "单个 Skill 资源不能超过 25 MB",
                            )
                        by_name[normalized.as_posix()] = entry
                    manifest_entry = by_name.get("skill.yaml")
                    if manifest_entry is None:
                        raise PlatformSkillError(
                            422,
                            "skill_manifest_missing",
                            "Skill 包根目录缺少 skill.yaml",
                        )
                    try:
                        manifest_payload = yaml.safe_load(
                            archive.read(manifest_entry).decode("utf-8-sig")
                        )
                        manifest = SkillManifest.model_validate(manifest_payload)
                    except (UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
                        raise PlatformSkillError(
                            422,
                            "skill_manifest_invalid",
                            f"Skill 清单无效：{exc}",
                        ) from exc
                    declared = {item.path: item for item in manifest.resources}
                    actual_resources = {
                        name for name in by_name if name.startswith("resources/")
                    }
                    if actual_resources != set(declared):
                        raise PlatformSkillError(
                            422,
                            "skill_resource_manifest_mismatch",
                            "Skill 包资源与清单声明不一致",
                        )
                    for path, resource in declared.items():
                        content = archive.read(by_name[path])
                        if hashlib.sha256(content).hexdigest() != resource.sha256:
                            raise PlatformSkillError(
                                422,
                                "skill_resource_hash_mismatch",
                                f"资源 {resource.key} 的 SHA-256 不一致",
                            )
                    version = await self.create_version(
                        SkillVersionCreate(manifest=manifest, changelog=changelog)
                    )
                    if self.resource_root is not None and manifest.resources:
                        version_root = self.resource_root / str(version.id)
                        version_root.mkdir(parents=True, exist_ok=False)
                        for path in declared:
                            destination = version_root / PurePosixPath(path)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(archive.read(by_name[path]))
                    return version
            except zipfile.BadZipFile as exc:
                raise PlatformSkillError(
                    422,
                    "skill_package_invalid",
                    "Skill 包不是有效 ZIP 文件",
                ) from exc
