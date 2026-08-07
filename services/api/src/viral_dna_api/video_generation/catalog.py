from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..models import VideoGenerationCapability, VideoGenerationModelOption

CATALOG_VERSION = "video-model-catalog-2026-08-07.2"
PRICING_VERSION = "video-pricing-cn-2026-08-07"


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
        return any(
            abs(duration_seconds - item) < 0.001
            for item in capability.supported_durations
        )
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
) -> VideoGenerationCapability:
    return VideoGenerationCapability(
        image_to_video=True,
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
    )


_MODELS = (
    VideoModelSpec(
        alias="bailian_wan_2_7_i2v",
        provider="bailian",
        model="wan2.7-i2v-2026-04-25",
        label="百炼 Wan 2.7 图生视频",
        description="百炼华北 2（北京）异步图生视频；支持 720P/1080P、2～15 秒。",
        capability=_capability(
            minimum=2,
            maximum=15,
            durations=[float(value) for value in range(2, 16)],
            resolutions=["720P", "1080P"],
            default_duration=5,
            prompt_characters=5000,
        ),
        pricing={
            "kind": "per_second_by_resolution",
            "currency": "CNY",
            "rates_micros": {"720P": 600_000, "1080P": 1_000_000},
            "source": "阿里云百炼公开刊例价",
        },
        recommended=True,
    ),
    VideoModelSpec(
        alias="seedance_2_0",
        provider="volc_ark",
        model="doubao-seedance-2-0-260128",
        label="Seedance 2.0",
        description="已保留体验模型别名；待火山方舟正式开放 API 后启用。",
        capability=_capability(
            minimum=2,
            maximum=12,
            durations=[float(value) for value in range(2, 13)],
            resolutions=["720P", "1080P"],
            default_duration=5,
        ),
        pricing={
            "kind": "provider_usage_tokens",
            "currency": "CNY",
            "source": "火山方舟任务 usage",
        },
        available=False,
        availability_note="火山方舟 Seedance 2.0 API 尚未 GA，目前只有体验入口",
    ),
    VideoModelSpec(
        alias="seedance_2_0_fast",
        provider="volc_ark",
        model="doubao-seedance-2-0-fast-260128",
        label="Seedance 2.0 Fast",
        description="已保留快速版稳定别名；待官方 Model ID 与 API 文档发布后启用。",
        capability=_capability(
            minimum=2,
            maximum=12,
            durations=[float(value) for value in range(2, 13)],
            resolutions=["720P", "1080P"],
            default_duration=5,
        ),
        pricing={
            "kind": "provider_usage_tokens",
            "currency": "CNY",
            "source": "火山方舟任务 usage",
        },
        available=False,
        availability_note="尚未核验到可公开调用的 Seedance 2.0 Fast API Model ID",
    ),
    VideoModelSpec(
        alias="seedance_2_5",
        provider="volc_ark",
        model=None,
        label="Seedance 2.5（待官方 API ID）",
        description="已保留稳定别名；取得官方 Model ID 与参数文档后无需改业务层即可启用。",
        capability=_capability(
            minimum=2,
            maximum=15,
            durations=[],
            resolutions=["720P", "1080P"],
            default_duration=5,
        ),
        pricing={"kind": "unknown", "currency": "CNY"},
        available=False,
        availability_note="尚未在火山方舟官方接口文档中核验到可调用的 2.5 Model ID",
    ),
    VideoModelSpec(
        alias="minimax_h3",
        provider="minimax",
        model="MiniMax-H3",
        label="MiniMax H3",
        description="MiniMax 当前 H3 视频模型；图片输入 5 张以内免费，输出按秒计费。",
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
        ),
        pricing={
            "kind": "per_second_by_resolution",
            "currency": "CNY",
            "rates_micros": {"768P": 500_000, "2K": 800_000},
            "source": "MiniMax 开放平台公开刊例价",
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
        return item

    def options(self) -> list[VideoGenerationModelOption]:
        return [item.as_option() for item in _MODELS]


def load_video_model_catalog() -> VideoModelCatalog:
    return VideoModelCatalog()
