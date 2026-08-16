from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ...models import ProductionProject, ShotPlan
from ..domain import (
    ReferenceProxyEngineClass,
    ReferenceProxyKind,
    ReferenceProxyPrivacyMode,
    ReferenceProxyQualityStatus,
    ReferenceProxyRenderProfile,
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
    engine_class: ReferenceProxyEngineClass = (
        ReferenceProxyEngineClass.DETERMINISTIC_LOCAL
    )
    render_profiles: tuple[ReferenceProxyRenderProfile, ...] = (
        ReferenceProxyRenderProfile.STRUCTURAL,
    )
    privacy_modes: tuple[ReferenceProxyPrivacyMode, ...] = (
        ReferenceProxyPrivacyMode.LOCAL_ONLY,
    )
    provider: str | None = None
    model: str | None = None
    estimated_unit_cost_micros: int | None = None
    cost_estimate_known: bool = False


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
    requested_render_profile: ReferenceProxyRenderProfile = (
        ReferenceProxyRenderProfile.STRUCTURAL
    )
    effective_render_profile: ReferenceProxyRenderProfile = (
        ReferenceProxyRenderProfile.STRUCTURAL
    )
    privacy_mode: ReferenceProxyPrivacyMode = ReferenceProxyPrivacyMode.LOCAL_ONLY
    base_engine: str | None = None
    base_engine_version: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    raw_source_uploaded: bool = False
    fallback_applied: bool = False
    fallback_reason: str | None = None
    estimated_cost_micros: int | None = None
    actual_cost_micros: int | None = None
    cost_estimate_known: bool = False
    actual_cost_known: bool = False


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


@dataclass(frozen=True, slots=True)
class ProxyEnhancementRequest:
    request_id: UUID
    project: ProductionProject
    shot: ShotPlan
    kind: ReferenceProxyKind
    base_output: ProxyGenerationOutput
    destination_path: Path
    thumbnail_path: Path
    run_root: Path
    duration_seconds: float | None
    privacy_mode: ReferenceProxyPrivacyMode
    allow_unknown_cost: bool = False


class ProxyEnhancementError(RuntimeError):
    """Enhancement failure with any provider usage already incurred."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        provider_model: str | None = None,
        provider_request_id: str | None = None,
        estimated_cost_micros: int | None = None,
        actual_cost_micros: int | None = None,
        cost_estimate_known: bool = False,
        actual_cost_known: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.provider_model = provider_model
        self.provider_request_id = provider_request_id
        self.estimated_cost_micros = estimated_cost_micros
        self.actual_cost_micros = actual_cost_micros
        self.cost_estimate_known = cost_estimate_known
        self.actual_cost_known = actual_cost_known


class ReferenceProxyEnhancer(Protocol):
    capability: ProxyEngineCapability

    async def enhance(self, request: ProxyEnhancementRequest) -> ProxyGenerationOutput: ...
