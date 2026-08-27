from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from ..models import (
    ReferenceAsset,
    ReferenceAssetType,
    ShotPlan,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
    VideoGenerationIntentIR,
    VideoGenerationReference,
    VideoIntentDimension,
    VideoIntentOperation,
    VideoPromptMention,
    VideoPromptReferenceKind,
    VideoPromptReferenceRole,
    VideoReferenceOrigin,
    VideoReferenceScope,
    VideoReferenceScopeKind,
)
from ..video_generation.drafts import current_default_input_plan
from .contracts import UnresolvedIntentRequirement

DIMENSION_ASSET_TYPES = {
    VideoIntentDimension.IDENTITY: {ReferenceAssetType.PERSON},
    VideoIntentDimension.WARDROBE: {ReferenceAssetType.WARDROBE},
    VideoIntentDimension.PRODUCT: {ReferenceAssetType.PRODUCT},
    VideoIntentDimension.SCENE: {ReferenceAssetType.SCENE},
    VideoIntentDimension.PROP: {ReferenceAssetType.PROP},
    VideoIntentDimension.STYLE: {ReferenceAssetType.STYLE},
}

DIMENSION_ROLES = {
    VideoIntentDimension.IDENTITY: VideoPromptReferenceRole.ACTOR_IDENTITY,
    VideoIntentDimension.WARDROBE: VideoPromptReferenceRole.WARDROBE,
    VideoIntentDimension.PRODUCT: VideoPromptReferenceRole.PRODUCT,
    VideoIntentDimension.SCENE: VideoPromptReferenceRole.SCENE,
    VideoIntentDimension.PROP: VideoPromptReferenceRole.COMPOSITION,
    VideoIntentDimension.STYLE: VideoPromptReferenceRole.STYLE,
}

ASSET_TYPE_LABELS = {
    ReferenceAssetType.PERSON: "人物",
    ReferenceAssetType.WARDROBE: "服装",
    ReferenceAssetType.PRODUCT: "产品",
    ReferenceAssetType.SCENE: "场景",
    ReferenceAssetType.PROP: "道具",
    ReferenceAssetType.STYLE: "风格",
}

ASSET_TYPE_ROLES = {
    ReferenceAssetType.PERSON: VideoPromptReferenceRole.ACTOR_IDENTITY,
    ReferenceAssetType.WARDROBE: VideoPromptReferenceRole.WARDROBE,
    ReferenceAssetType.PRODUCT: VideoPromptReferenceRole.PRODUCT,
    ReferenceAssetType.SCENE: VideoPromptReferenceRole.SCENE,
    ReferenceAssetType.PROP: VideoPromptReferenceRole.COMPOSITION,
    ReferenceAssetType.STYLE: VideoPromptReferenceRole.STYLE,
}

SOURCE_BY_KIND = {
    VideoPromptReferenceKind.APPROVED_IMAGE: VideoGenerationInputSource.APPROVED_IMAGES,
    VideoPromptReferenceKind.PROJECT_ASSET: VideoGenerationInputSource.PROJECT_ASSETS,
    VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET: (
        VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS
    ),
    VideoPromptReferenceKind.REFERENCE_VIDEO: VideoGenerationInputSource.REFERENCE_VIDEO,
    VideoPromptReferenceKind.DEPTH_CONTROL: VideoGenerationInputSource.DEPTH_CONTROL,
}


@dataclass(frozen=True, slots=True)
class ResolvedIntentReferences:
    input_plan: VideoGenerationInputPlan
    unresolved: tuple[UnresolvedIntentRequirement, ...]
    warnings: tuple[str, ...]
    transition_evidence: str


def _normalized(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _stable_key(reference: VideoGenerationReference) -> str:
    if reference.reference_kind == VideoPromptReferenceKind.APPROVED_IMAGE:
        beat_id = reference.visual_beat_id or (
            reference.scope.visual_beat_ids[0] if reference.scope.visual_beat_ids else None
        )
        if beat_id is not None:
            return f"approved_image:visual_beat:{beat_id}"
    return f"{reference.reference_kind.value}:{reference.reference_id}"


def _scope(shot: ShotPlan, indexes: list[int]) -> VideoReferenceScope:
    beats = [item for item in shot.visual_beats if item.index in indexes]
    if not beats:
        return VideoReferenceScope()
    return VideoReferenceScope(
        kind=VideoReferenceScopeKind.VISUAL_BEATS,
        visual_beat_ids=[item.id for item in beats],
        start_ratio=min(item.start_ratio for item in beats),
        end_ratio=max(item.end_ratio for item in beats),
    )


def _asset_candidates(
    assets: list[ReferenceAsset],
    target_name: str | None,
    accepted_types: set[ReferenceAssetType],
) -> list[ReferenceAsset]:
    typed = [
        item
        for item in assets
        if item.type in accepted_types and item.archived_at is None and item.rights_confirmed
    ]
    target = _normalized(target_name)
    if not target:
        return typed if len(typed) == 1 else []
    exact = [item for item in typed if _normalized(item.name) == target]
    if exact:
        return exact
    tagged = [
        item
        for item in typed
        if target
        in {
            _normalized(item.folder_name),
            *(_normalized(tag) for tag in item.tags),
        }
    ]
    if tagged:
        return tagged
    return [
        item
        for item in typed
        if target in _normalized(item.name) or _normalized(item.name) in target
    ]


def _reference(
    *,
    kind: VideoPromptReferenceKind,
    reference_id: UUID,
    label: str,
    role: VideoPromptReferenceRole,
    scope: VideoReferenceScope | None = None,
    visual_beat_id: UUID | None = None,
    automatic: bool = True,
    origin: VideoReferenceOrigin = VideoReferenceOrigin.INTENT_GENERATED,
) -> VideoGenerationReference:
    return VideoGenerationReference(
        reference_kind=kind,
        reference_id=reference_id,
        label=label,
        role=role,
        order=1,
        visual_beat_id=visual_beat_id,
        automatic=automatic,
        scope=scope or VideoReferenceScope(),
        origin=origin,
    )


def _mention_key(mention: VideoPromptMention) -> str:
    return f"{mention.reference_kind.value}:{mention.reference_id}"


def _explicit_reference(
    mention: VideoPromptMention,
    *,
    shot: ShotPlan,
    assets: list[ReferenceAsset],
) -> tuple[VideoGenerationReference | None, UnresolvedIntentRequirement | None]:
    kind = mention.reference_kind
    if kind == VideoPromptReferenceKind.PROJECT_ASSET:
        asset = next(
            (
                item
                for item in assets
                if item.id == mention.reference_id
                and item.archived_at is None
                and item.rights_confirmed
            ),
            None,
        )
        if asset is not None:
            return (
                _reference(
                    kind=kind,
                    reference_id=asset.id,
                    label=mention.label,
                    role=ASSET_TYPE_ROLES[asset.type],
                    origin=VideoReferenceOrigin.INTENT_EXPLICIT,
                ),
                None,
            )
    elif kind == VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET:
        binding = next(
            (item for item in shot.managed_asset_bindings if item.id == mention.reference_id),
            None,
        )
        if binding is not None:
            return (
                _reference(
                    kind=kind,
                    reference_id=binding.id,
                    label=f"托管角色/{binding.name}",
                    role=VideoPromptReferenceRole.ACTOR_IDENTITY,
                    origin=VideoReferenceOrigin.INTENT_EXPLICIT,
                ),
                None,
            )
    elif kind == VideoPromptReferenceKind.DEPTH_CONTROL:
        ready_depth = [
            item
            for item in shot.depth_control_assets
            if item.enabled and item.usable_for_generation
        ]
        depth = next((item for item in ready_depth if item.id == mention.reference_id), None)
        if depth is not None:
            return (
                _reference(
                    kind=kind,
                    reference_id=depth.id,
                    label=f"深度视频/分镜动作{ready_depth.index(depth) + 1}",
                    role=VideoPromptReferenceRole.DEPTH,
                    origin=VideoReferenceOrigin.INTENT_EXPLICIT,
                ),
                None,
            )
    elif kind == VideoPromptReferenceKind.APPROVED_IMAGE:
        beat = next(
            (
                item
                for item in shot.visual_beats
                if item.approved_image_candidate_id == mention.reference_id
            ),
            None,
        )
        if beat is not None:
            return (
                _reference(
                    kind=kind,
                    reference_id=mention.reference_id,
                    label=f"分镜图/图{beat.index}",
                    role=VideoPromptReferenceRole.COMPOSITION,
                    scope=_scope(shot, [beat.index]),
                    visual_beat_id=beat.id,
                    automatic=False,
                    origin=VideoReferenceOrigin.INTENT_EXPLICIT,
                ),
                None,
            )
    elif kind == VideoPromptReferenceKind.REFERENCE_VIDEO:
        binding = next(
            (
                item
                for item in shot.video_reference_bindings
                if item.id == mention.reference_id
                and item.enabled
                and item.media_type.value == "video"
            ),
            None,
        )
        if binding is not None:
            role = (
                VideoPromptReferenceRole.TRANSITION
                if binding.role.value == "transition"
                else VideoPromptReferenceRole.MOTION
            )
            return (
                _reference(
                    kind=kind,
                    reference_id=binding.id,
                    label=f"参考视频/视频{binding.order}",
                    role=role,
                    origin=VideoReferenceOrigin.INTENT_EXPLICIT,
                ),
                None,
            )
    return (
        None,
        UnresolvedIntentRequirement(
            code="explicit_reference_unavailable",
            dimension="general",
            message=f"创作意图中的“@{mention.label}”已失效或当前无权使用，请重新选择",
        ),
    )


def validate_intent_mentions(
    mentions: list[VideoPromptMention],
    *,
    shot: ShotPlan,
    assets: list[ReferenceAsset],
) -> tuple[UnresolvedIntentRequirement, ...]:
    failures: list[UnresolvedIntentRequirement] = []
    for mention in mentions:
        _candidate, failure = _explicit_reference(mention, shot=shot, assets=assets)
        if failure is not None:
            failures.append(failure)
    return tuple(failures)


def resolve_intent_references(
    *,
    intent: VideoGenerationIntentIR,
    shot: ShotPlan,
    assets: list[ReferenceAsset],
    explicit_mentions: list[VideoPromptMention],
    current_plan: VideoGenerationInputPlan,
    excluded_visual_beat_ids: list[UUID],
    removed_intent_reference_keys: list[str],
    locked_reference_keys: list[str],
) -> ResolvedIntentReferences:
    excluded_beats = {str(item) for item in excluded_visual_beat_ids}
    removed = set(removed_intent_reference_keys)
    locked = set(locked_reference_keys)
    references = [
        item
        for item in current_default_input_plan(shot).references
        if not item.visual_beat_id or str(item.visual_beat_id) not in excluded_beats
    ]
    manual = [
        item
        for item in current_plan.references
        if (
            not item.automatic
            and item.origin
            not in {
                VideoReferenceOrigin.INTENT_GENERATED,
                VideoReferenceOrigin.INTENT_EXPLICIT,
            }
        )
        or item.locked
        or _stable_key(item) in locked
    ]
    references.extend(manual)
    unresolved: list[UnresolvedIntentRequirement] = []
    warnings: list[str] = []
    transition_evidence = "none"
    valid_beat_indexes = {item.index for item in shot.visual_beats}
    explicit_by_key: dict[str, VideoGenerationReference] = {}
    for mention in explicit_mentions:
        candidate, failure = _explicit_reference(mention, shot=shot, assets=assets)
        if failure is not None:
            unresolved.append(failure)
            continue
        if candidate is None:
            continue
        mention_key = _mention_key(mention)
        explicit_by_key[mention_key] = candidate
        explicit_by_key[_stable_key(candidate)] = candidate
        if _stable_key(candidate) in removed:
            unresolved.append(
                UnresolvedIntentRequirement(
                    code="explicit_reference_manually_removed",
                    dimension="general",
                    message=(f"“@{candidate.label}”仍在创作意图中，但已在高级引用中人工移除"),
                )
            )
            continue
        references.append(candidate)

    for directive in intent.directives:
        if directive.operation not in {
            VideoIntentOperation.PRESERVE,
            VideoIntentOperation.REPLACE,
            VideoIntentOperation.REDESIGN,
        }:
            continue
        missing_beat_indexes = sorted(set(directive.visual_beat_indexes) - valid_beat_indexes)
        if missing_beat_indexes:
            unresolved.append(
                UnresolvedIntentRequirement(
                    code="visual_beat_not_found",
                    dimension=directive.dimension.value,
                    message=(
                        "创作意图引用了不存在的画面："
                        + "、".join(f"图{index}" for index in missing_beat_indexes)
                    ),
                )
            )
            continue
        if (
            directive.dimension in DIMENSION_ASSET_TYPES
            and directive.operation == VideoIntentOperation.REPLACE
        ):
            expected_role = DIMENSION_ROLES[directive.dimension]
            if directive.target_reference_key:
                explicit = explicit_by_key.get(directive.target_reference_key)
                if explicit is None:
                    unresolved.append(
                        UnresolvedIntentRequirement(
                            code="explicit_reference_not_resolved",
                            dimension=directive.dimension.value,
                            message="大模型引用的显式资产无法解析，请重新选择后再试",
                        )
                    )
                elif explicit.role != expected_role:
                    references = [
                        item for item in references if _stable_key(item) != _stable_key(explicit)
                    ]
                    unresolved.append(
                        UnresolvedIntentRequirement(
                            code="explicit_reference_type_mismatch",
                            dimension=directive.dimension.value,
                            message=(
                                f"“@{explicit.label}”不能用于{ASSET_TYPE_LABELS[next(iter(DIMENSION_ASSET_TYPES[directive.dimension]))]}替换"
                            ),
                        )
                    )
                continue
            compatible_explicit = {
                _stable_key(item): item
                for item in explicit_by_key.values()
                if item.role == expected_role
                and (
                    not directive.target_name
                    or _normalized(directive.target_name) in _normalized(item.label)
                )
            }
            if len(compatible_explicit) == 1:
                continue
            candidates = _asset_candidates(
                assets,
                directive.target_name,
                DIMENSION_ASSET_TYPES[directive.dimension],
            )
            if directive.dimension == VideoIntentDimension.IDENTITY:
                managed = [
                    item
                    for item in shot.managed_asset_bindings
                    if not directive.target_name
                    or _normalized(item.name) == _normalized(directive.target_name)
                ]
                prefer_project_asset = directive.preferred_source == "project_asset"
                if not prefer_project_asset and len(managed) == 1:
                    candidate = _reference(
                        kind=VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET,
                        reference_id=managed[0].id,
                        label=f"托管角色/{managed[0].name}",
                        role=VideoPromptReferenceRole.ACTOR_IDENTITY,
                    )
                    if _stable_key(candidate) not in removed:
                        references.append(candidate)
                    continue
                if directive.preferred_source == "managed_asset":
                    unresolved.append(
                        UnresolvedIntentRequirement(
                            code=(
                                "managed_asset_not_found"
                                if not managed
                                else "managed_asset_ambiguous"
                            ),
                            dimension=directive.dimension.value,
                            message=(
                                f"未找到“{directive.target_name or '未命名'}”对应的托管人物"
                                if not managed
                                else f"“{directive.target_name}”匹配到多个托管人物，请人工选择"
                            ),
                            candidates=[item.name for item in managed],
                        )
                    )
                    continue
            if len(candidates) != 1:
                unresolved.append(
                    UnresolvedIntentRequirement(
                        code=("asset_not_found" if not candidates else "asset_ambiguous"),
                        dimension=directive.dimension.value,
                        message=(
                            f"未找到“{directive.target_name or '未命名'}”对应的可用资产"
                            if not candidates
                            else f"“{directive.target_name}”匹配到多个资产，请人工选择"
                        ),
                        candidates=[item.name for item in candidates],
                    )
                )
                continue
            asset = candidates[0]
            candidate = _reference(
                kind=VideoPromptReferenceKind.PROJECT_ASSET,
                reference_id=asset.id,
                label=f"资产/{ASSET_TYPE_LABELS[asset.type]}/{asset.name}",
                role=DIMENSION_ROLES[directive.dimension],
                scope=_scope(shot, directive.visual_beat_indexes),
            )
            if _stable_key(candidate) not in removed:
                references.append(candidate)

        if (
            directive.dimension
            in {
                VideoIntentDimension.MOTION,
                VideoIntentDimension.CAMERA,
                VideoIntentDimension.TIMING,
                VideoIntentDimension.COMPOSITION,
            }
            and directive.operation == VideoIntentOperation.PRESERVE
        ):
            if directive.preferred_source != "depth_control":
                continue
            explicit_depth = (
                explicit_by_key.get(directive.target_reference_key)
                if directive.target_reference_key
                else None
            )
            if explicit_depth is None and not directive.target_reference_key:
                explicit_depths = {
                    _stable_key(item): item
                    for item in explicit_by_key.values()
                    if item.reference_kind == VideoPromptReferenceKind.DEPTH_CONTROL
                }
                if len(explicit_depths) == 1:
                    explicit_depth = next(iter(explicit_depths.values()))
            if explicit_depth is not None and (
                explicit_depth.reference_kind != VideoPromptReferenceKind.DEPTH_CONTROL
            ):
                references = [
                    item for item in references if _stable_key(item) != _stable_key(explicit_depth)
                ]
                unresolved.append(
                    UnresolvedIntentRequirement(
                        code="explicit_reference_type_mismatch",
                        dimension=directive.dimension.value,
                        message=f"“@{explicit_depth.label}”不是可用的深度视频",
                    )
                )
                continue
            depth = (
                None
                if explicit_depth is not None
                else next(
                    (
                        item
                        for item in shot.depth_control_assets
                        if item.enabled and item.usable_for_generation
                    ),
                    None,
                )
            )
            if explicit_depth is None and depth is None:
                unresolved.append(
                    UnresolvedIntentRequirement(
                        code="depth_control_not_ready",
                        dimension=directive.dimension.value,
                        message="创作意图要求保留动作或镜头，但当前没有可用的深度视频",
                    )
                )
            elif explicit_depth is None:
                candidate = _reference(
                    kind=VideoPromptReferenceKind.DEPTH_CONTROL,
                    reference_id=depth.id,
                    label="深度视频/分镜动作1",
                    role=VideoPromptReferenceRole.DEPTH,
                )
                if _stable_key(candidate) not in removed:
                    references.append(candidate)

        if directive.dimension == VideoIntentDimension.TRANSITION:
            if directive.operation == VideoIntentOperation.PRESERVE:
                # 普通参考视频目前没有可提交给 Provider 的稳定媒体契约，因此不能
                # 仅凭一个 UI 绑定伪装为已传入原片。先使用分析事实和前后分镜图，
                # 待模型目录声明 reference_video 并具备真实媒体传输后再升级为片段证据。
                if any(
                    item.transition_to_next_prompt
                    or item.transition_to_next_type != "model_generated"
                    for item in shot.visual_beats[:-1]
                ):
                    transition_evidence = "analyzed_facts"
                    warnings.append("尚无原转场视频片段，将使用前后画面和已分析的转场事实")
                elif directive.instruction:
                    transition_evidence = "user_instruction"
                else:
                    transition_evidence = "free"
            elif directive.operation == VideoIntentOperation.REDESIGN:
                transition_evidence = "user_instruction" if directive.instruction else "free"

    unique: dict[str, VideoGenerationReference] = {}
    for item in references:
        key = _stable_key(item)
        if key not in unique or item.locked:
            unique[key] = item
    ordered = [
        item.model_copy(update={"order": index})
        for index, item in enumerate(unique.values(), start=1)
    ]
    sources = list(dict.fromkeys(SOURCE_BY_KIND[item.reference_kind] for item in ordered))
    return ResolvedIntentReferences(
        input_plan=VideoGenerationInputPlan(sources=sources, references=ordered),
        unresolved=tuple(unresolved),
        warnings=tuple(warnings),
        transition_evidence=transition_evidence,
    )
