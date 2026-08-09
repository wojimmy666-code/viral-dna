from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from ..models import (
    GenerationCostSource,
    ImageExecutionMode,
    ProductionProject,
    ShotPlan,
    VideoGenerationCapability,
    VideoProviderTaskStatus,
)

VIDEO_REQUEST_SCHEMA_VERSION = "viral-dna-video-generation/v1"
VIDEO_PROMPT_VERSION = "shot-video-v1"
VIDEO_ADAPTER_PROTOCOL_VERSION = "viral-dna-video-adapter/v1"
MAX_GENERATED_VIDEO_BYTES = 500 * 1024 * 1024


class VideoGenerationError(RuntimeError):
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
class VideoGenerationRequest:
    project: ProductionProject
    shot: ShotPlan
    revision_id: UUID
    approved_image_candidate_id: UUID
    approved_image_path: Path
    approved_image_relative_path: str
    approved_image_sha256: str
    candidate_count: int
    duration_seconds: float
    execution_mode: ImageExecutionMode
    model_alias: str | None = None
    resolution: str | None = None
    allow_unknown_cost: bool = False
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class VideoAdapterRequest:
    request_id: UUID
    run_root: Path
    project: ProductionProject
    shot: ShotPlan
    approved_image_path: Path
    approved_image_sha256: str
    candidate_count: int
    duration_seconds: float
    width: int
    height: int
    positive_prompt: str
    negative_prompt: str
    seed: int | None
    capability: VideoGenerationCapability
    cancel_event: Event | None = None


@dataclass(frozen=True, slots=True)
class GeneratedVideo:
    path: Path
    media_type: str = "video/mp4"
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VideoAdapterResult:
    videos: tuple[GeneratedVideo, ...]
    provider_request_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    actual_cost_micros: int | None = None
    cost_source: GenerationCostSource | None = None


@dataclass(frozen=True, slots=True)
class VideoAdapterIdentity:
    execution_mode: ImageExecutionMode
    provider: str
    model: str
    model_snapshot: str
    adapter_id: str
    adapter_version: str
    protocol_version: str
    capability: VideoGenerationCapability
    estimated_cost_micros: int
    cost_estimate_known: bool
    cost_source: GenerationCostSource
    pricing_version: str
    execution_summary: dict[str, Any] = field(default_factory=dict)
    model_alias: str | None = None
    model_display_name: str | None = None
    pricing_snapshot: dict[str, Any] = field(default_factory=dict)


class VideoGenerationAdapter(Protocol):
    """Provider-neutral seam used by simulated and future remote adapters.

    Batch 4.5.1 ships only the simulated adapter. Batch 4.5.2 may register a
    domestic remote API adapter. A future local adapter can implement this
    protocol without changing the production-domain service, but local tool
    discovery and execution are intentionally not part of the current API.
    """

    identity: VideoAdapterIdentity

    async def generate(self, request: VideoAdapterRequest) -> VideoAdapterResult: ...


@dataclass(frozen=True, slots=True)
class ProviderCredentialValidation:
    valid: bool
    message: str
    latency_ms: int | None = None
    balance_known: bool = False
    balance_micros: int | None = None
    currency: str = "CNY"
    error_code: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class ProviderVideoRequest:
    request_id: UUID
    ordinal: int
    model_alias: str
    provider_model: str
    prompt: str
    negative_prompt: str
    first_frame_path: Path
    duration_seconds: float
    resolution: str
    aspect_ratio: str
    width: int
    height: int
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderSubmitResult:
    task_id: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderPollResult:
    status: VideoProviderTaskStatus
    raw: dict[str, Any] = field(default_factory=dict)
    output_url: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    actual_cost_micros: int | None = None
    cost_known: bool = False
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False


class VideoProviderAdapter(Protocol):
    provider_id: str
    adapter_version: str

    async def validate_credentials(
        self,
        api_key: str,
        base_url: str,
    ) -> ProviderCredentialValidation: ...

    async def submit(
        self,
        request: ProviderVideoRequest,
        *,
        api_key: str,
        base_url: str,
    ) -> ProviderSubmitResult: ...

    async def poll(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> ProviderPollResult: ...

    async def cancel(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ) -> bool: ...
