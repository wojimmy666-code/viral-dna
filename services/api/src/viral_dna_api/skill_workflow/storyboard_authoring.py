from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from ..account_preferences import UserPreferencesService
from ..ai.billing import PriceCatalog, PriceCatalogError, calculate_cost_micros
from ..ai.catalog import default_analysis_profile, load_model_plan
from ..ai.contracts import ModelProviderError, ModelRequest
from ..ai.router import ModelRouter
from ..ai.text_model_routing import preferred_text_model_aliases
from ..models import ModelTask, ModelUsage
from ..platform_skills.contracts import SkillManifest, SkillShotArchetype
from .contracts import (
    BrandSnapshot,
    CreativeBriefRevision,
    PromptQualityReport,
    RunContractRevision,
    ShotActionPhase,
    ShotCameraPlan,
    ShotCreativeSpec,
    ShotSoundPlan,
    ShotTransitionPlan,
    StyleBibleRevision,
)
from .storyboard_prompts import chinese_term, style_text

SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "ai" / "prompts" / "skill_storyboard_v2.md"
)


class AuthoredBeat(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=1000)
    audience_takeaway: str = Field(min_length=1, max_length=2000)
    content_units: list[str] = Field(min_length=1, max_length=30)
    suggested_shot_count: int = Field(ge=1)
    rhythm: str = Field(min_length=1, max_length=1000)
    transition_strategy: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class AuthoredShot(BaseModel):
    beat_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    archetype_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    narrative_purpose: str = Field(min_length=1, max_length=1000)
    scene: str = Field(min_length=1, max_length=2000)
    subject: str = Field(min_length=1, max_length=2000)
    initial_state: str = Field(min_length=1, max_length=1600)
    action_phases: list[str] = Field(min_length=1, max_length=20)
    end_state: str = Field(min_length=1, max_length=1600)
    lens_mm: int = Field(ge=8, le=1200)
    framing: str = Field(min_length=1, max_length=300)
    camera_position: str = Field(min_length=1, max_length=500)
    camera_motion: str = Field(min_length=1, max_length=1000)
    motion_extent: str = Field(default="", max_length=500)
    focus: str = Field(min_length=1, max_length=800)
    lighting: str = Field(min_length=1, max_length=1600)
    color_and_texture: str = Field(min_length=1, max_length=1600)
    synchronous_foley: list[str] = Field(min_length=1, max_length=20)
    ambience: str = Field(min_length=1, max_length=1000)
    music_cue: str = Field(default="", max_length=1000)
    forbidden_sounds: list[str] = Field(default_factory=list, max_length=20)
    transition_kind: str = Field(default="hard_cut", min_length=1, max_length=80)
    cut_in: str = Field(default="", max_length=1000)
    cut_out: str = Field(min_length=1, max_length=1000)
    continuity_note: str = Field(default="", max_length=1000)
    continuity_locks: list[str] = Field(min_length=1, max_length=50)
    failure_constraints: list[str] = Field(min_length=1, max_length=50)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    generation_duration_seconds: int = Field(ge=1, le=30)


class AuthoredStoryboard(BaseModel):
    creative_approach: str = Field(default="", max_length=300)
    beats: list[AuthoredBeat] = Field(min_length=1, max_length=30)
    shots: list[AuthoredShot] = Field(min_length=1)
    continuity_bible: dict[str, Any] = Field(default_factory=dict)
    edit_plan: dict[str, Any] = Field(default_factory=dict)
    project_negative_constraints: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_beat_links(self) -> AuthoredStoryboard:
        keys = {item.key for item in self.beats}
        missing = {item.beat_key for item in self.shots} - keys
        if missing:
            raise ValueError(f"分镜引用了不存在的大纲段落：{sorted(missing)}")
        return self


@dataclass(frozen=True, slots=True)
class StoryboardAuthoringContext:
    manifest: SkillManifest
    brand: BrandSnapshot
    brief: CreativeBriefRevision
    style_bible: StyleBibleRevision
    run_contract: RunContractRevision
    asset_facts: list[dict[str, Any]]
    approved_claims: list[dict[str, Any]]
    on_model_started: Callable[[str, str], Awaitable[None]] | None = None


class StoryboardAuthoringResult(BaseModel):
    model_config = {"frozen": True}

    storyboard: AuthoredStoryboard
    provider: str
    model: str
    request_id: str | None = None
    provider_ms: int = 0
    usage: ModelUsage | None = None
    actual_cost_micros: int = 0
    raw_content: str = ""


class StoryboardAuthoringError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        provider_error: ModelProviderError | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider_error = provider_error


class StoryboardAuthor(Protocol):
    async def author(self, context: StoryboardAuthoringContext) -> StoryboardAuthoringResult: ...

    async def rewrite_shot(
        self,
        context: StoryboardAuthoringContext,
        shot: ShotCreativeSpec,
        *,
        instruction: str,
        locked_fields: list[str],
    ) -> StoryboardAuthoringResult: ...


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _measured_cost(provider: str, model: str, usage: ModelUsage) -> int:
    try:
        price = PriceCatalog().snapshot_for(provider, model, usage.input_tokens)
    except PriceCatalogError:
        return 0
    return calculate_cost_micros(usage, price)


def _shot_count(context: StoryboardAuthoringContext) -> int:
    narrative = context.manifest.spec.narrative
    standard = next(iter(context.manifest.spec.canonical_cases), None)
    if standard is not None:
        scaled = round(
            context.brief.target_duration_seconds
            * standard.shot_count
            / standard.target_duration_seconds
        )
    else:
        density = narrative.shot_density.average_edit_duration_seconds
        average = max(0.25, (density.min + density.max) / 2)
        scaled = round(context.brief.target_duration_seconds / average)
    # A pacing suggestion, never a constraint on returned or manually edited shots.
    return max(1, scaled)


def _fit_archetypes(
    archetypes: list[SkillShotArchetype],
    count: int,
) -> list[SkillShotArchetype]:
    if not archetypes:
        generic = SkillShotArchetype(
            key="product_hero",
            title="产品价值镜头",
            purpose="以清晰主体和真实情境传达产品价值",
            coverage="product",
            preferred_lenses_mm=[50],
            preferred_framing=["中近景"],
            preferred_motion=["固定机位"],
            action_pattern=["主体完成一次清晰、可信的动作", "动作结束后稳定停留"],
            sound_pattern=["与动作匹配的近场拟音", "低电平环境声"],
            failure_constraints=["主体身份、结构和材质不得漂移"],
        )
        return [generic for _ in range(count)]
    if count == len(archetypes):
        return list(archetypes)
    if count < len(archetypes):
        protected = {
            "material_macro",
            "environment_axis",
            "product_hero",
            "packaging_tableau",
            "brand_endcard",
        }
        result = list(archetypes)
        removable = [index for index, item in enumerate(result) if item.key not in protected]
        while len(result) > count and removable:
            target = removable.pop(len(removable) // 2)
            result.pop(target)
            removable = [index - 1 if index > target else index for index in removable]
        return result[:count]
    result = list(archetypes)
    insertable = [item for item in archetypes if item.coverage == "detail"] or archetypes
    cursor = 0
    while len(result) < count:
        result.insert(max(1, len(result) - 2), insertable[cursor % len(insertable)])
        cursor += 1
    return result


def _beat_for_index(keys: list[str], index: int, total: int) -> str:
    position = (index + 0.5) / max(1, total)
    if position <= 0.12:
        offset = 0
    elif position <= 0.30:
        offset = 1
    elif position <= 0.72:
        offset = 2
    elif position <= 0.86:
        offset = 3
    else:
        offset = 4
    return keys[min(offset, len(keys) - 1)]


class ReferenceStyleStoryboardAuthor:
    """Offline, deterministic author that keeps the Skill's style contract intact."""

    async def author(self, context: StoryboardAuthoringContext) -> StoryboardAuthoringResult:
        if context.on_model_started:
            await context.on_model_started("local_rule_compiler", "viraldna-skill-director-v2")
        spec = context.manifest.spec
        count = _shot_count(context)
        archetypes = _fit_archetypes(spec.narrative.shot_archetypes, count)
        category = _clean(context.brand.visual_identity.get("category_name")) or "实体产品"
        scenes = context.brand.visual_identity.get("scenes") or []
        scene_hint = "、".join(_clean(item) for item in scenes if _clean(item))
        environment = f"项目素材实际呈现的{category}相关场景" + (
            f"，优先采用{scene_hint}" if scene_hint else ""
        )
        product = f"{context.brand.name} 的{category}产品"
        evidence_refs = [item["id"] for item in context.asset_facts[:8] if item.get("id")]
        approved_messages = [
            _clean(item.get("claim_text"))
            for item in context.approved_claims
            if _clean(item.get("claim_text"))
        ]
        core_message = approved_messages[0] if approved_messages else context.brief.objective
        patterns = spec.narrative.outline_pattern
        beat_keys = [item.key for item in patterns]
        counts = {key: 0 for key in beat_keys}
        for index in range(count):
            counts[_beat_for_index(beat_keys, index, count)] += 1
        beats = [
            AuthoredBeat(
                key=item.key,
                title={
                    "material_hook": "材料钩子",
                    "process_reveal": "空间与工艺建立",
                    "craft_proof": "制造与装配证明",
                    "test_proof": "检测与品质证明",
                    "brand_resolution": "产品与品牌收束",
                }.get(item.key, chinese_term(item.key)),
                purpose=item.purpose,
                audience_takeaway=(
                    core_message
                    if item.key in {"craft_proof", "test_proof"}
                    else context.brief.objective
                ),
                content_units=[
                    archetype.title
                    for index, archetype in enumerate(archetypes)
                    if _beat_for_index(beat_keys, index, count) == item.key
                ]
                or [item.purpose],
                suggested_shot_count=max(1, counts[item.key]),
                rhythm={
                    "material_hook": "以短促微距和材料声快速入题",
                    "process_reveal": "放宽空间后稳定推进",
                    "craft_proof": "以单次工艺动作形成连续机械击点",
                    "test_proof": "检测触点清晰、节奏精确",
                    "brand_resolution": "适度放慢，在产品和品牌上停稳",
                }.get(item.key, "动作完成点硬切"),
                transition_strategy="以动作完成点或同步拟音落点硬切，环境底噪连续衔接",
                evidence_refs=evidence_refs,
            )
            for item in patterns
        ]
        lighting = style_text(spec.style.lighting) or "沿用项目素材中的合理光源与明暗关系"
        color_texture = "；".join(
            filter(
                None, [style_text(spec.style.palette_policy), "、".join(spec.style.visual_keywords)]
            )
        )
        common_locks = [
            f"{product}的外形、比例、材料和品牌识别与项目素材一致",
            "空间、人物、服装、设备年代与光线方向跨镜头稳定",
            style_text(spec.style.camera.get("camera_character")) or "摄影质感与项目风格一致",
        ]
        shots: list[AuthoredShot] = []
        for index, archetype in enumerate(archetypes):
            lens = archetype.preferred_lenses_mm[0] if archetype.preferred_lenses_mm else 50
            framing = archetype.preferred_framing[0] if archetype.preferred_framing else "中近景"
            motion = (
                archetype.preferred_motion[index % len(archetype.preferred_motion)]
                if archetype.preferred_motion
                else "固定机位"
            )
            exact_brand = archetype.coverage == "brand"
            subject = (
                f"项目提供的{product}与原始包装、Logo平面素材"
                if exact_brand
                else f"项目素材中可确认的{product}、材料、工具或设备"
            )
            actions = archetype.action_pattern or [
                "主体完成一次真实、克制的动作",
                "动作结束后稳定停留",
            ]
            shots.append(
                AuthoredShot(
                    beat_key=_beat_for_index(beat_keys, index, count),
                    archetype_key=archetype.key,
                    title=archetype.title,
                    narrative_purpose=archetype.purpose,
                    scene=environment,
                    subject=subject,
                    initial_state=f"{subject}处于动作开始前的稳定状态，位置、朝向和结构与参考素材一致",
                    action_phases=actions,
                    end_state=f"完成{actions[-1]}后保持稳定，构图留出明确硬切点",
                    lens_mm=lens,
                    framing=framing,
                    camera_position="相机位于主体工作面的侧前方并保持水平，空间关系真实可信",
                    camera_motion=motion,
                    motion_extent=(
                        "相机绝对静止"
                        if "固定" in motion or "静止" in motion
                        else "4秒内仅移动约5–35厘米或不超过8%画幅"
                    ),
                    focus="焦点锁定在主体动作接触点或关键材料纹理，背景自然虚化且不来回抽动",
                    lighting=lighting,
                    color_and_texture=color_texture,
                    synchronous_foley=archetype.sound_pattern or ["与主体动作匹配的近场拟音"],
                    ambience="统一的低电平真实工作环境底噪跨镜头连续，不抢主体动作",
                    music_cue=style_text(spec.audio.get("editing_music"))
                    or "配乐在剪辑阶段根据项目设置处理",
                    forbidden_sounds=[
                        label
                        for key, label in (
                            ("dialogue", "对白"),
                            ("narration", "旁白"),
                            ("shot_music", "镜头内配乐"),
                        )
                        if spec.audio.get(key) == "forbidden"
                    ],
                    transition_kind=(spec.editing.allowed_transitions or ["hard_cut"])[0],
                    cut_in="承接上一镜头的运动方向或环境声床",
                    cut_out="在主要动作完成并停稳、同步拟音落点出现时硬切",
                    continuity_note="保持与前后镜头相同的产品几何、空间、人物、色彩和摄影机质感",
                    continuity_locks=common_locks,
                    failure_constraints=[
                        *archetype.failure_constraints,
                        "不得新增项目资料未提供的产品结构、机器、认证、读数或宣传声明",
                    ],
                    evidence_refs=evidence_refs,
                    generation_duration_seconds=archetype.generation_duration_seconds,
                )
            )
        storyboard = AuthoredStoryboard(
            creative_approach=(
                "；".join(item.purpose.rstrip("。；") for item in patterns)[:149] + "。"
            ),
            beats=beats,
            shots=shots,
            continuity_bible={
                "world": environment,
                "product": f"{product}以项目素材为唯一身份、结构、材质和比例依据",
                "character": (
                    "只使用项目素材可确认的人物；同一人物的年龄、面孔、工装和手套跨镜头一致"
                ),
                "palette": style_text(spec.style.palette_policy),
                "lighting": lighting,
                "cinematography": style_text(spec.style.camera),
                "texture": color_texture,
                "sound": style_text(spec.audio),
                "typography": "画面生成阶段禁止新增文字；Logo、包装和字体在后期确定性叠加",
            },
            edit_plan={
                "target_duration_seconds": context.brief.target_duration_seconds,
                "shot_count": count,
                "transition": "hard_cut",
                "detail_ratio": spec.narrative.shot_density.detail_ratio,
                "environment_ratio": spec.narrative.shot_density.environment_ratio,
                "music_bpm": spec.audio.get("editing_music", {}).get("bpm"),
                "cut_rules": spec.editing.cut_rules,
            },
            project_negative_constraints=list(spec.style.negative_lock),
        )
        return StoryboardAuthoringResult(
            storyboard=storyboard,
            provider="local_rule_compiler",
            model="viraldna-skill-director-v2",
        )

    async def rewrite_shot(
        self,
        context: StoryboardAuthoringContext,
        shot: ShotCreativeSpec,
        *,
        instruction: str,
        locked_fields: list[str],
    ) -> StoryboardAuthoringResult:
        authored = await self.author(context)
        replacement = next(
            (
                item
                for item in authored.storyboard.shots
                if item.archetype_key == shot.archetype_key
            ),
            authored.storyboard.shots[0],
        )
        if instruction.strip():
            replacement = replacement.model_copy(
                update={
                    "narrative_purpose": (
                        f"{replacement.narrative_purpose}；人工调整要求：{instruction.strip()}"
                    ),
                }
            )
        return StoryboardAuthoringResult(
            storyboard=authored.storyboard.model_copy(update={"shots": [replacement]}),
            provider=authored.provider,
            model=authored.model,
        )


class ModelStoryboardAuthor:
    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        preferences: UserPreferencesService | None = None,
        offline_author: StoryboardAuthor | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.preferences = preferences
        self.offline_author = offline_author or ReferenceStyleStoryboardAuthor()
        self.system_prompt = SYSTEM_PROMPT_PATH.read_text("utf-8").strip()

    async def _target(self, context: StoryboardAuthoringContext):
        preferred = context.run_contract.text_model_selection.strip()
        fallback_enabled = False
        aliases: dict[ModelTask, str] = {}
        if self.preferences is not None:
            settings = (await self.preferences.get()).settings
            aliases = preferred_text_model_aliases(
                settings.text_model_alias,
                settings.text_model_task_overrides,
            )
            fallback_enabled = settings.text_model_fallback_enabled
        if preferred not in {"", "workspace_default", "auto"}:
            aliases[ModelTask.PROMPT_GENERATION] = preferred
            fallback_enabled = False
        plan = load_model_plan(
            default_analysis_profile(),
            preferred_aliases=aliases,
            fallback_enabled=fallback_enabled,
        )
        targets = plan.targets_for(ModelTask.PROMPT_GENERATION) if plan else []
        return targets

    async def author(self, context: StoryboardAuthoringContext) -> StoryboardAuthoringResult:
        targets = await self._target(context)
        if not targets:
            return await self.offline_author.author(context)
        payload = {
            "brand": context.brand.model_dump(mode="json"),
            "brief": context.brief.model_dump(mode="json"),
            "style_bible": context.style_bible.model_dump(mode="json"),
            "skill": context.manifest.spec.model_dump(mode="json"),
            "assets": context.asset_facts,
            "approved_claims": context.approved_claims,
            "suggested_shot_count": _shot_count(context),
            "shot_count_policy": (
                "镜头数量仅供节奏参考；按实际叙事自由增减，至少一个，不设数量上限。"
            ),
        }
        schema = json.dumps(AuthoredStoryboard.model_json_schema(), ensure_ascii=False)
        user_prompt = (
            "请为当前项目生成完整、结构化的大纲和逐镜头导演设计。\n"
            f"项目上下文：\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
            f"输出必须严格符合 JSON Schema：\n{schema}"
        )
        failures: list[str] = []
        last_error: ModelProviderError | None = None
        for target in targets:
            if context.on_model_started:
                await context.on_model_started(target.provider, target.model)
            try:
                result = await self.router.provider_for(target).generate(
                    ModelRequest(
                        task=ModelTask.PROMPT_GENERATION,
                        target=target,
                        system_prompt=self.system_prompt,
                        user_prompt=user_prompt,
                    ),
                    AuthoredStoryboard,
                )
            except ModelProviderError as exc:
                last_error = exc
                failures.append(f"{target.model}：{exc}")
                if not exc.retryable:
                    break
                continue
            if not result.data.shots:
                raise StoryboardAuthoringError(
                    "storyboard_empty", "模型未返回任何镜头，请重新生成", retryable=True
                )
            return StoryboardAuthoringResult(
                storyboard=result.data,
                provider=target.provider,
                model=result.resolved_model,
                request_id=result.provider_request_id,
                provider_ms=result.latency_ms,
                raw_content=result.raw_content,
                usage=result.usage,
                actual_cost_micros=_measured_cost(
                    target.provider,
                    result.resolved_model,
                    result.usage,
                ),
            )
        code = last_error.code if last_error else "storyboard_model_failed"
        explanation = {
            "model_timeout": "文案模型请求超时，未收到完整分镜结果",
            "model_network_error": "无法连接文案模型服务，请检查连接后重试",
            "model_schema_invalid": "模型返回的大纲或镜头格式不完整，请重新生成",
            "model_response_invalid": "模型服务返回了无法读取的响应，请重试",
        }.get(code, "文案模型生成失败")
        if last_error and last_error.raw_content:
            try:
                raw = json.loads(last_error.raw_content)
                if isinstance(raw, dict) and raw.get("shots") == []:
                    code, explanation = "storyboard_empty", "模型未返回任何镜头，请重新生成"
            except (ValueError, TypeError):
                pass
        raise StoryboardAuthoringError(
            code,
            f"{explanation}。{failures[-1]}"[:2000] if failures else explanation,
            retryable=last_error.retryable if last_error else True,
            provider_error=last_error,
        )

    async def rewrite_shot(
        self,
        context: StoryboardAuthoringContext,
        shot: ShotCreativeSpec,
        *,
        instruction: str,
        locked_fields: list[str],
    ) -> StoryboardAuthoringResult:
        targets = await self._target(context)
        if not targets:
            return await self.offline_author.rewrite_shot(
                context,
                shot,
                instruction=instruction,
                locked_fields=locked_fields,
            )
        schema = json.dumps(AuthoredShot.model_json_schema(), ensure_ascii=False)
        user_prompt = (
            "重写一个镜头的结构化导演设计。必须保留 locked_fields 指定的字段，不得改变事实依据。\n"
            f"当前镜头：{shot.model_dump_json()}\n"
            f"调整要求：{instruction or '提高具体性、可执行性和模型稳定性'}\n"
            f"锁定字段：{json.dumps(locked_fields, ensure_ascii=False)}\n"
            f"项目品牌：{context.brand.name}\n目标：{context.brief.objective}\n"
            f"JSON Schema：{schema}"
        )
        failures: list[str] = []
        for target in targets:
            try:
                result = await self.router.provider_for(target).generate(
                    ModelRequest(
                        task=ModelTask.PROMPT_GENERATION,
                        target=target,
                        system_prompt=self.system_prompt,
                        user_prompt=user_prompt,
                    ),
                    AuthoredShot,
                )
            except ModelProviderError as exc:
                failures.append(f"{target.model}：{exc}")
                continue
            return StoryboardAuthoringResult(
                storyboard=AuthoredStoryboard(
                    beats=[
                        AuthoredBeat(
                            key=result.data.beat_key,
                            title="镜头重写",
                            purpose=result.data.narrative_purpose,
                            audience_takeaway=context.brief.objective,
                            content_units=[result.data.title],
                            suggested_shot_count=1,
                            rhythm="动作完成点硬切",
                            transition_strategy="保持相邻镜头连续",
                        )
                    ],
                    shots=[result.data],
                    project_negative_constraints=list(context.manifest.spec.style.negative_lock),
                ),
                provider=target.provider,
                model=result.resolved_model,
                request_id=result.provider_request_id,
                provider_ms=result.latency_ms,
                usage=result.usage,
                actual_cost_micros=_measured_cost(
                    target.provider,
                    result.resolved_model,
                    result.usage,
                ),
            )
        raise StoryboardAuthoringError(
            "shot_rewrite_model_failed",
            failures[-1] if failures else "镜头重写模型没有返回有效结果",
            retryable=True,
        )


def creative_spec_from_authored(shot: AuthoredShot) -> ShotCreativeSpec:
    return ShotCreativeSpec(
        archetype_key=shot.archetype_key,
        title=shot.title,
        narrative_purpose=shot.narrative_purpose,
        scene=shot.scene,
        subject=shot.subject,
        initial_state=shot.initial_state,
        action_phases=[
            ShotActionPhase(order=index, label=f"阶段 {index}", description=value)
            for index, value in enumerate(shot.action_phases, start=1)
        ],
        end_state=shot.end_state,
        camera=ShotCameraPlan(
            lens_mm=shot.lens_mm,
            framing=shot.framing,
            position=shot.camera_position,
            motion=shot.camera_motion,
            motion_extent=shot.motion_extent,
            focus=shot.focus,
        ),
        lighting=shot.lighting,
        color_and_texture=shot.color_and_texture,
        sound=ShotSoundPlan(
            synchronous_foley=shot.synchronous_foley,
            ambience=shot.ambience,
            music_cue=shot.music_cue,
            forbidden=shot.forbidden_sounds,
        ),
        transition=ShotTransitionPlan(
            kind=shot.transition_kind,
            cut_in=shot.cut_in,
            cut_out=shot.cut_out,
            continuity_note=shot.continuity_note,
        ),
        continuity_locks=shot.continuity_locks,
        failure_constraints=shot.failure_constraints,
        evidence_refs=shot.evidence_refs,
    )


def compile_image_prompt(
    spec: ShotCreativeSpec,
    *,
    brand_name: str,
    exact_asset_reserved: bool,
) -> str:
    exact = (
        "Logo、包装文字、认证标识只预留安全区域，禁止生成、临摹或重绘，后期使用原始平面素材确定性叠加。"
        if exact_asset_reserved
        else "画面中不得新增Logo、包装文字、字幕、水印、二维码或未经提供的图形。"
    )
    constraints = "；".join(spec.failure_constraints)
    locks = "；".join(spec.continuity_locks)
    return (
        f"【参考约束】以当前镜头绑定的{brand_name}产品、材料和场景素材作为主体身份、结构、比例与表面细节依据，不重新设计产品。\n"
        f"【主体与场景】{spec.subject}。{spec.scene}。静态画面定格在：{spec.initial_state}。只呈现一个明确视觉重点。\n"
        f"【构图与镜头】{spec.camera.lens_mm}mm镜头，{chinese_term(spec.camera.framing)}；{spec.camera.position}。{spec.camera.focus}。空间尺度与前后层次符合项目风格。\n"
        f"【光线与色彩】{spec.lighting}。{spec.color_and_texture}。\n"
        f"【连续性锁定】{locks}。本提示词只描述动作开始前的一张静态分镜图，不包含运镜、时间过程或转场。\n"
        f"【确定性图形】{exact}\n"
        f"【严格约束】{constraints}；主体几何、材质、数量、朝向和构图关系必须稳定。"
    )


def compile_video_prompt(
    spec: ShotCreativeSpec,
    *,
    order: int,
    generation_duration_seconds: int,
    aspect_ratio: str,
    fps: int,
) -> str:
    phases = "；随后".join(item.description for item in spec.action_phases)
    locks = "；".join(spec.continuity_locks)
    foley = "、".join(spec.sound.synchronous_foley)
    forbidden_audio = "、".join(spec.sound.forbidden)
    constraints = "；".join(spec.failure_constraints)
    return (
        f"【首帧约束】以当前上传并已采用的第{order:02d}张分镜图作为唯一首帧、主体、场景、构图和明暗关系约束，生成一个{generation_duration_seconds}秒、{aspect_ratio}、{fps}fps的单一连续镜头；不得重新设计首帧中的产品、人物、设备或空间。\n\n"
        f"【统一视觉锁定】{locks}。{spec.lighting}。{spec.color_and_texture}。"
        "全片摄影质感与色彩管理遵循当前 Skill 的风格。\n\n"
        f"【本镜头】{spec.camera.lens_mm}mm镜头，{chinese_term(spec.camera.framing)}；"
        f"{spec.camera.position}。起始状态：{spec.initial_state}。"
        f"动作仅完成一次：{phases}。结束状态：{spec.end_state}。"
        f"摄影机{chinese_term(spec.camera.motion)}，"
        f"{spec.camera.motion_extent or '运动幅度极小且稳定'}；"
        f"{spec.camera.focus}。在指定结束状态形成明确的剪辑落点，"
        f"方便{chinese_term(spec.transition.kind)}。\n\n"
        f"【同步音效】{foley}；{spec.sound.ambience}。"
        "声音必须与可见动作及环境匹配，不得无故出现新的声源；"
        f"禁止内容：{forbidden_audio or '未在本镜头指定的额外声音'}。\n\n"
        f"【剪辑落点】{spec.transition.cut_out}。{spec.transition.continuity_note}。\n\n"
        f"【严格约束】一镜到底，不得自动切镜或突然换景；{constraints}；不得生成字幕、Logo、水印或任何新增文字。"
    )


def assess_prompts(
    image_prompt: str,
    video_prompt: str,
    *,
    minimum_score: int,
    forbidden_copy_terms: list[str],
    allowed_context: str,
    required_image_sections: list[str] | None = None,
    required_video_sections: list[str] | None = None,
    image_character_range: tuple[int, int] = (260, 8000),
    video_character_range: tuple[int, int] = (450, 8000),
) -> PromptQualityReport:
    image_sections = required_image_sections or [
        "主体与场景",
        "构图与镜头",
        "光线与色彩",
        "严格约束",
    ]
    video_sections = required_video_sections or [
        "首帧约束",
        "统一视觉锁定",
        "本镜头",
        "同步音效",
        "严格约束",
    ]
    checks = {
        "image_sections": all(f"【{item}】" in image_prompt for item in image_sections),
        "video_sections": all(f"【{item}】" in video_prompt for item in video_sections),
        "image_static_only": not bool(
            re.search(r"\d+(?:\.\d+)?\s*[–—-]\s*\d+(?:\.\d+)?\s*秒", image_prompt)
        ),
        "first_frame_bound": "唯一首帧" in video_prompt,
        "camera_specific": bool(re.search(r"\d{2,3}mm", video_prompt)),
        "motion_specific": any(
            term in video_prompt for term in ("厘米", "%", "绝对静止", "运动幅度极小")
        ),
        "sound_present": "【同步音效】" in video_prompt and "环境" in video_prompt,
        "single_shot": "一镜到底" in video_prompt,
        "prompt_length": (
            image_character_range[0] <= len(image_prompt) <= image_character_range[1]
            and video_character_range[0] <= len(video_prompt) <= video_character_range[1]
        ),
        "no_case_leakage": not any(
            term
            and term.casefold() not in allowed_context.casefold()
            and term.casefold() in (image_prompt + video_prompt).casefold()
            for term in forbidden_copy_terms
        ),
    }
    score = round(sum(checks.values()) / len(checks) * 100)
    issues = [key for key, passed in checks.items() if not passed]
    return PromptQualityReport(
        score=score,
        passed=score >= minimum_score,
        issues=issues,
        checks=checks,
    )
