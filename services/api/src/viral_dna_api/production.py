from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Protocol
from urllib.parse import unquote
from uuid import UUID, uuid4

from PIL import Image, ImageOps
from pydantic import ValidationError

from .candidate_lifecycle import (
    archive_candidate_records,
    is_user_deleted_candidate,
    restore_candidate_records,
)
from .chinese import to_simplified
from .control_assets.domain import DepthControlAsset
from .control_assets.jobs.contracts import DepthControlJobContext
from .control_assets.jobs.domain import DepthControlJob
from .control_assets.models import (
    DepthControlCreate,
    DepthControlCreateResponse,
    DepthControlDeleteResponse,
    DepthControlUpdate,
    DepthControlUpdateResponse,
)
from .control_assets.service import DepthControlService, DepthControlServiceError
from .image_generation import ImageGenerationGateway, ImageGenerationGatewayError
from .image_generation.identity_policy import (
    IdentityPolicyViolation,
    validate_identity_bindings,
    validate_identity_generation,
)
from .managed_assets.service import ManagedAssetCatalogService, ManagedAssetServiceError
from .media import MediaProcessingError, MediaProcessor
from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
    ApprovalDecision,
    ApprovalEvent,
    CandidateActionResponse,
    CandidateApprovalRequest,
    CandidateBatchLifecycleRequest,
    CandidateBatchLifecycleResponse,
    CandidateSelectRequest,
    ChangeImpactRequest,
    ChangeImpactResponse,
    EditingHandoffClip,
    EditingHandoffManifest,
    GenerationCandidate,
    GenerationCandidateResponse,
    GenerationCandidateStatus,
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    GenerationRunResponse,
    ImageExecutionMode,
    ImageGenerationCreate,
    ImageGenerationInputMode,
    ProductionAdvanceRequest,
    ProductionAnalysisUpdatePreview,
    ProductionBranchCreate,
    ProductionChangeKind,
    ProductionGateStatus,
    ProductionProject,
    ProductionProjectCreate,
    ProductionProjectDetail,
    ProductionProjectStatus,
    ProductionProjectUpdate,
    ProductionPromptFieldDiff,
    ProductionPromptSyncChoice,
    ProductionPromptSyncRequest,
    ProductionRevision,
    ProductionRevisionDetail,
    ProductionRevisionResponse,
    ProductionRunStatus,
    ProductionShotPromptDiff,
    ProductionStep,
    PromptAssetMention,
    ReferenceAsset,
    ReferenceAssetCreate,
    ReferenceAssetResponse,
    ReferenceAssetType,
    ReferenceAssetUpdate,
    ReferenceBinding,
    ReferenceBindingInput,
    ReferenceRole,
    SceneBoundaryCandidate,
    Shot,
    ShotEvidence,
    ShotImageApprovalRevokeRequest,
    ShotKeyframeSelectRequest,
    ShotLifecycleStatus,
    ShotLifecycleUpdate,
    ShotMediaPreview,
    ShotPlan,
    ShotPlanBulkUpdate,
    ShotPlanCreate,
    ShotPlanDetailResponse,
    ShotPlanFieldsUpdate,
    ShotPlanReorder,
    ShotPlanResponse,
    ShotPlanUpdate,
    ShotSourceFrameApprovalRequest,
    ShotSourceKind,
    ShotVideoApprovalRevokeRequest,
    ShotVisualBeat,
    ShotVisualBeatCreate,
    ShotVisualBeatDelete,
    ShotVisualBeatReorder,
    ShotVisualBeatUpdate,
    Video,
    VideoClipAudioMode,
    VideoClipPreparation,
    VideoClipPreparationResponse,
    VideoClipPreparationStatus,
    VideoClipPreparationUpdate,
    VideoGenerationCreate,
    VideoGenerationInputSource,
    VideoPromptMention,
    VideoPromptReferenceKind,
    VideoProviderTask,
    VideoProviderTaskResponse,
    VideoProviderTaskStatus,
    VideoQualityStatus,
    WorkflowItemStatus,
)
from .notifications import NotificationPublisher
from .production_media import (
    ProductionVideoInspectionError,
    ProductionVideoInspector,
    VideoInspectionResult,
    map_timed_text,
    playback_alignment,
)
from .quality.continuity_service import ContinuityService, ContinuityServiceError
from .quality.contracts import ContinuityReportStatus
from .storage_errors import IncompatibleShotPlanSchemaError
from .video_generation import (
    OrderedReferenceFrame,
    VideoGenerationGateway,
    VideoGenerationGatewayError,
)
from .video_generation.errors import classify_video_provider_failure
from .workspace import WorkspaceError, WorkspaceManager

MAX_REFERENCE_IMAGE_BYTES = 15 * 1024 * 1024
MAX_REFERENCE_IMAGE_DIMENSION = 16_384
MAX_REFERENCE_IMAGE_PIXELS = 64_000_000
MAX_REFERENCE_ASSETS_PER_PROJECT = 50
REFERENCE_THUMBNAIL_SIZE = 480
PRODUCTION_SNAPSHOT_SCHEMA = "production-revision-v4"
SUPPORTED_PRODUCTION_SNAPSHOT_SCHEMAS = {
    "production-revision-v1",
    "production-revision-v2",
    "production-revision-v3",
    PRODUCTION_SNAPSHOT_SCHEMA,
}

_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}

_DEFAULT_ROLE_BY_REFERENCE_TYPE = {
    ReferenceAssetType.PERSON: ReferenceRole.IDENTITY,
    ReferenceAssetType.PRODUCT: ReferenceRole.PRODUCT,
    ReferenceAssetType.WARDROBE: ReferenceRole.WARDROBE,
    ReferenceAssetType.SCENE: ReferenceRole.SCENE,
    ReferenceAssetType.STYLE: ReferenceRole.STYLE,
    ReferenceAssetType.PROP: ReferenceRole.LAYOUT,
}

_DURATION_ALIGNMENT_WARNING_PREFIX = "裁剪后时长与原分镜差异过大"
_OPTIONAL_PREPARATION_STEPS = {
    ProductionStep.PROJECT_SETUP,
    ProductionStep.REFERENCE_ASSETS,
}


def _normalize_optional_preparation_step(step: ProductionStep) -> ProductionStep:
    """Project setup and references are editable views, not workflow gates."""
    if step in _OPTIONAL_PREPARATION_STEPS:
        return ProductionStep.SHOT_IMAGES
    return step


def _normalize_optional_preparation_project(
    project: ProductionProject,
) -> ProductionProject:
    normalized_step = _normalize_optional_preparation_step(project.active_step)
    if normalized_step == project.active_step:
        return project
    return project.model_copy(update={"active_step": normalized_step})


def _step_after_reference_change(
    project: ProductionProject,
    *,
    affects_bound_shots: bool = False,
) -> ProductionStep:
    if affects_bound_shots:
        return ProductionStep.SHOT_IMAGES
    return _normalize_optional_preparation_step(project.active_step)


def _duration_alignment_warning(playback_rate: float) -> str:
    return f"裁剪后时长与原分镜差异过大，将以 {playback_rate:.3f}× 对齐时间线；请在剪辑阶段复核节奏"


def _apply_video_preparation_policy(
    preparation: VideoClipPreparation,
) -> VideoClipPreparation:
    """Treat unsafe retiming as an editorial warning, including legacy records."""
    if preparation.duration_alignment != "outside_safe_range":
        return preparation
    blockers = [
        message
        for message in preparation.blocker_messages
        if not message.startswith(_DURATION_ALIGNMENT_WARNING_PREFIX)
    ]
    warnings = list(preparation.warning_messages)
    duration_warning = _duration_alignment_warning(preparation.video_playback_rate)
    if duration_warning not in warnings:
        warnings.append(duration_warning)
    status = preparation.status
    if status == VideoClipPreparationStatus.BLOCKED and not blockers:
        status = VideoClipPreparationStatus.READY
    if (
        blockers == preparation.blocker_messages
        and warnings == preparation.warning_messages
        and status == preparation.status
    ):
        return preparation
    return preparation.model_copy(
        update={
            "blocker_messages": blockers,
            "warning_messages": warnings,
            "status": status,
        }
    )


def _is_simulated_image_run(run: GenerationRun) -> bool:
    return run.kind == GenerationKind.IMAGE and (
        run.execution_mode == ImageExecutionMode.SIMULATED
        or run.provider.strip().casefold() == "simulated"
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def _filesystem_path(path: Path) -> Path:
    """Use Windows extended-length paths without persisting the OS-specific prefix."""
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    extended_prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(extended_prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{extended_prefix}UNC{separator}{raw[2:]}")
    return Path(f"{extended_prefix}{raw}")


def _resolve_workspace_source_path(raw_path: str, workspace_root: Path) -> Path:
    resolved = Path(raw_path).expanduser().resolve()
    resolved.relative_to(workspace_root)
    return resolved


class ProductionRepository(Protocol):
    async def get_record(self, record_id: UUID) -> AnalysisRecord | None: ...

    async def get_video(self, video_id: UUID) -> Video | None: ...

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None: ...

    async def get_report_by_analysis(
        self,
        analysis_id: UUID,
    ) -> AnalysisReport | None: ...

    async def save_production_bundle(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        *,
        reference_assets: list[ReferenceAsset] | None = None,
        shot_plans: list[ShotPlan] | None = None,
        reference_bindings: list[ReferenceBinding] | None = None,
        remove_reference_binding_ids: list[UUID] | None = None,
        generation_runs: list[GenerationRun] | None = None,
        generation_candidates: list[GenerationCandidate] | None = None,
        video_clip_preparations: list[VideoClipPreparation] | None = None,
        approval_events: list[ApprovalEvent] | None = None,
    ) -> tuple[ProductionProject, ProductionRevision]: ...

    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]: ...

    async def get_production_revision(
        self,
        revision_id: UUID,
    ) -> ProductionRevision | None: ...

    async def list_production_revisions(
        self,
        project_id: UUID,
    ) -> list[ProductionRevision]: ...

    async def get_reference_asset(self, asset_id: UUID) -> ReferenceAsset | None: ...

    async def list_reference_assets(self, project_id: UUID) -> list[ReferenceAsset]: ...

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]: ...

    async def reset_production_shot_workflow(self, project_id: UUID) -> None: ...

    async def list_reference_bindings(
        self,
        shot_plan_id: UUID,
    ) -> list[ReferenceBinding]: ...

    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None: ...

    async def save_generation_run(self, run: GenerationRun) -> GenerationRun: ...

    async def claim_generation_run(
        self,
        run_id: UUID,
        claimed_at: datetime,
    ) -> GenerationRun | None: ...

    async def get_generation_run(self, run_id: UUID) -> GenerationRun | None: ...

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]: ...

    async def get_generation_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate | None: ...

    async def list_generation_candidates(
        self,
        generation_run_id: UUID,
    ) -> list[GenerationCandidate]: ...

    async def list_generation_candidates_by_run_ids(
        self,
        generation_run_ids: set[UUID],
    ) -> list[GenerationCandidate]: ...

    async def save_video_clip_preparation(
        self,
        preparation: VideoClipPreparation,
    ) -> VideoClipPreparation: ...

    async def get_video_clip_preparation(
        self,
        shot_plan_id: UUID,
    ) -> VideoClipPreparation | None: ...

    async def list_video_clip_preparations(
        self,
        project_id: UUID,
    ) -> list[VideoClipPreparation]: ...

    async def save_video_provider_task(
        self,
        task: VideoProviderTask,
    ) -> VideoProviderTask: ...

    async def get_video_provider_task(
        self,
        task_id: UUID,
    ) -> VideoProviderTask | None: ...

    async def list_video_provider_tasks(
        self,
        generation_run_id: UUID,
    ) -> list[VideoProviderTask]: ...

    async def list_approval_events(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[ApprovalEvent]: ...


class ProjectAssetBridge(Protocol):
    async def create_reference(
        self,
        project: ProductionProject,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> ReferenceAsset: ...

    async def link_asset(
        self,
        project: ProductionProject,
        asset_id: UUID,
        reference_type: ReferenceAssetType | None = None,
    ) -> ReferenceAsset: ...

    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]: ...

    async def get_reference(
        self,
        asset_id: UUID,
        project_id: UUID | None = None,
        *,
        include_archived: bool = True,
    ) -> ReferenceAsset | None: ...

    async def update_reference(
        self,
        project_id: UUID,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
    ) -> ReferenceAsset: ...

    async def unlink_reference(self, project_id: UUID, asset_id: UUID) -> ReferenceAsset: ...

    async def resolve_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool,
    ) -> tuple[Path, str]: ...

    async def snapshot_reference(
        self,
        project_id: UUID,
        reference: ReferenceAsset,
    ) -> dict[str, object]: ...

    async def link_snapshot_reference(
        self,
        project: ProductionProject,
        payload: dict[str, object],
    ) -> ReferenceAsset: ...


class VideoInspector(Protocol):
    async def inspect(
        self,
        source_path: Path,
        cover_path: Path,
        *,
        cover_timestamp_seconds: float,
        expected_width: int | None,
        expected_height: int | None,
        expected_duration_seconds: float | None,
    ) -> VideoInspectionResult: ...


class ProductionServiceError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        provider_code: str | None = None,
        error_category: str | None = None,
        user_title: str | None = None,
        suggested_action: str | None = None,
        technical_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.provider_code = provider_code
        self.error_category = error_category
        self.user_title = user_title
        self.suggested_action = suggested_action
        self.technical_message = technical_message


@dataclass(frozen=True, slots=True)
class ReferenceImageInfo:
    extension: str
    mime_type: str
    width: int
    height: int
    sha256: str
    thumbnail: bytes


@dataclass(frozen=True, slots=True)
class VisualBeatFrameSpec:
    """A source-frame URL/time pair plus the timestamp to materialize locally."""

    source_url: str | None
    source_timestamp_seconds: float | None
    target_timestamp_seconds: float
    role: str


def _fail(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    provider_code: str | None = None,
    error_category: str | None = None,
    user_title: str | None = None,
    suggested_action: str | None = None,
    technical_message: str | None = None,
) -> ProductionServiceError:
    return ProductionServiceError(
        status_code,
        code,
        message,
        retryable=retryable,
        provider_code=provider_code,
        error_category=error_category,
        user_title=user_title,
        suggested_action=suggested_action,
        technical_message=technical_message,
    )


def _video_gateway_failure(exc: VideoGenerationGatewayError) -> ProductionServiceError:
    return _fail(
        exc.status_code,
        exc.code,
        str(exc),
        retryable=exc.retryable,
        provider_code=exc.provider_code,
        error_category=exc.error_category,
        user_title=exc.user_title,
        suggested_action=exc.suggested_action,
        technical_message=exc.technical_message,
    )


def _visual_beat(plan: ShotPlan, visual_beat_id: UUID | None) -> ShotVisualBeat:
    beats = sorted(plan.visual_beats, key=lambda item: item.index)
    if not beats:
        raise _fail(409, "visual_beat_required", "当前分镜至少需要保留一个画面")
    if visual_beat_id is None:
        return beats[0]
    for beat in beats:
        if beat.id == visual_beat_id:
            return beat
    raise _fail(404, "visual_beat_not_found", "指定的分镜画面不存在")


def _visual_beat_image_status(beats: list[ShotVisualBeat]) -> WorkflowItemStatus:
    targets = [item for item in beats if item.required] or list(beats)
    if targets and all(
        item.image_status == WorkflowItemStatus.APPROVED
        and item.approved_image_candidate_id is not None
        for item in targets
    ):
        return WorkflowItemStatus.APPROVED
    for status in (
        WorkflowItemStatus.STALE,
        WorkflowItemStatus.GENERATING,
        WorkflowItemStatus.REVIEW_REQUIRED,
        WorkflowItemStatus.FAILED,
        WorkflowItemStatus.READY,
    ):
        if any(item.image_status == status for item in targets):
            return status
    return WorkflowItemStatus.DRAFT


def _sync_shot_visual_beats(
    plan: ShotPlan,
    beats: list[ShotVisualBeat],
    *,
    revision_id: UUID,
    invalidate_video: bool = False,
) -> ShotPlan:
    ordered = sorted(beats, key=lambda item: item.index)
    primary = ordered[0]
    video_status = plan.video_status
    if invalidate_video and video_status in {
        WorkflowItemStatus.GENERATING,
        WorkflowItemStatus.REVIEW_REQUIRED,
        WorkflowItemStatus.APPROVED,
        WorkflowItemStatus.STALE,
    }:
        video_status = WorkflowItemStatus.STALE
    return plan.model_copy(
        update={
            "revision_id": revision_id,
            "visual_beats": ordered,
            "source_keyframe_url": primary.source_frame_url,
            "source_keyframe_relative_path": primary.source_frame_relative_path,
            "source_keyframe_timestamp_seconds": primary.source_timestamp_seconds,
            "source_keyframe_origin": (
                "analysis" if primary.source_origin == "legacy" else primary.source_origin
            ),
            "image_prompt": primary.image_prompt,
            "image_prompt_mentions": primary.image_prompt_mentions,
            "image_negative_constraints": primary.image_negative_constraints,
            "approved_image_candidate_id": primary.approved_image_candidate_id,
            "image_status": _visual_beat_image_status(ordered),
            "video_status": video_status,
            "updated_at": utc_now(),
        }
    )


def _run_matches_visual_beat(
    run: GenerationRun,
    plan: ShotPlan,
    visual_beat_id: UUID,
) -> bool:
    """Treat pre-v4 image runs as outputs of the migrated first visual beat."""
    if run.visual_beat_id is not None:
        return run.visual_beat_id == visual_beat_id
    return bool(plan.visual_beats and plan.visual_beats[0].id == visual_beat_id)


def _shot_for_visual_beat(plan: ShotPlan, beat: ShotVisualBeat) -> ShotPlan:
    """Build the legacy image-gateway view for one beat."""
    return plan.model_copy(
        update={
            "source_keyframe_url": beat.source_frame_url,
            "source_keyframe_relative_path": beat.source_frame_relative_path,
            "source_keyframe_timestamp_seconds": beat.source_timestamp_seconds,
            "source_keyframe_origin": (
                "analysis" if beat.source_origin == "legacy" else beat.source_origin
            ),
            "image_prompt": beat.image_prompt,
            "image_prompt_mentions": beat.image_prompt_mentions,
            "image_negative_constraints": beat.image_negative_constraints,
            "required": beat.required,
            "image_status": beat.image_status,
            "approved_image_candidate_id": beat.approved_image_candidate_id,
        }
    )


def _retime_visual_beats(beats: list[ShotVisualBeat]) -> list[ShotVisualBeat]:
    """Preserve relative weights while producing a contiguous 0..1 timeline."""
    if not beats:
        return []
    weights = [max(0.01, item.end_ratio - item.start_ratio) for item in beats]
    total = sum(weights)
    cursor = 0.0
    normalized: list[ShotVisualBeat] = []
    for index, (beat, weight) in enumerate(zip(beats, weights, strict=True), start=1):
        end = 1.0 if index == len(beats) else cursor + weight / total
        normalized.append(
            beat.model_copy(
                update={
                    "index": index,
                    "start_ratio": round(cursor, 6),
                    "end_ratio": round(end, 6),
                    "updated_at": utc_now(),
                }
            )
        )
        cursor = end
    return normalized


_VISUAL_PART_MARKER = re.compile(
    r"(?P<title>(?:第[一二三四五六七八九十0-9]+部分|(?:画面|场景)[一二三四五六七八九十0-9]+))\s*[：:]"
)


def _split_visual_beat_prompts(prompt: str) -> list[tuple[str, str]]:
    """Split common VLM 'first part / second part' output into visual nodes."""
    text = prompt.strip()
    matches = list(_VISUAL_PART_MARKER.finditer(text))
    if len(matches) < 2:
        return [("画面 1", text)]
    parts: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip(" ；;。\n\t")
        if body:
            parts.append((match.group("title"), body))
    return parts if len(parts) >= 2 else [("画面 1", text)]


def _visual_frame_role(url: str) -> str:
    stem = Path(unquote(url.split("?", 1)[0])).stem.lower()
    if stem.endswith("_start"):
        return "start"
    if stem.endswith("_end"):
        return "end"
    return "middle"


def _boundary_content_window(candidate: SceneBoundaryCandidate) -> tuple[float, float]:
    """Return transition start and the first stable frame of the new scene."""

    if candidate.hard_boundary:
        timestamp = round(float(candidate.timestamp_seconds), 3)
        return timestamp, timestamp
    evidence = sorted(float(item) for item in candidate.evidence_timestamps)
    transition_start = candidate.transition_start_seconds
    stable_new_scene = candidate.stable_new_scene_seconds
    if transition_start is None:
        transition_start = evidence[1] if len(evidence) >= 4 else candidate.timestamp_seconds
    if stable_new_scene is None:
        stable_new_scene = evidence[-1] if evidence else candidate.timestamp_seconds
    return (
        round(float(transition_start), 3),
        round(max(float(transition_start), float(stable_new_scene)), 3),
    )


def _report_shot_content_bounds(
    report: AnalysisReport,
    shot: Shot,
    media_shot: ShotEvidence | None = None,
) -> tuple[float, float]:
    """Recover a clean fact-analysis interval, including for legacy reports."""

    start = float(shot.start_seconds)
    end = float(shot.end_seconds)
    if shot.content_start_seconds is not None:
        start = float(shot.content_start_seconds)
    elif media_shot is not None and media_shot.content_start_seconds is not None:
        start = float(media_shot.content_start_seconds)
    if shot.content_end_seconds is not None:
        end = float(shot.content_end_seconds)
    elif media_shot is not None and media_shot.content_end_seconds is not None:
        end = float(media_shot.content_end_seconds)

    segmentation = report.media_evidence.segmentation if report.media_evidence else None
    if segmentation is not None:
        selected = [
            item for item in segmentation.candidates if item.selected_by_model or item.hard_boundary
        ]
        incoming = next(
            (
                item
                for item in selected
                if item.id in shot.source_candidate_ids
                or abs(item.timestamp_seconds - shot.start_seconds) <= 0.002
            ),
            None,
        )
        outgoing = next(
            (item for item in selected if abs(item.timestamp_seconds - shot.end_seconds) <= 0.002),
            None,
        )
        if incoming is not None:
            _, stable_new_scene = _boundary_content_window(incoming)
            start = max(start, stable_new_scene)
        if outgoing is not None:
            transition_start, _ = _boundary_content_window(outgoing)
            end = min(end, transition_start)
    if end - start < 0.05:
        return float(shot.start_seconds), float(shot.end_seconds)
    return round(start, 3), round(end, 3)


def _shot_frame_samples(
    report: AnalysisReport,
    shot: Shot,
) -> list[VisualBeatFrameSpec]:
    """Recover the real timestamp paired with every start/middle/end artifact."""

    media_shot: ShotEvidence | None = None
    if report.media_evidence is not None:
        media_shot = next(
            (item for item in report.media_evidence.shots if item.shot_id == shot.id),
            None,
        )
    start, end = _report_shot_content_bounds(report, shot, media_shot)
    duration = max(0.001, end - start)
    offset = min(0.18, max(0.001, duration * 0.2), duration / 3)
    representative = float(
        media_shot.representative_timestamp if media_shot is not None else start + duration / 2
    )
    timestamps = {
        "start": round(min(end, start + offset), 3),
        "middle": round(min(end, max(start, representative)), 3),
        "end": round(max(start, end - offset), 3),
    }

    evidence_urls = list(shot.evidence_frame_urls)
    if not evidence_urls and media_shot is not None:
        evidence_urls = list(media_shot.evidence_frame_urls)
    role_urls: dict[str, str] = {}
    evidence_timestamps = list(media_shot.evidence_timestamps) if media_shot is not None else []
    for url in evidence_urls:
        role_urls.setdefault(_visual_frame_role(url), url)
    if len(evidence_timestamps) == len(evidence_urls):
        for url, timestamp in zip(evidence_urls, evidence_timestamps, strict=True):
            timestamps[_visual_frame_role(url)] = round(float(timestamp), 3)
    keyframe_url = (
        shot.keyframe_url
        or (media_shot.keyframe_url if media_shot is not None else None)
        or (f"/api/v1/analyses/{report.analysis_id}/artifacts/shots/shot_{shot.index:03d}.jpg")
    )
    if keyframe_url:
        role_urls["middle"] = keyframe_url
    if evidence_urls:
        role_urls.setdefault("start", evidence_urls[0])
        role_urls.setdefault("end", evidence_urls[-1])

    return [
        VisualBeatFrameSpec(
            source_url=role_urls.get(role),
            source_timestamp_seconds=(timestamps[role] if role_urls.get(role) else None),
            target_timestamp_seconds=timestamps[role],
            role=role,
        )
        for role in ("start", "middle", "end")
    ]


def _visual_beat_frame_specs(
    report: AnalysisReport,
    shot: Shot,
    beat_count: int,
) -> list[VisualBeatFrameSpec]:
    """Spread ordered visual beats over real evidence without reusing one URL."""

    if beat_count <= 0:
        return []
    samples = _shot_frame_samples(report, shot)
    if beat_count == 1:
        return [samples[1]]

    first_target = samples[0].target_timestamp_seconds
    last_target = samples[-1].target_timestamp_seconds
    used_urls: set[str] = set()
    selected: list[VisualBeatFrameSpec] = []
    for index in range(beat_count):
        target = round(
            first_target + (last_target - first_target) * index / (beat_count - 1),
            3,
        )
        available = [
            item
            for item in samples
            if item.source_url is not None and item.source_url not in used_urls
        ]
        fallback = min(
            available,
            key=lambda item: abs(item.target_timestamp_seconds - target),
            default=None,
        )
        if fallback is not None:
            used_urls.add(fallback.source_url or "")
        selected.append(
            VisualBeatFrameSpec(
                source_url=fallback.source_url if fallback is not None else None,
                source_timestamp_seconds=(
                    fallback.source_timestamp_seconds if fallback is not None else None
                ),
                target_timestamp_seconds=target,
                role=fallback.role if fallback is not None else "generated",
            )
        )
    return selected


def _boundary_contaminated_visual_beat_ids(
    report: AnalysisReport,
    plan: ShotPlan,
) -> list[UUID]:
    """Find leading visual beats that still belong to the previous shot."""

    if plan.source_kind != ShotSourceKind.ANALYSIS or len(plan.visual_beats) <= 1:
        return []
    source_shot = next(
        (item for item in report.shots if item.id == plan.source_shot_id),
        None,
    )
    if source_shot is None:
        return []
    content_start, _ = _report_shot_content_bounds(report, source_shot)
    if content_start - plan.start_seconds < 0.05:
        return []
    ordered = sorted(plan.visual_beats, key=lambda item: item.index)
    contaminated: list[UUID] = []
    for beat in ordered:
        timestamp = beat.source_timestamp_seconds
        if timestamp is None or timestamp >= content_start - 0.002:
            break
        contaminated.append(beat.id)
    if not contaminated or len(contaminated) >= len(ordered):
        return []
    remaining = [item for item in ordered if item.id not in set(contaminated)]
    if not any(
        item.source_timestamp_seconds is not None
        and item.source_timestamp_seconds >= content_start - 0.002
        for item in remaining
    ):
        return []
    return contaminated


def _frame_sha256_and_dhash(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    with Image.open(BytesIO(payload)) as source:
        grayscale = ImageOps.grayscale(ImageOps.exif_transpose(source)).resize(
            (9, 8),
            Image.Resampling.LANCZOS,
        )
        flattened = getattr(grayscale, "get_flattened_data", None)
        pixels = list(flattened() if flattened is not None else grayscale.getdata())
    difference_hash = 0
    for row in range(8):
        row_offset = row * 9
        for column in range(8):
            difference_hash <<= 1
            if pixels[row_offset + column] > pixels[row_offset + column + 1]:
                difference_hash |= 1
    return hashlib.sha256(payload).hexdigest(), difference_hash


def _hash_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _visual_beat_timestamp_candidates(
    plan: ShotPlan,
    beat: ShotVisualBeat,
    target_timestamp_seconds: float,
) -> list[float]:
    duration = max(0.001, plan.end_seconds - plan.start_seconds)
    beat_start = plan.start_seconds + duration * beat.start_ratio
    beat_end = plan.start_seconds + duration * beat.end_ratio
    beat_duration = max(0.001, beat_end - beat_start)
    inset = min(0.18, max(0.001, beat_duration * 0.15), beat_duration / 3)
    raw = [
        target_timestamp_seconds,
        beat_start + beat_duration / 2,
        beat_start + inset,
        beat_end - inset,
        beat_start + beat_duration * 0.25,
        beat_start + beat_duration * 0.75,
    ]
    values: list[float] = []
    for value in raw:
        clamped = round(
            min(
                max(value, plan.start_seconds),
                max(plan.start_seconds, plan.end_seconds - 0.001),
            ),
            3,
        )
        if clamped not in values:
            values.append(clamped)
    return values


def _simplified_text(
    value: str,
    *,
    field_name: str,
    allow_empty: bool = False,
    max_length: int,
) -> str:
    normalized = (to_simplified(value) or "").strip()
    if not normalized and not allow_empty:
        raise _fail(422, "invalid_text", f"{field_name}不能为空")
    if len(normalized) > max_length:
        raise _fail(422, "invalid_text", f"{field_name}不能超过 {max_length} 个字符")
    return normalized


def _simplified_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = _simplified_text(
            value,
            field_name="标签",
            allow_empty=True,
            max_length=80,
        )
        if tag and tag not in normalized:
            normalized.append(tag)
    if len(normalized) > 20:
        raise _fail(422, "too_many_tags", "参考资产标签不能超过 20 个")
    return normalized


def _canonical_ratio(value: str) -> tuple[str, int, int]:
    try:
        width, height = (int(part) for part in value.split(":"))
    except (TypeError, ValueError) as exc:
        raise _fail(422, "invalid_aspect_ratio", "输出画面比例格式无效") from exc
    if width <= 0 or height <= 0:
        raise _fail(422, "invalid_aspect_ratio", "输出画面比例必须大于零")
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}", width, height


def _output_settings(
    ratio_value: str,
    width: int | None,
    height: int | None,
) -> tuple[str, int, int]:
    ratio, ratio_width, ratio_height = _canonical_ratio(ratio_value)
    if width is None or height is None:
        if ratio_width >= ratio_height:
            height = 1080
            width = round(height * ratio_width / ratio_height)
        else:
            width = 1080
            height = round(width * ratio_height / ratio_width)
        width += width % 2
        height += height % 2
    if not 256 <= width <= 8192 or not 256 <= height <= 8192:
        raise _fail(422, "invalid_output_size", "输出尺寸必须在 256 到 8192 像素之间")
    expected = ratio_width / ratio_height
    actual = width / height
    if abs(actual - expected) / expected > 0.02:
        raise _fail(422, "output_ratio_mismatch", "输出尺寸与画面比例不匹配")
    return ratio, width, height


_SUPPORTED_OUTPUT_RATIOS = ("9:16", "16:9", "1:1", "4:5")


def _default_output_ratio(
    width: int | None,
    height: int | None,
    fallback: str,
) -> str:
    if not width or not height or width <= 0 or height <= 0:
        return fallback
    source_ratio = width / height

    def orientation(value: float) -> str:
        if abs(1 - value) <= 0.06:
            return "square"
        return "landscape" if value > 1 else "portrait"

    source_orientation = orientation(source_ratio)
    ranked: list[tuple[int, int, int, str]] = []
    for index, candidate in enumerate(_SUPPORTED_OUTPUT_RATIOS):
        candidate_width, candidate_height = (int(part) for part in candidate.split(":"))
        candidate_ratio = candidate_width / candidate_height
        ranked.append(
            (
                round(abs(math.log(source_ratio / candidate_ratio)) * 1_000_000_000_000),
                0 if orientation(candidate_ratio) == source_orientation else 1,
                index,
                candidate,
            )
        )
    return min(ranked)[3]


def inspect_reference_image(payload: bytes, declared_mime_type: str | None) -> ReferenceImageInfo:
    if not payload:
        raise _fail(422, "empty_reference_image", "参考图片不能为空")
    if len(payload) > MAX_REFERENCE_IMAGE_BYTES:
        raise _fail(413, "reference_image_too_large", "参考图片不能超过 15 MB")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as opened:
                image_format = (opened.format or "").upper()
                if image_format not in _IMAGE_FORMATS:
                    raise _fail(415, "unsupported_reference_image", "仅支持 JPG、PNG 和 WebP")
                if getattr(opened, "n_frames", 1) != 1:
                    raise _fail(415, "animated_reference_image", "参考图片必须是静态图片")
                raw_width, raw_height = opened.size
                opened.verify()

            if (
                raw_width <= 0
                or raw_height <= 0
                or raw_width > MAX_REFERENCE_IMAGE_DIMENSION
                or raw_height > MAX_REFERENCE_IMAGE_DIMENSION
                or raw_width * raw_height > MAX_REFERENCE_IMAGE_PIXELS
            ):
                raise _fail(
                    413,
                    "reference_image_dimensions_too_large",
                    "参考图片尺寸不能超过 16384 像素或 6400 万像素",
                )

            extension, mime_type = _IMAGE_FORMATS[image_format]
            declared = (declared_mime_type or "").split(";", 1)[0].strip().lower()
            if declared and declared not in {mime_type, "application/octet-stream"}:
                raise _fail(415, "reference_image_mime_mismatch", "图片媒体类型与文件内容不一致")

            with Image.open(BytesIO(payload)) as source:
                thumbnail = ImageOps.exif_transpose(source)
                width, height = thumbnail.size
                thumbnail.thumbnail(
                    (REFERENCE_THUMBNAIL_SIZE, REFERENCE_THUMBNAIL_SIZE),
                    Image.Resampling.LANCZOS,
                )
                has_alpha = thumbnail.mode in {"RGBA", "LA"} or "transparency" in thumbnail.info
                thumbnail = thumbnail.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                thumbnail.save(output, format="WEBP", quality=84, method=4)
    except ProductionServiceError:
        raise
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise _fail(415, "invalid_reference_image", "参考图片文件已损坏或格式无效") from exc

    return ReferenceImageInfo(
        extension=extension,
        mime_type=mime_type,
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
        thumbnail=output.getvalue(),
    )


def _revision_response(revision: ProductionRevision) -> ProductionRevisionResponse:
    return ProductionRevisionResponse.model_validate(
        revision.model_dump(exclude={"snapshot_relative_path"})
    )


class ProductionService:
    def __init__(
        self,
        repository: ProductionRepository,
        workspace: WorkspaceManager,
        image_gateway: ImageGenerationGateway | None = None,
        media_processor: MediaProcessor | None = None,
        project_assets: ProjectAssetBridge | None = None,
        video_gateway: VideoGenerationGateway | None = None,
        notification_publisher: NotificationPublisher | None = None,
        video_inspector: VideoInspector | None = None,
        continuity_service: ContinuityService | None = None,
        managed_asset_service: ManagedAssetCatalogService | None = None,
        depth_control_service: DepthControlService | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.project_assets = project_assets
        self.media_processor = media_processor or MediaProcessor()
        self.image_gateway = image_gateway or ImageGenerationGateway(
            workspace,
            repository=repository,
        )
        self.video_gateway = video_gateway or VideoGenerationGateway(
            workspace,
            media_processor=self.media_processor,
        )
        self.notification_publisher = notification_publisher
        self.video_inspector = video_inspector or ProductionVideoInspector(self.media_processor)
        self.continuity = continuity_service or ContinuityService(repository)
        self.managed_assets = managed_asset_service
        self.depth_controls = depth_control_service or DepthControlService(workspace)
        self._lock_guard = asyncio.Lock()
        self._project_locks: dict[UUID, asyncio.Lock] = {}
        self._generation_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._generation_cancellations: dict[UUID, Event] = {}

    async def _project_lock(self, project_id: UUID) -> asyncio.Lock:
        async with self._lock_guard:
            return self._project_locks.setdefault(project_id, asyncio.Lock())

    async def _notify_generation_run(self, run: GenerationRun) -> None:
        """Publish a safe account notification without affecting generation results."""
        if self.notification_publisher is None:
            return
        if run.status not in {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.BLOCKED,
            ProductionRunStatus.CANCELLED,
        }:
            return
        try:
            project = await self._require_project(run.project_id)
            plan = await self._require_shot(run.shot_plan_id)
            candidates = await self.repository.list_generation_candidates(run.id)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.status
                    in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }
                ),
                candidates[0] if candidates else None,
            )
            kind_label = "视频" if run.kind == GenerationKind.VIDEO else "图片"
            category = (
                "video_generation" if run.kind == GenerationKind.VIDEO else "image_generation"
            )
            model_label = run.model_display_name or run.model_alias or run.model
            action_payload = {
                "record_id": str(project.record_id),
                "project_id": str(project.id),
                "shot_plan_id": str(plan.id),
                "step": "shot_videos" if run.kind == GenerationKind.VIDEO else "shot_images",
                "run_id": str(run.id),
            }
            if candidate is not None:
                action_payload["candidate_id"] = str(candidate.id)

            if run.status in {ProductionRunStatus.QUEUED, ProductionRunStatus.RUNNING}:
                notification_status = "in_progress"
                level = "info"
                title = f"分镜 {plan.index} 的{kind_label}生成已开始"
                message = f"{model_label} 正在处理，完成后会在这里通知你。"
                action_label = "查看进度"
            elif run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}:
                notification_status = "succeeded"
                level = "success"
                title = f"分镜 {plan.index} 的{kind_label}候选已生成"
                if run.actual_cost_known:
                    cost_text = f"实际 ¥{run.actual_cost_micros / 1_000_000:.2f}"
                elif run.cost_estimate_known:
                    cost_text = f"预计 ¥{run.estimated_cost_micros / 1_000_000:.2f}"
                else:
                    cost_text = "费用待 Provider 回传"
                message = f"{model_label} · {len(candidates)} 个候选 · {cost_text}"
                action_label = "查看候选"
            elif run.status in {ProductionRunStatus.FAILED, ProductionRunStatus.BLOCKED}:
                notification_status = "failed"
                level = "error"
                failure = (
                    classify_video_provider_failure(
                        provider=run.provider,
                        code=run.error_code,
                        message=run.error_technical_message or run.error_message,
                        retryable=run.error_retryable,
                        provider_code=run.provider_error_code,
                    )
                    if run.kind == GenerationKind.VIDEO
                    else None
                )
                if failure and failure.suggested_action == "open_model_settings":
                    title = (
                        f"{model_label} 已暂停生成"
                        if failure.category == "inference_limit"
                        else run.error_title or failure.title
                    )
                    message = run.error_message or failure.message
                    action_label = {
                        "inference_limit": "处理模型限制",
                        "balance": "检查账户余额",
                        "authentication": "检查模型设置",
                        "configuration": "完成模型配置",
                    }.get(failure.category, "检查模型设置")
                    action_payload.update(
                        {
                            "provider": run.provider,
                            "model_alias": run.model_alias or "",
                            "failure_category": failure.category,
                        }
                    )
                    await self.notification_publisher.publish(
                        category=category,
                        level=level,
                        status=notification_status,
                        title=title,
                        message=message,
                        event_key=f"generation:{run.id}",
                        action_kind="model_settings",
                        action_label=action_label,
                        action_payload=action_payload,
                    )
                    return
                title = (
                    run.error_title
                    or (failure.title if failure else None)
                    or f"分镜 {plan.index} 的{kind_label}生成失败"
                )
                message = (
                    run.error_message
                    or (failure.message if failure else None)
                    or "请打开对应分镜查看错误详情，调整设置后重试。"
                )
                action_label = "查看分镜"
            else:
                notification_status = "cancelled"
                level = "warning"
                title = f"分镜 {plan.index} 的{kind_label}生成已取消"
                message = "本次任务未产生可审核候选。"
                action_label = "返回分镜"

            await self.notification_publisher.publish(
                category=category,
                level=level,
                status=notification_status,
                title=title,
                message=message,
                event_key=f"generation:{run.id}",
                action_kind="production_shot",
                action_label=action_label,
                action_payload=action_payload,
            )
        except Exception:
            # Notification delivery is secondary and must never change generation state.
            return

    async def _notify_candidate_lifecycle(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        *,
        affected_count: int,
        restored: bool,
        kind: GenerationKind,
    ) -> None:
        if self.notification_publisher is None:
            return
        action = "恢复" if restored else "移入回收站"
        kind_label = "图片" if kind == GenerationKind.IMAGE else "视频"
        try:
            await self.notification_publisher.publish(
                category="production",
                level="success",
                status="succeeded",
                title=f"已{action} {affected_count} 个{kind_label}候选",
                message=(
                    f"分镜 {plan.index} 的候选已恢复为可采用状态。"
                    if restored
                    else f"分镜 {plan.index} 的候选文件仍会保留，可从回收站恢复。"
                ),
                event_key=(
                    f"{kind.value}-candidates:{project.current_revision_id}:"
                    f"{'restore' if restored else 'archive'}"
                ),
                action_kind="production_shot",
                action_label="查看分镜",
                action_payload={
                    "project_id": str(project.id),
                    "shot_plan_id": str(plan.id),
                    "candidate_id": "",
                },
            )
        except Exception:
            return

    async def create_project(
        self,
        record_id: UUID,
        payload: ProductionProjectCreate,
    ) -> ProductionProjectDetail:
        record = await self.repository.get_record(record_id)
        if record is None:
            raise _fail(404, "record_not_found", "分析记录不存在")
        analysis_id = payload.base_analysis_id or record.latest_analysis_id
        if analysis_id is None:
            raise _fail(409, "analysis_required", "请先完成视频分析")
        analysis, report = await self._completed_analysis(record, analysis_id)
        video = await self.repository.get_video(record.video_id)
        if video is None:
            raise _fail(409, "video_missing", "分析记录缺少视频信息")

        ratio_value = payload.output_aspect_ratio or _default_output_ratio(
            video.width,
            video.height,
            report.prompt_package.aspect_ratio,
        )
        ratio, width, height = _output_settings(
            ratio_value,
            payload.output_width,
            payload.output_height,
        )
        default_name = f"{record.name} 复刻方案"
        project = ProductionProject(
            record_id=record.id,
            video_id=video.id,
            base_analysis_id=analysis.id,
            prompt_source_analysis_id=analysis.id,
            source_prompt_package_id=report.prompt_package.id,
            name=_simplified_text(
                payload.name or default_name,
                field_name="创作方案名称",
                max_length=120,
            ),
            output_aspect_ratio=ratio,
            output_width=width,
            output_height=height,
            budget_limit_micros=payload.budget_limit_micros,
        )
        self.workspace.initialize_production(record.id, project.id)
        revision_id = uuid4()
        shot_plans = self._initial_shot_plans(
            project,
            report,
            revision_id,
        )
        shot_plans = await self._materialize_visual_beat_source_frames(
            project,
            shot_plans,
            report,
            revision_id,
            plan_ids={item.id for item in shot_plans if len(item.visual_beats) > 1},
        )
        project, revision = await self._prepare_revision(
            project,
            ProductionChangeKind.PROJECT_CREATED,
            "创建创作方案并冻结基础分析",
            revision_id=revision_id,
            report=report,
            reference_assets=[],
            shot_plans=shot_plans,
            reference_bindings=[],
        )
        await self.repository.save_production_bundle(
            project,
            revision,
            shot_plans=shot_plans,
        )
        return ProductionProjectDetail(
            project=project,
            current_revision=_revision_response(revision),
            revision_count=1,
            reference_count=0,
            shot_count=len(shot_plans),
        )

    async def list_projects(self, record_id: UUID) -> list[ProductionProject]:
        if await self.repository.get_record(record_id) is None:
            raise _fail(404, "record_not_found", "分析记录不存在")
        projects = [
            _normalize_optional_preparation_project(project)
            for project in await self.repository.list_production_projects(record_id)
        ]
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    async def get_project(self, project_id: UUID) -> ProductionProjectDetail:
        project = await self._require_project(project_id)
        project, shots = await self._ensure_project_shots(project)
        revisions = await self.repository.list_production_revisions(project.id)
        references = await self._list_reference_assets(project.id)
        current = next(
            (item for item in revisions if item.id == project.current_revision_id),
            None,
        )
        active_shots = [
            item for item in shots if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
        ]
        return ProductionProjectDetail(
            project=project,
            current_revision=_revision_response(current) if current else None,
            revision_count=len(revisions),
            reference_count=sum(item.archived_at is None for item in references),
            shot_count=len(active_shots),
            discarded_shot_count=len(shots) - len(active_shots),
            approved_image_count=sum(
                item.image_status == WorkflowItemStatus.APPROVED for item in active_shots
            ),
            stale_image_count=sum(
                item.image_status == WorkflowItemStatus.STALE for item in active_shots
            ),
        )

    async def update_project(
        self,
        project_id: UUID,
        payload: ProductionProjectUpdate,
    ) -> ProductionProjectDetail:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            updates: dict[str, object] = {}
            if "name" in fields:
                if payload.name is None:
                    raise _fail(422, "invalid_name", "创作方案名称不能为空")
                updates["name"] = _simplified_text(
                    payload.name,
                    field_name="创作方案名称",
                    max_length=120,
                )
            ratio_value = (
                payload.output_aspect_ratio
                if "output_aspect_ratio" in fields and payload.output_aspect_ratio is not None
                else project.output_aspect_ratio
            )
            if "output_aspect_ratio" in fields and payload.output_aspect_ratio is None:
                raise _fail(422, "invalid_aspect_ratio", "输出画面比例不能为空")
            dimensions_changed = "output_width" in fields or "output_height" in fields
            ratio_changed = "output_aspect_ratio" in fields
            output_fields_provided = dimensions_changed or ratio_changed
            output_changed = False
            if output_fields_provided:
                selected_width = payload.output_width if dimensions_changed else None
                selected_height = payload.output_height if dimensions_changed else None
                ratio, width, height = _output_settings(
                    ratio_value,
                    selected_width,
                    selected_height,
                )
                output_changed = (
                    ratio != project.output_aspect_ratio
                    or width != project.output_width
                    or height != project.output_height
                )
                updates.update(
                    output_aspect_ratio=ratio,
                    output_width=width,
                    output_height=height,
                )
            plans = await self.repository.list_shot_plans(project.id)
            if (
                output_changed
                and any(
                    item.image_status == WorkflowItemStatus.APPROVED
                    or item.video_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "输出规格修改会使全部已审批分镜过期，请确认影响范围后重试",
                )
            if "budget_limit_micros" in fields:
                updates["budget_limit_micros"] = payload.budget_limit_micros
            updates["updated_at"] = utc_now()
            updated = ProductionProject.model_validate(
                {**project.model_dump(mode="python"), **updates}
            )
            revision_id = uuid4()
            next_plans = plans
            changed_plans: list[ShotPlan] = []
            if output_changed:
                next_plans, changed_plans = self._mark_plans_stale(
                    plans,
                    {item.id for item in plans},
                    revision_id,
                )
            updated, revision = await self._prepare_revision(
                updated,
                ProductionChangeKind.PROJECT_SETTINGS_CHANGED,
                "更新创作方案设置",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                updated,
                revision,
                shot_plans=changed_plans,
            )
        return await self.get_project(project_id)

    async def create_branch(
        self,
        project_id: UUID,
        payload: ProductionBranchCreate,
    ) -> ProductionProjectDetail:
        source_project = await self._require_project(project_id)
        source_revision_id = payload.source_revision_id or source_project.current_revision_id
        if source_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无可分支的版本")
        source_revision = await self._require_revision(source_project, source_revision_id)
        source_snapshot = await self._read_revision_snapshot(source_project, source_revision)
        try:
            frozen_project = _normalize_optional_preparation_project(
                ProductionProject.model_validate(source_snapshot["project"])
            )
        except (KeyError, TypeError, ValidationError) as exc:
            raise _fail(409, "invalid_revision_snapshot", "源版本快照无法用于创建分支") from exc

        now = utc_now()
        branch_id = uuid4()
        branch_revision_id = uuid4()
        branch = ProductionProject(
            id=branch_id,
            record_id=source_project.record_id,
            video_id=frozen_project.video_id,
            base_analysis_id=frozen_project.base_analysis_id,
            prompt_source_analysis_id=(
                frozen_project.prompt_source_analysis_id or frozen_project.base_analysis_id
            ),
            source_prompt_package_id=frozen_project.source_prompt_package_id,
            source_project_id=source_project.id,
            source_revision_id=source_revision.id,
            name=_simplified_text(
                payload.name or f"{source_project.name} 分支",
                field_name="创作方案名称",
                max_length=120,
            ),
            status=ProductionProjectStatus.DRAFT,
            active_step=frozen_project.active_step,
            output_aspect_ratio=frozen_project.output_aspect_ratio,
            output_width=frozen_project.output_width,
            output_height=frozen_project.output_height,
            budget_limit_micros=frozen_project.budget_limit_micros,
            created_at=now,
            updated_at=now,
        )
        self.workspace.initialize_production(branch.record_id, branch.id)
        cloned_assets, asset_ids = await self._clone_snapshot_assets(
            source_project,
            branch,
            source_snapshot,
        )
        cloned_shots, cloned_bindings = await self._clone_snapshot_shots(
            source_project,
            branch,
            branch_revision_id,
            source_snapshot,
            asset_ids,
        )
        branch, revision = await self._prepare_revision(
            branch,
            ProductionChangeKind.BRANCH_CREATED,
            f"从版本 {source_revision.revision_number} 创建分支",
            revision_id=branch_revision_id,
            reference_assets=cloned_assets,
            shot_plans=cloned_shots,
            reference_bindings=cloned_bindings,
        )
        await self.repository.save_production_bundle(
            branch,
            revision,
            reference_assets=cloned_assets if self.project_assets is None else None,
            shot_plans=cloned_shots,
            reference_bindings=cloned_bindings,
        )
        active_cloned_shots = [
            item for item in cloned_shots if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
        ]
        return ProductionProjectDetail(
            project=branch,
            current_revision=_revision_response(revision),
            revision_count=1,
            reference_count=len(cloned_assets),
            shot_count=len(active_cloned_shots),
            discarded_shot_count=len(cloned_shots) - len(active_cloned_shots),
            approved_image_count=sum(
                item.image_status == WorkflowItemStatus.APPROVED for item in active_cloned_shots
            ),
            stale_image_count=sum(
                item.image_status == WorkflowItemStatus.STALE for item in active_cloned_shots
            ),
        )

    async def list_revisions(self, project_id: UUID) -> list[ProductionRevisionResponse]:
        await self._require_project(project_id)
        revisions = await self.repository.list_production_revisions(project_id)
        return [_revision_response(item) for item in reversed(revisions)]

    async def get_revision(
        self,
        project_id: UUID,
        revision_id: UUID,
    ) -> ProductionRevisionDetail:
        project = await self._require_project(project_id)
        revision = await self._require_revision(project, revision_id)
        snapshot = await self._read_revision_snapshot(project, revision)
        return ProductionRevisionDetail(
            **_revision_response(revision).model_dump(),
            snapshot=snapshot,
        )

    async def create_reference(
        self,
        project_id: UUID,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        declared_mime_type: str | None,
        filename: str = "",
    ) -> ReferenceAssetResponse:
        project = await self._require_project(project_id)
        if self.project_assets is not None:
            return await self._create_workspace_reference(
                project, payload, file_payload, filename, declared_mime_type
            )
        image = await asyncio.to_thread(
            inspect_reference_image,
            file_payload,
            declared_mime_type,
        )
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            active_count = sum(item.archived_at is None for item in existing)
            if active_count >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            if not payload.rights_confirmed:
                raise _fail(422, "rights_confirmation_required", "请先确认拥有该参考图片的使用权")

            asset_id = uuid4()
            asset_root = self.workspace.reference_asset_root(
                project.record_id,
                project.id,
                asset_id,
            )
            original = asset_root / f"original{image.extension}"
            thumbnail = asset_root / "thumbnail.webp"
            asset = ReferenceAsset(
                id=asset_id,
                project_id=project.id,
                type=payload.type,
                name=_simplified_text(
                    payload.name,
                    field_name="参考资产名称",
                    max_length=120,
                ),
                description=_simplified_text(
                    payload.description,
                    field_name="参考资产说明",
                    allow_empty=True,
                    max_length=2000,
                ),
                relative_path=self.workspace.relative(original),
                thumbnail_relative_path=self.workspace.relative(thumbnail),
                mime_type=image.mime_type,
                width=image.width,
                height=image.height,
                sha256=image.sha256,
                tags=_simplified_tags(payload.tags),
                rights_confirmed=True,
                rights_note=(
                    _simplified_text(
                        payload.rights_note,
                        field_name="权利说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.rights_note is not None
                    else None
                ),
            )
            await asyncio.to_thread(
                self._write_reference_files,
                project,
                asset,
                file_payload,
                image.thumbnail,
            )
            next_project = ProductionProject.model_validate(
                {
                    **project.model_dump(mode="python"),
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": _step_after_reference_change(project),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"新增参考资产：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[asset],
            )
        return self._reference_response(asset, next_project.current_revision_id)

    async def _create_workspace_reference(
        self,
        project: ProductionProject,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            self._require_expected_revision(project, payload.expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            if len(existing) >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            asset = await self.project_assets.create_reference(
                project,
                payload,
                file_payload,
                filename,
                declared_mime_type,
            )
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": _step_after_reference_change(project),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"新增参考资产：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(next_project, revision)
        return self._reference_response(asset, next_project.current_revision_id)

    async def link_reference(
        self,
        project_id: UUID,
        asset_id: UUID,
        expected_revision_id: UUID,
        reference_type: ReferenceAssetType | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(409, "asset_library_not_enabled", "资产库尚未启用")
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            if any(item.id == asset_id for item in existing):
                raise _fail(409, "asset_already_linked", "该资产已添加到当前创作方案")
            if len(existing) >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            asset = await self.project_assets.link_asset(project, asset_id, reference_type)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": _step_after_reference_change(project),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"从资产库添加：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(next_project, revision)
        return self._reference_response(asset, next_project.current_revision_id)

    async def _update_workspace_reference(
        self,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
        project_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        asset = await self.project_assets.get_reference(asset_id, project_id)
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self.project_assets.get_reference(asset_id, asset.project_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(409, "reference_asset_archived", "已移出项目的参考资产不能修改")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "参考资产修改会使已绑定分镜过期，请确认影响范围后重试",
                )
            updated_asset = await self.project_assets.update_reference(
                project.id,
                asset.id,
                payload,
            )
            snapshot_assets = await self._list_reference_assets(
                project.id,
                include_archived=True,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(
                update={
                    "active_step": _step_after_reference_change(
                        project,
                        affects_bound_shots=bool(impacted_ids),
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"更新资产库参考：{updated_asset.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return self._reference_response(updated_asset, next_project.current_revision_id)

    async def _archive_workspace_reference(
        self,
        asset_id: UUID,
        expected_revision_id: UUID,
        confirm_stale: bool,
        project_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        asset = await self.project_assets.get_reference(asset_id, project_id)
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self.project_assets.get_reference(asset_id, asset.project_id)
            if asset is None:
                raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, expected_revision_id)
            if asset.archived_at is not None:
                return self._reference_response(asset, project.current_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "移出参考资产会使已绑定分镜过期，请确认影响范围后重试",
                )
            archived = await self.project_assets.unlink_reference(project.id, asset.id)
            snapshot_assets = await self._list_reference_assets(
                project.id,
                include_archived=True,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(
                update={
                    "active_step": _step_after_reference_change(
                        project,
                        affects_bound_shots=bool(impacted_ids),
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"从项目移出参考资产：{archived.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return self._reference_response(archived, next_project.current_revision_id)

    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAssetResponse]:
        project = await self._require_project(project_id)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        assets = await self._list_reference_assets(project.id, include_archived=include_archived)
        if not include_archived and self.project_assets is None:
            assets = [item for item in assets if item.archived_at is None]
        return [self._reference_response(item, project.current_revision_id) for item in assets]

    async def update_reference(
        self,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
        *,
        project_id: UUID | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is not None:
            return await self._update_workspace_reference(asset_id, payload, project_id)
        asset = await self._require_asset(asset_id)
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self._require_asset(asset_id)
            if asset.archived_at is not None:
                raise _fail(409, "reference_asset_archived", "已归档的参考资产不能继续修改")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            updates: dict[str, object] = {}
            if "name" in fields:
                if payload.name is None:
                    raise _fail(422, "invalid_name", "参考资产名称不能为空")
                updates["name"] = _simplified_text(
                    payload.name,
                    field_name="参考资产名称",
                    max_length=120,
                )
            if "description" in fields:
                updates["description"] = _simplified_text(
                    payload.description or "",
                    field_name="参考资产说明",
                    allow_empty=True,
                    max_length=2000,
                )
            if "tags" in fields:
                updates["tags"] = _simplified_tags(payload.tags or [])
            if "rights_confirmed" in fields:
                updates["rights_confirmed"] = bool(payload.rights_confirmed)
            if "rights_note" in fields:
                updates["rights_note"] = (
                    _simplified_text(
                        payload.rights_note,
                        field_name="权利说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.rights_note is not None
                    else None
                )
            updated_asset = ReferenceAsset.model_validate(
                {**asset.model_dump(mode="python"), **updates}
            )
            existing = await self._list_reference_assets(project.id, include_archived=True)
            snapshot_assets = [updated_asset if item.id == asset.id else item for item in existing]
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "参考资产修改会使已绑定分镜过期，请确认影响范围后重试",
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                project,
                updated_asset,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(
                update={
                    "active_step": _step_after_reference_change(
                        project,
                        affects_bound_shots=bool(impacted_ids),
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"更新参考资产：{updated_asset.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[updated_asset],
                shot_plans=changed_plans,
            )
        return self._reference_response(updated_asset, next_project.current_revision_id)

    async def archive_reference(
        self,
        asset_id: UUID,
        expected_revision_id: UUID,
        *,
        confirm_stale: bool = False,
        project_id: UUID | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is not None:
            return await self._archive_workspace_reference(
                asset_id, expected_revision_id, confirm_stale, project_id
            )
        asset = await self._require_asset(asset_id)
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self._require_asset(asset_id)
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, expected_revision_id)
            if asset.archived_at is not None:
                return self._reference_response(asset, project.current_revision_id)
            archived = ReferenceAsset.model_validate(
                {**asset.model_dump(mode="python"), "archived_at": utc_now()}
            )
            existing = await self._list_reference_assets(project.id, include_archived=True)
            snapshot_assets = [archived if item.id == asset.id else item for item in existing]
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "归档参考资产会使已绑定分镜过期，请确认影响范围后重试",
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                project,
                archived,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(
                update={
                    "active_step": _step_after_reference_change(
                        project,
                        affects_bound_shots=bool(impacted_ids),
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"归档参考资产：{archived.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[archived],
                shot_plans=changed_plans,
            )
        return self._reference_response(archived, next_project.current_revision_id)

    async def resolve_reference_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]:
        if self.project_assets is not None:
            return await self.project_assets.resolve_content(asset_id, thumbnail=thumbnail)
        asset = await self._require_asset(asset_id)
        project = await self._require_project(asset.project_id)
        relative_path = asset.thumbnail_relative_path if thumbnail else asset.relative_path
        if relative_path is None:
            raise _fail(404, "reference_thumbnail_missing", "参考资产缩略图不存在")
        candidate = self._resolve_reference_path(project, relative_path)
        filesystem_candidate = _filesystem_path(candidate)
        if not filesystem_candidate.is_file():
            raise _fail(404, "reference_file_missing", "参考资产文件不存在")
        return filesystem_candidate, "image/webp" if thumbnail else asset.mime_type

    @staticmethod
    def _shot_media_preview(
        plan: ShotPlan,
        kind: GenerationKind,
        candidates: list[GenerationCandidate],
    ) -> ShotMediaPreview | None:
        approved_id = (
            plan.approved_image_candidate_id
            if kind == GenerationKind.IMAGE
            else plan.approved_video_candidate_id
        )
        available = [
            candidate
            for candidate in candidates
            if candidate.kind == kind
            and candidate.thumbnail_relative_path is not None
            and candidate.status
            not in {GenerationCandidateStatus.REJECTED, GenerationCandidateStatus.ARCHIVED}
        ]
        if not available:
            return None

        approved = next(
            (candidate for candidate in available if candidate.id == approved_id),
            None,
        )
        selected = [
            candidate
            for candidate in available
            if candidate.status == GenerationCandidateStatus.SELECTED
        ]
        candidate = approved or max(
            selected or available,
            key=lambda item: (item.created_at, item.ordinal),
        )
        stage = kind.value
        preview_kind = (
            f"approved_{stage}"
            if approved is not None
            else f"selected_{stage}"
            if candidate.status == GenerationCandidateStatus.SELECTED
            else f"candidate_{stage}"
        )
        return ShotMediaPreview(
            thumbnail_url=f"/api/v1/generation-candidates/{candidate.id}/thumbnail",
            kind=preview_kind,
            candidate_id=candidate.id,
            updated_at=candidate.created_at,
        )

    async def _shot_media_previews(
        self,
        project_id: UUID,
        plans: list[ShotPlan],
    ) -> dict[UUID, tuple[ShotMediaPreview | None, ShotMediaPreview | None]]:
        runs = await self.repository.list_generation_runs(project_id)
        run_by_id = {run.id: run for run in runs}
        candidates = await self.repository.list_generation_candidates_by_run_ids(set(run_by_id))
        candidates_by_shot: dict[UUID, list[GenerationCandidate]] = {plan.id: [] for plan in plans}
        for candidate in candidates:
            run = run_by_id.get(candidate.generation_run_id)
            if run is not None and run.shot_plan_id in candidates_by_shot:
                candidates_by_shot[run.shot_plan_id].append(candidate)

        return {
            plan.id: (
                self._shot_media_preview(
                    plan,
                    GenerationKind.IMAGE,
                    candidates_by_shot[plan.id],
                ),
                self._shot_media_preview(
                    plan,
                    GenerationKind.VIDEO,
                    candidates_by_shot[plan.id],
                ),
            )
            for plan in plans
        }

    async def list_shots(self, project_id: UUID) -> list[ShotPlanResponse]:
        project = await self._require_project(project_id)
        project, plans = await self._ensure_project_shots(project)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        previews = await self._shot_media_previews(project.id, plans)
        return [
            ShotPlanResponse(
                plan=plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=project.current_revision_id,
                image_preview=previews[plan.id][0],
                video_preview=previews[plan.id][1],
            )
            for plan in plans
        ]

    async def create_shot(
        self,
        project_id: UUID,
        payload: ShotPlanCreate,
    ) -> ShotPlanDetailResponse:
        initial_project = await self._require_project(project_id)
        await self._ensure_project_shots(initial_project)
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            active = [item for item in plans if item.lifecycle_status == ShotLifecycleStatus.ACTIVE]
            discarded = [
                item for item in plans if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ]
            active.sort(key=lambda item: item.index)
            discarded.sort(key=lambda item: item.index)
            insert_index = len(active)
            if payload.insert_after_shot_plan_id is not None:
                after_index = next(
                    (
                        index
                        for index, item in enumerate(active)
                        if item.id == payload.insert_after_shot_plan_id
                    ),
                    None,
                )
                if after_index is None:
                    raise _fail(
                        422,
                        "insert_position_invalid",
                        "新增分镜的插入位置不存在或已舍弃",
                    )
                insert_index = after_index + 1

            revision_id = uuid4()
            now = utc_now()
            new_plan_id = uuid4()
            new_bindings: list[ReferenceBinding] = []
            source_keyframe_url: str | None = None
            source_keyframe_relative_path: str | None = None
            source_keyframe_timestamp: float | None = None

            if payload.mode == "duplicate":
                source_plan = next(
                    (item for item in plans if item.id == payload.source_shot_plan_id),
                    None,
                )
                if source_plan is None:
                    raise _fail(404, "source_shot_not_found", "要复制的源分镜不存在")
                source_keyframe_url = source_plan.source_keyframe_url
                source_keyframe_timestamp = source_plan.source_keyframe_timestamp_seconds
                if source_plan.source_keyframe_relative_path is not None:
                    source_path = self._resolve_source_keyframe(project, source_plan)
                    if source_path is None:
                        raise _fail(409, "source_keyframe_missing", "源分镜关键帧文件不存在")
                    destination = (
                        self.workspace.production_shot_root(
                            project.record_id,
                            project.id,
                            new_plan_id,
                        )
                        / "source-keyframes"
                        / f"{revision_id}.jpg"
                    )
                    source_bytes = await asyncio.to_thread(source_path.read_bytes)
                    await asyncio.to_thread(self._write_atomic, destination, source_bytes)
                    source_keyframe_relative_path = self.workspace.relative(destination)
                    source_keyframe_url = (
                        f"/api/v1/production-shots/{new_plan_id}/source-keyframe?v={revision_id}"
                    )
                cloned_visual_beats = await self._clone_visual_beats(
                    source_project=project,
                    target_project=project,
                    source_plan=source_plan,
                    target_shot_plan_id=new_plan_id,
                    revision_id=revision_id,
                    primary_source_url=source_keyframe_url,
                    primary_source_relative_path=source_keyframe_relative_path,
                )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"duplicate-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.DUPLICATE,
                    source_keyframe_url=source_keyframe_url,
                    source_keyframe_relative_path=source_keyframe_relative_path,
                    source_keyframe_timestamp_seconds=source_keyframe_timestamp,
                    source_keyframe_origin="duplicate",
                    start_seconds=source_plan.start_seconds,
                    end_seconds=source_plan.end_seconds,
                    duration_seconds=source_plan.duration_seconds,
                    image_prompt=source_plan.image_prompt,
                    image_prompt_mentions=source_plan.image_prompt_mentions,
                    image_negative_constraints=source_plan.image_negative_constraints,
                    video_prompt=source_plan.video_prompt,
                    video_prompt_mentions=source_plan.video_prompt_mentions,
                    video_negative_constraints=source_plan.video_negative_constraints,
                    locks=source_plan.locks,
                    required=source_plan.required,
                    image_status=(
                        WorkflowItemStatus.READY
                        if source_plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    visual_beats=cloned_visual_beats,
                    created_at=now,
                    updated_at=now,
                )
                for binding in await self.repository.list_reference_bindings(source_plan.id):
                    new_bindings.append(
                        binding.model_copy(
                            update={
                                "id": uuid4(),
                                "shot_plan_id": new_plan_id,
                                "created_at": now,
                            }
                        )
                    )
            elif payload.mode == "video_range":
                start = float(payload.start_seconds or 0)
                end = float(payload.end_seconds or 0)
                timestamp = float(
                    payload.source_keyframe_timestamp_seconds
                    if payload.source_keyframe_timestamp_seconds is not None
                    else start + (end - start) / 2
                )
                video = await self.repository.get_video(project.video_id)
                if video is None:
                    raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
                source_video = self._resolve_video_file(video)
                destination = (
                    self.workspace.production_shot_root(
                        project.record_id,
                        project.id,
                        new_plan_id,
                    )
                    / "source-keyframes"
                    / f"{revision_id}.jpg"
                )
                temporary = destination.parent / f".tmp-{revision_id}.jpg"
                filesystem_temporary = _filesystem_path(temporary)
                filesystem_destination = _filesystem_path(destination)
                try:
                    await self.media_processor.extract_frame(
                        source_video,
                        timestamp,
                        filesystem_temporary,
                    )
                    await asyncio.to_thread(
                        self._validate_keyframe_file,
                        filesystem_temporary,
                    )
                    filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(filesystem_temporary, filesystem_destination)
                except MediaProcessingError as exc:
                    raise _fail(422, exc.code, str(exc)) from exc
                except OSError as exc:
                    raise _fail(507, "keyframe_write_failed", "无法保存新增分镜关键帧") from exc
                finally:
                    filesystem_temporary.unlink(missing_ok=True)
                duration = max(0.01, end - start)
                prompt = _simplified_text(
                    payload.image_prompt,
                    field_name="图片提示词",
                    allow_empty=True,
                    max_length=8000,
                )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"video-range-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.VIDEO_RANGE,
                    source_keyframe_url=(
                        f"/api/v1/production-shots/{new_plan_id}/source-keyframe?v={revision_id}"
                    ),
                    source_keyframe_relative_path=self.workspace.relative(destination),
                    source_keyframe_timestamp_seconds=round(timestamp, 3),
                    source_keyframe_origin="video_selection",
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    image_prompt=prompt,
                    video_prompt=f"持续 {duration:.2f} 秒。",
                    image_status=(
                        WorkflowItemStatus.READY if prompt.strip() else WorkflowItemStatus.DRAFT
                    ),
                    created_at=now,
                    updated_at=now,
                )
            else:
                previous = active[insert_index - 1] if insert_index else None
                start = float(
                    payload.start_seconds
                    if payload.start_seconds is not None
                    else previous.end_seconds
                    if previous is not None
                    else 0
                )
                end = float(
                    payload.end_seconds
                    if payload.end_seconds is not None and payload.end_seconds > start
                    else start + 3
                )
                duration = max(0.01, end - start)
                prompt = _simplified_text(
                    payload.image_prompt,
                    field_name="图片提示词",
                    allow_empty=True,
                    max_length=8000,
                )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"blank-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.BLANK,
                    source_keyframe_url=None,
                    source_keyframe_origin="blank",
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    image_prompt=prompt,
                    video_prompt=f"持续 {duration:.2f} 秒。",
                    image_status=(
                        WorkflowItemStatus.READY if prompt.strip() else WorkflowItemStatus.DRAFT
                    ),
                    created_at=now,
                    updated_at=now,
                )

            active.insert(insert_index, new_plan)
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
                force_ids={new_plan_id},
            )
            all_bindings = await self._all_bindings(plans)
            all_bindings.extend(new_bindings)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": now,
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"新增分镜并插入到第 {insert_index + 1} 位",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                reference_bindings=new_bindings,
            )
        return await self.get_shot(new_plan_id)

    async def discard_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotLifecycleUpdate,
    ) -> list[ShotPlanResponse]:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            if plan.lifecycle_status == ShotLifecycleStatus.DISCARDED:
                return await self.list_shots(project.id)
            active = [item for item in plans if item.lifecycle_status == ShotLifecycleStatus.ACTIVE]
            if len(active) <= 1:
                raise _fail(409, "last_active_shot", "创作方案至少需要保留一个有效分镜")
            revision_id = uuid4()
            discarded_plan = plan.model_copy(
                update={
                    "lifecycle_status": ShotLifecycleStatus.DISCARDED,
                    "revision_id": revision_id,
                    "updated_at": utc_now(),
                }
            )
            next_active = [item for item in active if item.id != plan.id]
            discarded = [
                item for item in plans if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ] + [discarded_plan]
            next_plans, changed_plans = self._resequence_plans(
                next_active,
                discarded,
                revision_id,
                force_ids={plan.id},
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"舍弃分镜 {plan.index}",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(plan.project_id)

    async def restore_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotLifecycleUpdate,
    ) -> list[ShotPlanResponse]:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            if plan.lifecycle_status == ShotLifecycleStatus.ACTIVE:
                return await self.list_shots(project.id)
            active = sorted(
                (item for item in plans if item.lifecycle_status == ShotLifecycleStatus.ACTIVE),
                key=lambda item: item.index,
            )
            insert_index = len(active)
            if payload.insert_after_shot_plan_id is not None:
                after_index = next(
                    (
                        index
                        for index, item in enumerate(active)
                        if item.id == payload.insert_after_shot_plan_id
                    ),
                    None,
                )
                if after_index is None:
                    raise _fail(422, "insert_position_invalid", "恢复分镜的插入位置无效")
                insert_index = after_index + 1
            revision_id = uuid4()
            restored = plan.model_copy(
                update={
                    "lifecycle_status": ShotLifecycleStatus.ACTIVE,
                    "revision_id": revision_id,
                    "updated_at": utc_now(),
                }
            )
            active.insert(insert_index, restored)
            discarded = [
                item
                for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.DISCARDED and item.id != plan.id
            ]
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
                force_ids={plan.id},
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"恢复分镜并插入到第 {insert_index + 1} 位",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(plan.project_id)

    async def reorder_shots(
        self,
        project_id: UUID,
        payload: ShotPlanReorder,
    ) -> list[ShotPlanResponse]:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            active_by_id = {
                item.id: item
                for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
            }
            requested_ids = payload.ordered_shot_plan_ids
            if set(requested_ids) != set(active_by_id):
                raise _fail(
                    422,
                    "shot_order_incomplete",
                    "排序必须包含当前全部有效分镜，且不能包含已舍弃分镜",
                )
            current_ids = [
                item.id for item in sorted(active_by_id.values(), key=lambda item: item.index)
            ]
            if requested_ids == current_ids:
                return await self.list_shots(project.id)
            revision_id = uuid4()
            active = [active_by_id[item_id] for item_id in requested_ids]
            discarded = [
                item for item in plans if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ]
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                "调整有效分镜顺序",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(project_id)

    async def get_shot(self, shot_plan_id: UUID) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        project, _ = await self._ensure_project_shots(project)
        plan = await self._require_shot(shot_plan_id)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        await self._restore_legacy_archived_video_candidates(project, plan)
        runs = await self.repository.list_generation_runs(project.id, plan.id)
        preparation = await self.repository.get_video_clip_preparation(plan.id)
        if preparation is not None:
            preparation = _apply_video_preparation_policy(preparation)
        if preparation is not None and (
            plan.video_status != WorkflowItemStatus.APPROVED
            or preparation.candidate_id != plan.approved_video_candidate_id
        ):
            preparation = preparation.model_copy(
                update={
                    "status": VideoClipPreparationStatus.STALE,
                    "blocker_messages": ["已采用视频发生变化，需要重新完成剪辑准备"],
                    "warning_messages": [],
                }
            )
        return ShotPlanDetailResponse(
            plan=plan,
            reference_bindings=await self.repository.list_reference_bindings(plan.id),
            current_revision_id=project.current_revision_id,
            generation_runs=[await self._run_response(run) for run in reversed(runs)],
            approval_events=await self.repository.list_approval_events(
                project.id,
                plan.id,
            ),
            video_preparation=(
                self._video_preparation_response(preparation) if preparation is not None else None
            ),
        )

    async def prepare_depth_control_job(
        self,
        shot_plan_id: UUID,
        expected_revision_id: UUID | None,
    ) -> DepthControlJobContext:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        if expected_revision_id is not None:
            self._require_expected_revision(project, expected_revision_id)
        video = await self.repository.get_video(project.video_id)
        if video is None:
            raise _fail(404, "source_video_not_found", "创作方案原视频不存在")
        try:
            if video.stored_relative_path:
                source_path = self.workspace.resolve(video.stored_relative_path)
                source_relative_path = video.stored_relative_path
            elif video.stored_path:
                source_path = await asyncio.to_thread(
                    _resolve_workspace_source_path,
                    video.stored_path,
                    self.workspace.root,
                )
                source_relative_path = self.workspace.relative(source_path)
            else:
                raise ValueError("missing source path")
        except (OSError, ValueError, WorkspaceError) as exc:
            raise _fail(409, "source_video_path_invalid", "原视频文件路径无效") from exc
        fingerprint_payload = json.dumps(
            {
                "source_video_id": str(video.id),
                "source_relative_path": source_relative_path,
                "source_sha256": video.sha256,
                "shot_plan_id": str(plan.id),
                "start_seconds": round(plan.start_seconds, 6),
                "end_seconds": round(plan.end_seconds, 6),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return DepthControlJobContext(
            project=project,
            shot=plan,
            source_path=source_path,
            source_relative_path=source_relative_path,
            source_video_id=video.id,
            source_fingerprint=hashlib.sha256(fingerprint_payload).hexdigest(),
        )

    async def commit_depth_control_job(
        self,
        job: DepthControlJob,
        asset: DepthControlAsset,
    ) -> UUID:
        lock = await self._project_lock(job.project_id)
        try:
            async with lock:
                project = await self._require_project(job.project_id)
                plan = await self._require_shot(job.shot_plan_id)
                current = await self.prepare_depth_control_job(plan.id, None)
                if current.source_fingerprint != job.source_fingerprint:
                    raise _fail(
                        409,
                        "depth_source_changed",
                        "原视频或分镜时间范围已变化，当前深度结果不会自动启用，请重新生成。",
                    )
                revision_id = uuid4()
                now = utc_now()
                prior_assets = [
                    item.model_copy(update={"enabled": False, "updated_at": now})
                    if item.enabled
                    else item
                    for item in plan.depth_control_assets
                ]
                has_prior_video = plan.approved_video_candidate_id is not None
                updated = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        "depth_control_assets": [*prior_assets, asset],
                        "video_status": (
                            WorkflowItemStatus.STALE
                            if has_prior_video
                            else WorkflowItemStatus.DRAFT
                        ),
                        "approved_video_candidate_id": None,
                        "updated_at": now,
                    }
                )
                plans = await self.repository.list_shot_plans(project.id)
                next_plans = [updated if item.id == updated.id else item for item in plans]
                next_project = project.model_copy(
                    update={
                        "status": ProductionProjectStatus.ACTIVE,
                        "active_step": ProductionStep.SHOT_VIDEOS,
                        "updated_at": now,
                    }
                )
                next_project, revision = await self._prepare_revision(
                    next_project,
                    ProductionChangeKind.REFERENCE_CHANGED,
                    f"为分镜 {updated.index} 生成全场景深度控制视频",
                    revision_id=revision_id,
                    shot_plans=next_plans,
                    reference_bindings=await self._all_bindings(next_plans),
                )
                await self.repository.save_production_bundle(
                    next_project,
                    revision,
                    shot_plans=[updated],
                )
        except Exception:
            deletion = await self.depth_controls.stage_content_deletion(asset)
            await self.depth_controls.finalize_staged_content(deletion)
            raise
        return revision_id

    async def create_depth_control(
        self,
        shot_plan_id: UUID,
        payload: DepthControlCreate,
    ) -> DepthControlCreateResponse:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        video = await self.repository.get_video(project.video_id)
        if video is None:
            raise _fail(404, "source_video_not_found", "创作方案原视频不存在")
        try:
            if video.stored_relative_path:
                source_path = self.workspace.resolve(video.stored_relative_path)
            elif video.stored_path:
                source_path = await asyncio.to_thread(
                    _resolve_workspace_source_path,
                    video.stored_path,
                    self.workspace.root,
                )
            else:
                raise ValueError("missing source path")
        except (OSError, ValueError, WorkspaceError) as exc:
            raise _fail(409, "source_video_path_invalid", "原视频文件路径无效") from exc
        try:
            asset = await self.depth_controls.generate(
                project=project,
                shot=plan,
                source_path=source_path,
                source_video_id=video.id,
            )
        except DepthControlServiceError as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc

        lock = await self._project_lock(project.id)
        try:
            async with lock:
                project = await self._require_project(project.id)
                self._require_expected_revision(project, payload.expected_revision_id)
                plan = await self._require_shot(plan.id)
                revision_id = uuid4()
                prior_assets = [
                    item.model_copy(update={"enabled": False, "updated_at": utc_now()})
                    if item.enabled
                    else item
                    for item in plan.depth_control_assets
                ]
                has_prior_video = plan.approved_video_candidate_id is not None
                updated = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        "depth_control_assets": [*prior_assets, asset],
                        "video_status": (
                            WorkflowItemStatus.STALE
                            if has_prior_video
                            else WorkflowItemStatus.DRAFT
                        ),
                        "approved_video_candidate_id": None,
                        "updated_at": utc_now(),
                    }
                )
                plans = await self.repository.list_shot_plans(project.id)
                next_plans = [updated if item.id == updated.id else item for item in plans]
                next_project = project.model_copy(
                    update={
                        "status": ProductionProjectStatus.ACTIVE,
                        "active_step": ProductionStep.SHOT_VIDEOS,
                        "updated_at": utc_now(),
                    }
                )
                next_project, revision = await self._prepare_revision(
                    next_project,
                    ProductionChangeKind.REFERENCE_CHANGED,
                    f"为分镜 {updated.index} 生成全场景深度控制视频",
                    revision_id=revision_id,
                    shot_plans=next_plans,
                    reference_bindings=await self._all_bindings(next_plans),
                )
                await self.repository.save_production_bundle(
                    next_project,
                    revision,
                    shot_plans=[updated],
                )
        except Exception:
            deletion = await self.depth_controls.stage_content_deletion(asset)
            await self.depth_controls.finalize_staged_content(deletion)
            raise
        return DepthControlCreateResponse(current_revision_id=revision_id, asset=asset)

    async def update_depth_control(
        self,
        shot_plan_id: UUID,
        asset_id: UUID,
        payload: DepthControlUpdate,
    ) -> DepthControlUpdateResponse:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plan = await self._require_shot(plan.id)
            target = next((item for item in plan.depth_control_assets if item.id == asset_id), None)
            if target is None:
                raise _fail(404, "depth_control_not_found", "当前分镜中不存在该深度控制视频")
            if payload.enabled and not target.usable_for_generation:
                raise _fail(422, "depth_control_not_ready", "该深度控制视频尚未通过质检")
            now = utc_now()
            assets = [
                item.model_copy(
                    update={
                        "enabled": payload.enabled if item.id == asset_id else False,
                        "updated_at": now,
                    }
                )
                if item.id == asset_id or (payload.enabled and item.enabled)
                else item
                for item in plan.depth_control_assets
            ]
            revision_id = uuid4()
            updated = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "depth_control_assets": assets,
                    "video_status": (
                        WorkflowItemStatus.STALE
                        if plan.approved_video_candidate_id is not None
                        else WorkflowItemStatus.DRAFT
                    ),
                    "approved_video_candidate_id": None,
                    "updated_at": now,
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated if item.id == updated.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"{'启用' if payload.enabled else '停用'}分镜 {updated.index} 的深度控制视频",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=await self._all_bindings(next_plans),
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated],
            )
        selected = next(item for item in assets if item.id == asset_id)
        return DepthControlUpdateResponse(current_revision_id=revision_id, asset=selected)

    async def delete_depth_control(
        self,
        shot_plan_id: UUID,
        asset_id: UUID,
        expected_revision_id: UUID,
    ) -> DepthControlDeleteResponse:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        lock = await self._project_lock(project.id)
        staged_deletion = None
        revision_id = uuid4()
        async with lock:
            project = await self._require_project(project.id)
            self._require_expected_revision(project, expected_revision_id)
            plan = await self._require_shot(plan.id)
            target = next((item for item in plan.depth_control_assets if item.id == asset_id), None)
            if target is None:
                raise _fail(404, "depth_control_not_found", "当前分镜中不存在该深度控制视频")
            try:
                staged_deletion = await self.depth_controls.stage_content_deletion(target)
            except DepthControlServiceError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            updated = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "depth_control_assets": [
                        item for item in plan.depth_control_assets if item.id != asset_id
                    ],
                    "video_status": (
                        WorkflowItemStatus.STALE
                        if plan.approved_video_candidate_id is not None
                        else WorkflowItemStatus.DRAFT
                    ),
                    "approved_video_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated if item.id == updated.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": utc_now()})
            try:
                next_project, revision = await self._prepare_revision(
                    next_project,
                    ProductionChangeKind.REFERENCE_CHANGED,
                    f"删除分镜 {updated.index} 的深度控制视频",
                    revision_id=revision_id,
                    shot_plans=next_plans,
                    reference_bindings=await self._all_bindings(next_plans),
                )
                await self.repository.save_production_bundle(
                    next_project,
                    revision,
                    shot_plans=[updated],
                )
            except Exception:
                assert staged_deletion is not None
                await self.depth_controls.restore_staged_content(staged_deletion)
                raise
        assert staged_deletion is not None
        removed = await self.depth_controls.finalize_staged_content(staged_deletion)
        return DepthControlDeleteResponse(
            current_revision_id=revision_id,
            asset_id=asset_id,
            local_content_removed=removed,
            cleanup_warning=None if removed else "记录已删除，但本地文件仍待清理",
        )

    async def preview_analysis_update(
        self,
        project_id: UUID,
        target_analysis_id: UUID | None = None,
    ) -> ProductionAnalysisUpdatePreview:
        project = await self._require_project(project_id)
        record = await self.repository.get_record(project.record_id)
        if record is None:
            raise _fail(404, "record_not_found", "创作方案所属分析记录不存在")
        target_id = target_analysis_id or record.latest_analysis_id or project.base_analysis_id
        prompt_source_id = project.prompt_source_analysis_id or project.base_analysis_id
        _, prompt_base_report = await self._completed_analysis(record, prompt_source_id)
        _, structural_base_report = await self._completed_analysis(
            record,
            project.base_analysis_id,
        )
        _, target_report = await self._completed_analysis(record, target_id)
        plans = await self.repository.list_shot_plans(project.id)
        if not plans:
            project, plans = await self._ensure_project_shots(project)
        return self._build_analysis_update_preview(
            project,
            prompt_base_report,
            target_report,
            plans,
            structural_base_report=structural_base_report,
        )

    async def sync_analysis_prompts(
        self,
        project_id: UUID,
        payload: ProductionPromptSyncRequest,
    ) -> ProductionProjectDetail:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            record = await self.repository.get_record(project.record_id)
            if record is None:
                raise _fail(404, "record_not_found", "创作方案所属分析记录不存在")
            prompt_source_id = project.prompt_source_analysis_id or project.base_analysis_id
            _, prompt_base_report = await self._completed_analysis(
                record,
                prompt_source_id,
            )
            _, structural_base_report = await self._completed_analysis(
                record,
                project.base_analysis_id,
            )
            _, target_report = await self._completed_analysis(
                record,
                payload.target_analysis_id,
            )
            plans = await self.repository.list_shot_plans(project.id)
            preview = self._build_analysis_update_preview(
                project,
                prompt_base_report,
                target_report,
                plans,
                structural_base_report=structural_base_report,
            )
            if not preview.update_available:
                raise _fail(409, "analysis_prompts_current", "当前方案提示词已经是最新版本")
            if not preview.compatible:
                raise _fail(
                    409,
                    "analysis_structure_changed",
                    "新分析没有可安全一一对应的提示词字段，请等待结构同步功能",
                )

            valid_fields = {
                (shot.shot_plan_id, field.field_key): field
                for shot in preview.shots
                for field in shot.fields
            }
            decisions = {
                (item.shot_plan_id, item.field_key): item.choice for item in payload.decisions
            }
            unknown = set(decisions) - set(valid_fields)
            if unknown:
                raise _fail(
                    422,
                    "invalid_prompt_sync_decision",
                    "提示词同步选择已失效，请刷新差异后重试",
                )

            target_templates = {
                item.source_shot_id: item
                for item in self._initial_shot_plans(project, target_report, uuid4())
            }
            revision_id = uuid4()
            now = utc_now()
            changed_plans: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            synced_field_count = 0
            preview_by_plan = {item.shot_plan_id: item for item in preview.shots}

            for plan in plans:
                shot_diff = preview_by_plan.get(plan.id)
                target = target_templates.get(plan.source_shot_id)
                if shot_diff is None or target is None:
                    next_plans.append(plan)
                    continue

                next_beats = list(plan.visual_beats)
                next_video_prompt = plan.video_prompt
                plan_changed = False
                target_beats = {item.index: item for item in target.visual_beats}
                for field in shot_diff.fields:
                    choice = decisions.get(
                        (plan.id, field.field_key),
                        field.suggested_choice,
                    )
                    if choice != ProductionPromptSyncChoice.USE_LATEST:
                        continue
                    if field.field_kind == "video_prompt":
                        if next_video_prompt != field.latest_value:
                            next_video_prompt = field.latest_value
                            plan_changed = True
                            synced_field_count += 1
                        continue
                    beat_index = field.visual_beat_index
                    target_beat = target_beats.get(beat_index or -1)
                    if target_beat is None:
                        continue
                    next_beats = [
                        beat.model_copy(
                            update={
                                "image_prompt": field.latest_value,
                                "updated_at": now,
                            }
                        )
                        if beat.index == beat_index
                        else beat
                        for beat in next_beats
                    ]
                    plan_changed = True
                    synced_field_count += 1

                if plan_changed:
                    updated = _sync_shot_visual_beats(
                        plan,
                        next_beats,
                        revision_id=revision_id,
                        invalidate_video=False,
                    ).model_copy(
                        update={
                            "video_prompt": next_video_prompt,
                            "revision_id": revision_id,
                            "updated_at": now,
                        }
                    )
                    changed_plans.append(updated)
                    next_plans.append(updated)
                else:
                    next_plans.append(plan)

            updated_project = project.model_copy(
                update={
                    "prompt_source_analysis_id": target_report.analysis_id,
                    "source_prompt_package_id": target_report.prompt_package.id,
                    "updated_at": now,
                }
            )
            updated_project, revision = await self._prepare_revision(
                updated_project,
                ProductionChangeKind.ANALYSIS_PROMPTS_SYNCED,
                f"同步新分析提示词，共更新 {synced_field_count} 个字段",
                revision_id=revision_id,
                report=target_report,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                updated_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.get_project(project_id)

    def _build_analysis_update_preview(
        self,
        project: ProductionProject,
        base_report: AnalysisReport,
        target_report: AnalysisReport,
        plans: list[ShotPlan],
        *,
        structural_base_report: AnalysisReport | None = None,
    ) -> ProductionAnalysisUpdatePreview:
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无可同步的版本")

        base_templates = {
            item.source_shot_id: item
            for item in self._initial_shot_plans(project, base_report, uuid4())
        }
        target_templates = {
            item.source_shot_id: item
            for item in self._initial_shot_plans(project, target_report, uuid4())
        }
        current_by_source = {
            item.source_shot_id: item
            for item in plans
            if item.source_kind == ShotSourceKind.ANALYSIS
        }
        structural_report = structural_base_report or base_report
        structural_templates = {
            item.source_shot_id: item
            for item in self._initial_shot_plans(project, structural_report, uuid4())
        }
        base_ids = set(structural_templates)
        target_ids = set(target_templates)
        structural_messages: list[str] = []
        added = sorted(target_ids - base_ids)
        removed = sorted(base_ids - target_ids)
        if added:
            structural_messages.append(f"新分析增加 {len(added)} 个分镜")
        if removed:
            structural_messages.append(f"新分析减少 {len(removed)} 个分镜")
        missing_current = sorted(base_ids - set(current_by_source))
        if missing_current:
            structural_messages.append(f"当前方案缺少 {len(missing_current)} 个原分析分镜")

        target_titles = {item.id: item.title for item in target_report.shots}
        shot_diffs: list[ProductionShotPromptDiff] = []
        automatic_count = 0
        conflict_count = 0

        for source_id in sorted(
            set(base_templates) & target_ids & set(current_by_source),
            key=lambda value: current_by_source[value].index,
        ):
            base = base_templates[source_id]
            current = current_by_source[source_id]
            latest = target_templates[source_id]
            base_beats = {item.index: item for item in base.visual_beats}
            current_beats = {item.index: item for item in current.visual_beats}
            latest_beats = {item.index: item for item in latest.visual_beats}
            if set(base_beats) != set(latest_beats) or set(base_beats) != set(current_beats):
                structural_messages.append(f"分镜 {current.index} 的画面数量或顺序发生变化")

            fields: list[ProductionPromptFieldDiff] = []
            for beat_index in sorted(set(base_beats) & set(current_beats) & set(latest_beats)):
                if set(base_beats) != set(latest_beats) or set(base_beats) != set(current_beats):
                    continue
                base_value = base_beats[beat_index].image_prompt
                current_value = current_beats[beat_index].image_prompt
                latest_value = latest_beats[beat_index].image_prompt
                if self._same_prompt(current_value, latest_value):
                    continue
                manually_edited = not self._same_prompt(current_value, base_value)
                suggested = (
                    ProductionPromptSyncChoice.KEEP_CURRENT
                    if manually_edited
                    else ProductionPromptSyncChoice.USE_LATEST
                )
                fields.append(
                    ProductionPromptFieldDiff(
                        field_key=f"visual_beat:{beat_index}:image_prompt",
                        field_kind="image_prompt",
                        label=f"画面 {beat_index} 图片提示词",
                        visual_beat_index=beat_index,
                        base_value=base_value,
                        current_value=current_value,
                        latest_value=latest_value,
                        manually_edited=manually_edited,
                        suggested_choice=suggested,
                    )
                )
                if suggested == ProductionPromptSyncChoice.KEEP_CURRENT:
                    conflict_count += 1
                else:
                    automatic_count += 1

            if not self._same_prompt(current.video_prompt, latest.video_prompt):
                manually_edited = not self._same_prompt(
                    current.video_prompt,
                    base.video_prompt,
                )
                suggested = (
                    ProductionPromptSyncChoice.KEEP_CURRENT
                    if manually_edited
                    else ProductionPromptSyncChoice.USE_LATEST
                )
                fields.append(
                    ProductionPromptFieldDiff(
                        field_key="video_prompt",
                        field_kind="video_prompt",
                        label="视频提示词",
                        base_value=base.video_prompt,
                        current_value=current.video_prompt,
                        latest_value=latest.video_prompt,
                        manually_edited=manually_edited,
                        suggested_choice=suggested,
                    )
                )
                if suggested == ProductionPromptSyncChoice.KEEP_CURRENT:
                    conflict_count += 1
                else:
                    automatic_count += 1

            if fields:
                shot_diffs.append(
                    ProductionShotPromptDiff(
                        shot_plan_id=current.id,
                        source_shot_id=source_id,
                        index=current.index,
                        title=target_titles.get(source_id) or f"分镜 {current.index}",
                        fields=fields,
                    )
                )

        structural_messages = list(dict.fromkeys(structural_messages))
        changed_field_count = automatic_count + conflict_count
        prompt_source_id = project.prompt_source_analysis_id or project.base_analysis_id
        target_is_new = target_report.analysis_id != prompt_source_id
        structural_change_detected = bool(structural_messages)
        return ProductionAnalysisUpdatePreview(
            project_id=project.id,
            current_revision_id=project.current_revision_id,
            base_analysis_id=project.base_analysis_id,
            prompt_source_analysis_id=prompt_source_id,
            target_analysis_id=target_report.analysis_id,
            target_prompt_package_id=target_report.prompt_package.id,
            target_generated_at=target_report.generated_at,
            update_available=(target_is_new and changed_field_count > 0)
            or structural_change_detected,
            compatible=changed_field_count > 0,
            structural_change_detected=structural_change_detected,
            structural_change_messages=structural_messages,
            changed_field_count=changed_field_count,
            automatic_field_count=automatic_count,
            conflict_field_count=conflict_count,
            shots=shot_diffs,
        )

    @staticmethod
    def _same_prompt(left: str, right: str) -> bool:
        return " ".join(left.split()) == " ".join(right.split())

    async def _restore_legacy_archived_video_candidates(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> None:
        """Restore video candidates archived by the former latest-run-only policy.

        Video candidates did not previously support an explicit user archive action, so an
        archived video without an archive reason is a safe, idempotent legacy-repair target.
        Missing files remain archived and future explicit archives can opt out by recording
        ``archive_reason`` in the quality report.
        """

        for run in await self.repository.list_generation_runs(project.id, plan.id):
            if run.kind != GenerationKind.VIDEO:
                continue
            for candidate in await self.repository.list_generation_candidates(run.id):
                if (
                    candidate.status != GenerationCandidateStatus.ARCHIVED
                    or candidate.archive_reason is not None
                    or candidate.quality_report.get("archive_reason")
                ):
                    continue
                try:
                    candidate_path = _filesystem_path(
                        self.workspace.resolve(candidate.relative_path)
                    )
                except (OSError, WorkspaceError):
                    continue
                if not candidate_path.is_file():
                    continue
                restored_status = (
                    GenerationCandidateStatus.SELECTED
                    if candidate.id == plan.approved_video_candidate_id
                    else GenerationCandidateStatus.READY
                )
                await self.repository.save_generation_candidate(
                    candidate.model_copy(update={"status": restored_status})
                )

    async def _save_visual_beat_plan(
        self,
        project: ProductionProject,
        updated_plan: ShotPlan,
        *,
        revision_id: UUID,
        summary: str,
        change_kind: ProductionChangeKind = ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
    ) -> None:
        plans = await self.repository.list_shot_plans(project.id)
        next_plans = [updated_plan if item.id == updated_plan.id else item for item in plans]
        next_project = project.model_copy(
            update={
                "status": ProductionProjectStatus.ACTIVE,
                "active_step": ProductionStep.SHOT_IMAGES,
                "updated_at": utc_now(),
            }
        )
        next_project, revision = await self._prepare_revision(
            next_project,
            change_kind,
            summary,
            revision_id=revision_id,
            shot_plans=next_plans,
        )
        await self.repository.save_production_bundle(
            next_project,
            revision,
            shot_plans=[updated_plan],
        )

    async def create_visual_beat(
        self,
        shot_plan_id: UUID,
        payload: ShotVisualBeatCreate,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beats = sorted(plan.visual_beats, key=lambda item: item.index)
            if len(beats) >= 20:
                raise _fail(409, "visual_beat_limit_reached", "一个分镜最多包含 20 个画面")
            insert_index = len(beats)
            if payload.insert_after_visual_beat_id is not None:
                found = next(
                    (
                        index
                        for index, item in enumerate(beats)
                        if item.id == payload.insert_after_visual_beat_id
                    ),
                    None,
                )
                if found is None:
                    raise _fail(422, "visual_beat_insert_position_invalid", "画面插入位置不存在")
                insert_index = found + 1

            beat_id = uuid4()
            source_path: str | None = None
            source_url: str | None = None
            source_sha256: str | None = None
            source_origin = "blank"
            timestamp = payload.source_timestamp_seconds
            if timestamp is not None:
                if timestamp < plan.start_seconds or timestamp > plan.end_seconds:
                    raise _fail(
                        422,
                        "visual_beat_timestamp_out_of_range",
                        "画面源帧必须位于当前分镜范围内",
                    )
                video = await self.repository.get_video(project.video_id)
                if video is None:
                    raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
                destination = (
                    self.workspace.production_shot_root(
                        project.record_id,
                        project.id,
                        plan.id,
                    )
                    / "visual-beats"
                    / str(beat_id)
                    / "source-frame.jpg"
                )
                temporary = destination.parent / ".source-frame.tmp.jpg"
                try:
                    await self.media_processor.extract_frame(
                        self._resolve_video_file(video),
                        float(timestamp),
                        _filesystem_path(temporary),
                    )
                    await asyncio.to_thread(self._validate_keyframe_file, temporary)
                    _filesystem_path(destination).parent.mkdir(parents=True, exist_ok=True)
                    os.replace(_filesystem_path(temporary), _filesystem_path(destination))
                except MediaProcessingError as exc:
                    raise _fail(422, exc.code, str(exc)) from exc
                finally:
                    _filesystem_path(temporary).unlink(missing_ok=True)
                source_path = self.workspace.relative(destination)
                source_url = (
                    f"/api/v1/production-shots/{plan.id}/visual-beats/{beat_id}/source-frame"
                )
                source_sha256, _ = await asyncio.to_thread(
                    _frame_sha256_and_dhash,
                    _filesystem_path(destination),
                )
                source_origin = "video_selection"

            prompt = _simplified_text(
                payload.image_prompt,
                field_name="画面图片提示词",
                allow_empty=True,
                max_length=8000,
            )
            new_beat = ShotVisualBeat(
                id=beat_id,
                index=insert_index + 1,
                title=payload.title or f"画面 {insert_index + 1}",
                start_ratio=(
                    payload.start_ratio
                    if payload.start_ratio is not None
                    else insert_index / (len(beats) + 1)
                ),
                end_ratio=(
                    payload.end_ratio
                    if payload.end_ratio is not None
                    else (insert_index + 1) / (len(beats) + 1)
                ),
                source_frame_url=source_url,
                source_frame_relative_path=source_path,
                source_timestamp_seconds=timestamp,
                source_frame_sha256=source_sha256,
                source_origin=source_origin,
                image_prompt=prompt,
                required=payload.required,
                image_status=(WorkflowItemStatus.READY if prompt else WorkflowItemStatus.DRAFT),
            )
            beats.insert(insert_index, new_beat)
            beats = _retime_visual_beats(beats)
            revision_id = uuid4()
            updated_plan = _sync_shot_visual_beats(
                plan,
                beats,
                revision_id=revision_id,
                invalidate_video=True,
            )
            await self._save_visual_beat_plan(
                project,
                updated_plan,
                revision_id=revision_id,
                summary=f"为分镜 {plan.index} 新增画面 {insert_index + 1}",
            )
        return await self.get_shot(plan.id)

    async def update_visual_beat(
        self,
        shot_plan_id: UUID,
        visual_beat_id: UUID,
        payload: ShotVisualBeatUpdate,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(plan, visual_beat_id)
            fields = payload.model_dump(
                exclude={"expected_revision_id", "confirm_stale"},
                exclude_unset=True,
            )
            text_fields = {
                "title": (120, False),
                "image_prompt": (8000, True),
                "transition_to_next_prompt": (2000, True),
            }
            for field, (limit, allow_empty) in text_fields.items():
                if field in fields:
                    fields[field] = _simplified_text(
                        fields[field],
                        field_name="画面字段",
                        allow_empty=allow_empty,
                        max_length=limit,
                    )
            image_inputs_changed = bool(
                {"image_prompt", "image_prompt_mentions", "image_negative_constraints"}
                & fields.keys()
            )
            structural_changed = bool(
                {
                    "start_ratio",
                    "end_ratio",
                    "transition_to_next_type",
                    "transition_to_next_duration_seconds",
                    "transition_to_next_prompt",
                }
                & fields.keys()
            )
            downstream = plan.video_status in {
                WorkflowItemStatus.GENERATING,
                WorkflowItemStatus.REVIEW_REQUIRED,
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }
            if (
                downstream
                and (image_inputs_changed or structural_changed)
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "修改画面会让当前分镜视频及下游结果过期，请确认后重试",
                )
            if image_inputs_changed:
                next_prompt = str(fields.get("image_prompt", beat.image_prompt)).strip()
                fields.update(
                    {
                        "approved_image_candidate_id": None,
                        "image_status": (
                            WorkflowItemStatus.READY if next_prompt else WorkflowItemStatus.DRAFT
                        ),
                    }
                )
            fields["updated_at"] = utc_now()
            updated_beat = beat.model_copy(update=fields)
            beats = [updated_beat if item.id == beat.id else item for item in plan.visual_beats]
            # Validate explicit timing against adjacent beats before persisting.
            validated = ShotPlan.model_validate(
                plan.model_copy(update={"visual_beats": beats}).model_dump(mode="python")
            )
            revision_id = uuid4()
            updated_plan = _sync_shot_visual_beats(
                validated,
                validated.visual_beats,
                revision_id=revision_id,
                invalidate_video=image_inputs_changed or structural_changed,
            )
            await self._save_visual_beat_plan(
                project,
                updated_plan,
                revision_id=revision_id,
                summary=f"更新分镜 {plan.index} 的画面 {beat.index}",
                change_kind=ProductionChangeKind.SHOT_PLAN_CHANGED,
            )
        return await self.get_shot(plan.id)

    async def reorder_visual_beats(
        self,
        shot_plan_id: UUID,
        payload: ShotVisualBeatReorder,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            by_id = {item.id: item for item in plan.visual_beats}
            if set(payload.ordered_visual_beat_ids) != set(by_id):
                raise _fail(422, "visual_beat_order_incomplete", "排序必须包含当前分镜的全部画面")
            beats = _retime_visual_beats(
                [by_id[item_id] for item_id in payload.ordered_visual_beat_ids]
            )
            revision_id = uuid4()
            updated_plan = _sync_shot_visual_beats(
                plan,
                beats,
                revision_id=revision_id,
                invalidate_video=True,
            )
            await self._save_visual_beat_plan(
                project,
                updated_plan,
                revision_id=revision_id,
                summary=f"调整分镜 {plan.index} 的画面顺序",
            )
        return await self.get_shot(plan.id)

    async def delete_visual_beat(
        self,
        shot_plan_id: UUID,
        visual_beat_id: UUID,
        payload: ShotVisualBeatDelete,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(plan, visual_beat_id)
            if len(plan.visual_beats) <= 1:
                raise _fail(409, "last_visual_beat", "一个分镜至少需要保留一个画面")
            downstream = plan.video_status in {
                WorkflowItemStatus.GENERATING,
                WorkflowItemStatus.REVIEW_REQUIRED,
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }
            if downstream and not payload.confirm_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "删除画面会让当前分镜视频及下游结果过期，请确认后重试",
                )
            beats = _retime_visual_beats([item for item in plan.visual_beats if item.id != beat.id])
            revision_id = uuid4()
            updated_plan = _sync_shot_visual_beats(
                plan,
                beats,
                revision_id=revision_id,
                invalidate_video=True,
            )
            await self._save_visual_beat_plan(
                project,
                updated_plan,
                revision_id=revision_id,
                summary=f"删除分镜 {plan.index} 的画面 {beat.index}",
            )
        return await self.get_shot(plan.id)

    async def resolve_visual_beat_source_frame(
        self,
        shot_plan_id: UUID,
        visual_beat_id: UUID,
    ) -> tuple[Path, str]:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        beat = _visual_beat(plan, visual_beat_id)
        path = self._resolve_source_keyframe(
            project,
            _shot_for_visual_beat(plan, beat),
        )
        if path is None:
            raise _fail(404, "visual_beat_source_frame_missing", "当前画面的源帧文件不存在")
        return path, "image/jpeg"

    async def prepare_video_clip(
        self,
        shot_plan_id: UUID,
        payload: VideoClipPreparationUpdate,
    ) -> VideoClipPreparationResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if (
                plan.video_status != WorkflowItemStatus.APPROVED
                or plan.approved_video_candidate_id is None
            ):
                raise _fail(
                    409,
                    "video_approval_required",
                    "请先确认采用一个视频候选，再完成剪辑准备",
                )
            candidate = await self._require_candidate(plan.approved_video_candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if (
                candidate.kind != GenerationKind.VIDEO
                or run.kind != GenerationKind.VIDEO
                or run.project_id != project.id
                or run.shot_plan_id != plan.id
                or candidate.status != GenerationCandidateStatus.SELECTED
            ):
                raise _fail(
                    409,
                    "approved_video_candidate_mismatch",
                    "已采用视频与当前分镜不匹配，请重新选择候选",
                )

            existing = await self.repository.get_video_clip_preparation(plan.id)
            same_candidate = existing is not None and existing.candidate_id == candidate.id
            candidate_duration = float(candidate.duration_seconds or plan.duration_seconds)
            trim_in = float(
                payload.trim_in_seconds
                if payload.trim_in_seconds is not None
                else existing.trim_in_seconds
                if same_candidate
                else 0.0
            )
            trim_out = float(
                payload.trim_out_seconds
                if payload.trim_out_seconds is not None
                else existing.trim_out_seconds
                if same_candidate
                else candidate_duration
            )
            if trim_out - trim_in < 0.2:
                raise _fail(422, "video_trim_too_short", "视频裁剪后至少保留 0.2 秒")
            if trim_in < 0 or trim_out > candidate_duration + 0.05:
                raise _fail(
                    422,
                    "video_trim_out_of_range",
                    f"视频入点和出点必须位于 0–{candidate_duration:.2f} 秒范围内",
                )
            requested_cover = float(
                payload.cover_timestamp_seconds
                if payload.cover_timestamp_seconds is not None
                else (
                    existing.cover_timestamp_seconds
                    if same_candidate
                    else trim_in + (trim_out - trim_in) / 2
                )
            )
            if not trim_in <= requested_cover <= trim_out:
                raise _fail(422, "video_cover_out_of_range", "封面帧必须位于入点和出点之间")

            revision_id = uuid4()
            cover_path = (
                self.workspace.production_paths(project.record_id, project.id).timelines
                / "preparations"
                / str(plan.id)
                / str(revision_id)
                / "cover.webp"
            )
            cover_filesystem_path = _filesystem_path(cover_path.resolve())
            source_path, _ = await self.resolve_candidate_content(candidate.id)
            try:
                inspection = await self.video_inspector.inspect(
                    source_path,
                    cover_filesystem_path,
                    cover_timestamp_seconds=requested_cover,
                    expected_width=candidate.width,
                    expected_height=candidate.height,
                    expected_duration_seconds=candidate.duration_seconds,
                )
            except ProductionVideoInspectionError as exc:
                raise _fail(409, exc.code, str(exc)) from exc
            actual_duration = float(inspection.metadata.duration_seconds)
            if trim_out > actual_duration + 0.05:
                raise _fail(
                    422,
                    "video_trim_out_of_range",
                    f"视频实际时长为 {actual_duration:.2f} 秒，请调整出点",
                )

            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            if report is None:
                raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
            evidence = report.evidence_timeline
            media_evidence = report.media_evidence
            source_audio_url = media_evidence.audio_url if media_evidence else None
            audio_mode = (
                payload.audio_mode
                or (existing.audio_mode if same_candidate else None)
                or (VideoClipAudioMode.SOURCE if source_audio_url else VideoClipAudioMode.MUTED)
            )
            transcript_cues = (
                map_timed_text(
                    evidence.transcript_segments,
                    source_start_seconds=plan.start_seconds,
                    source_end_seconds=plan.end_seconds,
                    kind="transcript",
                )
                if evidence is not None
                else []
            )
            subtitle_cues = (
                map_timed_text(
                    evidence.subtitle_cues,
                    source_start_seconds=plan.start_seconds,
                    source_end_seconds=plan.end_seconds,
                    kind="subtitle",
                )
                if evidence is not None
                else []
            )
            prepared_duration = round(trim_out - trim_in, 3)
            playback_rate, duration_alignment = playback_alignment(
                prepared_duration,
                plan.duration_seconds,
            )
            blockers: list[str] = []
            warning_messages: list[str] = []
            if duration_alignment == "outside_safe_range":
                warning_messages.append(_duration_alignment_warning(playback_rate))
            if audio_mode == VideoClipAudioMode.SOURCE and not source_audio_url:
                blockers.append("基础分析没有可用原音轨，请改为静音或重新分析音频")
            quality_status = VideoQualityStatus(inspection.quality_status)
            if quality_status == VideoQualityStatus.FAILED:
                blockers.append("视频技术质检未通过")
            preparation_status = (
                VideoClipPreparationStatus.BLOCKED if blockers else VideoClipPreparationStatus.READY
            )
            now = utc_now()
            preparation = VideoClipPreparation(
                id=existing.id if existing is not None else uuid4(),
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                trim_in_seconds=round(trim_in, 3),
                trim_out_seconds=round(trim_out, 3),
                prepared_duration_seconds=prepared_duration,
                timeline_duration_seconds=round(plan.duration_seconds, 3),
                video_playback_rate=playback_rate,
                duration_alignment=duration_alignment,
                cover_timestamp_seconds=inspection.cover_timestamp_seconds,
                cover_relative_path=self.workspace.relative(cover_path),
                audio_mode=audio_mode,
                audio_mapping_strategy=(
                    "preserve_source_timeline"
                    if audio_mode == VideoClipAudioMode.SOURCE and source_audio_url
                    else "source_audio_unavailable"
                    if audio_mode == VideoClipAudioMode.SOURCE
                    else "muted"
                ),
                source_audio_url=source_audio_url,
                source_audio_start_seconds=round(plan.start_seconds, 3),
                source_audio_end_seconds=round(plan.end_seconds, 3),
                transcript_cues=transcript_cues,
                subtitle_cues=subtitle_cues,
                quality_status=quality_status,
                quality_report=inspection.quality_report,
                status=preparation_status,
                blocker_messages=blockers,
                warning_messages=warning_messages,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
            )
            updated_candidate = candidate.model_copy(
                update={
                    "width": inspection.metadata.width,
                    "height": inspection.metadata.height,
                    "duration_seconds": inspection.metadata.duration_seconds,
                    "quality_report": inspection.quality_report,
                }
            )
            updated_plan = plan.model_copy(update={"revision_id": revision_id, "updated_at": now})
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            preparations = await self.repository.list_video_clip_preparations(project.id)
            next_preparations = [item for item in preparations if item.shot_plan_id != plan.id] + [
                preparation
            ]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_PREPARATION_CHANGED,
                f"更新分镜 {plan.index} 的剪辑准备参数",
                revision_id=revision_id,
                shot_plans=next_plans,
                video_clip_preparations=next_preparations,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                video_clip_preparations=[preparation],
            )
            await asyncio.to_thread(
                self._update_candidate_quality_metadata,
                project,
                plan,
                run,
                updated_candidate,
            )
        return self._video_preparation_response(preparation)

    async def resolve_video_preparation_cover(
        self,
        shot_plan_id: UUID,
    ) -> tuple[Path, str]:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        preparation = await self.repository.get_video_clip_preparation(plan.id)
        if preparation is None:
            raise _fail(404, "video_preparation_missing", "当前分镜尚未生成剪辑封面")
        try:
            candidate = self.workspace.resolve(preparation.cover_relative_path).resolve()
        except WorkspaceError as exc:
            raise _fail(409, "invalid_video_cover_path", "剪辑封面路径无效") from exc
        root = self.workspace.production_paths(project.record_id, project.id).timelines.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise _fail(409, "invalid_video_cover_path", "剪辑封面路径无效") from exc
        filesystem_candidate = _filesystem_path(candidate)
        if not filesystem_candidate.is_file():
            raise _fail(404, "video_cover_missing", "剪辑封面文件不存在")
        return filesystem_candidate, "image/webp"

    async def update_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotPlanUpdate,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            image_changed = bool(
                fields
                & {
                    "image_prompt",
                    "image_prompt_mentions",
                    "image_negative_constraints",
                    "locks",
                    "reference_bindings",
                }
            )
            video_changed = bool(
                fields
                & {
                    "video_prompt",
                    "video_prompt_mentions",
                    "video_negative_constraints",
                    "managed_asset_bindings",
                    "video_reference_bindings",
                    "locks",
                }
            )
            requires_confirmation = (
                image_changed and plan.image_status == WorkflowItemStatus.APPROVED
            ) or (video_changed and plan.video_status == WorkflowItemStatus.APPROVED)
            if requires_confirmation and not payload.confirm_stale:
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "该修改会使已审批结果过期，请确认影响范围后重试",
                )

            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            current_bindings = [item for item in all_bindings if item.shot_plan_id == plan.id]
            next_bindings = current_bindings
            removed_binding_ids: list[UUID] = []
            normalized_payload = payload
            if "image_prompt_mentions" in fields:
                normalized_mentions = await self._validate_prompt_mentions(
                    project,
                    payload.image_prompt_mentions or [],
                )
                normalized_payload = payload.model_copy(
                    update={"image_prompt_mentions": normalized_mentions}
                )
            if "managed_asset_bindings" in fields:
                requested_bindings = payload.managed_asset_bindings or []
                if requested_bindings and self.managed_assets is None:
                    raise _fail(
                        409,
                        "managed_asset_service_unavailable",
                        "供应商托管资产目录服务尚未配置",
                    )
                verified_bindings = []
                for binding in requested_bindings:
                    try:
                        verified_bindings.append(
                            await self.managed_assets.verify_binding(binding)  # type: ignore[union-attr]
                        )
                    except ManagedAssetServiceError as exc:
                        raise _fail(exc.status_code, exc.code, str(exc)) from exc
                normalized_payload = normalized_payload.model_copy(
                    update={"managed_asset_bindings": verified_bindings}
                )
            if "video_prompt_mentions" in fields:
                normalized_video_mentions = await self._validate_video_prompt_mentions(
                    project,
                    plan,
                    payload.video_prompt_mentions or [],
                    managed_asset_bindings=(
                        normalized_payload.managed_asset_bindings
                        if "managed_asset_bindings" in fields
                        else plan.managed_asset_bindings
                    ),
                    video_reference_bindings=(
                        normalized_payload.video_reference_bindings
                        if "video_reference_bindings" in fields
                        else plan.video_reference_bindings
                    ),
                )
                normalized_payload = normalized_payload.model_copy(
                    update={"video_prompt_mentions": normalized_video_mentions}
                )
            if "reference_bindings" in fields or "image_prompt_mentions" in fields:
                binding_inputs = (
                    payload.reference_bindings or []
                    if "reference_bindings" in fields
                    else [
                        ReferenceBindingInput(
                            reference_asset_id=item.reference_asset_id,
                            role=item.role,
                            weight=item.weight,
                            crop_hint=item.crop_hint,
                            notes=item.notes,
                        )
                        for item in current_bindings
                    ]
                )
                binding_inputs = await self._append_mention_bindings(
                    project,
                    binding_inputs,
                    normalized_payload.image_prompt_mentions
                    if "image_prompt_mentions" in fields
                    else plan.image_prompt_mentions,
                )
                next_bindings = await self._build_bindings(
                    project,
                    plan,
                    binding_inputs,
                )
                removed_binding_ids = [item.id for item in current_bindings]
                all_bindings = [
                    item for item in all_bindings if item.shot_plan_id != plan.id
                ] + next_bindings

            revision_id = uuid4()
            updated = self._apply_shot_fields(
                plan,
                normalized_payload,
                fields,
                revision_id,
                image_changed=image_changed,
                video_changed=video_changed,
            )
            next_plans = [updated if item.id == updated.id else item for item in plans]
            next_active_step = project.active_step
            if image_changed:
                next_active_step = ProductionStep.SHOT_IMAGES
            elif video_changed:
                next_active_step = ProductionStep.SHOT_VIDEOS
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": next_active_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                f"更新分镜 {updated.index} 创作计划",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated],
                reference_bindings=(
                    next_bindings
                    if "reference_bindings" in fields or "image_prompt_mentions" in fields
                    else None
                ),
                remove_reference_binding_ids=removed_binding_ids,
            )
        return await self.get_shot(shot_plan_id)

    async def bulk_update_shots(
        self,
        project_id: UUID,
        payload: ShotPlanBulkUpdate,
    ) -> list[ShotPlanResponse]:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            plans_by_id = {item.id: item for item in plans}
            missing = [
                item.shot_plan_id
                for item in payload.updates
                if item.shot_plan_id not in plans_by_id
            ]
            if missing:
                raise _fail(404, "shot_plan_not_found", "批量更新包含不存在的分镜")
            if any(
                plans_by_id[item.shot_plan_id].lifecycle_status != ShotLifecycleStatus.ACTIVE
                for item in payload.updates
            ):
                raise _fail(409, "shot_discarded", "已舍弃分镜需要先恢复后才能修改")

            impacted_approved = any(
                (
                    plans_by_id[item.shot_plan_id].image_status
                    == WorkflowItemStatus.APPROVED
                    and self._image_fields_changed(item)
                )
                or (
                    plans_by_id[item.shot_plan_id].video_status
                    == WorkflowItemStatus.APPROVED
                    and self._video_fields_changed(item)
                )
                for item in payload.updates
            )
            if impacted_approved and not payload.confirm_stale:
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "批量修改会使已审批结果过期，请确认影响范围后重试",
                )

            revision_id = uuid4()
            all_bindings = await self._all_bindings(plans)
            changed_plans: list[ShotPlan] = []
            new_bindings: list[ReferenceBinding] = []
            removed_binding_ids: list[UUID] = []
            for item in payload.updates:
                current = plans_by_id[item.shot_plan_id]
                fields = item.model_fields_set - {"shot_plan_id"}
                normalized_item = item
                if "image_prompt_mentions" in fields:
                    normalized_mentions = await self._validate_prompt_mentions(
                        project,
                        item.image_prompt_mentions or [],
                    )
                    normalized_item = item.model_copy(
                        update={"image_prompt_mentions": normalized_mentions}
                    )
                if "managed_asset_bindings" in fields:
                    requested_bindings = item.managed_asset_bindings or []
                    if requested_bindings and self.managed_assets is None:
                        raise _fail(
                            409,
                            "managed_asset_service_unavailable",
                            "供应商托管资产目录服务尚未配置",
                        )
                    verified_bindings = []
                    for binding in requested_bindings:
                        try:
                            verified_bindings.append(
                                await self.managed_assets.verify_binding(binding)  # type: ignore[union-attr]
                            )
                        except ManagedAssetServiceError as exc:
                            raise _fail(exc.status_code, exc.code, str(exc)) from exc
                    normalized_item = normalized_item.model_copy(
                        update={"managed_asset_bindings": verified_bindings}
                    )
                if "video_prompt_mentions" in fields:
                    normalized_video_mentions = await self._validate_video_prompt_mentions(
                        project,
                        current,
                        item.video_prompt_mentions or [],
                        managed_asset_bindings=(
                            normalized_item.managed_asset_bindings
                            if "managed_asset_bindings" in fields
                            else current.managed_asset_bindings
                        ),
                        video_reference_bindings=(
                            normalized_item.video_reference_bindings
                            if "video_reference_bindings" in fields
                            else current.video_reference_bindings
                        ),
                    )
                    normalized_item = normalized_item.model_copy(
                        update={"video_prompt_mentions": normalized_video_mentions}
                    )
                if "reference_bindings" in fields or "image_prompt_mentions" in fields:
                    previous = [
                        binding for binding in all_bindings if binding.shot_plan_id == current.id
                    ]
                    binding_inputs = (
                        item.reference_bindings or []
                        if "reference_bindings" in fields
                        else [
                            ReferenceBindingInput(
                                reference_asset_id=binding.reference_asset_id,
                                role=binding.role,
                                weight=binding.weight,
                                crop_hint=binding.crop_hint,
                                notes=binding.notes,
                            )
                            for binding in previous
                        ]
                    )
                    binding_inputs = await self._append_mention_bindings(
                        project,
                        binding_inputs,
                        normalized_item.image_prompt_mentions
                        if "image_prompt_mentions" in fields
                        else current.image_prompt_mentions,
                    )
                    replacements = await self._build_bindings(
                        project,
                        current,
                        binding_inputs,
                    )
                    removed_binding_ids.extend(binding.id for binding in previous)
                    all_bindings = [
                        binding for binding in all_bindings if binding.shot_plan_id != current.id
                    ] + replacements
                    new_bindings.extend(replacements)
                updated = self._apply_shot_fields(
                    current,
                    normalized_item,
                    fields,
                    revision_id,
                    image_changed=self._image_fields_changed(item),
                    video_changed=self._video_fields_changed(item),
                )
                plans_by_id[updated.id] = updated
                changed_plans.append(updated)

            next_plans = [plans_by_id[item.id] for item in plans]
            any_image_change = any(self._image_fields_changed(item) for item in payload.updates)
            any_video_change = any(self._video_fields_changed(item) for item in payload.updates)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if any_image_change
                        else ProductionStep.SHOT_VIDEOS
                        if any_video_change
                        else project.active_step
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                f"批量更新 {len(changed_plans)} 个分镜创作计划",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                reference_bindings=new_bindings,
                remove_reference_binding_ids=removed_binding_ids,
            )
        return await self.list_shots(project_id)

    async def change_impact(
        self,
        project_id: UUID,
        payload: ChangeImpactRequest,
    ) -> ChangeImpactResponse:
        project = await self._require_project(project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        plans = await self.repository.list_shot_plans(project.id)
        impacted: list[ShotPlan]
        if payload.change_type == "project_settings":
            impacted = plans
        elif payload.change_type == "reference_asset":
            asset_ids = set(payload.reference_asset_ids)
            impacted_ids: set[UUID] = set()
            for plan in plans:
                bindings = await self.repository.list_reference_bindings(plan.id)
                if any(item.reference_asset_id in asset_ids for item in bindings):
                    impacted_ids.add(plan.id)
            impacted = [item for item in plans if item.id in impacted_ids]
        else:
            requested = set(payload.shot_plan_ids)
            impacted = [item for item in plans if item.id in requested]

        downstream_only = payload.change_type in {
            "candidate_selection",
            "image_approval_revoke",
        }
        stale_stages = (
            [
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            ]
            if downstream_only
            else [
                ProductionStep.SHOT_IMAGES,
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            ]
        )
        stale_candidates = (
            []
            if payload.change_type == "image_approval_revoke"
            else [
                item.approved_image_candidate_id
                for item in impacted
                if item.approved_image_candidate_id is not None
            ]
        )
        downstream_result_statuses = {
            WorkflowItemStatus.GENERATING,
            WorkflowItemStatus.REVIEW_REQUIRED,
            WorkflowItemStatus.APPROVED,
            WorkflowItemStatus.STALE,
        }
        downstream_stage_active = project.active_step in {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }
        requires_confirmation = (
            (
                any(item.video_status in downstream_result_statuses for item in impacted)
                or (bool(impacted) and downstream_stage_active)
            )
            if downstream_only
            else any(
                item.image_status == WorkflowItemStatus.APPROVED
                or item.video_status == WorkflowItemStatus.APPROVED
                for item in impacted
            )
        )
        count = len(impacted)
        return ChangeImpactResponse(
            impacted_shot_plan_ids=[item.id for item in impacted],
            impacted_shot_ids=[item.source_shot_id for item in impacted],
            stale_candidate_ids=stale_candidates,
            stale_stage_ids=stale_stages if count else [],
            requires_confirmation=requires_confirmation,
            summary=(
                f"将重新打开 {count} 个分镜的图片审核，并使其后续结果过期"
                if count and payload.change_type == "image_approval_revoke"
                else (
                    f"将影响 {count} 个分镜，并使其后续结果过期"
                    if count
                    else "当前修改不会使已生成结果过期"
                )
            ),
        )

    async def resolve_source_video(
        self,
        project_id: UUID,
    ) -> tuple[Path, str]:
        project = await self._require_project(project_id)
        video = await self.repository.get_video(project.video_id)
        if video is None:
            raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
        path = self._resolve_video_file(video)
        media_type = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
        }.get(path.suffix.lower(), "application/octet-stream")
        return path, media_type

    async def resolve_source_keyframe_content(
        self,
        shot_plan_id: UUID,
    ) -> tuple[Path, str]:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        path = self._resolve_source_keyframe(project, plan)
        if path is None:
            raise _fail(404, "source_keyframe_missing", "当前分镜关键帧不存在")
        return path, "image/jpeg"

    async def select_source_keyframe(
        self,
        shot_plan_id: UUID,
        payload: ShotKeyframeSelectRequest,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(plan, payload.visual_beat_id)
            timestamp = float(payload.timestamp_seconds)
            if timestamp < plan.start_seconds - 0.001 or timestamp > plan.end_seconds + 0.001:
                raise _fail(
                    422,
                    "keyframe_timestamp_out_of_range",
                    (
                        f"关键帧时间必须位于分镜 {plan.start_seconds:.3f}s "
                        f"到 {plan.end_seconds:.3f}s 之间"
                    ),
                )
            has_reviewed_output = (
                beat.approved_image_candidate_id is not None
                or beat.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
            )
            if has_reviewed_output and not payload.confirm_stale:
                raise _fail(
                    409,
                    "keyframe_change_confirmation_required",
                    "替换关键帧会保留旧图片候选，但会使当前采用状态和后续结果过期，请确认后重试",
                )
            timestamp = min(
                max(timestamp, plan.start_seconds),
                max(plan.start_seconds, plan.end_seconds - 0.001),
            )
            video = await self.repository.get_video(project.video_id)
            if video is None:
                raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
            source_video = self._resolve_video_file(video)
            revision_id = uuid4()
            keyframe_root = (
                self.workspace.production_shot_root(
                    project.record_id,
                    project.id,
                    plan.id,
                )
                / "visual-beats"
                / str(beat.id)
                / "source-frames"
            )
            destination = keyframe_root / f"{revision_id}.jpg"
            temporary = keyframe_root / f".tmp-{revision_id}.jpg"
            filesystem_temporary = _filesystem_path(temporary)
            filesystem_destination = _filesystem_path(destination)
            try:
                await self.media_processor.extract_frame(
                    source_video,
                    timestamp,
                    filesystem_temporary,
                )
                await asyncio.to_thread(
                    self._validate_keyframe_file,
                    filesystem_temporary,
                )
                filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(filesystem_temporary, filesystem_destination)
            except MediaProcessingError as exc:
                raise _fail(422, exc.code, str(exc)) from exc
            except OSError as exc:
                raise _fail(507, "keyframe_write_failed", "无法保存所选关键帧") from exc
            finally:
                filesystem_temporary.unlink(missing_ok=True)
            source_sha256, _ = await asyncio.to_thread(
                _frame_sha256_and_dhash,
                filesystem_destination,
            )

            candidate_updates = await self._reset_selected_image_candidates(
                project,
                plan,
                visual_beat_id=beat.id,
            )
            updated_beat = beat.model_copy(
                update={
                    "source_frame_url": (
                        f"/api/v1/production-shots/{plan.id}/visual-beats/{beat.id}/source-frame"
                        f"?v={revision_id}"
                    ),
                    "source_frame_relative_path": self.workspace.relative(destination),
                    "source_timestamp_seconds": round(timestamp, 3),
                    "source_frame_sha256": source_sha256,
                    "source_frame_warning": None,
                    "source_origin": "video_selection",
                    "image_status": (
                        WorkflowItemStatus.READY
                        if beat.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
                invalidate_video=True,
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SOURCE_KEYFRAME_CHANGED,
                f"将分镜 {plan.index} 画面 {beat.index} 的关键帧切换到 {timestamp:.3f}s",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=candidate_updates,
            )
        return await self.get_shot(shot_plan_id)

    async def approve_source_keyframe(
        self,
        shot_plan_id: UUID,
        payload: ShotSourceFrameApprovalRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(plan, payload.visual_beat_id)
            replacing_approved = (
                beat.image_status == WorkflowItemStatus.APPROVED
                and beat.approved_image_candidate_id is not None
            )
            has_downstream_impact = replacing_approved and self._image_choice_has_downstream_impact(
                project, plan
            )
            if has_downstream_impact and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "改用当前关键帧会使该分镜的后续视频或合成结果过期，请确认影响后重试",
                )
            gateway_plan = _shot_for_visual_beat(plan, beat)
            source_path = self._resolve_source_keyframe(project, gateway_plan)
            if source_path is None:
                raise _fail(409, "source_keyframe_required", "当前分镜没有可读取的关键帧")
            revision_id = uuid4()
            run, candidate = await asyncio.to_thread(
                self._create_source_frame_candidate,
                project,
                gateway_plan,
                revision_id,
                source_path,
                beat.id,
            )
            candidate_updates = await self._reset_selected_image_candidates(
                project,
                plan,
                visual_beat_id=beat.id,
            )
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=GenerationKind.IMAGE,
                decision=ApprovalDecision.APPROVED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="确认说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "直接使用源视频关键帧，未调用图片生成模型"
                ),
            )
            updated_beat = beat.model_copy(
                update={
                    "image_status": WorkflowItemStatus.APPROVED,
                    "approved_image_candidate_id": candidate.id,
                    "updated_at": utc_now(),
                }
            )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
                invalidate_video=has_downstream_impact,
            )
            current_preparation = await self.repository.get_video_clip_preparation(plan.id)
            updated_preparation = (
                current_preparation.model_copy(
                    update={
                        "revision_id": revision_id,
                        "status": VideoClipPreparationStatus.STALE,
                        "blocker_messages": ["起始图片已经更换，需要重新生成视频并完成剪辑准备"],
                        "warning_messages": [],
                        "updated_at": utc_now(),
                    }
                )
                if current_preparation is not None and has_downstream_impact
                else None
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            preparations = await self.repository.list_video_clip_preparations(project.id)
            next_preparations = [item for item in preparations if item.shot_plan_id != plan.id]
            if updated_preparation is not None:
                next_preparations.append(updated_preparation)
            elif current_preparation is not None:
                next_preparations.append(current_preparation)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_APPROVED,
                f"直接确认分镜 {plan.index} 画面 {beat.index} 的源视频关键帧",
                revision_id=revision_id,
                shot_plans=next_plans,
                video_clip_preparations=next_preparations,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=[*candidate_updates, candidate],
                video_clip_preparations=(
                    [updated_preparation] if updated_preparation is not None else None
                ),
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(candidate),
            approval_event=event,
        )

    async def create_image_run(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
    ) -> GenerationRunResponse:
        run = await self._enqueue_image_run(shot_plan_id, payload)
        self._schedule_image_run(run.id)
        return await self._run_response(run)

    async def create_video_run(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
    ) -> GenerationRunResponse:
        run = await self._enqueue_video_run(shot_plan_id, payload)
        self._schedule_video_run(run.id)
        return await self._run_response(run)

    async def _validate_video_input_plan(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        payload: VideoGenerationCreate,
        capability,
    ) -> None:
        """Validate only the media inputs explicitly selected by the user.

        Prompt text is always submitted. Audio intentionally does not exist in
        this contract; source/generated audio is handled later by the editor.
        """
        sources = set(payload.input_plan.sources)
        source_by_reference_kind = {
            VideoPromptReferenceKind.APPROVED_IMAGE: VideoGenerationInputSource.APPROVED_IMAGES,
            VideoPromptReferenceKind.PROJECT_ASSET: VideoGenerationInputSource.PROJECT_ASSETS,
            VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET: (
                VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS
            ),
            VideoPromptReferenceKind.REFERENCE_VIDEO: VideoGenerationInputSource.REFERENCE_VIDEO,
            VideoPromptReferenceKind.DEPTH_CONTROL: VideoGenerationInputSource.DEPTH_CONTROL,
        }
        selected_reference_keys = {
            (reference.reference_kind, reference.reference_id)
            for reference in payload.input_plan.references
        }
        for reference in payload.input_plan.references:
            required_source = source_by_reference_kind[reference.reference_kind]
            if required_source not in sources:
                raise _fail(
                    409,
                    "video_generation_reference_source_disabled",
                    f"生成参考 @{reference.label} 尚未启用对应输入来源",
                )
        for mention in plan.video_prompt_mentions:
            if f"@{mention.label}" not in plan.video_prompt:
                raise _fail(
                    409,
                    "video_prompt_reference_token_missing",
                    f"视频提示词引用 @{mention.label} 已不在正文中，请重新选择或移除该引用",
                )
            required_source = source_by_reference_kind[mention.reference_kind]
            if required_source not in sources:
                raise _fail(
                    409,
                    "video_prompt_reference_source_disabled",
                    f"视频提示词中的 @{mention.label} 尚未启用对应生成输入",
                )
        for mention in plan.video_prompt_mentions:
            if (mention.reference_kind, mention.reference_id) not in selected_reference_keys:
                raise _fail(
                    409,
                    "video_prompt_reference_not_selected",
                    f"提示词引用 @{mention.label} 尚未通过 +参考 加入本次生成",
                )
        if not sources:
            if not capability.text_to_video:
                raise _fail(
                    422,
                    "video_text_to_video_unsupported",
                    "当前模型不支持纯文生视频，请选择图片或资产输入，或切换模型",
                )
            return

        image_sources = {
            VideoGenerationInputSource.APPROVED_IMAGES,
            VideoGenerationInputSource.PROJECT_ASSETS,
        }
        if sources & image_sources and not capability.image_to_video:
            raise _fail(422, "video_image_input_unsupported", "当前模型不支持图片输入")
        if (
            VideoGenerationInputSource.APPROVED_IMAGES in sources
            and not await self._has_valid_approved_image_output(project, plan)
        ):
            raise _fail(409, "approved_image_required", "请先确认用于生成视频的分镜图片")
        if VideoGenerationInputSource.PROJECT_ASSETS in sources:
            asset_ids = {
                reference.reference_id
                for reference in payload.input_plan.references
                if reference.reference_kind == VideoPromptReferenceKind.PROJECT_ASSET
            } or {
                mention.reference_asset_id
                for beat in plan.visual_beats
                for mention in (beat.image_prompt_mentions or plan.image_prompt_mentions)
            }
            if not asset_ids:
                raise _fail(
                    409,
                    "video_project_asset_required",
                    "当前分镜尚未在提示词中关联项目图片资产",
                )
        if VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS in sources:
            if not capability.managed_assets.supported:
                raise _fail(
                    422,
                    "video_managed_assets_unsupported",
                    "当前模型不支持 Provider 托管资产",
                )
            if not plan.managed_asset_bindings:
                raise _fail(409, "video_managed_asset_required", "请先选择 Provider 托管人物资产")
        if VideoGenerationInputSource.REFERENCE_VIDEO in sources:
            if not capability.reference_video:
                raise _fail(422, "video_reference_video_unsupported", "当前模型不支持普通参考视频")
            raise _fail(
                409,
                "video_reference_video_not_bound",
                "当前分镜尚未绑定普通参考视频；该输入不会自动使用原视频",
            )
        if VideoGenerationInputSource.DEPTH_CONTROL in sources:
            if not (
                capability.depth_control_video
                or capability.reference_route.supports_depth_control_video
            ):
                raise _fail(422, "video_depth_control_unsupported", "当前模型不支持深度视频控制")
            if not any(
                item.enabled and item.usable_for_generation
                for item in plan.depth_control_assets
            ):
                raise _fail(409, "depth_control_required", "请先生成并启用一个可用的深度控制视频")

    async def _enqueue_video_run(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
        *,
        retry_of_run_id: UUID | None = None,
        retry_count: int = 0,
    ) -> GenerationRun:
        plan = await self._require_shot(shot_plan_id)
        self._ensure_shot_active(plan)
        project = await self._require_project(plan.project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        allowed_video_steps = {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }
        if project.active_step not in allowed_video_steps:
            raise _fail(
                409,
                "video_stage_not_active",
                "请先完成全部必需分镜图片并进入分段视频阶段",
            )
        if not plan.video_prompt.strip():
            raise _fail(409, "video_prompt_required", "请先填写视频提示词")
        if payload.generation_intent == "new_variation" and payload.seed is None:
            payload = payload.model_copy(update={"seed": secrets.randbelow(2_147_483_648)})
        try:
            execution_mode = ImageExecutionMode(payload.execution_mode)
        except ValueError as exc:
            raise _fail(422, "video_execution_mode_invalid", "视频生成执行模式无效") from exc
        validate_mode = getattr(self.video_gateway, "validate_execution_mode", None)
        if callable(validate_mode):
            try:
                validate_mode(execution_mode)
            except VideoGenerationGatewayError as exc:
                raise _video_gateway_failure(exc) from exc

        duration_seconds = round(payload.duration_seconds or plan.duration_seconds, 3)
        try:
            identity, resolved = self.video_gateway.resolve_identity(
                execution_mode=execution_mode.value,
                model_alias=payload.model_alias,
                duration_seconds=duration_seconds,
                resolution=payload.resolution,
                candidate_count=payload.candidate_count,
                allow_unknown_cost=payload.allow_unknown_cost,
            )
        except VideoGenerationGatewayError as exc:
            raise _video_gateway_failure(exc) from exc
        await self._validate_video_input_plan(
            project,
            plan,
            payload,
            identity.capability,
        )
        payload = payload.model_copy(
            update={
                "duration_seconds": duration_seconds,
                "model_alias": identity.model_alias,
                "resolution": resolved.resolution if resolved is not None else payload.resolution,
            }
        )

        active_statuses = {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.CANCELLATION_REQUESTED,
        }
        existing_runs = await self.repository.list_generation_runs(project.id, plan.id)
        if any(
            item.kind == GenerationKind.VIDEO and item.status in active_statuses
            for item in existing_runs
        ):
            raise _fail(409, "generation_already_running", "该分镜已有视频生成任务在执行")

        run_id = uuid4()
        request_payload = payload.model_dump(mode="json")
        queue_root = (
            self.workspace.production_shot_root(project.record_id, project.id, plan.id)
            / "videos"
            / str(run_id)
        )
        queue_path = queue_root / "queue.json"
        fingerprint = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        await asyncio.to_thread(
            self._write_json_atomic,
            queue_path,
            {
                "schema_version": "viral-dna-video-job/v1",
                "run_id": str(run_id),
                "shot_plan_id": str(plan.id),
                "request": request_payload,
                "retry_of_run_id": str(retry_of_run_id) if retry_of_run_id else None,
                "retry_count": retry_count,
            },
        )
        now = utc_now()
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            revision_id=payload.expected_revision_id,
            kind=GenerationKind.VIDEO,
            input_mode=payload.input_mode,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            model_alias=identity.model_alias,
            model_display_name=identity.model_display_name,
            prompt_version="shot-video-v1",
            schema_version="viral-dna-video-job/v1",
            pricing_version=identity.pricing_version,
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(queue_path),
            execution_mode=execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            capability_snapshot=identity.capability.model_dump(mode="json"),
            execution_summary=identity.execution_summary,
            cost_source=identity.cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            actual_cost_known=False,
            cost_currency="CNY",
            pricing_snapshot=identity.pricing_snapshot,
            request_payload=request_payload,
            retry_of_run_id=retry_of_run_id,
            retry_count=retry_count,
            status=ProductionRunStatus.QUEUED,
            estimated_cost_micros=identity.estimated_cost_micros,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_generation_run(run)
        await self._notify_generation_run(run)
        if retry_of_run_id is not None:
            source_tasks = await self.repository.list_video_provider_tasks(retry_of_run_id)
            for source_task in source_tasks:
                if not source_task.provider_task_id or source_task.status in {
                    VideoProviderTaskStatus.FAILED,
                    VideoProviderTaskStatus.CANCELLED,
                }:
                    continue
                await self.repository.save_video_provider_task(
                    source_task.model_copy(
                        update={
                            "id": uuid4(),
                            "generation_run_id": run.id,
                            "project_id": run.project_id,
                            "shot_plan_id": run.shot_plan_id,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                )
        return run

    def _schedule_video_run(self, run_id: UUID) -> None:
        current = self._generation_tasks.get(run_id)
        if current is not None and not current.done():
            return
        cancellation = Event()
        self._generation_cancellations[run_id] = cancellation
        task = asyncio.create_task(
            self._run_queued_video(run_id, cancellation),
            name=f"viral-dna-video-{run_id}",
        )
        self._generation_tasks[run_id] = task

    async def _run_queued_video(self, run_id: UUID, cancellation: Event) -> None:
        try:
            running = await self.repository.claim_generation_run(run_id, utc_now())
            if running is None:
                return
            payload = VideoGenerationCreate.model_validate(running.request_payload)
            await self._execute_video_run_request(
                running.shot_plan_id,
                payload,
                run_id=running.id,
                cancellation=cancellation,
                queued_run=running,
            )
        except asyncio.CancelledError:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "视频生成任务已取消",
            )
        except ProductionServiceError as exc:
            if cancellation.is_set() or exc.code == "generation_cancelled":
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "视频生成任务已取消",
                )
            else:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.FAILED,
                    exc.code,
                    str(exc),
                    error_retryable=exc.retryable,
                    provider_error_code=exc.provider_code,
                    error_category=exc.error_category,
                    error_title=exc.user_title,
                    error_action=exc.suggested_action,
                    error_technical_message=exc.technical_message,
                )
        except Exception as exc:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.FAILED,
                "generation_worker_failed",
                str(exc)[:2000],
            )
        finally:
            self._generation_cancellations.pop(run_id, None)
            current = self._generation_tasks.get(run_id)
            if current is asyncio.current_task():
                self._generation_tasks.pop(run_id, None)

    async def _enqueue_image_run(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
        *,
        retry_of_run_id: UUID | None = None,
        retry_count: int = 0,
    ) -> GenerationRun:
        plan = await self._require_shot(shot_plan_id)
        self._ensure_shot_active(plan)
        project = await self._require_project(plan.project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        beat = _visual_beat(plan, payload.visual_beat_id)
        if payload.visual_beat_id != beat.id:
            payload = payload.model_copy(update={"visual_beat_id": beat.id})
        if payload.generation_intent == "new_variation" and payload.seed is None:
            payload = payload.model_copy(update={"seed": secrets.randbelow(2_147_483_648)})
        if not beat.image_prompt.strip():
            raise _fail(409, "image_prompt_required", "请先填写图片提示词")
        if beat.image_status == WorkflowItemStatus.APPROVED:
            raise _fail(409, "image_already_approved", "已采用画面需要先取消采用再重新生成")
        bindings = await self.repository.list_reference_bindings(plan.id)
        assets = await self._list_reference_assets(project.id)
        gateway_plan = _shot_for_visual_beat(plan, beat)
        try:
            identity_policy = validate_identity_bindings(bindings, assets)
            validate_identity_generation(
                state=identity_policy,
                input_mode=payload.input_mode,
                source_present=bool(
                    gateway_plan.source_keyframe_url
                    or gateway_plan.source_keyframe_relative_path
                ),
            )
        except IdentityPolicyViolation as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc
        active_statuses = {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.CANCELLATION_REQUESTED,
        }
        existing_runs = await self.repository.list_generation_runs(project.id, plan.id)
        if any(
            item.kind == GenerationKind.IMAGE
            and _run_matches_visual_beat(item, plan, beat.id)
            and item.status in active_statuses
            for item in existing_runs
        ):
            raise _fail(409, "generation_already_running", "该画面已有图片生成任务在执行")
        settings_service = getattr(self.image_gateway, "settings_service", None)
        settings = settings_service.get() if settings_service is not None else None
        if settings is not None and not settings.enabled:
            raise _fail(409, "image_generation_not_configured", "请先配置并启用真实图片生成引擎")
        try:
            execution_mode = ImageExecutionMode(
                payload.execution_mode
                or (
                    settings.execution_mode
                    if settings is not None
                    else ImageExecutionMode.REMOTE_API
                )
            )
        except ValueError as exc:
            raise _fail(422, "image_execution_mode_invalid", "图片生成执行模式无效") from exc
        run_id = uuid4()
        request_payload = payload.model_dump(mode="json")
        queue_root = (
            self.workspace.production_shot_root(project.record_id, project.id, plan.id)
            / "images"
            / str(run_id)
        )
        queue_path = queue_root / "queue.json"
        fingerprint = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        await asyncio.to_thread(
            self._write_json_atomic,
            queue_path,
            {
                "schema_version": "viral-dna-image-job/v1",
                "run_id": str(run_id),
                "shot_plan_id": str(plan.id),
                "request": request_payload,
                "retry_of_run_id": str(retry_of_run_id) if retry_of_run_id else None,
                "retry_count": retry_count,
            },
        )
        now = utc_now()
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            visual_beat_id=beat.id,
            revision_id=payload.expected_revision_id,
            kind=GenerationKind.IMAGE,
            input_mode=payload.input_mode,
            provider="pending",
            model="pending",
            model_snapshot="pending",
            prompt_version="shot-image-v3",
            schema_version="viral-dna-image-job/v1",
            pricing_version="pending",
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(queue_path),
            execution_mode=execution_mode,
            adapter_id="pending",
            adapter_version="batch4.2.4",
            cost_source=GenerationCostSource.UNKNOWN,
            cost_estimate_known=False,
            request_payload=request_payload,
            retry_of_run_id=retry_of_run_id,
            retry_count=retry_count,
            status=ProductionRunStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_generation_run(run)
        await self._notify_generation_run(run)
        return run

    def _schedule_image_run(self, run_id: UUID) -> None:
        current = self._generation_tasks.get(run_id)
        if current is not None and not current.done():
            return
        cancellation = Event()
        self._generation_cancellations[run_id] = cancellation
        task = asyncio.create_task(
            self._run_queued_image(run_id, cancellation),
            name=f"viral-dna-image-{run_id}",
        )
        self._generation_tasks[run_id] = task

    async def _run_queued_image(self, run_id: UUID, cancellation: Event) -> None:
        try:
            running = await self.repository.claim_generation_run(run_id, utc_now())
            if running is None:
                return
            payload = ImageGenerationCreate.model_validate(running.request_payload)
            await self._execute_image_run_request(
                running.shot_plan_id,
                payload,
                run_id=running.id,
                cancellation=cancellation,
                queued_run=running,
            )
        except asyncio.CancelledError:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "图片生成任务已取消",
            )
        except ProductionServiceError as exc:
            if cancellation.is_set() or exc.code == "generation_cancelled":
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "生成任务已取消",
                )
            else:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.FAILED,
                    exc.code,
                    str(exc),
                )
        except Exception as exc:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.FAILED,
                "generation_worker_failed",
                str(exc)[:2000],
            )
        finally:
            self._generation_cancellations.pop(run_id, None)
            current = self._generation_tasks.get(run_id)
            if current is asyncio.current_task():
                self._generation_tasks.pop(run_id, None)

    async def _mark_generation_terminal(
        self,
        run_id: UUID,
        status: ProductionRunStatus,
        error_code: str,
        error_message: str,
        *,
        error_retryable: bool = False,
        provider_error_code: str | None = None,
        error_category: str | None = None,
        error_title: str | None = None,
        error_action: str | None = None,
        error_technical_message: str | None = None,
    ) -> GenerationRun:
        run = await self._require_run(run_id)
        if run.status in {
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.BLOCKED,
            ProductionRunStatus.CANCELLED,
        }:
            return run
        provider_tasks = (
            await self.repository.list_video_provider_tasks(run.id)
            if run.kind == GenerationKind.VIDEO
            else []
        )
        failed_task = next(
            (
                item
                for item in provider_tasks
                if item.error_code or item.error_message or item.error_technical_message
            ),
            None,
        )
        failure = (
            classify_video_provider_failure(
                provider=run.provider,
                code=error_code or (failed_task.error_code if failed_task else None),
                message=(
                    error_technical_message
                    or (failed_task.error_technical_message if failed_task else None)
                    or error_message
                    or (failed_task.error_message if failed_task else None)
                ),
                retryable=error_retryable or bool(failed_task and failed_task.retryable),
                provider_code=(
                    provider_error_code
                    or (failed_task.provider_error_code if failed_task else None)
                ),
            )
            if run.kind == GenerationKind.VIDEO and status == ProductionRunStatus.FAILED
            else None
        )
        now = utc_now()
        updated = run.model_copy(
            update={
                "status": status,
                "cancellation_requested": status == ProductionRunStatus.CANCELLED,
                "provider_request_id": (
                    run.provider_request_id
                    or (failed_task.provider_task_id if failed_task else None)
                ),
                "error_code": failure.code if failure else error_code,
                "error_message": failure.message if failure else error_message,
                "provider_error_code": (
                    provider_error_code
                    or (failed_task.provider_error_code if failed_task else None)
                    or (failure.provider_code if failure else None)
                ),
                "error_category": error_category or (failure.category if failure else None),
                "error_title": error_title or (failure.title if failure else None),
                "error_technical_message": (
                    error_technical_message
                    or (failed_task.error_technical_message if failed_task else None)
                    or (failure.technical_message if failure else None)
                ),
                "error_retryable": error_retryable or bool(failure and failure.retryable),
                "error_action": error_action or (failure.suggested_action if failure else None),
                "updated_at": now,
                "last_heartbeat_at": now,
                "completed_at": now,
            }
        )
        await self.repository.save_generation_run(updated)
        await self._notify_generation_run(updated)
        return updated

    async def cancel_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        run = await self._require_run(run_id)
        if run.status in {
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
            ProductionRunStatus.BLOCKED,
        }:
            return await self._run_response(run)
        now = utc_now()
        requested = run.model_copy(
            update={
                "status": ProductionRunStatus.CANCELLATION_REQUESTED,
                "cancellation_requested": True,
                "updated_at": now,
            }
        )
        await self.repository.save_generation_run(requested)
        if run.kind == GenerationKind.VIDEO:
            try:
                await self.video_gateway.cancel(run_id)
            except Exception:
                # Local cancellation must still complete even when an upstream Provider
                # does not expose cancellation or is temporarily unreachable.
                pass
        cancellation = self._generation_cancellations.get(run_id)
        if cancellation is not None:
            cancellation.set()
        task = self._generation_tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            latest = await self._require_run(run_id)
            if latest.status not in {
                ProductionRunStatus.COMPLETED,
                ProductionRunStatus.CACHED,
                ProductionRunStatus.CANCELLED,
            }:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "图片生成任务已取消",
                )
        else:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "生成任务已取消",
            )
        return await self.get_generation_run(run_id)

    async def retry_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        source = await self._require_run(run_id)
        if source.status not in {
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
            ProductionRunStatus.BLOCKED,
        }:
            raise _fail(409, "generation_retry_unavailable", "只有失败或已取消的任务可以重试")
        project = await self._require_project(source.project_id)
        payload_data = dict(source.request_payload)
        payload_data["expected_revision_id"] = str(project.current_revision_id)
        if source.kind == GenerationKind.VIDEO:
            provider_tasks = await self.repository.list_video_provider_tasks(source.id)
            if any(
                not item.provider_task_id
                and item.status
                in {
                    VideoProviderTaskStatus.PENDING_SUBMISSION,
                    VideoProviderTaskStatus.UNKNOWN,
                }
                for item in provider_tasks
            ):
                raise _fail(
                    409,
                    "video_provider_submission_ambiguous",
                    "上游提交结果不明确；为避免重复扣费，请先在 Provider 控制台核对任务",
                )
            video_payload = VideoGenerationCreate.model_validate(payload_data)
            run = await self._enqueue_video_run(
                source.shot_plan_id,
                video_payload,
                retry_of_run_id=source.id,
                retry_count=source.retry_count + 1,
            )
            self._schedule_video_run(run.id)
        else:
            image_payload = ImageGenerationCreate.model_validate(payload_data)
            run = await self._enqueue_image_run(
                source.shot_plan_id,
                image_payload,
                retry_of_run_id=source.id,
                retry_count=source.retry_count + 1,
            )
            self._schedule_image_run(run.id)
        return await self._run_response(run)

    async def recover_generation_runs(self) -> dict[str, int]:
        recovered = 0
        interrupted = 0
        cancelled = 0
        for project in await self.repository.list_production_projects():
            for run in await self.repository.list_generation_runs(project.id):
                if run.status == ProductionRunStatus.QUEUED and run.request_payload:
                    if run.kind == GenerationKind.VIDEO:
                        self._schedule_video_run(run.id)
                    else:
                        self._schedule_image_run(run.id)
                    recovered += 1
                elif run.status == ProductionRunStatus.CANCELLATION_REQUESTED:
                    await self._mark_generation_terminal(
                        run.id,
                        ProductionRunStatus.CANCELLED,
                        "generation_cancelled",
                        "服务重启前已请求取消任务",
                    )
                    cancelled += 1
                elif run.status == ProductionRunStatus.RUNNING:
                    provider_tasks = (
                        await self.repository.list_video_provider_tasks(run.id)
                        if run.kind == GenerationKind.VIDEO
                        and run.execution_mode == ImageExecutionMode.REMOTE_API
                        else []
                    )
                    if provider_tasks and all(
                        item.provider_task_id
                        or item.status
                        in {
                            VideoProviderTaskStatus.FAILED,
                            VideoProviderTaskStatus.CANCELLED,
                        }
                        for item in provider_tasks
                    ):
                        resumed = run.model_copy(
                            update={
                                "status": ProductionRunStatus.QUEUED,
                                "updated_at": utc_now(),
                                "error_code": None,
                                "error_message": None,
                                "provider_error_code": None,
                                "error_category": None,
                                "error_title": None,
                                "error_technical_message": None,
                                "error_retryable": False,
                                "error_action": None,
                            }
                        )
                        await self.repository.save_generation_run(resumed)
                        self._schedule_video_run(run.id)
                        recovered += 1
                    else:
                        await self._mark_generation_terminal(
                            run.id,
                            ProductionRunStatus.FAILED,
                            "generation_interrupted",
                            "服务重启导致任务中断，请人工重试以避免重复计费",
                        )
                        interrupted += 1
        return {
            "recovered": recovered,
            "interrupted": interrupted,
            "cancelled": cancelled,
        }

    async def shutdown_generation_runs(self) -> None:
        tasks = [task for task in self._generation_tasks.values() if not task.done()]
        for cancellation in self._generation_cancellations.values():
            cancellation.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_image_run_request(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
        *,
        run_id: UUID,
        cancellation: Event,
        queued_run: GenerationRun,
    ) -> GenerationRunResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(
                plan,
                payload.visual_beat_id or queued_run.visual_beat_id,
            )
            gateway_plan = _shot_for_visual_beat(plan, beat)
            if not beat.image_prompt.strip():
                raise _fail(409, "image_prompt_required", "请先填写图片提示词")
            if beat.image_status == WorkflowItemStatus.APPROVED:
                raise _fail(409, "image_already_approved", "已采用画面需要先取消采用再重新生成")

            uses_images = payload.input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
            bindings = await self.repository.list_reference_bindings(plan.id)
            assets = await self._list_reference_assets(project.id)
            assets_by_id = {item.id: item for item in assets}
            for binding in bindings:
                asset = assets_by_id.get(binding.reference_asset_id)
                if asset is None or asset.archived_at is not None:
                    raise _fail(
                        409,
                        "reference_binding_invalid",
                        "分镜绑定了不存在或已归档的参考资产",
                    )
                if not asset.rights_confirmed:
                    raise _fail(409, "reference_rights_required", "分镜参考资产尚未完成权利确认")
            source_path = (
                self._resolve_source_keyframe(project, gateway_plan)
                if uses_images
                else None
            )
            try:
                run, candidates = await self.image_gateway.generate(
                    project,
                    gateway_plan,
                    payload.expected_revision_id,
                    bindings,
                    assets,
                    candidate_count=payload.candidate_count,
                    source_path=source_path,
                    input_mode=payload.input_mode,
                    execution_mode=payload.execution_mode,
                    model_alias=payload.model_alias,
                    allow_unknown_cost=payload.allow_unknown_cost,
                    seed=payload.seed,
                    reuse_cache=payload.generation_intent != "new_variation",
                    run_id=run_id,
                    cancel_event=cancellation,
                )
            except ImageGenerationGatewayError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            now = utc_now()
            run = run.model_copy(
                update={
                    "visual_beat_id": beat.id,
                    "request_payload": queued_run.request_payload,
                    "retry_of_run_id": queued_run.retry_of_run_id,
                    "retry_count": queued_run.retry_count,
                    "created_at": queued_run.created_at,
                    "started_at": queued_run.started_at,
                    "updated_at": now,
                    "last_heartbeat_at": now,
                }
            )
            if cancellation.is_set() or run.error_code == "generation_cancelled":
                cancelled = run.model_copy(
                    update={
                        "status": ProductionRunStatus.CANCELLED,
                        "cancellation_requested": True,
                        "error_code": "generation_cancelled",
                        "error_message": "图片生成任务已取消",
                        "completed_at": now,
                    }
                )
                await self.repository.save_generation_run(cancelled)
                return await self._run_response(cancelled)
            if _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_generation_forbidden",
                    "模拟占位图不能作为图片生成结果，请先配置真实生图引擎",
                )
            prior_candidate_updates = await self._reset_selected_image_candidates(
                project,
                plan,
                visual_beat_id=beat.id,
            )
            revision_id = uuid4()
            updated_beat = beat.model_copy(
                update={
                    "image_status": (
                        WorkflowItemStatus.REVIEW_REQUIRED
                        if candidates
                        else WorkflowItemStatus.FAILED
                    ),
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "estimated_cost_micros": (
                        project.estimated_cost_micros + run.estimated_cost_micros
                    ),
                    "actual_cost_micros": project.actual_cost_micros + run.actual_cost_micros,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                (
                    f"为分镜 {plan.index} 画面 {beat.index} 创建 {len(candidates)} 个图片候选"
                    if candidates
                    else (
                        f"分镜 {plan.index} 画面 {beat.index} 图片生成失败："
                        f"{run.error_code or 'unknown'}"
                    )
                ),
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=[*prior_candidate_updates, *candidates],
            )
        await self._notify_generation_run(run)
        return await self.get_generation_run(run.id)

    async def _execute_video_run_request(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
        *,
        run_id: UUID,
        cancellation: Event,
        queued_run: GenerationRun,
    ) -> GenerationRunResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if project.active_step not in {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }:
                raise _fail(
                    409,
                    "video_stage_not_active",
                    "当前方案不在分段视频阶段",
                )
            if not plan.video_prompt.strip():
                raise _fail(409, "video_prompt_required", "请先填写视频提示词")
            identity, _ = self.video_gateway.resolve_identity(
                execution_mode=payload.execution_mode,
                model_alias=payload.model_alias,
                duration_seconds=round(payload.duration_seconds or plan.duration_seconds, 3),
                resolution=payload.resolution,
                candidate_count=payload.candidate_count,
                allow_unknown_cost=payload.allow_unknown_cost,
            )
            await self._validate_video_input_plan(
                project,
                plan,
                payload,
                identity.capability,
            )
            target_beats = [item for item in plan.visual_beats if item.required] or list(
                plan.visual_beats
            )
            reference_frames: list[OrderedReferenceFrame] = []
            if payload.input_plan.includes(VideoGenerationInputSource.APPROVED_IMAGES):
                approved_mentions = {
                    item.reference_id: item
                    for item in payload.input_plan.references
                    if item.reference_kind == VideoPromptReferenceKind.APPROVED_IMAGE
                }
                approved_targets = sorted(
                    (
                        beat
                        for beat in target_beats
                        if not approved_mentions
                        or beat.approved_image_candidate_id in approved_mentions
                    ),
                    key=lambda beat: (
                        approved_mentions.get(beat.approved_image_candidate_id).order
                        if beat.approved_image_candidate_id in approved_mentions
                        else beat.index
                    ),
                )
                for ordinal, beat in enumerate(approved_targets, start=1):
                    if beat.approved_image_candidate_id is None:
                        raise _fail(
                            409,
                            "approved_image_required",
                            f"画面 {beat.index} 缺少已确认图片",
                        )
                    candidate = await self._require_candidate(beat.approved_image_candidate_id)
                    source_run = await self._require_run(candidate.generation_run_id)
                    if not _run_matches_visual_beat(source_run, plan, beat.id):
                        raise _fail(
                            409,
                            "approved_candidate_mismatch",
                            f"画面 {beat.index} 的已采用图片与画面记录不匹配",
                        )
                    candidate_path, _ = await self.resolve_candidate_content(candidate.id)
                    reference_frames.append(
                        OrderedReferenceFrame(
                            visual_beat_id=beat.id,
                            ordinal=ordinal,
                            title=(
                                approved_mentions[beat.approved_image_candidate_id].label
                                if beat.approved_image_candidate_id in approved_mentions
                                else beat.title
                            ),
                            candidate_id=candidate.id,
                            path=candidate_path,
                            relative_path=candidate.relative_path,
                            sha256=candidate.sha256,
                            start_ratio=beat.start_ratio,
                            end_ratio=beat.end_ratio,
                            transition_to_next_type=beat.transition_to_next_type,
                            transition_to_next_duration_seconds=(
                                beat.transition_to_next_duration_seconds
                            ),
                            transition_to_next_prompt=beat.transition_to_next_prompt,
                            role="composition",
                            source_kind="approved_frame",
                        )
                    )
            if (
                payload.input_plan.includes(VideoGenerationInputSource.PROJECT_ASSETS)
                and self.project_assets is not None
            ):
                asset_roles = {
                    ReferenceAssetType.PERSON: "actor_identity",
                    ReferenceAssetType.SCENE: "scene",
                    ReferenceAssetType.WARDROBE: "wardrobe",
                    ReferenceAssetType.PRODUCT: "product",
                    ReferenceAssetType.PROP: "composition",
                    ReferenceAssetType.STYLE: "composition",
                }
                seen_asset_ids: set[UUID] = set()
                video_asset_mentions = [
                    item
                    for item in payload.input_plan.references
                    if item.reference_kind == VideoPromptReferenceKind.PROJECT_ASSET
                ]
                if video_asset_mentions:
                    mention_sources = [
                        (target_beats[0], mention.reference_id, mention.label)
                        for mention in sorted(video_asset_mentions, key=lambda item: item.order)
                    ]
                else:
                    mention_sources = [
                        (beat, mention.reference_asset_id, mention.label)
                        for beat in sorted(target_beats, key=lambda item: item.index)
                        for mention in (beat.image_prompt_mentions or plan.image_prompt_mentions)
                    ]
                for beat, reference_asset_id, mention_label in mention_sources:
                    if reference_asset_id in seen_asset_ids:
                        continue
                    reference = await self.project_assets.get_reference(
                        reference_asset_id,
                        project.id,
                        include_archived=False,
                    )
                    if reference is None or not reference.rights_confirmed:
                        raise _fail(
                            422,
                            "video_reference_asset_unavailable",
                            f"参考资产 @{mention_label} 不存在、已归档或尚未确认使用权",
                        )
                    path, mime_type = await self.project_assets.resolve_content(
                        reference.id,
                        thumbnail=False,
                    )
                    if not mime_type.startswith("image/"):
                        raise _fail(
                            422,
                            "video_reference_asset_type_invalid",
                            f"参考资产 @{mention_label} 不是可用图片",
                        )
                    seen_asset_ids.add(reference.id)
                    reference_frames.append(
                        OrderedReferenceFrame(
                            visual_beat_id=beat.id,
                            ordinal=len(reference_frames) + 1,
                            title=mention_label or f"资产/{reference.name}",
                            candidate_id=reference.id,
                            path=path,
                            relative_path=reference.relative_path,
                            sha256=reference.sha256,
                            start_ratio=beat.start_ratio,
                            end_ratio=beat.end_ratio,
                            transition_to_next_type="cut",
                            transition_to_next_duration_seconds=0,
                            role=asset_roles[reference.type],
                            source_kind="project_asset",
                        )
                    )
            duration_seconds = round(
                payload.duration_seconds or plan.duration_seconds,
                3,
            )
            try:
                run, candidates = await self.video_gateway.generate(
                    project,
                    plan,
                    payload.expected_revision_id,
                    tuple(reference_frames),
                    candidate_count=payload.candidate_count,
                    duration_seconds=duration_seconds,
                    execution_mode=payload.execution_mode,
                    model_alias=payload.model_alias,
                    resolution=payload.resolution,
                    allow_unknown_cost=payload.allow_unknown_cost,
                    seed=payload.seed,
                    input_plan=payload.input_plan,
                    run_id=run_id,
                    cancel_event=cancellation,
                )
            except VideoGenerationGatewayError as exc:
                raise _video_gateway_failure(exc) from exc

            now = utc_now()
            run = run.model_copy(
                update={
                    "request_payload": queued_run.request_payload,
                    "retry_of_run_id": queued_run.retry_of_run_id,
                    "retry_count": queued_run.retry_count,
                    "created_at": queued_run.created_at,
                    "started_at": queued_run.started_at,
                    "updated_at": now,
                    "last_heartbeat_at": now,
                }
            )
            if cancellation.is_set() or run.error_code == "generation_cancelled":
                cancelled = run.model_copy(
                    update={
                        "status": ProductionRunStatus.CANCELLED,
                        "cancellation_requested": True,
                        "error_code": "generation_cancelled",
                        "error_message": "视频生成任务已取消",
                        "completed_at": now,
                    }
                )
                await self.repository.save_generation_run(cancelled)
                return await self._run_response(cancelled)

            revision_id = uuid4()
            preserve_approval = (
                plan.video_status == WorkflowItemStatus.APPROVED
                and plan.approved_video_candidate_id is not None
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": (
                        plan.video_status
                        if preserve_approval
                        else (
                            WorkflowItemStatus.REVIEW_REQUIRED
                            if candidates
                            else WorkflowItemStatus.FAILED
                        )
                    ),
                    "approved_video_candidate_id": (
                        plan.approved_video_candidate_id if preserve_approval else None
                    ),
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        project.active_step if preserve_approval else ProductionStep.SHOT_VIDEOS
                    ),
                    "estimated_cost_micros": (
                        project.estimated_cost_micros + run.estimated_cost_micros
                    ),
                    "actual_cost_micros": project.actual_cost_micros + run.actual_cost_micros,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_CANDIDATES_CREATED,
                f"为分镜 {plan.index} 创建 {len(candidates)} 个视频候选",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=candidates,
            )
        await self._notify_generation_run(run)
        return await self.get_generation_run(run.id)

    async def get_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        run = await self._require_run(run_id)
        await self._require_project(run.project_id)
        return await self._run_response(run)

    async def archive_generation_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
        *,
        actor_account_id: UUID | None = None,
    ) -> CandidateBatchLifecycleResponse:
        candidate = await self._require_candidate(payload.candidate_ids[0])
        run = await self._require_run(candidate.generation_run_id)
        if run.kind == GenerationKind.IMAGE:
            return await self.archive_image_candidates(
                payload,
                actor_account_id=actor_account_id,
            )
        return await self.archive_video_candidates(
            payload,
            actor_account_id=actor_account_id,
        )

    async def restore_generation_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
    ) -> CandidateBatchLifecycleResponse:
        candidate = await self._require_candidate(payload.candidate_ids[0])
        run = await self._require_run(candidate.generation_run_id)
        if run.kind == GenerationKind.IMAGE:
            return await self.restore_image_candidates(payload)
        return await self.restore_video_candidates(payload)

    async def archive_image_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
        *,
        actor_account_id: UUID | None = None,
    ) -> CandidateBatchLifecycleResponse:
        first_candidate = await self._require_candidate(payload.candidate_ids[0])
        first_run = await self._require_run(first_candidate.generation_run_id)
        lock = await self._project_lock(first_run.project_id)
        async with lock:
            project, plan, beat, candidates = await self._load_image_candidate_batch(
                payload.candidate_ids
            )
            self._require_expected_revision(project, payload.expected_revision_id)

            if any(item.id == beat.approved_image_candidate_id for item in candidates):
                raise _fail(
                    409,
                    "approved_image_candidate_archive_forbidden",
                    "已采用的图片不能删除，请先取消采用或改用其他图片",
                )
            unavailable = [
                item
                for item in candidates
                if item.status == GenerationCandidateStatus.REJECTED
                or is_user_deleted_candidate(item)
            ]
            if unavailable:
                raise _fail(
                    409,
                    "image_candidate_archive_unavailable",
                    "所选图片包含已退回或已删除候选，请刷新后重试",
                )

            now = utc_now()
            revision_id = uuid4()
            candidate_ids = {item.id for item in candidates}
            updated_candidates = archive_candidate_records(
                candidates,
                actor_account_id=actor_account_id,
                archived_at=now,
            )

            remaining_candidates: list[GenerationCandidate] = []
            for run in await self.repository.list_generation_runs(project.id, plan.id):
                if run.kind != GenerationKind.IMAGE or not _run_matches_visual_beat(
                    run,
                    plan,
                    beat.id,
                ):
                    continue
                remaining_candidates.extend(
                    item
                    for item in await self.repository.list_generation_candidates(run.id)
                    if item.id not in candidate_ids
                    and item.status != GenerationCandidateStatus.REJECTED
                    and not is_user_deleted_candidate(item)
                )

            selected_deleted = any(
                item.status == GenerationCandidateStatus.SELECTED for item in candidates
            )
            updated_beat = beat
            if selected_deleted and beat.image_status not in {
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }:
                updated_beat = beat.model_copy(
                    update={
                        "image_status": (
                            WorkflowItemStatus.REVIEW_REQUIRED
                            if remaining_candidates
                            else WorkflowItemStatus.READY
                        ),
                        "updated_at": now,
                    }
                )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_CANDIDATES_ARCHIVED,
                f"删除分镜 {plan.index} 画面 {beat.index} 的 {len(candidates)} 个图片候选",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )

        await self._notify_candidate_lifecycle(
            next_project,
            updated_plan,
            affected_count=len(updated_candidates),
            restored=False,
            kind=GenerationKind.IMAGE,
        )
        return CandidateBatchLifecycleResponse(
            project_id=next_project.id,
            shot_plan_id=updated_plan.id,
            current_revision_id=next_project.current_revision_id,
            candidates=[self._candidate_response(item) for item in updated_candidates],
            affected_count=len(updated_candidates),
        )

    async def restore_image_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
    ) -> CandidateBatchLifecycleResponse:
        first_candidate = await self._require_candidate(payload.candidate_ids[0])
        first_run = await self._require_run(first_candidate.generation_run_id)
        lock = await self._project_lock(first_run.project_id)
        async with lock:
            project, plan, beat, candidates = await self._load_image_candidate_batch(
                payload.candidate_ids
            )
            self._require_expected_revision(project, payload.expected_revision_id)
            if not all(is_user_deleted_candidate(item) for item in candidates):
                raise _fail(
                    409,
                    "image_candidate_restore_unavailable",
                    "仅能恢复由用户删除的图片候选",
                )

            now = utc_now()
            revision_id = uuid4()
            updated_candidates = restore_candidate_records(candidates)
            updated_beat = beat
            if beat.image_status not in {
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }:
                updated_beat = beat.model_copy(
                    update={
                        "image_status": WorkflowItemStatus.REVIEW_REQUIRED,
                        "updated_at": now,
                    }
                )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_CANDIDATES_RESTORED,
                f"恢复分镜 {plan.index} 画面 {beat.index} 的 {len(candidates)} 个图片候选",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )

        await self._notify_candidate_lifecycle(
            next_project,
            updated_plan,
            affected_count=len(updated_candidates),
            restored=True,
            kind=GenerationKind.IMAGE,
        )
        return CandidateBatchLifecycleResponse(
            project_id=next_project.id,
            shot_plan_id=updated_plan.id,
            current_revision_id=next_project.current_revision_id,
            candidates=[self._candidate_response(item) for item in updated_candidates],
            affected_count=len(updated_candidates),
        )

    async def archive_video_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
        *,
        actor_account_id: UUID | None = None,
    ) -> CandidateBatchLifecycleResponse:
        first_candidate = await self._require_candidate(payload.candidate_ids[0])
        first_run = await self._require_run(first_candidate.generation_run_id)
        lock = await self._project_lock(first_run.project_id)
        async with lock:
            project, plan, candidates = await self._load_video_candidate_batch(
                payload.candidate_ids
            )
            self._require_expected_revision(project, payload.expected_revision_id)

            approved_candidate_id = plan.approved_video_candidate_id
            if any(item.id == approved_candidate_id for item in candidates):
                raise _fail(
                    409,
                    "approved_video_candidate_archive_forbidden",
                    "已采用的视频不能移入回收站，请先取消采用或改用其他视频",
                )
            unavailable = [
                item
                for item in candidates
                if item.status
                not in {
                    GenerationCandidateStatus.READY,
                    GenerationCandidateStatus.SELECTED,
                }
            ]
            if unavailable:
                raise _fail(
                    409,
                    "video_candidate_archive_unavailable",
                    "所选视频包含已退回或已归档候选，请刷新后重试",
                )

            now = utc_now()
            revision_id = uuid4()
            candidate_ids = {item.id for item in candidates}
            updated_candidates = archive_candidate_records(
                candidates,
                actor_account_id=actor_account_id,
                archived_at=now,
            )

            remaining_candidates: list[GenerationCandidate] = []
            for run in await self.repository.list_generation_runs(project.id, plan.id):
                if run.kind != GenerationKind.VIDEO:
                    continue
                remaining_candidates.extend(
                    item
                    for item in await self.repository.list_generation_candidates(run.id)
                    if item.id not in candidate_ids
                    and item.status
                    in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }
                )

            next_video_status = plan.video_status
            if (
                any(item.status == GenerationCandidateStatus.SELECTED for item in candidates)
                and plan.video_status != WorkflowItemStatus.APPROVED
            ):
                next_video_status = (
                    WorkflowItemStatus.REVIEW_REQUIRED
                    if remaining_candidates
                    else WorkflowItemStatus.READY
                )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": next_video_status,
                    "updated_at": now,
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == updated_plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_CANDIDATES_ARCHIVED,
                f"将分镜 {plan.index} 的 {len(candidates)} 个视频候选移入回收站",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )

        await self._notify_candidate_lifecycle(
            next_project,
            updated_plan,
            affected_count=len(updated_candidates),
            restored=False,
            kind=GenerationKind.VIDEO,
        )
        return CandidateBatchLifecycleResponse(
            project_id=next_project.id,
            shot_plan_id=updated_plan.id,
            current_revision_id=next_project.current_revision_id,
            candidates=[self._candidate_response(item) for item in updated_candidates],
            affected_count=len(updated_candidates),
        )

    async def restore_video_candidates(
        self,
        payload: CandidateBatchLifecycleRequest,
    ) -> CandidateBatchLifecycleResponse:
        first_candidate = await self._require_candidate(payload.candidate_ids[0])
        first_run = await self._require_run(first_candidate.generation_run_id)
        lock = await self._project_lock(first_run.project_id)
        async with lock:
            project, plan, candidates = await self._load_video_candidate_batch(
                payload.candidate_ids
            )
            self._require_expected_revision(project, payload.expected_revision_id)

            restorable = all(is_user_deleted_candidate(item) for item in candidates)
            if not restorable:
                raise _fail(
                    409,
                    "video_candidate_restore_unavailable",
                    "仅能恢复由用户移入回收站的视频候选",
                )

            now = utc_now()
            revision_id = uuid4()
            updated_candidates = restore_candidate_records(candidates)

            next_video_status = plan.video_status
            if plan.video_status not in {
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }:
                next_video_status = WorkflowItemStatus.REVIEW_REQUIRED
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": next_video_status,
                    "updated_at": now,
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == updated_plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": now})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_CANDIDATES_RESTORED,
                f"恢复分镜 {plan.index} 的 {len(candidates)} 个视频候选",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )

        await self._notify_candidate_lifecycle(
            next_project,
            updated_plan,
            affected_count=len(updated_candidates),
            restored=True,
            kind=GenerationKind.VIDEO,
        )
        return CandidateBatchLifecycleResponse(
            project_id=next_project.id,
            shot_plan_id=updated_plan.id,
            current_revision_id=next_project.current_revision_id,
            candidates=[self._candidate_response(item) for item in updated_candidates],
            affected_count=len(updated_candidates),
        )

    async def select_candidate(
        self,
        candidate_id: UUID,
        payload: CandidateSelectRequest,
    ) -> CandidateActionResponse:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        lock = await self._project_lock(run.project_id)
        async with lock:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            plan = await self._require_shot(run.shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(run.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if candidate.kind != run.kind:
                raise _fail(409, "candidate_kind_mismatch", "候选类型与生成任务不匹配")
            if run.kind == GenerationKind.IMAGE and _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_candidate_forbidden",
                    "模拟占位候选不能选择，请使用真实模型生成或直接采用源关键帧",
                )
            if candidate.status == GenerationCandidateStatus.REJECTED or (
                candidate.status == GenerationCandidateStatus.ARCHIVED
                and (
                    run.kind != GenerationKind.IMAGE
                    or is_user_deleted_candidate(candidate)
                )
            ):
                raise _fail(409, "candidate_unavailable", "该候选已退回或归档")
            beat = (
                _visual_beat(plan, run.visual_beat_id) if run.kind == GenerationKind.IMAGE else None
            )
            target_status = beat.image_status if beat is not None else plan.video_status
            if run.kind == GenerationKind.VIDEO and target_status == WorkflowItemStatus.APPROVED:
                raise _fail(
                    409,
                    "video_already_approved",
                    "当前已有采用视频，请直接使用“改用此视频”切换候选",
                )
            if run.kind != GenerationKind.IMAGE and target_status == WorkflowItemStatus.STALE:
                raise _fail(409, "candidate_stale", "分镜输入已修改，请重新生成候选")
            shot_runs = [
                item
                for item in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                )
                if item.kind == run.kind
                and (beat is None or _run_matches_visual_beat(item, plan, beat.id))
            ]
            run_candidates: list[GenerationCandidate] = []
            for shot_run in shot_runs:
                run_candidates.extend(await self.repository.list_generation_candidates(shot_run.id))
            updated_candidates = [
                item.model_copy(
                    update={
                        "status": (
                            GenerationCandidateStatus.SELECTED
                            if item.id == candidate.id
                            else (
                                GenerationCandidateStatus.READY
                                if item.status == GenerationCandidateStatus.SELECTED
                                else item.status
                            )
                        )
                    }
                )
                for item in run_candidates
            ]
            selected = next(item for item in updated_candidates if item.id == candidate.id)
            revision_id = uuid4()
            if run.kind == GenerationKind.IMAGE:
                assert beat is not None
                change_kind = ProductionChangeKind.IMAGE_CANDIDATE_SELECTED
                summary = f"选择分镜 {plan.index} 画面 {beat.index} 的图片候选 {candidate.ordinal}"
                updated_beat = beat.model_copy(
                    update={
                        "image_status": WorkflowItemStatus.REVIEW_REQUIRED,
                        "approved_image_candidate_id": None,
                        "updated_at": utc_now(),
                    }
                )
                updated_plan = _sync_shot_visual_beats(
                    plan,
                    [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                    revision_id=revision_id,
                )
            else:
                if project.active_step != ProductionStep.SHOT_VIDEOS:
                    raise _fail(409, "video_stage_not_active", "当前方案不在分段视频阶段")
                plan_updates = {
                    "video_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_video_candidate_id": None,
                }
                change_kind = ProductionChangeKind.VIDEO_CANDIDATE_SELECTED
                summary = f"选择分镜 {plan.index} 的视频候选 {candidate.ordinal}"
                updated_plan = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        **plan_updates,
                        "updated_at": utc_now(),
                    }
                )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                change_kind,
                summary,
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(selected),
        )

    async def approve_candidate(
        self,
        candidate_id: UUID,
        payload: CandidateApprovalRequest,
    ) -> CandidateActionResponse:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        lock = await self._project_lock(run.project_id)
        async with lock:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            plan = await self._require_shot(run.shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(run.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if candidate.kind != run.kind:
                raise _fail(409, "candidate_kind_mismatch", "候选类型与生成任务不匹配")
            if run.kind == GenerationKind.IMAGE and _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_candidate_forbidden",
                    "模拟占位候选不能确认，请使用真实模型生成或直接采用源关键帧",
                )
            beat = (
                _visual_beat(plan, run.visual_beat_id) if run.kind == GenerationKind.IMAGE else None
            )
            target_status = beat.image_status if beat is not None else plan.video_status
            direct_image_approval = (
                run.kind == GenerationKind.IMAGE and payload.decision == ApprovalDecision.APPROVED
            )
            replacing_image_approval = (
                direct_image_approval
                and target_status == WorkflowItemStatus.APPROVED
                and beat is not None
                and beat.approved_image_candidate_id != candidate.id
            )
            replacing_video_approval = (
                run.kind == GenerationKind.VIDEO
                and payload.decision == ApprovalDecision.APPROVED
                and target_status == WorkflowItemStatus.APPROVED
                and plan.approved_video_candidate_id != candidate.id
            )
            preserving_video_approval_on_reject = (
                run.kind == GenerationKind.VIDEO
                and payload.decision == ApprovalDecision.REJECTED
                and target_status == WorkflowItemStatus.APPROVED
                and plan.approved_video_candidate_id != candidate.id
            )
            replacing_approved = replacing_image_approval or replacing_video_approval
            direct_approval = direct_image_approval or replacing_video_approval
            if (
                target_status == WorkflowItemStatus.APPROVED
                and payload.decision == ApprovalDecision.APPROVED
                and not replacing_approved
            ):
                raise _fail(
                    409,
                    (
                        "image_already_approved"
                        if run.kind == GenerationKind.IMAGE
                        else "video_already_approved"
                    ),
                    (
                        "该分镜图片已审批，如需修改请先调整分镜输入"
                        if run.kind == GenerationKind.IMAGE
                        else "该分镜视频已审批，如需修改请先取消采用"
                    ),
                )
            if (
                payload.decision == ApprovalDecision.APPROVED
                and not direct_approval
                and candidate.status != GenerationCandidateStatus.SELECTED
            ):
                raise _fail(409, "candidate_selection_required", "请先选择候选，再执行审批")
            if candidate.status == GenerationCandidateStatus.REJECTED:
                raise _fail(409, "candidate_unavailable", "已退回候选不能审批")
            if candidate.status == GenerationCandidateStatus.ARCHIVED and (
                not direct_image_approval or is_user_deleted_candidate(candidate)
            ):
                raise _fail(409, "candidate_unavailable", "已归档候选不能审批")
            if target_status == WorkflowItemStatus.STALE and not direct_image_approval:
                raise _fail(409, "candidate_stale", "分镜输入已修改，请重新生成候选")
            shot_runs = [
                item
                for item in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                )
                if item.kind == run.kind
                and (beat is None or _run_matches_visual_beat(item, plan, beat.id))
            ]
            image_downstream_impact = (
                replacing_image_approval and self._image_choice_has_downstream_impact(project, plan)
            )
            video_downstream_impact = replacing_video_approval and project.active_step in {
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            requires_downstream_confirmation = image_downstream_impact or video_downstream_impact
            invalidate_preparation = image_downstream_impact or replacing_video_approval
            if requires_downstream_confirmation and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    (
                        "改用该历史视频会使本分镜的剪辑或导出结果过期，请确认影响后重试"
                        if replacing_video_approval
                        else "改用该历史候选会使本分镜的后续视频或合成结果过期，请确认影响后重试"
                    ),
                )
            if (
                run.kind == GenerationKind.VIDEO
                and payload.decision == ApprovalDecision.REJECTED
                and target_status == WorkflowItemStatus.APPROVED
                and not preserving_video_approval_on_reject
            ):
                raise _fail(
                    409,
                    "video_already_approved",
                    "当前采用视频不能直接退回，请先取消采用",
                )

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=run.kind,
                decision=payload.decision,
                reason=(
                    _simplified_text(
                        payload.reason or "",
                        field_name="退回原因",
                        max_length=1000,
                    )
                    if payload.decision == ApprovalDecision.REJECTED
                    else (
                        _simplified_text(
                            payload.reason,
                            field_name="审批说明",
                            allow_empty=True,
                            max_length=1000,
                        )
                        if payload.reason is not None
                        else None
                    )
                ),
            )
            updated_candidate = candidate
            candidate_updates: list[GenerationCandidate] = []
            if payload.decision == ApprovalDecision.APPROVED:
                for shot_run in shot_runs:
                    for item in await self.repository.list_generation_candidates(shot_run.id):
                        if item.id == candidate.id:
                            updated_candidate = item.model_copy(
                                update={
                                    "status": GenerationCandidateStatus.SELECTED,
                                }
                            )
                            candidate_updates.append(updated_candidate)
                        elif item.status == GenerationCandidateStatus.SELECTED:
                            candidate_updates.append(
                                item.model_copy(
                                    update={
                                        "status": GenerationCandidateStatus.READY,
                                    }
                                )
                            )
                next_status = WorkflowItemStatus.APPROVED
                approved_candidate_id: UUID | None = candidate.id
                change_kind = (
                    ProductionChangeKind.IMAGE_APPROVED
                    if run.kind == GenerationKind.IMAGE
                    else ProductionChangeKind.VIDEO_APPROVED
                )
                summary = (
                    (
                        f"审批通过分镜 {plan.index} 画面 {beat.index} 图片"
                        if beat is not None
                        else f"审批通过分镜 {plan.index} 图片"
                    )
                    if run.kind == GenerationKind.IMAGE
                    else f"审批通过分镜 {plan.index} 视频"
                )
            else:
                updated_candidate = candidate.model_copy(
                    update={"status": GenerationCandidateStatus.REJECTED}
                )
                candidate_updates.append(updated_candidate)
                other_candidates: list[GenerationCandidate] = []
                for shot_run in shot_runs:
                    other_candidates.extend(
                        item
                        for item in await self.repository.list_generation_candidates(shot_run.id)
                        if item.id != candidate.id
                        and item.status
                        in {
                            GenerationCandidateStatus.READY,
                            GenerationCandidateStatus.SELECTED,
                        }
                    )
                next_status = (
                    WorkflowItemStatus.APPROVED
                    if preserving_video_approval_on_reject
                    else (
                        WorkflowItemStatus.REVIEW_REQUIRED
                        if other_candidates
                        else WorkflowItemStatus.READY
                    )
                )
                approved_candidate_id = (
                    plan.approved_video_candidate_id
                    if preserving_video_approval_on_reject
                    else None
                )
                change_kind = (
                    ProductionChangeKind.IMAGE_REJECTED
                    if run.kind == GenerationKind.IMAGE
                    else ProductionChangeKind.VIDEO_REJECTED
                )
                summary = (
                    (
                        f"退回分镜 {plan.index} 画面 {beat.index} 图片候选"
                        if beat is not None
                        else f"退回分镜 {plan.index} 图片候选"
                    )
                    if run.kind == GenerationKind.IMAGE
                    else f"退回分镜 {plan.index} 视频候选"
                )
            if run.kind == GenerationKind.IMAGE:
                assert beat is not None
                active_step = ProductionStep.SHOT_IMAGES
                updated_beat = beat.model_copy(
                    update={
                        "image_status": next_status,
                        "approved_image_candidate_id": approved_candidate_id,
                        "updated_at": utc_now(),
                    }
                )
                updated_plan = _sync_shot_visual_beats(
                    plan,
                    [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                    revision_id=revision_id,
                    invalidate_video=image_downstream_impact,
                )
            else:
                if project.active_step not in {
                    ProductionStep.SHOT_VIDEOS,
                    ProductionStep.EDITING,
                    ProductionStep.EXPORT,
                }:
                    raise _fail(409, "video_stage_not_active", "当前方案不在分段视频阶段")
                plan_updates = {
                    "video_status": next_status,
                    "approved_video_candidate_id": approved_candidate_id,
                }
                active_step = (
                    project.active_step
                    if preserving_video_approval_on_reject
                    else ProductionStep.SHOT_VIDEOS
                )
                updated_plan = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        **plan_updates,
                        "updated_at": utc_now(),
                    }
                )
            updated_preparation: VideoClipPreparation | None = None
            next_preparations: list[VideoClipPreparation] | None = None
            if invalidate_preparation:
                current_preparation = await self.repository.get_video_clip_preparation(plan.id)
                if current_preparation is not None:
                    updated_preparation = current_preparation.model_copy(
                        update={
                            "revision_id": revision_id,
                            "status": VideoClipPreparationStatus.STALE,
                            "blocker_messages": [
                                (
                                    "已改用其他视频候选，需要重新完成剪辑准备"
                                    if replacing_video_approval
                                    else "起始图片已经更换，需要重新生成视频并完成剪辑准备"
                                )
                            ],
                            "warning_messages": [],
                            "updated_at": utc_now(),
                        }
                    )
                    preparations = await self.repository.list_video_clip_preparations(project.id)
                    next_preparations = [
                        item for item in preparations if item.shot_plan_id != plan.id
                    ]
                    next_preparations.append(updated_preparation)
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": active_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                change_kind,
                summary,
                revision_id=revision_id,
                shot_plans=next_plans,
                video_clip_preparations=next_preparations,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=candidate_updates,
                video_clip_preparations=(
                    [updated_preparation] if updated_preparation is not None else None
                ),
                approval_events=[event],
            )
            if (
                run.kind == GenerationKind.VIDEO
                and plan.approved_video_candidate_id
                != updated_plan.approved_video_candidate_id
            ):
                await self.continuity.invalidate_for_shot(
                    project.id,
                    plan.id,
                    revision_id,
                )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def revoke_image_approval(
        self,
        shot_plan_id: UUID,
        payload: ShotImageApprovalRevokeRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            beat = _visual_beat(plan, payload.visual_beat_id)
            if beat.image_status != WorkflowItemStatus.APPROVED:
                raise _fail(409, "image_not_approved", "当前画面图片尚未采用，无需取消")
            if beat.approved_image_candidate_id is None:
                raise _fail(
                    409,
                    "approved_candidate_missing",
                    "当前画面的已采用图片记录不完整，请重新打开方案后重试",
                )

            candidate = await self._require_candidate(beat.approved_image_candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if (
                candidate.kind != GenerationKind.IMAGE
                or run.project_id != project.id
                or run.shot_plan_id != plan.id
                or not _run_matches_visual_beat(run, plan, beat.id)
            ):
                raise _fail(
                    409,
                    "approved_candidate_mismatch",
                    "当前分镜的已采用图片与候选记录不匹配",
                )
            if candidate.status == GenerationCandidateStatus.REJECTED:
                raise _fail(
                    409,
                    "approved_candidate_unavailable",
                    "当前已采用图片已退回，无法重新打开审核",
                )

            downstream_result_statuses = {
                WorkflowItemStatus.GENERATING,
                WorkflowItemStatus.REVIEW_REQUIRED,
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }
            downstream_stage_active = project.active_step in {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            has_downstream_impact = (
                plan.video_status in downstream_result_statuses or downstream_stage_active
            )
            if has_downstream_impact and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "取消采用会使该分镜的后续视频或合成结果过期，请确认影响后重试",
                )

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=run.kind,
                decision=ApprovalDecision.REVOKED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="取消采用说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "重新打开图片审核"
                ),
            )
            updated_candidate = (
                candidate
                if candidate.status == GenerationCandidateStatus.SELECTED
                else candidate.model_copy(update={"status": GenerationCandidateStatus.SELECTED})
            )
            updated_beat = beat.model_copy(
                update={
                    "image_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            updated_plan = _sync_shot_visual_beats(
                plan,
                [updated_beat if item.id == beat.id else item for item in plan.visual_beats],
                revision_id=revision_id,
                invalidate_video=has_downstream_impact,
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            current_preparation = await self.repository.get_video_clip_preparation(plan.id)
            updated_preparation = (
                current_preparation.model_copy(
                    update={
                        "revision_id": revision_id,
                        "status": VideoClipPreparationStatus.STALE,
                        "blocker_messages": ["起始图片已取消采用，需要重新生成视频并完成剪辑准备"],
                        "warning_messages": [],
                        "updated_at": utc_now(),
                    }
                )
                if current_preparation is not None and has_downstream_impact
                else None
            )
            preparations = await self.repository.list_video_clip_preparations(project.id)
            next_preparations = [item for item in preparations if item.shot_plan_id != plan.id]
            if updated_preparation is not None:
                next_preparations.append(updated_preparation)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_APPROVAL_REVOKED,
                f"取消采用分镜 {plan.index} 画面 {beat.index} 图片，重新打开图片审核",
                revision_id=revision_id,
                shot_plans=next_plans,
                video_clip_preparations=next_preparations,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                video_clip_preparations=(
                    [updated_preparation] if updated_preparation is not None else None
                ),
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def revoke_video_approval(
        self,
        shot_plan_id: UUID,
        payload: ShotVideoApprovalRevokeRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if plan.video_status != WorkflowItemStatus.APPROVED:
                raise _fail(409, "video_not_approved", "当前分镜视频尚未采用，无需取消")
            if plan.approved_video_candidate_id is None:
                raise _fail(
                    409,
                    "approved_video_candidate_missing",
                    "当前分镜的已采用视频记录不完整，请重新打开方案后重试",
                )
            candidate = await self._require_candidate(plan.approved_video_candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if (
                candidate.kind != GenerationKind.VIDEO
                or run.kind != GenerationKind.VIDEO
                or run.project_id != project.id
                or run.shot_plan_id != plan.id
            ):
                raise _fail(
                    409,
                    "approved_video_candidate_mismatch",
                    "当前分镜的已采用视频与候选记录不匹配",
                )
            if candidate.status in {
                GenerationCandidateStatus.REJECTED,
                GenerationCandidateStatus.ARCHIVED,
            }:
                raise _fail(
                    409,
                    "approved_video_candidate_unavailable",
                    "当前已采用视频已归档或退回，无法重新打开审核",
                )
            has_downstream_impact = project.active_step in {
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            if has_downstream_impact and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "取消采用会使剪辑或导出结果过期，请确认影响后重试",
                )

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=GenerationKind.VIDEO,
                decision=ApprovalDecision.REVOKED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="取消采用说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "重新打开视频审核"
                ),
            )
            updated_candidate = (
                candidate
                if candidate.status == GenerationCandidateStatus.SELECTED
                else candidate.model_copy(update={"status": GenerationCandidateStatus.SELECTED})
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_video_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            current_preparation = await self.repository.get_video_clip_preparation(plan.id)
            updated_preparation = (
                current_preparation.model_copy(
                    update={
                        "revision_id": revision_id,
                        "status": VideoClipPreparationStatus.STALE,
                        "blocker_messages": ["视频已取消采用，需要重新完成剪辑准备"],
                        "warning_messages": [],
                        "updated_at": utc_now(),
                    }
                )
                if current_preparation is not None
                else None
            )
            preparations = await self.repository.list_video_clip_preparations(project.id)
            next_preparations = [item for item in preparations if item.shot_plan_id != plan.id]
            if updated_preparation is not None:
                next_preparations.append(updated_preparation)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_VIDEOS,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_APPROVAL_REVOKED,
                f"取消采用分镜 {plan.index} 视频，重新打开视频审核",
                revision_id=revision_id,
                shot_plans=next_plans,
                video_clip_preparations=next_preparations,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                video_clip_preparations=(
                    [updated_preparation] if updated_preparation is not None else None
                ),
                approval_events=[event],
            )
            await self.continuity.invalidate_for_shot(
                project.id,
                plan.id,
                revision_id,
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def resolve_candidate_content(
        self,
        candidate_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        plan = await self._require_shot(run.shot_plan_id)
        project = await self._require_project(run.project_id)
        relative_path = candidate.thumbnail_relative_path if thumbnail else candidate.relative_path
        if relative_path is None:
            raise _fail(404, "candidate_thumbnail_missing", "候选缩略图不存在")
        try:
            resolved = self.workspace.resolve(relative_path).resolve()
        except WorkspaceError as exc:
            raise _fail(409, "invalid_candidate_path", "候选文件路径无效") from exc
        root = (
            self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            )
            / ("images" if candidate.kind == GenerationKind.IMAGE else "videos")
            / str(run.id)
        ).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise _fail(409, "invalid_candidate_path", "候选文件路径无效") from exc
        filesystem_path = _filesystem_path(resolved)
        if not filesystem_path.is_file():
            raise _fail(404, "candidate_file_missing", "候选文件不存在")
        if thumbnail:
            return filesystem_path, "image/webp"
        return filesystem_path, (
            "image/jpeg" if candidate.kind == GenerationKind.IMAGE else "video/mp4"
        )

    async def _has_valid_approved_image_output(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> bool:
        targets = [item for item in plan.visual_beats if item.required] or list(plan.visual_beats)
        if not targets:
            return False
        for beat in targets:
            candidate_id = beat.approved_image_candidate_id
            if beat.image_status != WorkflowItemStatus.APPROVED or candidate_id is None:
                return False
            candidate = await self.repository.get_generation_candidate(candidate_id)
            if (
                candidate is None
                or candidate.kind != GenerationKind.IMAGE
                or candidate.status != GenerationCandidateStatus.SELECTED
            ):
                return False
            run = await self.repository.get_generation_run(candidate.generation_run_id)
            if not (
                run is not None
                and run.project_id == project.id
                and run.shot_plan_id == plan.id
                and run.kind == GenerationKind.IMAGE
                and _run_matches_visual_beat(run, plan, beat.id)
                and run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
                and not _is_simulated_image_run(run)
            ):
                return False
            try:
                await self.resolve_candidate_content(candidate.id)
            except ProductionServiceError:
                return False
        return True

    async def _has_valid_approved_video_output(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> bool:
        candidate_id = plan.approved_video_candidate_id
        if plan.video_status != WorkflowItemStatus.APPROVED or candidate_id is None:
            return False
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if (
            candidate is None
            or candidate.kind != GenerationKind.VIDEO
            or candidate.status != GenerationCandidateStatus.SELECTED
        ):
            return False
        run = await self.repository.get_generation_run(candidate.generation_run_id)
        if not (
            run is not None
            and run.project_id == project.id
            and run.shot_plan_id == plan.id
            and run.kind == GenerationKind.VIDEO
            and run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
        ):
            return False
        try:
            await self.resolve_candidate_content(candidate.id)
        except ProductionServiceError:
            return False
        return True

    async def gate_status(self, project_id: UUID) -> ProductionGateStatus:
        project = await self._require_project(project_id)
        project, plans = await self._ensure_project_shots(project)
        required = [
            item
            for item in plans
            if item.lifecycle_status == ShotLifecycleStatus.ACTIVE and item.required
        ]
        video_stage = project.active_step in {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }
        prepared: list[ShotPlan] = []
        quality_warnings: list[ShotPlan] = []
        if video_stage:
            approved = [
                item
                for item in required
                if await self._has_valid_approved_video_output(project, item)
            ]
            for item in approved:
                preparation = await self.repository.get_video_clip_preparation(item.id)
                if preparation is not None:
                    preparation = _apply_video_preparation_policy(preparation)
                if (
                    preparation is not None
                    and preparation.candidate_id == item.approved_video_candidate_id
                    and preparation.status == VideoClipPreparationStatus.READY
                ):
                    prepared.append(item)
                    if (
                        preparation.quality_status == VideoQualityStatus.WARNING
                        or preparation.warning_messages
                    ):
                        quality_warnings.append(item)
                elif item.approved_video_candidate_id is not None:
                    candidate = await self.repository.get_generation_candidate(
                        item.approved_video_candidate_id
                    )
                    quality_report = candidate.quality_report if candidate is not None else {}
                    if (
                        not quality_report
                        or quality_report.get("status") == VideoQualityStatus.WARNING.value
                        or quality_report.get("warnings")
                    ):
                        quality_warnings.append(item)
            stale = [item for item in required if item.video_status == WorkflowItemStatus.STALE]
            next_step = (
                ProductionStep.EDITING
                if project.active_step == ProductionStep.SHOT_VIDEOS
                else None
            )
            pending_label = "必需分镜视频"
        else:
            approved = [
                item
                for item in required
                if await self._has_valid_approved_image_output(project, item)
            ]
            stale = [item for item in required if item.image_status == WorkflowItemStatus.STALE]
            next_step = ProductionStep.SHOT_VIDEOS
            pending_label = "必需分镜图片"
        blockers: list[str] = []
        if not required:
            blockers.append("创作方案没有必需分镜")
        pending = len(required) - len(approved)
        if pending:
            blockers.append(f"仍有 {pending} 个{pending_label}未审批")
        if stale:
            blockers.append(f"有 {len(stale)} 个分镜结果已过期")
        continuity_report = await self.continuity.latest_report(project.id) if video_stage else None
        continuity_status = "not_run"
        continuity_verification_state = None
        continuity_blocker_count = 0
        continuity_warning_count = 0
        if continuity_report is not None:
            continuity_status = continuity_report.status.value
            continuity_verification_state = continuity_report.verification_state.value
            continuity_blocker_count = continuity_report.blocker_count
            continuity_warning_count = continuity_report.warning_count
            if continuity_report.status == ContinuityReportStatus.STALE:
                blockers.append("相邻分镜连续性质检已过期，请重新检查")
            elif continuity_report.blocker_count:
                blockers.append(f"连续性质检仍有 {continuity_report.blocker_count} 个阻断问题")
        return ProductionGateStatus(
            project_id=project.id,
            current_step=project.active_step,
            next_step=next_step,
            allowed=bool(required) and not blockers,
            required_shot_count=len(required),
            approved_shot_count=len(approved),
            prepared_shot_count=len(prepared),
            quality_warning_shot_count=len(quality_warnings),
            stale_shot_count=len(stale),
            continuity_status=continuity_status,
            continuity_verification_state=continuity_verification_state,
            continuity_blocker_count=continuity_blocker_count,
            continuity_warning_count=continuity_warning_count,
            blocker_messages=blockers,
        )

    async def get_editing_handoff(self, project_id: UUID) -> EditingHandoffManifest:
        project = await self._require_project(project_id)
        manifest_path = (
            self.workspace.production_paths(project.record_id, project.id).timelines
            / "editing-handoff.json"
        )
        filesystem_path = _filesystem_path(manifest_path.resolve())
        if not filesystem_path.is_file():
            raise _fail(
                404,
                "editing_handoff_missing",
                "尚未生成剪辑交接清单，请先确认全部必需视频并进入视频剪辑",
            )
        try:
            manifest = EditingHandoffManifest.model_validate_json(
                filesystem_path.read_text("utf-8-sig")
            )
        except (OSError, ValidationError) as exc:
            raise _fail(
                409,
                "editing_handoff_invalid",
                "剪辑交接清单损坏，请重新推进工作流",
            ) from exc
        if manifest.project_id != project.id:
            raise _fail(409, "editing_handoff_mismatch", "剪辑交接清单与当前创作方案不匹配")
        return manifest

    async def _build_editing_handoff(
        self,
        project: ProductionProject,
        revision_id: UUID,
    ) -> EditingHandoffManifest:
        report = await self.repository.get_report_by_analysis(project.base_analysis_id)
        if report is None:
            raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
        source_audio_url = report.media_evidence.audio_url if report.media_evidence else None
        plans = sorted(
            (
                item
                for item in await self.repository.list_shot_plans(project.id)
                if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
            ),
            key=lambda item: item.index,
        )
        clips: list[EditingHandoffClip] = []
        timeline_cursor = 0.0
        for plan in plans:
            if not await self._has_valid_approved_video_output(project, plan):
                continue
            preparation = await self.repository.get_video_clip_preparation(plan.id)
            if preparation is not None:
                preparation = _apply_video_preparation_policy(preparation)
            legacy_preparation = (
                preparation
                if preparation is not None
                and preparation.candidate_id == plan.approved_video_candidate_id
                and preparation.status == VideoClipPreparationStatus.READY
                else None
            )
            candidate = await self.repository.get_generation_candidate(
                plan.approved_video_candidate_id
            )
            if candidate is None:
                if plan.required:
                    raise _fail(
                        409,
                        "editing_handoff_candidate_missing",
                        f"分镜 {plan.index} 的已采用视频不存在",
                    )
                continue

            candidate_duration = round(
                float(candidate.duration_seconds or plan.duration_seconds),
                3,
            )
            if legacy_preparation is not None:
                trim_in = legacy_preparation.trim_in_seconds
                trim_out = legacy_preparation.trim_out_seconds
                timeline_duration = legacy_preparation.timeline_duration_seconds
                playback_rate = legacy_preparation.video_playback_rate
                cover_url = f"/api/v1/production-shots/{plan.id}/video-preparation/cover"
                cover_timestamp = legacy_preparation.cover_timestamp_seconds
                audio_mode = legacy_preparation.audio_mode
                source_audio_start = legacy_preparation.source_audio_start_seconds
                source_audio_end = legacy_preparation.source_audio_end_seconds
                transcript_cues = legacy_preparation.transcript_cues
                subtitle_cues = legacy_preparation.subtitle_cues
                quality_status = legacy_preparation.quality_status
                quality_report = legacy_preparation.quality_report
                blocker_messages = legacy_preparation.blocker_messages
                warning_messages = legacy_preparation.warning_messages
            else:
                trim_in = 0.0
                trim_out = candidate_duration
                timeline_duration = round(float(plan.duration_seconds), 3)
                playback_rate, duration_alignment = playback_alignment(
                    candidate_duration,
                    timeline_duration,
                )
                cover_url = f"/api/v1/generation-candidates/{candidate.id}/thumbnail"
                cover_timestamp = round(candidate_duration / 2, 3)
                audio_mode = (
                    VideoClipAudioMode.SOURCE if source_audio_url else VideoClipAudioMode.MUTED
                )
                source_audio_start = round(plan.start_seconds, 3)
                source_audio_end = round(plan.end_seconds, 3)
                evidence = report.evidence_timeline
                transcript_cues = (
                    map_timed_text(
                        evidence.transcript_segments,
                        source_start_seconds=plan.start_seconds,
                        source_end_seconds=plan.end_seconds,
                        kind="transcript",
                    )
                    if evidence is not None
                    else []
                )
                subtitle_cues = (
                    map_timed_text(
                        evidence.subtitle_cues,
                        source_start_seconds=plan.start_seconds,
                        source_end_seconds=plan.end_seconds,
                        kind="subtitle",
                    )
                    if evidence is not None
                    else []
                )
                quality_report = candidate.quality_report or {}
                try:
                    quality_status = VideoQualityStatus(
                        quality_report.get("status", VideoQualityStatus.WARNING)
                    )
                except ValueError:
                    quality_status = VideoQualityStatus.WARNING
                blocker_messages = []
                warning_messages = [
                    str(item) for item in quality_report.get("warnings", []) if str(item).strip()
                ]
                if not quality_report:
                    warning_messages.append("将在视频剪辑阶段完成基础质检")
                if duration_alignment == "outside_safe_range":
                    warning_messages.append(_duration_alignment_warning(playback_rate))
                warning_messages = list(dict.fromkeys(warning_messages))
            timeline_start = round(timeline_cursor, 3)
            timeline_end = round(timeline_start + timeline_duration, 3)
            clips.append(
                EditingHandoffClip(
                    shot_plan_id=plan.id,
                    shot_index=plan.index,
                    candidate_id=candidate.id,
                    candidate_content_url=(f"/api/v1/generation-candidates/{candidate.id}/content"),
                    cover_url=cover_url,
                    cover_timestamp_seconds=cover_timestamp,
                    timeline_start_seconds=timeline_start,
                    timeline_end_seconds=timeline_end,
                    timeline_duration_seconds=timeline_duration,
                    trim_in_seconds=trim_in,
                    trim_out_seconds=trim_out,
                    video_playback_rate=playback_rate,
                    audio_mode=audio_mode,
                    source_audio_start_seconds=source_audio_start,
                    source_audio_end_seconds=source_audio_end,
                    transcript_cues=transcript_cues,
                    subtitle_cues=subtitle_cues,
                    quality_status=quality_status,
                    quality_report=quality_report,
                    blocker_messages=blocker_messages,
                    warning_messages=warning_messages,
                )
            )
            timeline_cursor = timeline_end
        if not clips:
            raise _fail(409, "editing_handoff_empty", "没有可交给剪辑阶段的视频片段")

        source_clips = [item for item in clips if item.audio_mode == VideoClipAudioMode.SOURCE]
        ranges_are_contiguous = all(
            abs(left.source_audio_end_seconds - right.source_audio_start_seconds) <= 0.05
            for left, right in zip(
                source_clips,
                source_clips[1:],
                strict=False,
            )
        )
        if source_audio_url and len(source_clips) == len(clips) and ranges_are_contiguous:
            audio_strategy = "continuous_source_track"
        elif source_clips:
            audio_strategy = "per_shot"
        else:
            audio_strategy = "muted"
        return EditingHandoffManifest(
            project_id=project.id,
            revision_id=revision_id,
            source_analysis_id=project.base_analysis_id,
            source_audio_url=source_audio_url,
            audio_strategy=audio_strategy,
            timeline_duration_seconds=round(timeline_cursor, 3),
            clips=clips,
        )

    async def advance(
        self,
        project_id: UUID,
        payload: ProductionAdvanceRequest,
    ) -> ProductionProjectDetail:
        initial_project = await self._require_project(project_id)
        await self._ensure_project_shots(initial_project)
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if project.active_step == payload.target_step:
                label = (
                    "分段视频" if payload.target_step == ProductionStep.SHOT_VIDEOS else "视频剪辑"
                )
                raise _fail(409, "workflow_already_advanced", f"当前方案已进入{label}阶段")
            expected_target = (
                ProductionStep.EDITING
                if project.active_step == ProductionStep.SHOT_VIDEOS
                else ProductionStep.SHOT_VIDEOS
            )
            if payload.target_step != expected_target:
                raise _fail(
                    409,
                    "unsupported_target_step",
                    f"当前阶段只能推进到 {expected_target.value}",
                )
            if payload.target_step == ProductionStep.EDITING:
                try:
                    await self.continuity.ensure_current_report(project.id)
                except ContinuityServiceError as exc:
                    raise _fail(exc.status_code, exc.code, str(exc)) from exc
            gate = await self.gate_status(project.id)
            if not gate.allowed:
                raise _fail(
                    409,
                    "workflow_gate_blocked",
                    "；".join(gate.blocker_messages) or "当前步骤尚未满足推进条件",
                )
            revision_id = uuid4()
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": payload.target_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.WORKFLOW_ADVANCED,
                (
                    "所有必需分镜视频已审批，推进到视频剪辑"
                    if payload.target_step == ProductionStep.EDITING
                    else "所有必需分镜图片已审批，推进到分段视频"
                ),
                revision_id=revision_id,
            )
            if payload.target_step == ProductionStep.EDITING:
                handoff = await self._build_editing_handoff(next_project, revision_id)
                handoff_path = (
                    self.workspace.production_paths(project.record_id, project.id).timelines
                    / "editing-handoff.json"
                )
                try:
                    await asyncio.to_thread(
                        self._write_json_atomic,
                        _filesystem_path(handoff_path.resolve()),
                        handoff.model_dump(mode="json"),
                    )
                except OSError as exc:
                    raise _fail(
                        500,
                        "editing_handoff_write_failed",
                        "无法写入剪辑交接清单，请检查工作区权限后重试",
                    ) from exc
            await self.repository.save_production_bundle(next_project, revision)
        return await self.get_project(project_id)

    async def mark_export_completed(
        self,
        project_id: UUID,
        timeline_revision_id: UUID,
        export_job_id: UUID,
    ) -> None:
        """Close the production workflow after a validated final export succeeds."""

        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            if (
                project.active_step == ProductionStep.EXPORT
                and project.status == ProductionProjectStatus.COMPLETED
            ):
                return
            if project.active_step != ProductionStep.EDITING:
                raise _fail(409, "export_stage_conflict", "创作方案当前不在视频剪辑阶段")
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.COMPLETED,
                    "active_step": ProductionStep.EXPORT,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.WORKFLOW_ADVANCED,
                (
                    f"时间线 {timeline_revision_id} 已生成并校验最终高清成片；"
                    f"导出任务 {export_job_id}"
                ),
            )
            await self.repository.save_production_bundle(next_project, revision)

    async def _extract_visual_beat_source_frame(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        beat: ShotVisualBeat,
        source_video: Path,
        revision_id: UUID,
        target_timestamp_seconds: float,
        prior_hashes: list[int],
    ) -> tuple[str, str, float, str, int, str | None] | None:
        frame_root = (
            self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            )
            / "visual-beats"
            / str(beat.id)
            / "source-frames"
        )
        destination = frame_root / f"{revision_id}.jpg"
        temporary_paths: list[Path] = []
        best: tuple[int, Path, float, str, int] | None = None
        for timestamp in _visual_beat_timestamp_candidates(
            plan,
            beat,
            target_timestamp_seconds,
        ):
            temporary = frame_root / f".candidate-{uuid4().hex[:8]}.jpg"
            temporary_paths.append(temporary)
            try:
                await self.media_processor.extract_frame(
                    source_video,
                    timestamp,
                    _filesystem_path(temporary),
                )
                await asyncio.to_thread(self._validate_keyframe_file, temporary)
                sha256, difference_hash = await asyncio.to_thread(
                    _frame_sha256_and_dhash,
                    _filesystem_path(temporary),
                )
            except (MediaProcessingError, OSError, ProductionServiceError):
                _filesystem_path(temporary).unlink(missing_ok=True)
                continue
            distance = (
                min(_hash_distance(difference_hash, item) for item in prior_hashes)
                if prior_hashes
                else 64
            )
            candidate = (distance, temporary, timestamp, sha256, difference_hash)
            if best is None or candidate[0] > best[0]:
                best = candidate
            if not prior_hashes or distance > 4:
                break

        if best is None:
            for temporary in temporary_paths:
                _filesystem_path(temporary).unlink(missing_ok=True)
            return None
        _, best_path, timestamp, sha256, difference_hash = best
        try:
            _filesystem_path(destination).parent.mkdir(parents=True, exist_ok=True)
            os.replace(_filesystem_path(best_path), _filesystem_path(destination))
        except OSError:
            for temporary in temporary_paths:
                _filesystem_path(temporary).unlink(missing_ok=True)
            return None
        finally:
            for temporary in temporary_paths:
                if temporary != best_path:
                    _filesystem_path(temporary).unlink(missing_ok=True)
        warning = "duplicate_frame" if prior_hashes and best[0] <= 4 else None
        relative_path = self.workspace.relative(destination)
        source_url = (
            f"/api/v1/production-shots/{plan.id}/visual-beats/{beat.id}/source-frame"
            f"?v={revision_id}"
        )
        return (
            source_url,
            relative_path,
            round(timestamp, 3),
            sha256,
            difference_hash,
            warning,
        )

    async def _materialize_visual_beat_source_frames(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
        report: AnalysisReport,
        revision_id: UUID,
        *,
        plan_ids: set[UUID],
    ) -> list[ShotPlan]:
        report_shots = {item.id: item for item in report.shots}
        source_video: Path | None = None
        video = await self.repository.get_video(project.video_id)
        if video is not None:
            try:
                source_video = self._resolve_video_file(video)
            except ProductionServiceError:
                source_video = None

        materialized: list[ShotPlan] = []
        for plan in plans:
            if (
                plan.id not in plan_ids
                or plan.source_kind != ShotSourceKind.ANALYSIS
                or len(plan.visual_beats) <= 1
            ):
                materialized.append(plan)
                continue
            source_shot = report_shots.get(plan.source_shot_id)
            if source_shot is None:
                materialized.append(plan)
                continue
            beats = sorted(plan.visual_beats, key=lambda item: item.index)
            specs = _visual_beat_frame_specs(report, source_shot, len(beats))
            prior_frames: list[tuple[int, str]] = []
            next_beats: list[ShotVisualBeat] = []
            for beat, spec in zip(beats, specs, strict=True):
                if beat.source_origin in {"video_selection", "duplicate"}:
                    preserved_hash = beat.source_frame_sha256
                    preserved_dhash: int | None = None
                    preserved_path = self._resolve_source_keyframe(
                        project,
                        _shot_for_visual_beat(plan, beat),
                    )
                    if preserved_path is not None:
                        try:
                            preserved_hash, preserved_dhash = await asyncio.to_thread(
                                _frame_sha256_and_dhash,
                                preserved_path,
                            )
                        except OSError:
                            preserved_dhash = None
                    next_beat = beat.model_copy(update={"source_frame_sha256": preserved_hash})
                    if preserved_dhash is not None:
                        prior_frames.append((preserved_dhash, beat.image_prompt.strip()))
                    next_beats.append(next_beat)
                    continue

                prior_hashes = [
                    item_hash
                    for item_hash, prior_prompt in prior_frames
                    if prior_prompt != beat.image_prompt.strip()
                ]
                extracted = None
                if source_video is not None:
                    target_timestamp = (
                        beat.source_timestamp_seconds
                        if beat.source_timestamp_seconds is not None
                        else spec.target_timestamp_seconds
                    )
                    extracted = await self._extract_visual_beat_source_frame(
                        project,
                        plan,
                        beat,
                        source_video,
                        revision_id,
                        target_timestamp,
                        prior_hashes,
                    )

                if extracted is not None:
                    (
                        source_url,
                        source_relative_path,
                        source_timestamp,
                        source_sha256,
                        source_dhash,
                        source_warning,
                    ) = extracted
                    source_origin = "auto_extract"
                else:
                    source_url = spec.source_url
                    source_relative_path = None
                    source_timestamp = spec.source_timestamp_seconds
                    source_sha256 = None
                    source_dhash = None
                    source_warning = "frame_extract_failed" if source_video is not None else None
                    source_origin = "analysis" if source_url else "blank"
                    fallback = beat.model_copy(
                        update={
                            "source_frame_url": source_url,
                            "source_frame_relative_path": None,
                            "source_timestamp_seconds": source_timestamp,
                        }
                    )
                    fallback_path = self._resolve_source_keyframe(
                        project,
                        _shot_for_visual_beat(plan, fallback),
                    )
                    if fallback_path is not None:
                        try:
                            source_sha256, source_dhash = await asyncio.to_thread(
                                _frame_sha256_and_dhash,
                                fallback_path,
                            )
                        except OSError:
                            source_dhash = None

                if source_dhash is not None:
                    if (
                        prior_hashes
                        and min(_hash_distance(source_dhash, item) for item in prior_hashes) <= 4
                    ):
                        source_warning = "duplicate_frame"
                    prior_frames.append((source_dhash, beat.image_prompt.strip()))
                elif source_url and any(item.source_frame_url == source_url for item in next_beats):
                    source_warning = "duplicate_frame"
                next_beats.append(
                    beat.model_copy(
                        update={
                            "source_frame_url": source_url,
                            "source_frame_relative_path": source_relative_path,
                            "source_timestamp_seconds": source_timestamp,
                            "source_frame_sha256": source_sha256,
                            "source_frame_warning": source_warning,
                            "source_origin": source_origin,
                            "updated_at": utc_now(),
                        }
                    )
                )
            materialized.append(
                _sync_shot_visual_beats(
                    plan,
                    next_beats,
                    revision_id=revision_id,
                    invalidate_video=False,
                )
            )
        return materialized

    @staticmethod
    def _visual_beat_frame_mapping_repair_needed(
        report: AnalysisReport,
        plan: ShotPlan,
    ) -> bool:
        if (
            plan.source_kind != ShotSourceKind.ANALYSIS
            or len(plan.visual_beats) <= 1
            or any(beat.image_status == WorkflowItemStatus.GENERATING for beat in plan.visual_beats)
        ):
            return False
        source_shot = next(
            (item for item in report.shots if item.id == plan.source_shot_id),
            None,
        )
        if source_shot is None:
            return False
        beats = sorted(plan.visual_beats, key=lambda item: item.index)
        eligible = [item for item in beats if item.source_origin in {"analysis", "legacy", "blank"}]
        urls = [item.source_frame_url for item in eligible if item.source_frame_url]
        if len(urls) != len(set(urls)):
            return True
        specs = _visual_beat_frame_specs(report, source_shot, len(beats))
        for beat, spec in zip(beats, specs, strict=True):
            if beat.source_origin not in {"analysis", "legacy", "blank"}:
                continue
            if beat.source_frame_url != spec.source_url:
                return True
            if beat.source_frame_url and (
                beat.source_timestamp_seconds is None
                or spec.source_timestamp_seconds is None
                or abs(beat.source_timestamp_seconds - spec.source_timestamp_seconds) > 0.002
            ):
                return True
        return False

    async def _repair_visual_beat_frame_mappings(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        report = await self.repository.get_report_by_analysis(project.base_analysis_id)
        if report is None or report.video_id != project.video_id:
            return project, plans
        affected_ids = {
            plan.id for plan in plans if self._visual_beat_frame_mapping_repair_needed(report, plan)
        }
        if not affected_ids:
            return project, plans

        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            if report is None or report.video_id != project.video_id:
                return project, plans
            affected_ids = {
                plan.id
                for plan in plans
                if self._visual_beat_frame_mapping_repair_needed(report, plan)
            }
            if not affected_ids:
                return project, plans

            revision_id = uuid4()
            materialized = await self._materialize_visual_beat_source_frames(
                project,
                plans,
                report,
                revision_id,
                plan_ids=affected_ids,
            )
            old_by_id = {item.id: item for item in plans}
            changed_plans: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            candidate_updates_by_id: dict[UUID, GenerationCandidate] = {}
            source_fields = (
                "source_frame_url",
                "source_frame_relative_path",
                "source_timestamp_seconds",
                "source_frame_sha256",
                "source_frame_warning",
                "source_origin",
            )
            for materialized_plan in materialized:
                original_plan = old_by_id[materialized_plan.id]
                if materialized_plan.id not in affected_ids:
                    next_plans.append(original_plan)
                    continue
                old_beats = {item.id: item for item in original_plan.visual_beats}
                next_beats: list[ShotVisualBeat] = []
                changed_beat_ids: list[UUID] = []
                for beat in materialized_plan.visual_beats:
                    old_beat = old_beats[beat.id]
                    changed = any(
                        getattr(old_beat, field) != getattr(beat, field) for field in source_fields
                    )
                    if not changed:
                        next_beats.append(old_beat)
                        continue
                    changed_beat_ids.append(beat.id)
                    reviewed = (
                        old_beat.approved_image_candidate_id is not None
                        or old_beat.image_status
                        in {
                            WorkflowItemStatus.REVIEW_REQUIRED,
                            WorkflowItemStatus.APPROVED,
                            WorkflowItemStatus.STALE,
                        }
                    )
                    next_beats.append(
                        beat.model_copy(
                            update={
                                "approved_image_candidate_id": None,
                                "image_status": (
                                    WorkflowItemStatus.STALE
                                    if reviewed
                                    else (
                                        WorkflowItemStatus.READY
                                        if beat.image_prompt.strip()
                                        else WorkflowItemStatus.DRAFT
                                    )
                                ),
                                "updated_at": utc_now(),
                            }
                        )
                    )
                if not changed_beat_ids:
                    next_plans.append(original_plan)
                    continue
                for beat_id in changed_beat_ids:
                    for candidate in await self._reset_selected_image_candidates(
                        project,
                        original_plan,
                        visual_beat_id=beat_id,
                    ):
                        candidate_updates_by_id[candidate.id] = candidate
                updated_plan = _sync_shot_visual_beats(
                    original_plan,
                    next_beats,
                    revision_id=revision_id,
                    invalidate_video=True,
                )
                changed_plans.append(updated_plan)
                next_plans.append(updated_plan)

            if not changed_plans:
                return project, plans
            downstream_steps = {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if project.active_step in downstream_steps
                        else project.active_step
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SOURCE_KEYFRAME_CHANGED,
                f"修复 {len(changed_plans)} 个分镜的多画面源帧映射",
                revision_id=revision_id,
                report=report,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                generation_candidates=list(candidate_updates_by_id.values()),
            )
        return next_project, next_plans

    async def _repair_boundary_contaminated_visual_beats(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        """Remove legacy leading beats sourced from the previous shot transition."""

        report = await self.repository.get_report_by_analysis(project.base_analysis_id)
        if report is None or report.video_id != project.video_id:
            return project, plans
        affected = {plan.id: _boundary_contaminated_visual_beat_ids(report, plan) for plan in plans}
        affected = {plan_id: beat_ids for plan_id, beat_ids in affected.items() if beat_ids}
        if not affected:
            return project, plans

        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            if report is None or report.video_id != project.video_id:
                return project, plans
            affected = {
                plan.id: _boundary_contaminated_visual_beat_ids(report, plan) for plan in plans
            }
            affected = {plan_id: beat_ids for plan_id, beat_ids in affected.items() if beat_ids}
            if not affected:
                return project, plans

            revision_id = uuid4()
            changed_plans: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            candidate_updates_by_id: dict[UUID, GenerationCandidate] = {}
            for plan in plans:
                removed_ids = set(affected.get(plan.id, []))
                if not removed_ids:
                    next_plans.append(plan)
                    continue
                retained = _retime_visual_beats(
                    [item for item in plan.visual_beats if item.id not in removed_ids]
                )
                if len(retained) == 1:
                    retained = [
                        retained[0].model_copy(
                            update={"index": 1, "title": "画面 1", "updated_at": utc_now()}
                        )
                    ]
                for beat_id in removed_ids:
                    for candidate in await self._reset_selected_image_candidates(
                        project,
                        plan,
                        visual_beat_id=beat_id,
                    ):
                        candidate_updates_by_id[candidate.id] = candidate
                updated = _sync_shot_visual_beats(
                    plan,
                    retained,
                    revision_id=revision_id,
                    invalidate_video=True,
                )
                primary = retained[0]
                updated = updated.model_copy(
                    update={
                        "video_prompt": (
                            f"{primary.image_prompt}；持续 {plan.duration_seconds:.2f} 秒。"
                        ),
                        "approved_video_candidate_id": None,
                        "updated_at": utc_now(),
                    }
                )
                changed_plans.append(updated)
                next_plans.append(updated)

            if not changed_plans:
                return project, plans
            downstream_steps = {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if project.active_step in downstream_steps
                        else project.active_step
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"移除 {len(changed_plans)} 个分镜中被上一分镜污染的开头画面",
                revision_id=revision_id,
                report=report,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                generation_candidates=list(candidate_updates_by_id.values()),
            )
        return next_project, next_plans

    def _initial_shot_plans(
        self,
        project: ProductionProject,
        report: AnalysisReport,
        revision_id: UUID,
    ) -> list[ShotPlan]:
        prompt_shots = {item.shot_id: item for item in report.prompt_package.shots}
        plans: list[ShotPlan] = []
        for shot in sorted(report.shots, key=lambda item: item.index):
            prompt_shot = prompt_shots.get(shot.id)
            duration = max(0.01, shot.end_seconds - shot.start_seconds)
            image_prompt = prompt_shot.prompt if prompt_shot is not None else shot.prompt
            negative_constraints = (
                prompt_shot.negative_constraints
                if prompt_shot is not None
                else report.prompt_package.negative_constraints
            )
            video_prompt = (
                f"{shot.prompt}；动作过程：{shot.action}；"
                f"运镜：{shot.camera}；持续 {duration:.2f} 秒。"
            )
            structured_beats = sorted(
                shot.visual_beats,
                key=lambda item: (item.start_seconds, item.index),
            )
            visual_prompt_parts = (
                [(item.title, item.image_prompt) for item in structured_beats]
                if structured_beats
                else _split_visual_beat_prompts(image_prompt)
            )
            beat_count = len(visual_prompt_parts)
            if structured_beats:
                samples = _shot_frame_samples(report, shot)
                frame_specs = []
                for item in structured_beats:
                    target = round(item.source_timestamp_seconds, 3)
                    closest = min(
                        samples,
                        key=lambda sample: abs(sample.target_timestamp_seconds - target),
                    )
                    frame_specs.append(
                        VisualBeatFrameSpec(
                            source_url=closest.source_url,
                            source_timestamp_seconds=closest.source_timestamp_seconds,
                            target_timestamp_seconds=target,
                            role=closest.role,
                        )
                    )
            else:
                frame_specs = _visual_beat_frame_specs(report, shot, beat_count)
            content_start, content_end = _report_shot_content_bounds(report, shot)
            content_duration = max(0.001, content_end - content_start)
            visual_beats: list[ShotVisualBeat] = []
            for beat_index, ((title, beat_prompt), frame_spec) in enumerate(
                zip(visual_prompt_parts, frame_specs, strict=True),
                start=1,
            ):
                source_url = frame_spec.source_url
                if structured_beats:
                    source_fact = structured_beats[beat_index - 1]
                    start_ratio = max(
                        0.0,
                        min(1.0, (source_fact.start_seconds - content_start) / content_duration),
                    )
                    end_ratio = max(
                        start_ratio + 0.000001,
                        min(1.0, (source_fact.end_seconds - content_start) / content_duration),
                    )
                else:
                    start_ratio = (beat_index - 1) / beat_count
                    end_ratio = beat_index / beat_count
                visual_beats.append(
                    ShotVisualBeat(
                        index=beat_index,
                        title=title,
                        start_ratio=start_ratio,
                        end_ratio=end_ratio,
                        source_frame_url=source_url,
                        source_timestamp_seconds=frame_spec.source_timestamp_seconds,
                        source_origin="analysis" if source_url else "blank",
                        image_prompt=_simplified_text(
                            beat_prompt,
                            field_name="画面图片提示词",
                            allow_empty=True,
                            max_length=8000,
                        ),
                        image_negative_constraints=[
                            _simplified_text(
                                item,
                                field_name="图片负面约束",
                                max_length=500,
                            )
                            for item in negative_constraints
                        ],
                        image_status=(
                            WorkflowItemStatus.READY
                            if beat_prompt.strip()
                            else WorkflowItemStatus.DRAFT
                        ),
                        transition_to_next_type=(
                            "model_generated" if beat_index < beat_count else "cut"
                        ),
                        transition_to_next_duration_seconds=(0.5 if beat_index < beat_count else 0),
                    )
                )
            primary_beat = visual_beats[0]
            plans.append(
                ShotPlan(
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=shot.id,
                    index=shot.index,
                    source_keyframe_url=primary_beat.source_frame_url,
                    source_keyframe_timestamp_seconds=(primary_beat.source_timestamp_seconds),
                    source_keyframe_origin="analysis",
                    start_seconds=shot.start_seconds,
                    end_seconds=shot.end_seconds,
                    duration_seconds=duration,
                    image_prompt=_simplified_text(
                        primary_beat.image_prompt,
                        field_name="图片提示词",
                        allow_empty=True,
                        max_length=8000,
                    ),
                    image_negative_constraints=[
                        _simplified_text(
                            item,
                            field_name="图片负面约束",
                            max_length=500,
                        )
                        for item in negative_constraints
                    ],
                    video_prompt=_simplified_text(
                        video_prompt,
                        field_name="视频提示词",
                        allow_empty=True,
                        max_length=8000,
                    ),
                    video_negative_constraints=[
                        _simplified_text(
                            item,
                            field_name="视频负面约束",
                            max_length=500,
                        )
                        for item in report.prompt_package.negative_constraints
                    ],
                    image_status=(
                        WorkflowItemStatus.READY
                        if primary_beat.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    visual_beats=visual_beats,
                )
            )
        return plans

    async def _ensure_project_shots(
        self,
        project: ProductionProject,
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        incompatible_schema = False
        try:
            plans = await self.repository.list_shot_plans(project.id)
        except IncompatibleShotPlanSchemaError:
            plans = []
            incompatible_schema = True
        if plans:
            current_project = await self._require_project(project.id)
            current_project, plans = await self._repair_legacy_simulated_outputs(
                current_project,
                plans,
            )
            current_project, plans = await self._expand_legacy_visual_beats(
                current_project,
                plans,
            )
            current_project, plans = await self._repair_visual_beat_frame_mappings(
                current_project,
                plans,
            )
            return await self._repair_boundary_contaminated_visual_beats(
                current_project,
                plans,
            )
        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            try:
                plans = await self.repository.list_shot_plans(project.id)
            except IncompatibleShotPlanSchemaError:
                await self.repository.reset_production_shot_workflow(project.id)
                plans = []
                incompatible_schema = True
            if plans:
                return project, plans
            if incompatible_schema:
                project = project.model_copy(
                    update={
                        "status": ProductionProjectStatus.DRAFT,
                        "active_step": ProductionStep.SHOT_IMAGES,
                        "updated_at": utc_now(),
                    }
                )
            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            if report is None or report.video_id != project.video_id:
                raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
            revision_id = uuid4()
            plans = self._initial_shot_plans(project, report, revision_id)
            plans = await self._materialize_visual_beat_source_frames(
                project,
                plans,
                report,
                revision_id,
                plan_ids={item.id for item in plans if len(item.visual_beats) > 1},
            )
            project, revision = await self._prepare_revision(
                project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                (
                    "重建当前版本的分镜工作流"
                    if incompatible_schema
                    else "为早期创作方案补充分镜创作计划"
                ),
                revision_id=revision_id,
                report=report,
                shot_plans=plans,
            )
            await self.repository.save_production_bundle(
                project,
                revision,
                shot_plans=plans,
            )
        project, plans = await self._repair_legacy_simulated_outputs(project, plans)
        project, plans = await self._expand_legacy_visual_beats(project, plans)
        project, plans = await self._repair_visual_beat_frame_mappings(project, plans)
        return await self._repair_boundary_contaminated_visual_beats(project, plans)

    @staticmethod
    def _legacy_visual_beat_expansion_needed(plans: list[ShotPlan]) -> bool:
        return any(
            plan.source_kind == ShotSourceKind.ANALYSIS
            and len(plan.visual_beats) == 1
            and plan.visual_beats[0].source_origin == "legacy"
            and len(_split_visual_beat_prompts(plan.visual_beats[0].image_prompt)) > 1
            for plan in plans
        )

    async def _expand_legacy_visual_beats(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        """Upgrade pre-v4 multi-scene prompts into ordered visual beats once."""
        if not self._legacy_visual_beat_expansion_needed(plans):
            return project, plans

        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            if not self._legacy_visual_beat_expansion_needed(plans):
                return project, plans

            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            report_shots = (
                {item.id: item for item in report.shots}
                if report is not None and report.video_id == project.video_id
                else {}
            )
            revision_id = uuid4()
            now = utc_now()
            changed: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            candidate_updates_by_id: dict[UUID, GenerationCandidate] = {}

            for plan in plans:
                if not (
                    plan.source_kind == ShotSourceKind.ANALYSIS
                    and len(plan.visual_beats) == 1
                    and plan.visual_beats[0].source_origin == "legacy"
                ):
                    next_plans.append(plan)
                    continue
                original = plan.visual_beats[0]
                prompt_parts = _split_visual_beat_prompts(original.image_prompt)
                if len(prompt_parts) <= 1:
                    next_plans.append(plan)
                    continue

                source_shot = report_shots.get(plan.source_shot_id)
                existing_result = (
                    original.approved_image_candidate_id is not None
                    or original.image_status
                    in {
                        WorkflowItemStatus.GENERATING,
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.APPROVED,
                        WorkflowItemStatus.STALE,
                    }
                )
                beat_count = len(prompt_parts)
                frame_specs = (
                    _visual_beat_frame_specs(report, source_shot, beat_count)
                    if report is not None and source_shot is not None
                    else [
                        VisualBeatFrameSpec(
                            source_url=(original.source_frame_url if index == 0 else None),
                            source_timestamp_seconds=(
                                original.source_timestamp_seconds if index == 0 else None
                            ),
                            target_timestamp_seconds=round(
                                plan.start_seconds
                                + plan.duration_seconds * index / max(1, beat_count - 1),
                                3,
                            ),
                            role="legacy" if index == 0 else "generated",
                        )
                        for index in range(beat_count)
                    ]
                )
                expanded: list[ShotVisualBeat] = []
                for beat_index, ((title, beat_prompt), frame_spec) in enumerate(
                    zip(prompt_parts, frame_specs, strict=True),
                    start=1,
                ):
                    start_ratio = (beat_index - 1) / beat_count
                    end_ratio = beat_index / beat_count
                    source_url = frame_spec.source_url
                    source_relative_path = None
                    source_timestamp = frame_spec.source_timestamp_seconds
                    source_origin = "analysis" if source_url else "blank"
                    if beat_index == 1:
                        approved_candidate_id = None
                        image_status = (
                            WorkflowItemStatus.STALE
                            if existing_result
                            else (
                                WorkflowItemStatus.READY
                                if beat_prompt.strip()
                                else WorkflowItemStatus.DRAFT
                            )
                        )
                        beat_id = original.id
                        created_at = original.created_at
                    else:
                        approved_candidate_id = None
                        image_status = (
                            WorkflowItemStatus.READY
                            if beat_prompt.strip()
                            else WorkflowItemStatus.DRAFT
                        )
                        beat_id = uuid4()
                        created_at = now
                    expanded.append(
                        ShotVisualBeat(
                            id=beat_id,
                            index=beat_index,
                            title=_simplified_text(
                                title,
                                field_name="画面名称",
                                max_length=120,
                            ),
                            start_ratio=start_ratio,
                            end_ratio=end_ratio,
                            source_frame_url=source_url,
                            source_frame_relative_path=source_relative_path,
                            source_timestamp_seconds=source_timestamp,
                            source_origin=source_origin,
                            image_prompt=_simplified_text(
                                beat_prompt,
                                field_name="画面图片提示词",
                                allow_empty=True,
                                max_length=8000,
                            ),
                            image_prompt_mentions=original.image_prompt_mentions,
                            image_negative_constraints=(original.image_negative_constraints),
                            required=original.required,
                            image_status=image_status,
                            approved_image_candidate_id=approved_candidate_id,
                            transition_to_next_type=(
                                "model_generated" if beat_index < beat_count else "cut"
                            ),
                            transition_to_next_duration_seconds=(
                                0.5 if beat_index < beat_count else 0
                            ),
                            created_at=created_at,
                            updated_at=now,
                        )
                    )

                updated = _sync_shot_visual_beats(
                    plan,
                    expanded,
                    revision_id=revision_id,
                    invalidate_video=True,
                )
                changed.append(updated)
                next_plans.append(updated)
                if existing_result:
                    for candidate in await self._reset_selected_image_candidates(
                        project,
                        plan,
                        visual_beat_id=original.id,
                    ):
                        candidate_updates_by_id[candidate.id] = candidate

            if not changed:
                return project, plans
            if report is not None:
                changed_ids = {item.id for item in changed}
                next_plans = await self._materialize_visual_beat_source_frames(
                    project,
                    next_plans,
                    report,
                    revision_id,
                    plan_ids=changed_ids,
                )
                changed = [item for item in next_plans if item.id in changed_ids]

            downstream_steps = {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if project.active_step in downstream_steps
                        else project.active_step
                    ),
                    "updated_at": now,
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"将 {len(changed)} 个历史多场景提示词拆分为有序画面",
                revision_id=revision_id,
                report=report,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed,
                generation_candidates=list(candidate_updates_by_id.values()),
            )
        return next_project, next_plans

    async def _legacy_simulation_repair_needed(
        self,
        plans: list[ShotPlan],
    ) -> bool:
        for plan in plans:
            for run in await self.repository.list_generation_runs(
                plan.project_id,
                plan.id,
            ):
                if not _is_simulated_image_run(run):
                    continue
                for candidate in await self.repository.list_generation_candidates(run.id):
                    if (
                        candidate.status != GenerationCandidateStatus.ARCHIVED
                        or candidate.id == plan.approved_image_candidate_id
                    ):
                        return True
        return False

    async def _repair_legacy_simulated_outputs(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        if not await self._legacy_simulation_repair_needed(plans):
            return project, plans

        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            if not await self._legacy_simulation_repair_needed(plans):
                return project, plans

            revision_id = uuid4()
            candidate_updates: list[GenerationCandidate] = []
            simulated_candidate_ids: dict[UUID, set[UUID]] = {}
            had_reviewable_simulated: set[UUID] = set()
            eligible_active_candidates: set[UUID] = set()

            for plan in plans:
                simulated_ids = simulated_candidate_ids.setdefault(plan.id, set())
                for run in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                ):
                    candidates = await self.repository.list_generation_candidates(run.id)
                    if _is_simulated_image_run(run):
                        for candidate in candidates:
                            simulated_ids.add(candidate.id)
                            if candidate.status in {
                                GenerationCandidateStatus.READY,
                                GenerationCandidateStatus.SELECTED,
                            }:
                                had_reviewable_simulated.add(plan.id)
                            if candidate.status != GenerationCandidateStatus.ARCHIVED:
                                candidate_updates.append(
                                    candidate.model_copy(
                                        update={
                                            "status": GenerationCandidateStatus.ARCHIVED,
                                        }
                                    )
                                )
                    else:
                        eligible_active_candidates.update(
                            candidate.id
                            for candidate in candidates
                            if candidate.status
                            in {
                                GenerationCandidateStatus.READY,
                                GenerationCandidateStatus.SELECTED,
                            }
                        )

            changed_plans: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            for plan in plans:
                invalid_approval = plan.approved_image_candidate_id in simulated_candidate_ids.get(
                    plan.id, set()
                )
                simulated_review_state = (
                    plan.id in had_reviewable_simulated
                    and plan.image_status
                    in {
                        WorkflowItemStatus.GENERATING,
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.APPROVED,
                        WorkflowItemStatus.STALE,
                    }
                    and (plan.approved_image_candidate_id is None or invalid_approval)
                )
                if not invalid_approval and not simulated_review_state:
                    next_plans.append(plan)
                    continue

                has_eligible_candidate = any(
                    candidate_id in eligible_active_candidates
                    for candidate_id in (await self._candidate_ids_for_plan(project.id, plan.id))
                )
                image_status = (
                    WorkflowItemStatus.REVIEW_REQUIRED
                    if has_eligible_candidate
                    else (
                        WorkflowItemStatus.READY
                        if plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    )
                )
                video_status = (
                    WorkflowItemStatus.STALE
                    if plan.video_status
                    in {
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.APPROVED,
                        WorkflowItemStatus.STALE,
                    }
                    else plan.video_status
                )
                updated_plan = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        "image_status": image_status,
                        "video_status": video_status,
                        "approved_image_candidate_id": None,
                        "updated_at": utc_now(),
                    }
                )
                changed_plans.append(updated_plan)
                next_plans.append(updated_plan)

            rollback_steps = {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if changed_plans and project.active_step in rollback_steps
                        else project.active_step
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                (
                    f"归档 {len(candidate_updates)} 个历史模拟图片候选，"
                    f"重置 {len(changed_plans)} 个错误确认的分镜"
                ),
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                generation_candidates=candidate_updates,
            )
        return next_project, next_plans

    async def _candidate_ids_for_plan(
        self,
        project_id: UUID,
        shot_plan_id: UUID,
    ) -> set[UUID]:
        candidate_ids: set[UUID] = set()
        for run in await self.repository.list_generation_runs(project_id, shot_plan_id):
            if _is_simulated_image_run(run):
                continue
            candidate_ids.update(
                candidate.id
                for candidate in await self.repository.list_generation_candidates(run.id)
                if candidate.status
                in {
                    GenerationCandidateStatus.READY,
                    GenerationCandidateStatus.SELECTED,
                }
            )
        return candidate_ids

    @staticmethod
    def _resequence_plans(
        active: list[ShotPlan],
        discarded: list[ShotPlan],
        revision_id: UUID,
        *,
        force_ids: set[UUID] | None = None,
    ) -> tuple[list[ShotPlan], list[ShotPlan]]:
        forced = force_ids or set()
        ordered = [*active, *sorted(discarded, key=lambda item: item.index)]
        next_plans: list[ShotPlan] = []
        changed: list[ShotPlan] = []
        now = utc_now()
        for next_index, plan in enumerate(ordered, start=1):
            if plan.index != next_index or plan.id in forced:
                plan = plan.model_copy(
                    update={
                        "index": next_index,
                        "revision_id": revision_id,
                        "updated_at": now,
                    }
                )
                changed.append(plan)
            next_plans.append(plan)
        return next_plans, changed

    @staticmethod
    def _image_fields_changed(payload: ShotPlanFieldsUpdate) -> bool:
        return bool(
            payload.model_fields_set
            & {
                "image_prompt",
                "image_prompt_mentions",
                "image_negative_constraints",
                "locks",
                "reference_bindings",
            }
        )

    @staticmethod
    def _video_fields_changed(payload: ShotPlanFieldsUpdate) -> bool:
        return bool(
            payload.model_fields_set
            & {
                "video_prompt",
                "video_prompt_mentions",
                "video_negative_constraints",
                "managed_asset_bindings",
                "video_reference_bindings",
                "locks",
            }
        )

    @staticmethod
    def _mark_plans_stale(
        plans: list[ShotPlan],
        impacted_ids: set[UUID],
        revision_id: UUID,
    ) -> tuple[list[ShotPlan], list[ShotPlan]]:
        next_plans: list[ShotPlan] = []
        changed: list[ShotPlan] = []
        for plan in plans:
            if plan.id not in impacted_ids:
                next_plans.append(plan)
                continue
            image_status = (
                WorkflowItemStatus.STALE
                if plan.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                or plan.approved_image_candidate_id is not None
                else plan.image_status
            )
            video_status = (
                WorkflowItemStatus.STALE
                if plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                else plan.video_status
            )
            updated = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "image_status": image_status,
                    "video_status": video_status,
                    "updated_at": utc_now(),
                }
            )
            next_plans.append(updated)
            changed.append(updated)
        return next_plans, changed

    def _apply_shot_fields(
        self,
        plan: ShotPlan,
        payload: ShotPlanFieldsUpdate,
        fields: set[str],
        revision_id: UUID,
        *,
        image_changed: bool,
        video_changed: bool,
    ) -> ShotPlan:
        updates: dict[str, object] = {
            "revision_id": revision_id,
            "updated_at": utc_now(),
        }
        for field_name, label, max_length in (
            ("image_prompt", "图片提示词", 8000),
            ("video_prompt", "视频提示词", 8000),
        ):
            if field_name in fields:
                value = getattr(payload, field_name)
                if value is None:
                    raise _fail(422, "invalid_shot_plan", f"{label}不能为 null")
                updates[field_name] = _simplified_text(
                    value,
                    field_name=label,
                    allow_empty=True,
                    max_length=max_length,
                )
        if "image_prompt_mentions" in fields:
            if payload.image_prompt_mentions is None:
                raise _fail(422, "invalid_shot_plan", "提示词资产关联不能为 null")
            updates["image_prompt_mentions"] = payload.image_prompt_mentions
        for field_name, label in (
            ("image_negative_constraints", "图片负面约束"),
            ("video_negative_constraints", "视频负面约束"),
        ):
            if field_name in fields:
                values = getattr(payload, field_name)
                if values is None:
                    raise _fail(422, "invalid_shot_plan", f"{label}不能为 null")
                updates[field_name] = [
                    _simplified_text(
                        value,
                        field_name=label,
                        max_length=500,
                    )
                    for value in values
                ]
        if "locks" in fields:
            if payload.locks is None:
                raise _fail(422, "invalid_shot_plan", "锁定项不能为 null")
            updates["locks"] = payload.locks
        if "managed_asset_bindings" in fields:
            if payload.managed_asset_bindings is None:
                raise _fail(422, "invalid_shot_plan", "托管资产绑定不能为 null")
            updates["managed_asset_bindings"] = payload.managed_asset_bindings
        if "video_prompt_mentions" in fields:
            if payload.video_prompt_mentions is None:
                raise _fail(422, "invalid_shot_plan", "视频提示词引用不能为 null")
            updates["video_prompt_mentions"] = payload.video_prompt_mentions
        if "video_reference_bindings" in fields:
            if payload.video_reference_bindings is None:
                raise _fail(422, "invalid_shot_plan", "视频参考绑定不能为 null")
            updates["video_reference_bindings"] = payload.video_reference_bindings
        if "required" in fields:
            if payload.required is None:
                raise _fail(422, "invalid_shot_plan", "必需分镜不能为 null")
            updates["required"] = payload.required

        next_image_prompt = str(updates.get("image_prompt", plan.image_prompt))
        if image_changed:
            has_prior_result = (
                plan.approved_image_candidate_id is not None
                or plan.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.STALE,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                }
            )
            updates["image_status"] = (
                WorkflowItemStatus.STALE
                if has_prior_result
                else (
                    WorkflowItemStatus.READY
                    if next_image_prompt.strip()
                    else WorkflowItemStatus.DRAFT
                )
            )
            if not has_prior_result:
                updates["approved_image_candidate_id"] = None
            updates["video_status"] = (
                WorkflowItemStatus.STALE
                if plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                else WorkflowItemStatus.DRAFT
            )
        elif video_changed:
            next_video_prompt = str(updates.get("video_prompt", plan.video_prompt))
            has_prior_result = (
                plan.approved_video_candidate_id is not None
                or plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
            )
            updates["video_status"] = (
                WorkflowItemStatus.STALE
                if has_prior_result
                else (
                    WorkflowItemStatus.READY
                    if next_video_prompt.strip()
                    else WorkflowItemStatus.DRAFT
                )
            )
            if not has_prior_result:
                updates["approved_video_candidate_id"] = None
        updated_plan = ShotPlan.model_validate({**plan.model_dump(mode="python"), **updates})
        if image_changed and updated_plan.visual_beats:
            primary = updated_plan.visual_beats[0]
            beat_updates: dict[str, object] = {
                "image_status": updated_plan.image_status,
                "approved_image_candidate_id": updated_plan.approved_image_candidate_id,
                "updated_at": utc_now(),
            }
            for field_name in (
                "image_prompt",
                "image_prompt_mentions",
                "image_negative_constraints",
            ):
                if field_name in fields:
                    beat_updates[field_name] = getattr(updated_plan, field_name)
            updated_primary = primary.model_copy(update=beat_updates)
            return _sync_shot_visual_beats(
                updated_plan,
                [
                    updated_primary if item.id == primary.id else item
                    for item in updated_plan.visual_beats
                ],
                revision_id=revision_id,
                invalidate_video=True,
            )
        return updated_plan

    async def _validate_prompt_mentions(
        self,
        project: ProductionProject,
        mentions: list[PromptAssetMention],
    ) -> list[PromptAssetMention]:
        assets = {item.id: item for item in await self._list_reference_assets(project.id)}
        normalized: list[PromptAssetMention] = []
        for mention in mentions:
            asset = assets.get(mention.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(
                    422,
                    "prompt_reference_not_found",
                    "提示词关联的参考资产不存在或已归档",
                )
            if not asset.rights_confirmed:
                raise _fail(
                    422,
                    "reference_rights_required",
                    "提示词关联的参考资产尚未完成权利确认",
                )
            normalized.append(
                PromptAssetMention(
                    reference_asset_id=asset.id,
                    label=_simplified_text(
                        mention.label,
                        field_name="提示词资产名称",
                        max_length=120,
                    ),
                )
            )
        return normalized

    async def _validate_video_prompt_mentions(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        mentions: list[VideoPromptMention],
        *,
        managed_asset_bindings=None,
        video_reference_bindings=None,
    ) -> list[VideoPromptMention]:
        assets = {item.id: item for item in await self._list_reference_assets(project.id)}
        managed = {
            item.id: item
            for item in (
                plan.managed_asset_bindings
                if managed_asset_bindings is None
                else managed_asset_bindings
            )
        }
        video_bindings = {
            item.id: item
            for item in (
                plan.video_reference_bindings
                if video_reference_bindings is None
                else video_reference_bindings
            )
        }
        depth_assets = {item.id: item for item in plan.depth_control_assets}
        approved_candidates = {
            item.approved_image_candidate_id
            for item in plan.visual_beats
            if item.approved_image_candidate_id is not None
        }
        normalized: list[VideoPromptMention] = []
        for mention in sorted(mentions, key=lambda item: item.order):
            kind = mention.reference_kind
            reference_id = mention.reference_id
            if kind == VideoPromptReferenceKind.PROJECT_ASSET:
                asset = assets.get(reference_id)
                if asset is None or asset.archived_at is not None:
                    raise _fail(
                        422,
                        "video_prompt_reference_not_found",
                        "视频提示词关联的项目资产不存在或已归档",
                    )
                if not asset.rights_confirmed:
                    raise _fail(
                        422,
                        "reference_rights_required",
                        "视频提示词关联的项目资产尚未完成权利确认",
                    )
            elif kind == VideoPromptReferenceKind.APPROVED_IMAGE:
                if reference_id not in approved_candidates:
                    raise _fail(
                        422,
                        "video_prompt_reference_not_approved",
                        "视频提示词关联的分镜图已失效或尚未采用",
                    )
            elif kind == VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET:
                if reference_id not in managed:
                    raise _fail(
                        422,
                        "video_prompt_managed_asset_not_bound",
                        "视频提示词关联的托管角色尚未绑定到当前分镜",
                    )
            elif kind == VideoPromptReferenceKind.REFERENCE_VIDEO:
                binding = video_bindings.get(reference_id)
                if (
                    binding is None
                    or binding.media_type.value != "video"
                    or not binding.enabled
                ):
                    raise _fail(
                        422,
                        "video_prompt_reference_video_not_bound",
                        "视频提示词关联的参考视频不存在、已停用或不是视频",
                    )
            elif kind == VideoPromptReferenceKind.DEPTH_CONTROL:
                depth = depth_assets.get(reference_id)
                if depth is None or not depth.enabled or not depth.usable_for_generation:
                    raise _fail(
                        422,
                        "video_prompt_depth_control_not_ready",
                        "视频提示词关联的深度视频尚未启用或不可用于生成",
                    )
            normalized.append(
                mention.model_copy(
                    update={
                        "label": _simplified_text(
                            mention.label,
                            field_name="视频提示词引用名称",
                            max_length=260,
                        ),
                        "order": len(normalized) + 1,
                    }
                )
            )
        return normalized

    async def _append_mention_bindings(
        self,
        project: ProductionProject,
        inputs: list[ReferenceBindingInput],
        mentions: list[PromptAssetMention],
    ) -> list[ReferenceBindingInput]:
        assets = {item.id: item for item in await self._list_reference_assets(project.id)}
        existing_ids = {item.reference_asset_id for item in inputs}
        merged = list(inputs)
        for mention in mentions:
            if mention.reference_asset_id in existing_ids:
                continue
            asset = assets.get(mention.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(
                    422,
                    "prompt_reference_not_found",
                    "提示词关联的参考资产不存在或已归档",
                )
            merged.append(
                ReferenceBindingInput(
                    reference_asset_id=asset.id,
                    role=_DEFAULT_ROLE_BY_REFERENCE_TYPE[asset.type],
                    weight=1,
                    notes=f"由提示词 @{mention.label} 自动关联",
                )
            )
            existing_ids.add(asset.id)
        return merged

    async def _build_bindings(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        inputs: list[ReferenceBindingInput],
    ) -> list[ReferenceBinding]:
        assets = {item.id: item for item in await self._list_reference_assets(project.id)}
        bindings: list[ReferenceBinding] = []
        for item in inputs:
            asset = assets.get(item.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(422, "reference_asset_not_found", "绑定的参考资产不存在或已归档")
            if not asset.rights_confirmed:
                raise _fail(422, "reference_rights_required", "绑定的参考资产尚未完成权利确认")
            bindings.append(
                ReferenceBinding(
                    shot_plan_id=plan.id,
                    reference_asset_id=asset.id,
                    role=item.role,
                    weight=item.weight,
                    crop_hint=(
                        _simplified_text(
                            item.crop_hint,
                            field_name="裁剪提示",
                            allow_empty=True,
                            max_length=200,
                        )
                        if item.crop_hint is not None
                        else None
                    ),
                    notes=(
                        _simplified_text(
                            item.notes,
                            field_name="绑定说明",
                            allow_empty=True,
                            max_length=500,
                        )
                        if item.notes is not None
                        else None
                    ),
                )
            )
        try:
            validate_identity_bindings(bindings, assets.values())
        except IdentityPolicyViolation as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc
        return bindings

    async def _all_bindings(
        self,
        plans: list[ShotPlan],
    ) -> list[ReferenceBinding]:
        bindings: list[ReferenceBinding] = []
        for plan in plans:
            bindings.extend(await self.repository.list_reference_bindings(plan.id))
        return bindings

    async def _run_response(self, run: GenerationRun) -> GenerationRunResponse:
        candidates = await self.repository.list_generation_candidates(run.id)
        provider_tasks = (
            await self.repository.list_video_provider_tasks(run.id)
            if run.kind == GenerationKind.VIDEO
            else []
        )
        failed_task = next(
            (
                item
                for item in provider_tasks
                if item.error_code or item.error_message or item.error_technical_message
            ),
            None,
        )
        failure = (
            classify_video_provider_failure(
                provider=run.provider,
                code=run.error_code or (failed_task.error_code if failed_task else None),
                message=(
                    run.error_technical_message
                    or (failed_task.error_technical_message if failed_task else None)
                    or run.error_message
                    or (failed_task.error_message if failed_task else None)
                ),
                retryable=run.error_retryable or bool(failed_task and failed_task.retryable),
                provider_code=(
                    run.provider_error_code
                    or (failed_task.provider_error_code if failed_task else None)
                    or (
                        failed_task.error_code
                        if failed_task
                        and failed_task.error_code
                        and not failed_task.error_code.startswith("video_")
                        else None
                    )
                ),
            )
            if run.kind == GenerationKind.VIDEO
            and run.status in {ProductionRunStatus.FAILED, ProductionRunStatus.BLOCKED}
            else None
        )
        return GenerationRunResponse(
            id=run.id,
            project_id=run.project_id,
            shot_plan_id=run.shot_plan_id,
            visual_beat_id=run.visual_beat_id,
            revision_id=run.revision_id,
            kind=run.kind,
            input_mode=run.input_mode,
            provider=run.provider,
            model=run.model,
            model_snapshot=run.model_snapshot,
            model_alias=run.model_alias,
            model_display_name=run.model_display_name,
            execution_mode=run.execution_mode,
            adapter_id=run.adapter_id,
            adapter_version=run.adapter_version,
            protocol_version=run.protocol_version,
            provider_request_id=(
                run.provider_request_id or (failed_task.provider_task_id if failed_task else None)
            ),
            capability_snapshot=run.capability_snapshot,
            execution_summary=run.execution_summary,
            cost_source=run.cost_source,
            cost_estimate_known=run.cost_estimate_known,
            actual_cost_known=run.actual_cost_known,
            cost_currency=run.cost_currency,
            pricing_snapshot=run.pricing_snapshot,
            usage=run.usage,
            status=run.status,
            estimated_cost_micros=run.estimated_cost_micros,
            actual_cost_micros=run.actual_cost_micros,
            latency_ms=run.latency_ms,
            retry_count=run.retry_count,
            retry_of_run_id=run.retry_of_run_id,
            cancellation_requested=run.cancellation_requested,
            error_code=failure.code if failure else run.error_code,
            error_message=failure.message if failure else run.error_message,
            provider_error_code=(
                run.provider_error_code
                or (failed_task.provider_error_code if failed_task else None)
                or (failure.provider_code if failure else None)
            ),
            error_category=run.error_category or (failure.category if failure else None),
            error_title=run.error_title or (failure.title if failure else None),
            error_technical_message=(
                run.error_technical_message
                or (failed_task.error_technical_message if failed_task else None)
                or (failure.technical_message if failure else None)
            ),
            error_retryable=run.error_retryable or bool(failure and failure.retryable),
            error_action=run.error_action or (failure.suggested_action if failure else None),
            created_at=run.created_at,
            started_at=run.started_at,
            updated_at=run.updated_at,
            last_heartbeat_at=run.last_heartbeat_at,
            completed_at=run.completed_at,
            candidates=[self._candidate_response(item) for item in candidates],
            provider_tasks=[
                VideoProviderTaskResponse.model_validate(
                    item.model_dump(
                        include={
                            "id",
                            "generation_run_id",
                            "ordinal",
                            "provider",
                            "model_alias",
                            "provider_model",
                            "provider_task_id",
                            "status",
                            "estimated_cost_micros",
                            "actual_cost_micros",
                            "cost_known",
                            "error_code",
                            "error_message",
                            "retryable",
                            "provider_error_code",
                            "error_category",
                            "error_title",
                            "error_technical_message",
                            "error_action",
                            "submitted_at",
                            "last_polled_at",
                            "completed_at",
                        }
                    )
                )
                for item in provider_tasks
            ],
        )

    @staticmethod
    def _candidate_response(
        candidate: GenerationCandidate,
    ) -> GenerationCandidateResponse:
        return GenerationCandidateResponse(
            id=candidate.id,
            generation_run_id=candidate.generation_run_id,
            ordinal=candidate.ordinal,
            kind=candidate.kind,
            width=candidate.width,
            height=candidate.height,
            duration_seconds=candidate.duration_seconds,
            sha256=candidate.sha256,
            quality_report=candidate.quality_report,
            status=candidate.status,
            archived_at=candidate.archived_at,
            archived_by_account_id=candidate.archived_by_account_id,
            archive_reason=candidate.archive_reason,
            content_url=f"/api/v1/generation-candidates/{candidate.id}/content",
            thumbnail_url=f"/api/v1/generation-candidates/{candidate.id}/thumbnail",
            created_at=candidate.created_at,
        )

    @staticmethod
    def _video_preparation_response(
        preparation: VideoClipPreparation,
    ) -> VideoClipPreparationResponse:
        preparation = _apply_video_preparation_policy(preparation)
        return VideoClipPreparationResponse(
            id=preparation.id,
            project_id=preparation.project_id,
            revision_id=preparation.revision_id,
            shot_plan_id=preparation.shot_plan_id,
            candidate_id=preparation.candidate_id,
            trim_in_seconds=preparation.trim_in_seconds,
            trim_out_seconds=preparation.trim_out_seconds,
            prepared_duration_seconds=preparation.prepared_duration_seconds,
            timeline_duration_seconds=preparation.timeline_duration_seconds,
            video_playback_rate=preparation.video_playback_rate,
            duration_alignment=preparation.duration_alignment,
            cover_timestamp_seconds=preparation.cover_timestamp_seconds,
            cover_url=(
                f"/api/v1/production-shots/{preparation.shot_plan_id}/video-preparation/cover"
            ),
            audio_mode=preparation.audio_mode,
            audio_mapping_strategy=preparation.audio_mapping_strategy,
            source_audio_available=preparation.source_audio_url is not None,
            source_audio_start_seconds=preparation.source_audio_start_seconds,
            source_audio_end_seconds=preparation.source_audio_end_seconds,
            transcript_cues=preparation.transcript_cues,
            subtitle_cues=preparation.subtitle_cues,
            quality_status=preparation.quality_status,
            quality_report=preparation.quality_report,
            status=preparation.status,
            blocker_messages=preparation.blocker_messages,
            warning_messages=preparation.warning_messages,
            created_at=preparation.created_at,
            updated_at=preparation.updated_at,
        )

    def _update_candidate_quality_metadata(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        run: GenerationRun,
        candidate: GenerationCandidate,
    ) -> None:
        try:
            metadata_path = self.workspace.resolve(candidate.metadata_relative_path).resolve()
            run_root = (
                self.workspace.production_shot_root(
                    project.record_id,
                    project.id,
                    plan.id,
                )
                / "videos"
                / str(run.id)
            ).resolve()
            metadata_path.relative_to(run_root)
            filesystem_path = _filesystem_path(metadata_path)
            payload: dict[str, object] = {}
            if filesystem_path.is_file():
                loaded = json.loads(filesystem_path.read_text("utf-8-sig"))
                if isinstance(loaded, dict):
                    payload = loaded
            payload.update(
                {
                    "width": candidate.width,
                    "height": candidate.height,
                    "duration_seconds": candidate.duration_seconds,
                    "quality_report": candidate.quality_report,
                }
            )
            self._write_json_atomic(metadata_path, payload)
        except (OSError, ValueError, json.JSONDecodeError, WorkspaceError):
            # The SQLite record is authoritative; metadata repair is best-effort.
            return

    def _resolve_video_file(self, video: Video) -> Path:
        if video.stored_relative_path:
            try:
                relative_candidate = self.workspace.resolve(video.stored_relative_path)
            except WorkspaceError:
                relative_candidate = None
            if relative_candidate is not None:
                filesystem_candidate = _filesystem_path(relative_candidate)
                if filesystem_candidate.is_file():
                    return filesystem_candidate
        if video.stored_path:
            filesystem_candidate = _filesystem_path(Path(video.stored_path).resolve())
            if filesystem_candidate.is_file():
                return filesystem_candidate
        raise _fail(404, "source_video_file_missing", "源视频文件不存在，请重新采集或上传")

    @staticmethod
    def _validate_keyframe_file(path: Path) -> None:
        filesystem_path = _filesystem_path(path)
        try:
            with Image.open(filesystem_path) as source:
                source.verify()
            with Image.open(filesystem_path) as source:
                width, height = ImageOps.exif_transpose(source).size
        except OSError as exc:
            raise _fail(422, "keyframe_image_invalid", "提取出的关键帧文件无效") from exc
        if (
            width <= 0
            or height <= 0
            or width > MAX_REFERENCE_IMAGE_DIMENSION
            or height > MAX_REFERENCE_IMAGE_DIMENSION
            or width * height > MAX_REFERENCE_IMAGE_PIXELS
        ):
            raise _fail(422, "keyframe_dimensions_invalid", "提取出的关键帧尺寸无效")

    @staticmethod
    def _image_choice_has_downstream_impact(
        project: ProductionProject,
        plan: ShotPlan,
    ) -> bool:
        return plan.video_status in {
            WorkflowItemStatus.GENERATING,
            WorkflowItemStatus.REVIEW_REQUIRED,
            WorkflowItemStatus.APPROVED,
            WorkflowItemStatus.STALE,
        } or project.active_step in {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }

    async def _reset_selected_image_candidates(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        *,
        visual_beat_id: UUID,
        keep_candidate_id: UUID | None = None,
    ) -> list[GenerationCandidate]:
        updates: list[GenerationCandidate] = []
        for run in await self.repository.list_generation_runs(project.id, plan.id):
            if run.kind != GenerationKind.IMAGE or not _run_matches_visual_beat(
                run, plan, visual_beat_id
            ):
                continue
            for candidate in await self.repository.list_generation_candidates(run.id):
                if (
                    candidate.status == GenerationCandidateStatus.SELECTED
                    and candidate.id != keep_candidate_id
                ):
                    updates.append(
                        candidate.model_copy(update={"status": GenerationCandidateStatus.READY})
                    )
        return updates

    def _create_source_frame_candidate(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        revision_id: UUID,
        source_path: Path,
        visual_beat_id: UUID,
    ) -> tuple[GenerationRun, GenerationCandidate]:
        started = datetime.now(UTC)
        source_payload = _filesystem_path(source_path).read_bytes()
        source_sha256 = hashlib.sha256(source_payload).hexdigest()
        try:
            with Image.open(BytesIO(source_payload)) as source:
                rendered = ImageOps.exif_transpose(source).convert("RGB")
        except OSError as exc:
            raise _fail(422, "source_keyframe_invalid", "当前分镜关键帧文件无效") from exc

        run_id = uuid4()
        run_root = (
            self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            )
            / "images"
            / str(run_id)
        )
        candidate_output = BytesIO()
        rendered.save(candidate_output, format="JPEG", quality=94, optimize=True)
        candidate_payload = candidate_output.getvalue()
        thumbnail = rendered.copy()
        thumbnail.thumbnail((640, 640), Image.Resampling.LANCZOS)
        thumbnail_output = BytesIO()
        thumbnail.save(thumbnail_output, format="WEBP", quality=84, method=4)

        candidate_path = run_root / "source-frame.jpg"
        thumbnail_path = run_root / "source-frame.webp"
        metadata_path = run_root / "source-frame.json"
        input_path = run_root / "input.json"
        manifest_path = run_root / "manifest.json"
        candidate_sha256 = hashlib.sha256(candidate_payload).hexdigest()
        input_payload = {
            "schema_version": "viral-dna-source-frame/v1",
            "project_id": str(project.id),
            "shot_plan_id": str(plan.id),
            "visual_beat_id": str(visual_beat_id),
            "revision_id": str(revision_id),
            "input_mode": ImageGenerationInputMode.KEYFRAME_EDIT.value,
            "source": {
                "relative_url": plan.source_keyframe_url,
                "relative_path": plan.source_keyframe_relative_path,
                "timestamp_seconds": plan.source_keyframe_timestamp_seconds,
                "sha256": source_sha256,
            },
            "execution": {
                "mode": ImageExecutionMode.SOURCE_FRAME.value,
                "model_call": False,
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        quality_report = {
            "schema_version": "viral-dna-image-quality/v1",
            "status": "manual_review_required",
            "summary": "已直接使用源视频关键帧，未调用生成模型；请人工核对画面内容。",
            "automated_checks": {
                "file_integrity": {"status": "passed", "decoded": True},
                "dimensions": {
                    "status": "passed",
                    "actual_width": rendered.width,
                    "actual_height": rendered.height,
                },
            },
            "manual_checks": [
                {
                    "id": "source_frame_review",
                    "label": "源视频关键帧画面",
                    "status": "required",
                }
            ],
        }
        candidate = GenerationCandidate(
            generation_run_id=run_id,
            ordinal=1,
            kind=GenerationKind.IMAGE,
            relative_path=self.workspace.relative(candidate_path),
            thumbnail_relative_path=self.workspace.relative(thumbnail_path),
            width=rendered.width,
            height=rendered.height,
            sha256=candidate_sha256,
            metadata_relative_path=self.workspace.relative(metadata_path),
            quality_report=quality_report,
            status=GenerationCandidateStatus.SELECTED,
        )
        metadata = {
            "schema_version": "viral-dna-generation-candidate/v1",
            "source_frame": True,
            "candidate_id": str(candidate.id),
            "request_fingerprint": fingerprint,
            "source_sha256": source_sha256,
            "sha256": candidate_sha256,
            "width": rendered.width,
            "height": rendered.height,
            "quality_report": quality_report,
        }
        manifest = {
            "schema_version": "viral-dna-image-generation-result/v1",
            "status": "completed",
            "request_id": str(run_id),
            "source_frame": True,
            "candidate_ids": [str(candidate.id)],
            "candidate_sha256": [candidate.sha256],
            "estimated_cost_micros": 0,
            "actual_cost_micros": 0,
            "cost_source": GenerationCostSource.UNMETERED.value,
        }
        self._write_atomic(candidate_path, candidate_payload)
        self._write_atomic(thumbnail_path, thumbnail_output.getvalue())
        self._write_json_atomic(metadata_path, metadata)
        self._write_json_atomic(input_path, input_payload)
        self._write_json_atomic(manifest_path, manifest)
        completed_at = datetime.now(UTC)
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            visual_beat_id=visual_beat_id,
            revision_id=revision_id,
            kind=GenerationKind.IMAGE,
            input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
            provider="source_video",
            model="selected-keyframe",
            model_snapshot="source-frame-v1",
            prompt_version="source-frame-v1",
            schema_version="viral-dna-source-frame/v1",
            pricing_version="zero-cost-v1",
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=ImageExecutionMode.SOURCE_FRAME,
            adapter_id="source-frame",
            adapter_version="batch4.2",
            capability_snapshot={"source_frame_passthrough": True},
            execution_summary={
                "model_call": False,
                "source_keyframe_timestamp_seconds": (plan.source_keyframe_timestamp_seconds),
            },
            cost_source=GenerationCostSource.UNMETERED,
            cost_estimate_known=True,
            usage={"model_calls": 0, "source_frames": 1},
            output_manifest_relative_path=self.workspace.relative(manifest_path),
            status=ProductionRunStatus.COMPLETED,
            estimated_cost_micros=0,
            actual_cost_micros=0,
            latency_ms=max(0, round((completed_at - started).total_seconds() * 1000)),
            completed_at=completed_at,
        )
        return run, candidate

    def _resolve_source_keyframe(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> Path | None:
        if plan.source_keyframe_relative_path is not None:
            try:
                candidate = self.workspace.resolve(plan.source_keyframe_relative_path).resolve()
            except WorkspaceError:
                return None
            root = self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            ).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return None
            filesystem_candidate = _filesystem_path(candidate)
            return filesystem_candidate if filesystem_candidate.is_file() else None

        source_url = plan.source_keyframe_url
        prefix = f"/api/v1/analyses/{project.base_analysis_id}/artifacts/"
        if not source_url or not source_url.startswith(prefix):
            return None
        relative = unquote(source_url[len(prefix) :]).replace(chr(92), "/")
        if not relative or Path(relative).is_absolute():
            return None
        roots = [
            self.workspace.analysis_root(
                project.record_id,
                project.base_analysis_id,
            ),
            self.workspace.root / "analyses" / str(project.base_analysis_id),
        ]
        for root in roots:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            filesystem_candidate = _filesystem_path(candidate)
            if filesystem_candidate.is_file():
                return filesystem_candidate
        return None

    async def _require_shot(self, shot_plan_id: UUID) -> ShotPlan:
        try:
            plan = await self.repository.get_shot_plan(shot_plan_id)
        except IncompatibleShotPlanSchemaError as exc:
            project = await self._require_project(exc.project_id)
            await self._ensure_project_shots(project)
            plan = None
        if plan is None:
            raise _fail(404, "shot_plan_not_found", "分镜创作计划不存在")
        return plan

    @staticmethod
    def _ensure_shot_active(plan: ShotPlan) -> None:
        if plan.lifecycle_status != ShotLifecycleStatus.ACTIVE:
            raise _fail(409, "shot_discarded", "已舍弃分镜需要先恢复后才能继续操作")

    async def _require_run(self, run_id: UUID) -> GenerationRun:
        run = await self.repository.get_generation_run(run_id)
        if run is None:
            raise _fail(404, "generation_run_not_found", "生成任务不存在")
        return run

    async def _require_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate:
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if candidate is None:
            raise _fail(404, "generation_candidate_not_found", "生成候选不存在")
        return candidate

    async def _load_video_candidate_batch(
        self,
        candidate_ids: list[UUID],
    ) -> tuple[ProductionProject, ShotPlan, list[GenerationCandidate]]:
        candidates: list[GenerationCandidate] = []
        runs: list[GenerationRun] = []
        for candidate_id in candidate_ids:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if candidate.kind != run.kind or run.kind != GenerationKind.VIDEO:
                raise _fail(
                    409,
                    "video_candidate_batch_required",
                    "批量操作仅支持视频候选",
                )
            candidates.append(candidate)
            runs.append(run)

        project_ids = {run.project_id for run in runs}
        shot_plan_ids = {run.shot_plan_id for run in runs}
        if len(project_ids) != 1 or len(shot_plan_ids) != 1:
            raise _fail(
                409,
                "video_candidate_batch_scope_mismatch",
                "一次只能处理同一分镜中的视频候选",
            )
        project = await self._require_project(next(iter(project_ids)))
        plan = await self._require_shot(next(iter(shot_plan_ids)))
        self._ensure_shot_active(plan)
        return project, plan, candidates

    async def _load_image_candidate_batch(
        self,
        candidate_ids: list[UUID],
    ) -> tuple[
        ProductionProject,
        ShotPlan,
        ShotVisualBeat,
        list[GenerationCandidate],
    ]:
        candidates: list[GenerationCandidate] = []
        runs: list[GenerationRun] = []
        for candidate_id in candidate_ids:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if candidate.kind != run.kind or run.kind != GenerationKind.IMAGE:
                raise _fail(
                    409,
                    "image_candidate_batch_required",
                    "批量操作仅支持图片候选",
                )
            candidates.append(candidate)
            runs.append(run)

        project_ids = {run.project_id for run in runs}
        shot_plan_ids = {run.shot_plan_id for run in runs}
        if len(project_ids) != 1 or len(shot_plan_ids) != 1:
            raise _fail(
                409,
                "image_candidate_batch_scope_mismatch",
                "一次只能处理同一分镜画面中的图片候选",
            )
        project = await self._require_project(next(iter(project_ids)))
        plan = await self._require_shot(next(iter(shot_plan_ids)))
        self._ensure_shot_active(plan)
        beats = [_visual_beat(plan, run.visual_beat_id) for run in runs]
        if len({item.id for item in beats}) != 1:
            raise _fail(
                409,
                "image_candidate_batch_visual_beat_mismatch",
                "一次只能处理同一画面的图片候选",
            )
        return project, plan, beats[0], candidates

    async def _completed_analysis(
        self,
        record: AnalysisRecord,
        analysis_id: UUID,
    ) -> tuple[AnalysisJob, AnalysisReport]:
        analysis = await self.repository.get_analysis(analysis_id)
        if (
            analysis is None
            or analysis.video_id != record.video_id
            or analysis.record_id not in {None, record.id}
        ):
            raise _fail(404, "analysis_not_found", "指定分析版本不属于当前记录")
        if analysis.stage != AnalysisStage.COMPLETED:
            raise _fail(409, "analysis_incomplete", "指定分析版本尚未完成")
        report = await self.repository.get_report_by_analysis(analysis.id)
        if report is None or report.video_id != record.video_id:
            raise _fail(409, "analysis_report_missing", "指定分析版本缺少分析报告")
        return analysis, report

    async def _require_project(self, project_id: UUID) -> ProductionProject:
        project = await self.repository.get_production_project(project_id)
        if project is None:
            raise _fail(404, "production_not_found", "创作方案不存在")
        return _normalize_optional_preparation_project(project)

    async def _require_revision(
        self,
        project: ProductionProject,
        revision_id: UUID,
    ) -> ProductionRevision:
        revision = await self.repository.get_production_revision(revision_id)
        if revision is None or revision.project_id != project.id:
            raise _fail(404, "revision_not_found", "创作方案版本不存在")
        return revision

    async def _list_reference_assets(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]:
        if self.project_assets is not None:
            return await self.project_assets.list_references(
                project_id, include_archived=include_archived
            )
        assets = await self.repository.list_reference_assets(project_id)
        if not include_archived:
            assets = [item for item in assets if item.archived_at is None]
        return assets

    async def _require_asset(
        self,
        asset_id: UUID,
        project_id: UUID | None = None,
    ) -> ReferenceAsset:
        asset = (
            await self.project_assets.get_reference(asset_id, project_id)
            if self.project_assets is not None
            else await self.repository.get_reference_asset(asset_id)
        )
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "参考资产不存在")
        return asset

    @staticmethod
    def _require_expected_revision(
        project: ProductionProject,
        expected_revision_id: UUID,
    ) -> None:
        if project.current_revision_id != expected_revision_id:
            raise _fail(409, "revision_conflict", "创作方案已更新，请刷新后重试")

    async def _prepare_revision(
        self,
        project: ProductionProject,
        change_kind: ProductionChangeKind,
        change_summary: str,
        *,
        revision_id: UUID | None = None,
        report: AnalysisReport | None = None,
        reference_assets: list[ReferenceAsset] | None = None,
        shot_plans: list[ShotPlan] | None = None,
        reference_bindings: list[ReferenceBinding] | None = None,
        video_clip_preparations: list[VideoClipPreparation] | None = None,
    ) -> tuple[ProductionProject, ProductionRevision]:
        revisions = await self.repository.list_production_revisions(project.id)
        revision_number = max((item.revision_number for item in revisions), default=0) + 1
        revision_id = revision_id or uuid4()
        paths = self.workspace.initialize_production(project.record_id, project.id)
        revision = ProductionRevision(
            id=revision_id,
            project_id=project.id,
            parent_revision_id=project.current_revision_id,
            revision_number=revision_number,
            change_kind=change_kind,
            change_summary=_simplified_text(
                change_summary,
                field_name="版本说明",
                max_length=500,
            ),
            snapshot_relative_path=self.workspace.relative(paths.revisions / f"{revision_id}.json"),
        )
        updated_project = ProductionProject.model_validate(
            {
                **project.model_dump(mode="python"),
                "current_revision_id": revision.id,
                "updated_at": utc_now(),
            }
        )
        snapshot = await self._build_snapshot(
            updated_project,
            revision,
            report=report,
            reference_assets=reference_assets,
            shot_plans=shot_plans,
            reference_bindings=reference_bindings,
            video_clip_preparations=video_clip_preparations,
        )
        await asyncio.to_thread(
            self._write_revision_files,
            updated_project,
            revision,
            snapshot,
        )
        return updated_project, revision

    async def _build_snapshot(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        *,
        report: AnalysisReport | None,
        reference_assets: list[ReferenceAsset] | None,
        shot_plans: list[ShotPlan] | None,
        reference_bindings: list[ReferenceBinding] | None,
        video_clip_preparations: list[VideoClipPreparation] | None,
    ) -> dict[str, object]:
        if report is None:
            report = await self.repository.get_report_by_analysis(
                project.prompt_source_analysis_id or project.base_analysis_id
            )
        if report is None or report.video_id != project.video_id:
            raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
        assets = (
            list(reference_assets)
            if reference_assets is not None
            else await self._list_reference_assets(project.id, include_archived=True)
        )
        plans = (
            list(shot_plans)
            if shot_plans is not None
            else await self.repository.list_shot_plans(project.id)
        )
        if reference_bindings is None:
            bindings: list[ReferenceBinding] = []
            for plan in plans:
                bindings.extend(await self.repository.list_reference_bindings(plan.id))
        else:
            bindings = list(reference_bindings)
        binding_groups = {
            plan.id: [item for item in bindings if item.shot_plan_id == plan.id] for plan in plans
        }
        reference_snapshots = (
            [await self.project_assets.snapshot_reference(project.id, item) for item in assets]
            if self.project_assets is not None
            else [item.model_dump(mode="json") for item in assets]
        )
        preparations = (
            list(video_clip_preparations)
            if video_clip_preparations is not None
            else await self.repository.list_video_clip_preparations(project.id)
        )
        return {
            "schema_version": PRODUCTION_SNAPSHOT_SCHEMA,
            "revision": _revision_response(revision).model_dump(mode="json"),
            "project": project.model_dump(mode="json"),
            "source_analysis": {
                "analysis_id": str(report.analysis_id),
                "generated_at": report.generated_at.isoformat(),
                "overview": report.overview.model_dump(mode="json"),
                "entities": [item.model_dump(mode="json") for item in report.entities],
                "prompt_package": report.prompt_package.model_dump(mode="json"),
                "shots": [item.model_dump(mode="json") for item in report.shots],
            },
            "references": reference_snapshots,
            "shot_plans": [
                {
                    "shot_plan": plan.model_dump(mode="json"),
                    "reference_bindings": [
                        item.model_dump(mode="json") for item in binding_groups[plan.id]
                    ],
                }
                for plan in plans
            ],
            "video_clip_preparations": [item.model_dump(mode="json") for item in preparations],
        }

    async def _read_revision_snapshot(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
    ) -> dict[str, object]:
        candidate = self.workspace.resolve(revision.snapshot_relative_path)
        revisions_root = self.workspace.production_paths(
            project.record_id,
            project.id,
        ).revisions.resolve()
        try:
            candidate.resolve().relative_to(revisions_root)
        except ValueError as exc:
            raise _fail(409, "invalid_revision_path", "创作方案版本路径无效") from exc
        filesystem_candidate = _filesystem_path(candidate)
        if not filesystem_candidate.is_file():
            raise _fail(409, "revision_snapshot_missing", "创作方案版本快照不存在")
        try:
            payload = await asyncio.to_thread(
                filesystem_candidate.read_text,
                "utf-8-sig",
            )
            snapshot = json.loads(payload)
        except (OSError, json.JSONDecodeError) as exc:
            raise _fail(409, "invalid_revision_snapshot", "创作方案版本快照已损坏") from exc
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") not in SUPPORTED_PRODUCTION_SNAPSHOT_SCHEMAS
        ):
            raise _fail(409, "invalid_revision_snapshot", "创作方案版本快照格式不受支持")
        return snapshot

    def _write_revision_files(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        snapshot: dict[str, object],
    ) -> None:
        paths = self.workspace.production_paths(project.record_id, project.id)
        snapshot_path = self.workspace.resolve(revision.snapshot_relative_path)
        try:
            snapshot_path.resolve().relative_to(paths.revisions.resolve())
        except ValueError as exc:
            raise _fail(409, "invalid_revision_path", "创作方案版本路径无效") from exc
        self._write_json_atomic(snapshot_path, snapshot)
        self._write_json_atomic(
            paths.project_metadata,
            {
                "schema_version": PRODUCTION_SNAPSHOT_SCHEMA,
                "project": project.model_dump(mode="json"),
                "current_revision": _revision_response(revision).model_dump(mode="json"),
            },
        )

    def _write_reference_files(
        self,
        project: ProductionProject,
        asset: ReferenceAsset,
        original: bytes,
        thumbnail: bytes,
    ) -> None:
        original_path = self._resolve_reference_path(project, asset.relative_path)
        if asset.thumbnail_relative_path is None:
            raise _fail(500, "reference_thumbnail_path_missing", "参考资产缩略图路径缺失")
        thumbnail_path = self._resolve_reference_path(
            project,
            asset.thumbnail_relative_path,
        )
        self._write_atomic(original_path, original)
        self._write_atomic(thumbnail_path, thumbnail)
        self._write_asset_metadata(project, asset)

    def _write_asset_metadata(
        self,
        project: ProductionProject,
        asset: ReferenceAsset,
    ) -> None:
        metadata_path = (
            self._resolve_reference_path(project, asset.relative_path).parent / "asset.json"
        )
        self._write_json_atomic(metadata_path, asset.model_dump(mode="json"))

    def _resolve_reference_path(
        self,
        project: ProductionProject,
        relative_path: str,
    ) -> Path:
        try:
            candidate = self.workspace.resolve(relative_path).resolve()
        except WorkspaceError as exc:
            raise _fail(409, "invalid_reference_path", "参考资产路径无效") from exc
        root = self.workspace.production_paths(
            project.record_id,
            project.id,
        ).references.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise _fail(409, "invalid_reference_path", "参考资产路径无效") from exc
        return candidate

    async def _clone_snapshot_assets(
        self,
        source_project: ProductionProject,
        branch: ProductionProject,
        snapshot: dict[str, object],
    ) -> tuple[list[ReferenceAsset], dict[UUID, UUID]]:
        raw_assets = snapshot.get("references", [])
        if not isinstance(raw_assets, list):
            raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效")
        cloned: list[ReferenceAsset] = []
        id_map: dict[UUID, UUID] = {}
        if self.project_assets is not None:
            for raw_asset in raw_assets:
                if not isinstance(raw_asset, dict):
                    raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效")
                if raw_asset.get("removed_at") or raw_asset.get("archived_at"):
                    continue
                linked = await self.project_assets.link_snapshot_reference(branch, raw_asset)
                raw_id = raw_asset.get("asset_id") or raw_asset.get("id")
                if raw_id is None:
                    raise _fail(409, "invalid_revision_snapshot", "源版本资产标识缺失")
                id_map[UUID(str(raw_id))] = linked.id
                cloned.append(linked)
            return cloned, id_map
        for raw_asset in raw_assets:
            try:
                source_asset = ReferenceAsset.model_validate(raw_asset)
            except ValidationError as exc:
                raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效") from exc
            if source_asset.archived_at is not None:
                continue
            source_original = self._resolve_reference_path(
                source_project,
                source_asset.relative_path,
            )
            filesystem_original = _filesystem_path(source_original)
            if not filesystem_original.is_file():
                raise _fail(409, "reference_file_missing", "源版本参考资产文件不存在")
            source_thumbnail = None
            if source_asset.thumbnail_relative_path:
                source_thumbnail = self._resolve_reference_path(
                    source_project,
                    source_asset.thumbnail_relative_path,
                )
                if not _filesystem_path(source_thumbnail).is_file():
                    source_thumbnail = None
            new_id = uuid4()
            destination_root = self.workspace.reference_asset_root(
                branch.record_id,
                branch.id,
                new_id,
            )
            destination_original = destination_root / source_original.name
            destination_thumbnail = destination_root / "thumbnail.webp"
            cloned_asset = ReferenceAsset.model_validate(
                {
                    **source_asset.model_dump(mode="python"),
                    "id": new_id,
                    "project_id": branch.id,
                    "relative_path": self.workspace.relative(destination_original),
                    "thumbnail_relative_path": (
                        self.workspace.relative(destination_thumbnail)
                        if source_thumbnail is not None
                        else None
                    ),
                    "created_at": utc_now(),
                    "archived_at": None,
                }
            )
            original_payload = await asyncio.to_thread(filesystem_original.read_bytes)
            await asyncio.to_thread(
                self._write_atomic,
                destination_original,
                original_payload,
            )
            if source_thumbnail is not None:
                thumbnail_payload = await asyncio.to_thread(
                    _filesystem_path(source_thumbnail).read_bytes
                )
                await asyncio.to_thread(
                    self._write_atomic,
                    destination_thumbnail,
                    thumbnail_payload,
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                branch,
                cloned_asset,
            )
            cloned.append(cloned_asset)
            id_map[source_asset.id] = cloned_asset.id
        return cloned, id_map

    async def _clone_visual_beats(
        self,
        *,
        source_project: ProductionProject,
        target_project: ProductionProject,
        source_plan: ShotPlan,
        target_shot_plan_id: UUID,
        revision_id: UUID,
        primary_source_url: str | None,
        primary_source_relative_path: str | None,
        asset_ids: dict[UUID, UUID] | None = None,
    ) -> list[ShotVisualBeat]:
        """Clone visual structure while deliberately dropping generated approvals."""
        cloned: list[ShotVisualBeat] = []
        now = utc_now()
        for position, beat in enumerate(
            sorted(source_plan.visual_beats, key=lambda item: item.index),
            start=1,
        ):
            cloned_id = uuid4()
            if position == 1:
                source_url = primary_source_url
                source_relative_path = primary_source_relative_path
                source_timestamp = beat.source_timestamp_seconds
                source_origin = "duplicate" if source_relative_path else beat.source_origin
            else:
                source_url = beat.source_frame_url
                source_relative_path = None
                source_timestamp = beat.source_timestamp_seconds
                source_origin = beat.source_origin
                if beat.source_frame_relative_path is not None:
                    source_path = self._resolve_source_keyframe(
                        source_project,
                        _shot_for_visual_beat(source_plan, beat),
                    )
                    if source_path is None:
                        raise _fail(
                            409,
                            "visual_beat_source_frame_missing",
                            f"源分镜画面 {beat.index} 的关键帧文件不存在",
                        )
                    destination = (
                        self.workspace.production_shot_root(
                            target_project.record_id,
                            target_project.id,
                            target_shot_plan_id,
                        )
                        / "visual-beats"
                        / str(cloned_id)
                        / "source-frames"
                        / f"{revision_id}.jpg"
                    )
                    payload = await asyncio.to_thread(source_path.read_bytes)
                    await asyncio.to_thread(self._write_atomic, destination, payload)
                    source_relative_path = self.workspace.relative(destination)
                    source_url = (
                        f"/api/v1/production-shots/{target_shot_plan_id}/visual-beats/"
                        f"{cloned_id}/source-frame?v={revision_id}"
                    )
                    source_origin = "duplicate"
                elif (source_url or "").startswith("/api/v1/production-shots/"):
                    source_url = None
                    source_timestamp = None
                    source_origin = "blank"

            mentions = beat.image_prompt_mentions
            if asset_ids is not None:
                mentions = [
                    mention.model_copy(
                        update={
                            "reference_asset_id": asset_ids[mention.reference_asset_id],
                        }
                    )
                    for mention in beat.image_prompt_mentions
                    if mention.reference_asset_id in asset_ids
                ]
            cloned.append(
                beat.model_copy(
                    update={
                        "id": cloned_id,
                        "index": position,
                        "source_frame_url": source_url,
                        "source_frame_relative_path": source_relative_path,
                        "source_timestamp_seconds": source_timestamp,
                        "source_origin": source_origin,
                        "image_prompt_mentions": mentions,
                        "image_status": (
                            WorkflowItemStatus.READY
                            if beat.image_prompt.strip()
                            else WorkflowItemStatus.DRAFT
                        ),
                        "approved_image_candidate_id": None,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            )
        return cloned

    async def _clone_snapshot_shots(
        self,
        source_project: ProductionProject,
        branch: ProductionProject,
        revision_id: UUID,
        snapshot: dict[str, object],
        asset_ids: dict[UUID, UUID],
    ) -> tuple[list[ShotPlan], list[ReferenceBinding]]:
        raw_plans = snapshot.get("shot_plans", [])
        if not isinstance(raw_plans, list):
            raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效")
        cloned_plans: list[ShotPlan] = []
        cloned_bindings: list[ReferenceBinding] = []
        for raw_entry in raw_plans:
            if not isinstance(raw_entry, dict):
                raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效")
            try:
                source_plan = ShotPlan.model_validate(raw_entry["shot_plan"])
                source_bindings = [
                    ReferenceBinding.model_validate(item)
                    for item in raw_entry.get("reference_bindings", [])
                ]
            except (KeyError, TypeError, ValidationError) as exc:
                raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效") from exc
            cloned_plan_id = uuid4()
            source_keyframe_url = source_plan.source_keyframe_url
            source_keyframe_relative_path = None
            if source_plan.source_keyframe_relative_path is not None:
                try:
                    source_keyframe = self.workspace.resolve(
                        source_plan.source_keyframe_relative_path
                    ).resolve()
                except WorkspaceError as exc:
                    raise _fail(
                        409,
                        "source_keyframe_path_invalid",
                        "源版本关键帧路径无效",
                    ) from exc
                source_shot_root = self.workspace.production_shot_root(
                    source_project.record_id,
                    source_project.id,
                    source_plan.id,
                ).resolve()
                try:
                    source_keyframe.relative_to(source_shot_root)
                except ValueError as exc:
                    raise _fail(
                        409,
                        "source_keyframe_path_invalid",
                        "源版本关键帧路径无效",
                    ) from exc
                filesystem_source = _filesystem_path(source_keyframe)
                if not filesystem_source.is_file():
                    raise _fail(
                        409,
                        "source_keyframe_missing",
                        "源版本所选关键帧文件不存在",
                    )
                destination = (
                    self.workspace.production_shot_root(
                        branch.record_id,
                        branch.id,
                        cloned_plan_id,
                    )
                    / "source-keyframes"
                    / f"{revision_id}.jpg"
                )
                payload = await asyncio.to_thread(filesystem_source.read_bytes)
                await asyncio.to_thread(self._write_atomic, destination, payload)
                source_keyframe_relative_path = self.workspace.relative(destination)
                source_keyframe_url = (
                    f"/api/v1/production-shots/{cloned_plan_id}/source-keyframe?v={revision_id}"
                )
            cloned_visual_beats = await self._clone_visual_beats(
                source_project=source_project,
                target_project=branch,
                source_plan=source_plan,
                target_shot_plan_id=cloned_plan_id,
                revision_id=revision_id,
                primary_source_url=source_keyframe_url,
                primary_source_relative_path=source_keyframe_relative_path,
                asset_ids=asset_ids,
            )
            cloned_plan = ShotPlan.model_validate(
                {
                    **source_plan.model_dump(mode="python"),
                    "id": cloned_plan_id,
                    "project_id": branch.id,
                    "revision_id": revision_id,
                    "source_keyframe_url": source_keyframe_url,
                    "source_keyframe_relative_path": source_keyframe_relative_path,
                    "image_prompt": cloned_visual_beats[0].image_prompt,
                    "image_prompt_mentions": (cloned_visual_beats[0].image_prompt_mentions),
                    "image_negative_constraints": (
                        cloned_visual_beats[0].image_negative_constraints
                    ),
                    "approved_image_candidate_id": None,
                    "approved_video_candidate_id": None,
                    "image_status": _visual_beat_image_status(cloned_visual_beats),
                    "video_status": WorkflowItemStatus.DRAFT,
                    "visual_beats": cloned_visual_beats,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            cloned_plans.append(cloned_plan)
            for binding in source_bindings:
                mapped_asset_id = asset_ids.get(binding.reference_asset_id)
                if mapped_asset_id is None:
                    continue
                cloned_bindings.append(
                    ReferenceBinding.model_validate(
                        {
                            **binding.model_dump(mode="python"),
                            "id": uuid4(),
                            "shot_plan_id": cloned_plan.id,
                            "reference_asset_id": mapped_asset_id,
                            "created_at": utc_now(),
                        }
                    )
                )
        return cloned_plans, cloned_bindings

    @staticmethod
    def _write_atomic(destination: Path, payload: bytes) -> None:
        filesystem_destination = _filesystem_path(destination)
        filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = filesystem_destination.parent / f".tmp-{uuid4().hex[:8]}"
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, filesystem_destination)
        except OSError as exc:
            raise _fail(507, "workspace_write_failed", "无法写入工作区文件") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _write_json_atomic(cls, destination: Path, payload: object) -> None:
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        cls._write_atomic(destination, serialized)

    def _reference_response(
        self,
        asset: ReferenceAsset,
        current_revision_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        return ReferenceAssetResponse(
            id=asset.id,
            project_id=asset.project_id,
            type=asset.type,
            name=asset.name,
            folder_id=asset.folder_id,
            folder_name=asset.folder_name,
            description=asset.description,
            mime_type=asset.mime_type,
            width=asset.width,
            height=asset.height,
            sha256=asset.sha256,
            tags=asset.tags,
            rights_confirmed=asset.rights_confirmed,
            rights_note=asset.rights_note,
            content_url=(
                f"/api/v1/assets/{asset.id}/content"
                if self.project_assets is not None
                else f"/api/v1/references/{asset.id}/content"
            ),
            thumbnail_url=(
                f"/api/v1/assets/{asset.id}/thumbnail"
                if self.project_assets is not None
                else f"/api/v1/references/{asset.id}/thumbnail"
            ),
            current_revision_id=current_revision_id,
            created_at=asset.created_at,
            archived_at=asset.archived_at,
        )
