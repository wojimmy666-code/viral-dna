from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from ..models import ShotPlan, VideoGenerationCapability
from ..reference_routes import (
    IdentityReferenceTransport,
    resolve_reference_route,
)
from ..video_generation.contracts import (
    DepthControlVideo,
    OrderedReferenceFrame,
    ProviderManagedAssetReference,
)
from .domain import PersonReferencePolicy


class VideoReferencePolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExcludedVideoReference:
    candidate_id: str
    title: str
    role: str
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedVideoReferencePlan:
    policy: PersonReferencePolicy
    strategy: str
    route_id: str
    identity_source: str
    spatial_control_source: str
    spatial_control_semantics: str
    reference_frames: tuple[OrderedReferenceFrame, ...]
    depth_control_videos: tuple[DepthControlVideo, ...]
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
            "effective_route_id": self.route_id,
            "identity_source": self.identity_source,
            "spatial_control_source": self.spatial_control_source,
            "spatial_control_semantics": self.spatial_control_semantics,
            "policy_version": self.policy_version,
            "fingerprint": self.fingerprint,
            "submitted_local_references": [
                {
                    "candidate_id": str(frame.candidate_id),
                    "ordinal": frame.ordinal,
                    "title": frame.title,
                    "role": frame.role,
                    "source_kind": frame.source_kind,
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
            "submitted_depth_controls": [
                {
                    "control_asset_id": str(item.control_asset_id),
                    "source_video_id": str(item.source_video_id),
                    "ordinal": item.ordinal,
                    "title": item.title,
                    "sha256": item.sha256,
                    "kind": item.kind,
                    "depth_convention": item.depth_convention,
                }
                for item in self.depth_control_videos
            ],
            "excluded_references": [asdict(item) for item in self.excluded_references],
            "warnings": list(self.warnings),
        }


def _renumber(frames: list[OrderedReferenceFrame]) -> tuple[OrderedReferenceFrame, ...]:
    return tuple(replace(frame, ordinal=index) for index, frame in enumerate(frames, start=1))


def _fingerprint(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _exclude(
    frame: OrderedReferenceFrame,
    *,
    reason_code: str,
    reason: str,
) -> ExcludedVideoReference:
    return ExcludedVideoReference(
        candidate_id=str(frame.candidate_id),
        title=frame.title,
        role=frame.role,
        reason_code=reason_code,
        reason=reason,
    )


def _identity_frame(frames: list[OrderedReferenceFrame]) -> OrderedReferenceFrame | None:
    return next((frame for frame in frames if frame.role == "actor_identity"), None)


def resolve_video_reference_plan(
    *,
    capability: VideoGenerationCapability,
    shot: ShotPlan,
    reference_frames: tuple[OrderedReferenceFrame, ...],
    managed_asset_references: tuple[ProviderManagedAssetReference, ...],
    depth_control_videos: tuple[DepthControlVideo, ...] = (),
    public_media_transport_ready: bool = False,
    depth_optional: bool = False,
) -> ResolvedVideoReferencePlan:
    """Compile creative appearance assets and one depth-control video.

    The planner is the final provider safety boundary. Depth is geometry only;
    identity and appearance are always sourced from explicit creative assets.
    """

    route_capability = capability.reference_route
    policy = capability.person_references.policy
    ordered = sorted(reference_frames, key=lambda item: item.ordinal)
    enabled_depth = tuple(depth_control_videos[:1])
    if not ordered and not managed_asset_references and not enabled_depth:
        seed = {
            "policy": policy.value,
            "strategy": "text_to_video",
            "route_id": "text_to_video",
            "policy_version": shot.reference_policy_version,
        }
        return ResolvedVideoReferencePlan(
            policy=policy,
            strategy="text_to_video",
            route_id="text_to_video",
            identity_source="prompt",
            spatial_control_source="none",
            spatial_control_semantics="none",
            reference_frames=(),
            depth_control_videos=(),
            managed_asset_references=(),
            excluded_references=(),
            warnings=(),
            policy_version=shot.reference_policy_version,
            fingerprint=_fingerprint(seed),
        )
    effective_route_capability = route_capability
    if depth_optional and route_capability.requires_depth_control_video and not enabled_depth:
        # Depth is an explicit optional generation input. A model route may
        # support it without forcing every request to use it.
        effective_route_capability = route_capability.model_copy(
            update={"requires_depth_control_video": False}
        )
    route = resolve_reference_route(
        effective_route_capability,
        has_managed_identity=bool(managed_asset_references),
        has_raw_reference_image=bool(ordered),
        has_depth_control_video=bool(enabled_depth),
        public_media_transport_ready=public_media_transport_ready,
    )
    if not route.generation_allowed:
        raise VideoReferencePolicyError(
            route.blocker_code or "video_reference_route_blocked",
            route.blocker_message or "当前模型参考素材路由不可用",
        )

    warnings = list(route.warnings)
    selected: list[OrderedReferenceFrame] = []
    excluded: list[ExcludedVideoReference] = []
    selected_managed: tuple[ProviderManagedAssetReference, ...] = ()

    if route.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET:
        if len(managed_asset_references) != 1:
            raise VideoReferencePolicyError(
                "video_managed_identity_count_invalid",
                "当前模型必须且只能绑定一个 Provider 托管演员",
            )
        selected_managed = managed_asset_references
        # Seedance 的人物身份只能来自托管演员。已确认成片帧可能含真人，
        # 因此仅提交角色明确的非人物外观资产。
        safe_roles = {"scene", "wardrobe", "product"}
        for frame in ordered:
            if frame.source_kind == "project_asset" and frame.role in safe_roles:
                selected.append(frame)
            else:
                excluded.append(
                    _exclude(
                        frame,
                        reason_code="managed_identity_isolation",
                        reason="托管演员是唯一身份来源；原始人物画面或复合成片帧不会提交",
                    )
                )
        strategy = "managed_actor_with_depth_and_appearance_assets"
    elif route.identity_transport == IdentityReferenceTransport.REFERENCE_IMAGE:
        identity = _identity_frame(ordered)
        if route_capability.identity_required and identity is None:
            # Existing approved keyframes remain a valid identity source for
            # models that accept raw people, but explicit person assets win.
            identity = next(
                (frame for frame in ordered if frame.source_kind == "approved_frame"),
                None,
            )
        if route_capability.identity_required and identity is None:
            raise VideoReferencePolicyError(
                "video_identity_image_required",
                "请先关联人物资产，或确认一张包含目标人物的分镜图",
            )
        if identity is not None:
            selected.append(identity)
        selected.extend(frame for frame in ordered if frame is not identity)
        strategy = (
            "identity_and_appearance_assets_with_depth"
            if enabled_depth
            else "identity_and_appearance_assets"
        )
    else:
        selected = ordered
        strategy = "person_free_with_depth" if enabled_depth else "person_free"

    maximum_inputs = max(1, capability.maximum_reference_images)
    reserved_inputs = len(selected_managed) + len(enabled_depth)
    image_limit = max(0, maximum_inputs - reserved_inputs)
    if len(selected) > image_limit:
        requested_inputs = len(selected) + reserved_inputs
        raise VideoReferencePolicyError(
            "provider_reference_limit",
            (
                f"当前模型最多支持 {maximum_inputs} 项生成参考，"
                f"本次需要 {requested_inputs} 项；系统不会自动丢弃参考，"
                "请切换模型或手动减少参考"
            ),
        )

    selected_frames = _renumber(selected)
    manifest_seed: dict[str, object] = {
        "policy": policy.value,
        "strategy": strategy,
        "route_id": route.route_id.value,
        "identity_source": route.identity_source,
        "spatial_control_source": route.spatial_control_source,
        "spatial_control_semantics": route.spatial_control_semantics.value,
        "policy_version": shot.reference_policy_version,
        "local": [
            {
                "candidate_id": str(item.candidate_id),
                "role": item.role,
                "source_kind": item.source_kind,
                "sha256": item.sha256,
            }
            for item in selected_frames
        ],
        "managed": [
            {
                "binding_id": str(item.binding_id),
                "provider": item.provider,
                "asset_id": item.asset_id,
            }
            for item in selected_managed
        ],
        "depth": [
            {"control_asset_id": str(item.control_asset_id), "sha256": item.sha256}
            for item in enabled_depth
        ],
        "excluded": [asdict(item) for item in excluded],
    }
    return ResolvedVideoReferencePlan(
        policy=policy,
        strategy=strategy,
        route_id=route.route_id.value,
        identity_source=route.identity_source,
        spatial_control_source=route.spatial_control_source,
        spatial_control_semantics=route.spatial_control_semantics.value,
        reference_frames=selected_frames,
        depth_control_videos=enabled_depth,
        managed_asset_references=selected_managed,
        excluded_references=tuple(excluded),
        warnings=tuple(warnings),
        policy_version=shot.reference_policy_version,
        fingerprint=_fingerprint(manifest_seed),
    )
