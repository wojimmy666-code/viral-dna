from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..models import (
    ManagedAssetKind,
    ManagedAssetRole,
    ProviderManagedAssetCapability,
    VideoGenerationCapability,
    VideoGenerationModelOption,
)
from ..reference_routes.domain import (
    IdentityReferenceTransport,
    MotionReferenceSemantics,
    MotionReferenceTransport,
    RouteSupportLevel,
    VideoReferenceRouteCapability,
    VideoReferenceRouteId,
)
from ..video_references.domain import (
    PersonReferenceCapability,
    PersonReferencePolicy,
    VideoReferenceRole,
)

CATALOG_VERSION = "video-model-catalog-2026-08-16.1"
PRICING_VERSION = "video-pricing-cn-2026-08-10"


class VideoModelCatalogError(ValueError):
    pass


def video_duration_is_supported(
    capability: VideoGenerationCapability,
    duration_seconds: float,
) -> bool:
    if not (
        capability.minimum_duration_seconds
        <= duration_seconds
        <= capability.maximum_duration_seconds
    ):
        return False
    if capability.supported_durations:
        return any(abs(duration_seconds - item) < 0.001 for item in capability.supported_durations)
    steps = (
        duration_seconds - capability.minimum_duration_seconds
    ) / capability.duration_step_seconds
    return abs(steps - round(steps)) < 0.001


def video_duration_constraint_text(capability: VideoGenerationCapability) -> str:
    if capability.supported_durations:
        values = "、".join(f"{item:g}" for item in capability.supported_durations)
        return f"仅支持 {values} 秒"
    return (
        f"支持 {capability.minimum_duration_seconds:g}～"
        f"{capability.maximum_duration_seconds:g} 秒，"
        f"按 {capability.duration_step_seconds:g} 秒调整"
    )


@dataclass(frozen=True, slots=True)
class VideoModelSpec:
    alias: str
    provider: str
    model: str | None
    label: str
    description: str
    capability: VideoGenerationCapability
    pricing: dict[str, Any]
    recommended: bool = False
    available: bool = True
    availability_note: str | None = None

    def as_option(self) -> VideoGenerationModelOption:
        return VideoGenerationModelOption(
            alias=self.alias,
            provider=self.provider,
            model=self.model,
            label=self.label,
            description=self.description,
            available=self.available,
            availability_note=self.availability_note,
            recommended=self.recommended,
            pricing_version=PRICING_VERSION,
            pricing=self.pricing,
            capabilities=self.capability,
        )


def _capability(
    *,
    minimum: float,
    maximum: float,
    durations: list[float],
    resolutions: list[str],
    duration_step: float = 1,
    default_duration: float | None = None,
    maximum_width: int = 1920,
    maximum_height: int = 1920,
    prompt_characters: int = 2000,
    seed: bool = True,
    ordered_multi_image: bool = False,
    maximum_reference_images: int = 1,
    managed_assets: bool = False,
    person_policy: PersonReferencePolicy = PersonReferencePolicy.RAW_SUPPORTED,
    supports_motion_proxy_video: bool = False,
    reference_route: VideoReferenceRouteCapability | None = None,
) -> VideoGenerationCapability:
    return VideoGenerationCapability(
        image_to_video=True,
        multi_image_reference=ordered_multi_image,
        ordered_reference_images=ordered_multi_image,
        minimum_reference_images=1,
        maximum_reference_images=maximum_reference_images,
        start_frame=True,
        end_frame=False,
        max_candidates=4,
        minimum_duration_seconds=minimum,
        maximum_duration_seconds=maximum,
        duration_step_seconds=duration_step,
        default_duration_seconds=(
            default_duration
            if default_duration is not None
            else (durations[0] if durations else minimum)
        ),
        supported_durations=durations,
        maximum_width=maximum_width,
        maximum_height=maximum_height,
        native_audio=False,
        supports_negative_prompt=True,
        supports_seed=seed,
        supports_camera_constraints=True,
        supported_resolutions=resolutions,
        supported_aspect_ratios=["16:9", "9:16", "1:1", "4:3", "3:4"],
        maximum_prompt_characters=prompt_characters,
        managed_assets=(
            ProviderManagedAssetCapability(
                supported=True,
                provider="volc_ark",
                catalog_browsing=True,
                asset_kinds=[
                    ManagedAssetKind.VIRTUAL_PERSON,
                    ManagedAssetKind.VERIFIED_PERSON,
                ],
                roles=[ManagedAssetRole.ACTOR_IDENTITY],
                maximum_bindings=1,
                reference_transport="asset_uri",
                requires_same_project=True,
            )
            if managed_assets
            else ProviderManagedAssetCapability()
        ),
        person_references=PersonReferenceCapability(
            policy=person_policy,
            allow_raw_photoreal_person=(
                person_policy
                in {
                    PersonReferencePolicy.RAW_SUPPORTED,
                    PersonReferencePolicy.MANAGED_OPTIONAL,
                }
            ),
            allow_provider_managed_identity=managed_assets,
            allow_asset_only_generation=(
                person_policy == PersonReferencePolicy.MANAGED_REQUIRED
            ),
            supports_pose_proxy_image=True,
            supports_motion_proxy_video=supports_motion_proxy_video,
            supported_roles=[
                VideoReferenceRole.ACTOR_IDENTITY,
                VideoReferenceRole.MOTION,
                VideoReferenceRole.COMPOSITION,
                VideoReferenceRole.SCENE,
                VideoReferenceRole.PRODUCT,
                VideoReferenceRole.WARDROBE,
                VideoReferenceRole.FIRST_FRAME,
                VideoReferenceRole.LAST_FRAME,
                VideoReferenceRole.TRANSITION,
            ],
        ),
        reference_route=(reference_route or VideoReferenceRouteCapability()),
    )


ORDERED_IMAGE_ROUTE = VideoReferenceRouteCapability(
    route_id=VideoReferenceRouteId.ORDERED_MULTI_IMAGE,
    label="原始画面多图参考",
    identity_transport=IdentityReferenceTransport.REFERENCE_IMAGE,
    accepts_raw_person_images=True,
)

SEEDANCE_MANAGED_ROUTE = VideoReferenceRouteCapability(
    route_id=VideoReferenceRouteId.SEEDANCE_MANAGED_ACTOR_MOTION_PROXY,
    label="托管演员 + 无身份动作视频",
    identity_transport=IdentityReferenceTransport.PROVIDER_MANAGED_ASSET,
    motion_transport=MotionReferenceTransport.REFERENCE_VIDEO,
    motion_semantics=MotionReferenceSemantics.GUIDED_REFERENCE,
    identity_required=True,
    accepts_raw_person_images=False,
    supports_pose_proxy_image=True,
    supports_motion_proxy_video=True,
    show_motion_proxy_controls=True,
    fallback_route_id=VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK,
    fallback_label="图片白模 + 文本动作描述",
)

MINIMAX_H3_ROUTE = VideoReferenceRouteCapability(
    route_id=VideoReferenceRouteId.MINIMAX_IDENTITY_IMAGE_MOTION_PROXY,
    label="人物参考图 + 动作视频",
    support_level=RouteSupportLevel.VERIFIED,
    identity_transport=IdentityReferenceTransport.REFERENCE_IMAGE,
    motion_transport=MotionReferenceTransport.REFERENCE_VIDEO,
    motion_semantics=MotionReferenceSemantics.GUIDED_REFERENCE,
    identity_required=True,
    accepts_raw_person_images=True,
    provider_verified=True,
    supports_pose_proxy_image=True,
    supports_motion_proxy_video=True,
    show_motion_proxy_controls=True,
    fallback_route_id=VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK,
    fallback_label="人物参考图 + 图片白模 + 文本动作描述",
    availability_note="MiniMax H3 全能参考入口支持图片与参考视频组合输入",
)

POSE_IMAGE_TEXT_ROUTE = VideoReferenceRouteCapability(
    route_id=VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK,
    label="人物参考图 + 文本动作描述",
    identity_transport=IdentityReferenceTransport.REFERENCE_IMAGE,
    motion_transport=MotionReferenceTransport.POSE_IMAGE_TEXT,
    motion_semantics=MotionReferenceSemantics.SUGGESTIVE,
    identity_required=True,
    accepts_raw_person_images=True,
    supports_pose_proxy_image=True,
    show_motion_proxy_controls=False,
)

WAN_VACE_ROUTE = VideoReferenceRouteCapability(
    route_id=VideoReferenceRouteId.WAN_VACE_POSEBODY_REPAINT,
    label="人物参考图 + PoseBody 控制视频",
    enabled=False,
    support_level=RouteSupportLevel.RESERVED,
    identity_transport=IdentityReferenceTransport.REFERENCE_IMAGE,
    motion_transport=MotionReferenceTransport.CONTROL_VIDEO,
    motion_semantics=MotionReferenceSemantics.STRUCTURAL_CONTROL,
    identity_required=True,
    accepts_raw_person_images=True,
    supports_pose_proxy_image=True,
    supports_motion_proxy_video=True,
    show_motion_proxy_controls=True,
    requires_public_media_url=True,
    availability_note="已完成 VACE 请求结构预留；启用前需配置 Provider 可访问的公网媒体暂存服务",
)


_MODELS = (
    VideoModelSpec(
        alias="bailian_wan_2_7_r2v",
        provider="bailian",
        model="wan2.7-r2v-2026-06-12",
        label="百炼 Wan 2.7 多图参考视频",
        description="按图1、图2等稳定顺序引用 1～5 张画面图，生成连续分镜视频。",
        capability=_capability(
            minimum=2,
            maximum=15,
            durations=[float(value) for value in range(2, 16)],
            resolutions=["720P", "1080P"],
            default_duration=5,
            prompt_characters=5000,
            ordered_multi_image=True,
            maximum_reference_images=5,
            reference_route=ORDERED_IMAGE_ROUTE,
        ),
        pricing={
            "kind": "per_second_by_resolution",
            "currency": "CNY",
            "rates_micros": {"720P": 600_000, "1080P": 1_000_000},
            "source": "阿里云百炼公开刊例价",
            "source_url": "https://help.aliyun.com/zh/model-studio/wan2-7-r2v",
        },
        recommended=True,
    ),
    VideoModelSpec(
        alias="bailian_wan_vace_posebody",
        provider="bailian",
        model="wanx2.1-vace-plus",
        label="阿里 Wan VACE · PoseBody",
        description="以目标人物参考图替换身份，以无身份动作视频作为 PoseBody 结构控制。",
        capability=_capability(
            minimum=1,
            maximum=5,
            durations=[1, 2, 3, 4, 5],
            resolutions=["720P"],
            default_duration=5,
            maximum_reference_images=2,
            supports_motion_proxy_video=True,
            reference_route=WAN_VACE_ROUTE,
        ),
        pricing={
            "kind": "unknown",
            "currency": "CNY",
            "source": "阿里云百炼 VACE 实际用量",
            "source_url": "https://help.aliyun.com/zh/model-studio/legacy-wanx-vace-api-reference",
        },
        available=False,
        availability_note=WAN_VACE_ROUTE.availability_note,
    ),
    VideoModelSpec(
        alias="seedance_2_0",
        provider="volc_ark",
        model="doubao-seedance-2-0-260128",
        label="Seedance 2.0",
        description="通过火山方舟全能参考 API 按图片1～图片9的顺序生成连续分镜视频。",
        capability=_capability(
            minimum=4,
            maximum=15,
            durations=[float(value) for value in range(4, 16)],
            resolutions=["480P", "720P", "1080P"],
            default_duration=5,
            ordered_multi_image=True,
            maximum_reference_images=9,
            managed_assets=True,
            person_policy=PersonReferencePolicy.MANAGED_REQUIRED,
            supports_motion_proxy_video=True,
            reference_route=SEEDANCE_MANAGED_ROUTE,
        ),
        pricing={
            "kind": "provider_usage_tokens",
            "currency": "CNY",
            "source": "火山方舟任务 usage",
        },
    ),
    VideoModelSpec(
        alias="seedance_2_0_fast",
        provider="volc_ark",
        model="doubao-seedance-2-0-fast-260128",
        label="Seedance 2.0 Fast",
        description="Seedance 2.0 快速版；通过火山方舟全能参考 API 接收最多 9 张有序参考图。",
        capability=_capability(
            minimum=4,
            maximum=15,
            durations=[float(value) for value in range(4, 16)],
            resolutions=["480P", "720P", "1080P"],
            default_duration=5,
            ordered_multi_image=True,
            maximum_reference_images=9,
            managed_assets=True,
            person_policy=PersonReferencePolicy.MANAGED_REQUIRED,
            supports_motion_proxy_video=True,
            reference_route=SEEDANCE_MANAGED_ROUTE,
        ),
        pricing={
            "kind": "provider_usage_tokens",
            "currency": "CNY",
            "source": "火山方舟任务 usage",
        },
    ),
    VideoModelSpec(
        alias="seedance_2_0_mini",
        provider="volc_ark",
        model="doubao-seedance-2-0-mini-260615",
        label="Seedance 2.0 Mini",
        description="Seedance 2.0 高性价比版本；支持音视图文参考，适合高频迭代和批量生成。",
        capability=_capability(
            minimum=4,
            maximum=15,
            durations=[float(value) for value in range(4, 16)],
            resolutions=["480P", "720P"],
            default_duration=5,
            ordered_multi_image=True,
            maximum_reference_images=9,
            managed_assets=True,
            person_policy=PersonReferencePolicy.MANAGED_REQUIRED,
            supports_motion_proxy_video=True,
            reference_route=SEEDANCE_MANAGED_ROUTE,
        ),
        pricing={
            "kind": "provider_usage_tokens",
            "currency": "CNY",
            "source": "火山方舟任务 usage",
            "source_url": "https://www.volcengine.com/activity/seedance2",
        },
    ),
    VideoModelSpec(
        alias="seedance_2_5",
        provider="volc_ark",
        model=None,
        label="Seedance 2.5（待工作流验收）",
        description="官方服务已开放；当前有序多图请求、Model ID 与参数边界尚未完成接入验收。",
        capability=_capability(
            minimum=2,
            maximum=15,
            durations=[],
            resolutions=["720P", "1080P"],
            default_duration=5,
        ),
        pricing={"kind": "unknown", "currency": "CNY"},
        available=False,
        availability_note="尚未完成 Model ID、有序多图参考和参数边界验收，不能用于当前流程",
    ),
    VideoModelSpec(
        alias="minimax_h3",
        provider="minimax",
        model="MiniMax-H3",
        label="MiniMax H3",
        description="通过 MiniMax H3 全能参考模式按图号接收最多 9 张有序参考图。",
        capability=_capability(
            minimum=4,
            maximum=15,
            durations=[float(value) for value in range(4, 16)],
            resolutions=["768P", "2K"],
            default_duration=5,
            maximum_width=2560,
            maximum_height=2560,
            prompt_characters=7000,
            seed=False,
            ordered_multi_image=True,
            maximum_reference_images=9,
            supports_motion_proxy_video=True,
            reference_route=MINIMAX_H3_ROUTE,
        ),
        pricing={
            "kind": "per_second_by_resolution",
            "currency": "CNY",
            "rates_micros": {"768P": 500_000, "2K": 800_000},
            "source": "MiniMax 开放平台公开刊例价",
            "source_url": "https://platform.minimaxi.com/docs/guides/pricing-paygo",
        },
    ),
    VideoModelSpec(
        alias="minimax_hailuo_2_3",
        provider="minimax",
        model="MiniMax-Hailuo-2.3",
        label="MiniMax Hailuo 2.3",
        description="MiniMax Hailuo 2.3 图生视频（历史型号，仍由官方 API 支持）。",
        capability=_capability(
            minimum=6,
            maximum=10,
            durations=[6, 10],
            resolutions=["768P", "1080P"],
            seed=False,
            reference_route=POSE_IMAGE_TEXT_ROUTE,
        ),
        pricing={
            "kind": "fixed_matrix",
            "currency": "CNY",
            "rates_micros": {
                "768P:6": 2_000_000,
                "768P:10": 4_000_000,
                "1080P:6": 3_500_000,
            },
            "source": "MiniMax 开放平台历史模型刊例价",
        },
        available=True,
        availability_note=None,
    ),
    VideoModelSpec(
        alias="minimax_hailuo_2_3_fast",
        provider="minimax",
        model="MiniMax-Hailuo-2.3-Fast",
        label="MiniMax Hailuo 2.3 Fast",
        description="MiniMax Hailuo 2.3 图生视频快速版。",
        capability=_capability(
            minimum=6,
            maximum=10,
            durations=[6, 10],
            resolutions=["768P", "1080P"],
            seed=False,
            reference_route=POSE_IMAGE_TEXT_ROUTE,
        ),
        pricing={
            "kind": "fixed_matrix",
            "currency": "CNY",
            "rates_micros": {
                "768P:6": 1_350_000,
                "768P:10": 2_250_000,
                "1080P:6": 2_310_000,
            },
            "source": "MiniMax 开放平台历史模型刊例价",
        },
        available=True,
        availability_note=None,
    ),
)

MODEL_BY_ALIAS = MappingProxyType({item.alias: item for item in _MODELS})


class VideoModelCatalog:
    catalog_version = CATALOG_VERSION
    pricing_version = PRICING_VERSION

    def option(self, alias: str, *, require_available: bool = True) -> VideoModelSpec:
        try:
            item = MODEL_BY_ALIAS[alias]
        except KeyError as exc:
            raise VideoModelCatalogError(f"未知的视频模型别名：{alias}") from exc
        if require_available and (not item.available or not item.model):
            raise VideoModelCatalogError(item.availability_note or "该视频模型暂不可调用")
        if require_available and not item.capability.reference_route.enabled:
            raise VideoModelCatalogError(
                item.capability.reference_route.availability_note
                or "该模型的参考素材路由尚未开放"
            )
        return item

    def options(self) -> list[VideoGenerationModelOption]:
        return [item.as_option() for item in _MODELS]


def load_video_model_catalog() -> VideoModelCatalog:
    return VideoModelCatalog()
