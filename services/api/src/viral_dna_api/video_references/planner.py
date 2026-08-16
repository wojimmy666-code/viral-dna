from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from ..models import ShotPlan, VideoGenerationCapability
from ..reference_routes import (
    IdentityReferenceTransport,
    VideoReferenceRouteId,
    resolve_reference_route,
)
from ..video_generation.contracts import (
    OrderedReferenceFrame,
    OrderedReferenceVideo,
    ProviderManagedAssetReference,
)
from .domain import (
    PersonContentClass,
    PersonReferencePolicy,
    VideoReferenceBinding,
    VideoReferenceSourceKind,
)


class VideoReferencePolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExcludedVideoReference:
    candidate_id: str
    title: str
    person_class: str
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedVideoReferencePlan:
    policy: PersonReferencePolicy
    strategy: str
    route_id: str
    effective_route_id: str
    identity_source: str
    motion_source: str
    motion_semantics: str
    fallback_applied: bool
    reference_frames: tuple[OrderedReferenceFrame, ...]
    reference_videos: tuple[OrderedReferenceVideo, ...]
    managed_asset_references: tuple[ProviderManagedAssetReference, ...]
    excluded_references: tuple[ExcludedVideoReference, ...]
    warnings: tuple[str, ...]
    policy_version: str
    fingerprint: str

    def manifest(self) -> dict[str, object]:
        return {
            "policy": self.policy.value,
            "strategy": self.strategy,
            "route_id": self.route_id,
            "effective_route_id": self.effective_route_id,
            "identity_source": self.identity_source,
            "motion_source": self.motion_source,
            "motion_semantics": self.motion_semantics,
            "fallback_applied": self.fallback_applied,
            "policy_version": self.policy_version,
            "fingerprint": self.fingerprint,
            "submitted_local_references": [
                {
                    "candidate_id": str(frame.candidate_id),
                    "ordinal": frame.ordinal,
                    "title": frame.title,
                    "sha256": frame.sha256,
                }
                for frame in self.reference_frames
            ],
            "submitted_managed_assets": [
                {
                    "binding_id": str(item.binding_id),
                    "provider": item.provider,
                    "asset_id": item.asset_id,
                    "role": item.role,
                }
                for item in self.managed_asset_references
            ],
            "submitted_proxy_videos": [
                {
                    "proxy_asset_id": str(item.proxy_asset_id),
                    "ordinal": item.ordinal,
                    "title": item.title,
                    "sha256": item.sha256,
                    "role": item.role,
                }
                for item in self.reference_videos
            ],
            "excluded_references": [asdict(item) for item in self.excluded_references],
            "warnings": list(self.warnings),
        }


def _binding_for_frame(
    frame: OrderedReferenceFrame,
    bindings: list[VideoReferenceBinding],
) -> VideoReferenceBinding | None:
    return next(
        (
            binding
            for binding in bindings
            if binding.enabled
            and binding.source_kind == VideoReferenceSourceKind.LOCAL_ORIGINAL
            and binding.image_candidate_id == frame.candidate_id
        ),
        None,
    )


def _content_class(binding: VideoReferenceBinding | None) -> PersonContentClass:
    return binding.person_class if binding is not None else PersonContentClass.UNKNOWN


def _renumber(
    frames: list[OrderedReferenceFrame],
) -> tuple[OrderedReferenceFrame, ...]:
    return tuple(replace(frame, ordinal=index) for index, frame in enumerate(frames, start=1))


def _fingerprint(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _exclude_unsubmitted_route_frames(
    frames: list[OrderedReferenceFrame],
    *,
    shot: ShotPlan,
    excluded: list[ExcludedVideoReference],
) -> None:
    """Record frames retained in the project but not accepted by this route."""

    for frame in frames:
        binding = _binding_for_frame(frame, shot.video_reference_bindings)
        excluded.append(
            ExcludedVideoReference(
                candidate_id=str(frame.candidate_id),
                title=frame.title,
                person_class=_content_class(binding).value,
                reason_code="reference_route_image_limit",
                reason="当前模型路由只提交一张身份/起始参考图；其余画面仍保留在项目中",
            )
        )


def resolve_video_reference_plan(
    *,
    capability: VideoGenerationCapability,
    shot: ShotPlan,
    reference_frames: tuple[OrderedReferenceFrame, ...],
    managed_asset_references: tuple[ProviderManagedAssetReference, ...],
    proxy_reference_frames: tuple[OrderedReferenceFrame, ...] = (),
    proxy_reference_videos: tuple[OrderedReferenceVideo, ...] = (),
) -> ResolvedVideoReferencePlan:
    """Compile creative references into the exact provider input set.

    This is the final safety boundary. Provider adapters only receive references
    returned by this function; frontend choices cannot bypass model policy.
    """

    person_capability = capability.person_references
    policy = person_capability.policy
    ordered = sorted(reference_frames, key=lambda item: item.ordinal)
    selected: list[OrderedReferenceFrame] = []
    excluded: list[ExcludedVideoReference] = []
    warnings: list[str] = []
    selected_videos: tuple[OrderedReferenceVideo, ...] = ()

    route_capability = capability.reference_route
    route = resolve_reference_route(
        route_capability,
        has_managed_identity=bool(managed_asset_references),
        has_raw_reference_image=bool(ordered),
        has_pose_proxy_image=bool(proxy_reference_frames),
        has_motion_proxy_video=bool(proxy_reference_videos),
        public_media_transport_ready=False,
    )
    if not route.generation_allowed:
        raise VideoReferencePolicyError(
            route.blocker_code or "video_reference_route_blocked",
            route.blocker_message or "当前模型参考路由不可用",
        )
    warnings.extend(route.warnings)
    if route.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
        if len(managed_asset_references) != 1:
            raise VideoReferencePolicyError(
                "video_managed_identity_count_invalid",
                "当前模型路由必须且只能提交一个 Provider 托管演员身份",
            )
        selected_managed_assets = managed_asset_references
    else:
        selected_managed_assets = ()
        if managed_asset_references:
            warnings.append(
                "当前模型使用目标人物参考图；项目中的 Provider 托管演员绑定未提交"
            )

    if route.route_id == VideoReferenceRouteId.SEEDANCE_MANAGED_ACTOR_MOTION_PROXY:
        strategy = "managed_identity_only"
        for frame in ordered:
            binding = _binding_for_frame(frame, shot.video_reference_bindings)
            content_class = _content_class(binding)
            if content_class in {
                PersonContentClass.NO_PERSON,
                PersonContentClass.NON_PHOTOREAL_PROXY,
            }:
                selected.append(frame)
                strategy = "managed_identity_with_safe_references"
                continue
            excluded.append(
                ExcludedVideoReference(
                    candidate_id=str(frame.candidate_id),
                    title=frame.title,
                    person_class=content_class.value,
                    reason_code="local_identity_reference_excluded",
                    reason="托管演员是唯一身份来源；原始或身份不明的本地人物画面不会提交",
                )
            )
        if route.motion_source == "motion_proxy_video":
            selected_videos = tuple(
                replace(item, ordinal=index)
                for index, item in enumerate(proxy_reference_videos[:1], start=1)
            )
            strategy = "managed_identity_with_motion_proxy"
        elif route.motion_source == "pose_proxy_image" and proxy_reference_frames:
            selected.extend(proxy_reference_frames[:1])
            strategy = "managed_identity_with_pose_proxy"
        if excluded:
            warnings.append(f"已按模型隐私策略排除 {len(excluded)} 张本地人物参考画面")
    elif route.route_id == VideoReferenceRouteId.MINIMAX_IDENTITY_IMAGE_MOTION_PROXY:
        selected = ordered[:1]
        _exclude_unsubmitted_route_frames(ordered[1:], shot=shot, excluded=excluded)
        if route.motion_source == "motion_proxy_video":
            selected_videos = tuple(
                replace(item, ordinal=index)
                for index, item in enumerate(proxy_reference_videos[:1], start=1)
            )
            strategy = "identity_image_with_motion_proxy"
        else:
            if route.motion_source == "pose_proxy_image" and proxy_reference_frames:
                selected.extend(proxy_reference_frames[:1])
            strategy = "identity_image_with_pose_text_fallback"
    elif route.route_id == VideoReferenceRouteId.WAN_VACE_POSEBODY_REPAINT:
        selected = ordered[:1]
        _exclude_unsubmitted_route_frames(ordered[1:], shot=shot, excluded=excluded)
        if not proxy_reference_videos:
            raise VideoReferencePolicyError(
                "video_motion_proxy_required",
                "Wan VACE PoseBody 路由需要一段已通过校验的视频白模",
            )
        selected_videos = tuple(
            replace(item, ordinal=index)
            for index, item in enumerate(proxy_reference_videos[:1], start=1)
        )
        strategy = "identity_image_with_posebody_control_video"
    elif (
        route.effective_route_id == VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK
        and policy in {
            PersonReferencePolicy.RAW_SUPPORTED,
            PersonReferencePolicy.MANAGED_OPTIONAL,
        }
    ):
        selected = ordered[:1]
        _exclude_unsubmitted_route_frames(ordered[1:], shot=shot, excluded=excluded)
        strategy = "identity_image_with_text_motion"
    elif (
        route.route_id == VideoReferenceRouteId.ORDERED_MULTI_IMAGE
        and policy in {
            PersonReferencePolicy.RAW_SUPPORTED,
            PersonReferencePolicy.MANAGED_OPTIONAL,
        }
    ):
        selected = ordered
        strategy = "raw_references"
        if selected_managed_assets:
            strategy = "managed_identity_with_raw_references"

    elif policy in {
        PersonReferencePolicy.RAW_SUPPORTED,
        PersonReferencePolicy.MANAGED_OPTIONAL,
    }:
        selected = ordered
        strategy = "raw_references"
        if selected_managed_assets:
            strategy = "managed_identity_with_raw_references"
    elif policy == PersonReferencePolicy.MANAGED_REQUIRED:
        if not selected_managed_assets:
            raise VideoReferencePolicyError(
                "video_managed_identity_required",
                "当前模型不接收原始真人身份素材；请先绑定 Provider 托管演员身份，"
                "或切换到支持原始素材的模型",
            )
        strategy = "managed_identity_only"
        for frame in ordered:
            binding = _binding_for_frame(frame, shot.video_reference_bindings)
            content_class = _content_class(binding)
            if content_class in {
                PersonContentClass.NO_PERSON,
                PersonContentClass.NON_PHOTOREAL_PROXY,
            }:
                selected.append(frame)
                strategy = "managed_identity_with_safe_references"
                continue
            excluded.append(
                ExcludedVideoReference(
                    candidate_id=str(frame.candidate_id),
                    title=frame.title,
                    person_class=content_class.value,
                    reason_code="local_identity_reference_excluded",
                    reason=(
                        "托管演员是唯一人物身份来源；原始或身份不明的本地画面不会提交给当前模型"
                    ),
                )
            )
        if excluded:
            warnings.append(f"已按模型策略排除 {len(excluded)} 张本地人物/身份不明参考画面")
        if proxy_reference_frames:
            selected.extend(proxy_reference_frames)
            strategy = "managed_identity_with_safe_references"
        if proxy_reference_videos:
            if not person_capability.supports_motion_proxy_video:
                raise VideoReferencePolicyError(
                    "video_motion_proxy_unsupported",
                    "当前模型不支持视频动作代理，请改用图片动作代理或切换模型",
                )
            selected_videos = tuple(
                replace(item, ordinal=index)
                for index, item in enumerate(proxy_reference_videos, start=1)
            )
            strategy = "managed_identity_with_motion_proxy"
    elif policy == PersonReferencePolicy.NO_PERSON:
        for frame in ordered:
            binding = _binding_for_frame(frame, shot.video_reference_bindings)
            content_class = _content_class(binding)
            if content_class != PersonContentClass.NO_PERSON:
                raise VideoReferencePolicyError(
                    "video_person_reference_not_allowed",
                    "当前模型不允许人物参考；请移除人物素材或切换模型",
                )
            selected.append(frame)
        if selected_managed_assets:
            raise VideoReferencePolicyError(
                "video_managed_person_not_allowed",
                "当前模型不允许托管人物身份",
            )
        strategy = "person_free_references"
    else:
        selected = ordered
        strategy = "legacy_unclassified_references"
        warnings.append("当前模型未声明人物参考策略，已按兼容模式提交；建议补齐模型能力声明")

    selected_frames = _renumber(selected)
    manifest_seed: dict[str, object] = {
        "policy": policy.value,
        "strategy": strategy,
        "route_id": route.route_id.value,
        "effective_route_id": route.effective_route_id.value,
        "identity_source": route.identity_source,
        "motion_source": route.motion_source,
        "motion_semantics": route.motion_semantics.value,
        "fallback_applied": route.fallback_applied,
        "policy_version": shot.reference_policy_version,
        "local": [
            {"candidate_id": str(item.candidate_id), "sha256": item.sha256}
            for item in selected_frames
        ],
        "managed": [
            {
                "binding_id": str(item.binding_id),
                "provider": item.provider,
                "asset_id": item.asset_id,
            }
            for item in selected_managed_assets
        ],
        "proxy_videos": [
            {"proxy_asset_id": str(item.proxy_asset_id), "sha256": item.sha256}
            for item in selected_videos
        ],
        "excluded": [asdict(item) for item in excluded],
    }
    return ResolvedVideoReferencePlan(
        policy=policy,
        strategy=strategy,
        route_id=route.route_id.value,
        effective_route_id=route.effective_route_id.value,
        identity_source=route.identity_source,
        motion_source=route.motion_source,
        motion_semantics=route.motion_semantics.value,
        fallback_applied=route.fallback_applied,
        reference_frames=selected_frames,
        reference_videos=selected_videos,
        managed_asset_references=selected_managed_assets,
        excluded_references=tuple(excluded),
        warnings=tuple(warnings),
        policy_version=shot.reference_policy_version,
        fingerprint=_fingerprint(manifest_seed),
    )
