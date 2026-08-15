from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain import (
    ReferenceProxyKind,
    ReferenceProxyQualityStatus,
    VideoReferenceMediaType,
)


@dataclass(frozen=True, slots=True)
class ProxyEngineCapability:
    engine: str
    version: str
    kinds: tuple[ReferenceProxyKind, ...]
    available: bool
    availability_note: str = ""
    production_ready: bool = False
    wholebody: bool = False
    hand_keypoints: bool = False
    video_tracking: bool = False
    runtime_provider: str = ""


@dataclass(frozen=True, slots=True)
class ProxyGenerationOutput:
    path: Path
    thumbnail_path: Path
    media_type: VideoReferenceMediaType
    identity_removed: bool
    validation_message: str
    semantic_validation_status: ReferenceProxyQualityStatus = (
        ReferenceProxyQualityStatus.LEGACY_UNVERIFIED
    )
    quality_score: float | None = None
    quality_metrics: dict[str, float | int | str | bool] | None = None
    manifest_path: Path | None = None
    quality_report_path: Path | None = None
    model_sha256: str | None = None


class ReferenceProxyEngine(Protocol):
    capability: ProxyEngineCapability

    def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        kind: ReferenceProxyKind,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> ProxyGenerationOutput: ...
