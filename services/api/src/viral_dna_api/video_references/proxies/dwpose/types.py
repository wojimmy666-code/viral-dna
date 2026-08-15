from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PoseObservation:
    """A single whole-body pose in source-image pixel coordinates."""

    keypoints: Any
    scores: Any
    bbox: tuple[float, float, float, float]
    detection_score: float


@dataclass(slots=True)
class PoseQualityReport:
    status: str
    score: float
    metrics: dict[str, float | int | str | bool]
    message: str
