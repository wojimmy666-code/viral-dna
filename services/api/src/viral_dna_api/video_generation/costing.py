from __future__ import annotations

from dataclasses import dataclass

from .catalog import PRICING_VERSION, VideoModelSpec


@dataclass(frozen=True, slots=True)
class VideoCostEstimate:
    known: bool
    micros: int | None
    pricing_version: str
    explanation: str


def estimate_video_cost(
    spec: VideoModelSpec,
    *,
    duration_seconds: float,
    resolution: str,
    candidate_count: int,
) -> VideoCostEstimate:
    pricing = spec.pricing
    kind = pricing.get("kind")
    rates = pricing.get("rates_micros") or {}
    if kind == "per_second_by_resolution" and resolution in rates:
        micros = round(float(rates[resolution]) * duration_seconds * candidate_count)
        return VideoCostEstimate(
            True,
            max(0, micros),
            PRICING_VERSION,
            f"{resolution} 按秒计费 × {duration_seconds:g} 秒 × {candidate_count} 个候选",
        )
    if kind == "fixed_matrix":
        duration_key = f"{duration_seconds:g}"
        key = f"{resolution}:{duration_key}"
        if key in rates:
            return VideoCostEstimate(
                True,
                int(rates[key]) * candidate_count,
                PRICING_VERSION,
                f"{resolution} / {duration_seconds:g} 秒固定单价 × {candidate_count} 个候选",
            )
    return VideoCostEstimate(
        False,
        None,
        PRICING_VERSION,
        "该模型需要根据 Provider 返回的实际 usage 结算，提交前无法给出可靠金额",
    )
