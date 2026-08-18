from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .domain import DepthControlJobStage

STAGE_RANGES: dict[DepthControlJobStage, tuple[int, int]] = {
    DepthControlJobStage.QUEUED: (0, 0),
    DepthControlJobStage.VALIDATING_INPUT: (0, 3),
    DepthControlJobStage.PROBING_MEDIA: (3, 6),
    DepthControlJobStage.CLIPPING_SOURCE: (6, 10),
    DepthControlJobStage.LOADING_MODEL: (10, 15),
    DepthControlJobStage.INFERRING_DEPTH: (15, 82),
    DepthControlJobStage.WRITING_DEPTH: (82, 90),
    DepthControlJobStage.ENCODING_VIDEO: (90, 95),
    DepthControlJobStage.VALIDATING_OUTPUT: (95, 98),
    DepthControlJobStage.PERSISTING_ASSET: (98, 99),
    DepthControlJobStage.COMPLETED: (100, 100),
}


@dataclass(frozen=True, slots=True)
class DepthProgressEvent:
    stage: DepthControlJobStage
    ratio: float
    message: str
    processed_frames: int | None = None
    total_frames: int | None = None
    process_id: int | None = None

    @property
    def percent(self) -> int:
        start, end = STAGE_RANGES[self.stage]
        ratio = max(0.0, min(1.0, self.ratio))
        return min(100, max(0, round(start + (end - start) * ratio)))


def estimate_remaining_seconds(
    *,
    started_at: datetime | None,
    processed_frames: int | None,
    total_frames: int | None,
) -> int | None:
    if started_at is None or not processed_frames or not total_frames:
        return None
    if processed_frames < 2 or processed_frames >= total_frames:
        return 0 if processed_frames >= total_frames else None
    elapsed = max(0.001, (datetime.now(UTC) - started_at).total_seconds())
    per_frame = elapsed / processed_frames
    return max(0, round((total_frames - processed_frames) * per_frame))
