from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from ..models import (
    GenerationCostSource,
    ImageExecutionMode,
    ImageGenerationCapability,
    ImageGenerationInputMode,
    ImageGenerationModelOption,
    ProductionProject,
    ReferenceAsset,
    ReferenceBinding,
    ShotPlan,
)

IMAGE_REQUEST_SCHEMA_VERSION = "viral-dna-image-generation/v1"
LOCAL_TOOL_PROTOCOL_VERSION = "viral-dna-image-tool/v1"
IMAGE_PROMPT_VERSION = "shot-image-v2"
MAX_GENERATED_IMAGE_BYTES = 25 * 1024 * 1024


class ImageGenerationError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ImageReferenceInput:
    asset_id: UUID
    name: str
    role: str
    path: Path
    relative_path: str
    sha256: str
    weight: float
    crop_hint: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    project: ProductionProject
    shot: ShotPlan
    revision_id: UUID
    input_mode: ImageGenerationInputMode
    source_path: Path | None
    source_sha256: str | None
    references: tuple[ImageReferenceInput, ...]
    candidate_count: int
    execution_mode: ImageExecutionMode
    allow_unknown_cost: bool = False
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    request_id: UUID
    run_root: Path
    project: ProductionProject
    shot: ShotPlan
    input_mode: ImageGenerationInputMode
    source_path: Path | None
    source_sha256: str | None
    references: tuple[ImageReferenceInput, ...]
    candidate_count: int
    width: int
    height: int
    positive_prompt: str
    negative_prompt: str
    seed: int | None
    capability: ImageGenerationCapability
    cancel_event: Event | None = None


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    payload: bytes
    media_type: str
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    images: tuple[GeneratedImage, ...]
    provider_request_id: str | None = None
    tool_id: str | None = None
    tool_version: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    actual_cost_micros: int | None = None
    cost_source: GenerationCostSource | None = None
    output_manifest_path: Path | None = None


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    execution_mode: ImageExecutionMode
    provider: str
    model: str
    model_snapshot: str
    adapter_id: str
    adapter_version: str
    protocol_version: str | None
    capability: ImageGenerationCapability
    model_option: ImageGenerationModelOption | None
    estimated_cost_micros: int
    cost_estimate_known: bool
    cost_source: GenerationCostSource
    execution_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolDetection:
    tool_id: str
    tool_version: str
    protocol_version: str
    capability: ImageGenerationCapability
    latency_ms: int


class ImageAdapter(Protocol):
    identity: AdapterIdentity

    async def generate(self, request: AdapterRequest) -> AdapterResult: ...


def build_reference_inputs(
    bindings: list[ReferenceBinding],
    assets: list[ReferenceAsset],
    *,
    resolve_path: Any,
) -> tuple[ImageReferenceInput, ...]:
    assets_by_id = {asset.id: asset for asset in assets}
    references: list[ImageReferenceInput] = []
    for binding in sorted(bindings, key=lambda item: (-item.weight, item.created_at)):
        asset = assets_by_id.get(binding.reference_asset_id)
        if asset is None:
            continue
        references.append(
            ImageReferenceInput(
                asset_id=asset.id,
                name=asset.name,
                role=binding.role.value,
                path=resolve_path(asset.relative_path),
                relative_path=asset.relative_path,
                sha256=asset.sha256,
                weight=binding.weight,
                crop_hint=binding.crop_hint,
                notes=binding.notes,
            )
        )
    return tuple(references)
