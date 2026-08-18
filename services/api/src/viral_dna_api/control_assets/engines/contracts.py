from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..jobs.domain import (
    DepthControlPreset,
    DepthExecutionDevice,
    DepthExecutionPreference,
)


@dataclass(frozen=True, slots=True)
class DepthEngineCapability:
    engine: str
    version: str
    model_variant: str
    available: bool
    availability_note: str
    repository_url: str
    checkpoint_path: Path | None
    runtime_path: Path | None
    license: str


@dataclass(frozen=True, slots=True)
class DepthEngineOutput:
    path: Path
    thumbnail_path: Path
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int
    validation_message: str
    validation_metrics: dict[str, float | int | str | bool] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class DepthGenerationProfile:
    preset: DepthControlPreset
    device: DepthExecutionDevice
    device_name: str
    target_fps: int
    input_size: int
    max_resolution: int
    timeout_seconds: int
    runtime_version: str | None = None
    engine_id: str = ""
    selection_reason: str = ""
    requested_execution_preference: DepthExecutionPreference = (
        DepthExecutionPreference.AUTO
    )
    account_id: UUID | None = None


class DepthEngineAdapter(Protocol):
    engine_id: str

    def capability(self) -> DepthEngineCapability: ...

    def install(self, progress) -> DepthEngineCapability: ...

    async def profile(self, requested: DepthControlPreset) -> DepthGenerationProfile: ...

    async def generate(self, **kwargs) -> DepthEngineOutput: ...
