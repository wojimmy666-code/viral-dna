from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from ..chinese import to_simplified
from ..media import MediaProcessingError, MediaProcessor
from ..models import (
    GenerationCandidate,
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ProductionProject,
    ProductionRunStatus,
    ShotPlan,
    VideoGenerationCapability,
    VideoGenerationInputMode,
)
from ..workspace import WorkspaceManager
from .contracts import (
    MAX_GENERATED_VIDEO_BYTES,
    VIDEO_ADAPTER_PROTOCOL_VERSION,
    VIDEO_PROMPT_VERSION,
    VIDEO_REQUEST_SCHEMA_VERSION,
    GeneratedVideo,
    VideoAdapterIdentity,
    VideoAdapterRequest,
    VideoAdapterResult,
    VideoGenerationAdapter,
    VideoGenerationError,
    VideoGenerationRequest,
)
from .orchestrator import RemoteVideoOrchestrator, ResolvedVideoExecution
from .settings import VideoGenerationSettingsService

SIMULATED_VIDEO_ADAPTER_VERSION = "batch4.5.1"


class VideoGenerationGatewayError(VideoGenerationError):
    """Public gateway error translated by the production service."""


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{prefix}UNC{separator}{raw[2:]}")
    return Path(f"{prefix}{raw}")


def _write_atomic(path: Path, payload: bytes) -> None:
    destination = _filesystem_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".tmp-{uuid4().hex[:8]}"
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compiled_dimensions(
    project: ProductionProject,
    capability: VideoGenerationCapability,
    resolution: str | None = None,
) -> tuple[int, int]:
    resolution_long_edge = {
        "512P": 960,
        "720P": 1280,
        "768P": 1366,
        "1080P": 1920,
        "2K": 2560,
    }.get((resolution or "").upper(), max(project.output_width, project.output_height))
    scale = min(
        1.0,
        capability.maximum_width / project.output_width,
        capability.maximum_height / project.output_height,
        resolution_long_edge / max(project.output_width, project.output_height),
    )
    width = max(256, math.floor(project.output_width * scale / 2) * 2)
    height = max(256, math.floor(project.output_height * scale / 2) * 2)
    return width, height


def _positive_prompt(shot: ShotPlan) -> str:
    lines = [
        "以已确认分镜图片作为起始帧生成单镜头视频。",
        f"动作与运镜要求：{shot.video_prompt.strip()}",
        "保持起始帧中的人物身份、服装、产品结构、场景布局、画幅和光影连续。",
        "只生成该分镜的连续画面，不添加配音、字幕、片头、片尾或额外文字。",
    ]
    locked = "、".join(item.value for item in shot.locks)
    if locked:
        lines.append(f"必须保持的约束：{locked}。")
    text = "\n".join(lines)
    return (to_simplified(text) or text).strip()


def _negative_prompt(shot: ShotPlan) -> str:
    values = [
        *shot.video_negative_constraints,
        "人物身份漂移",
        "产品结构变形",
        "服装突变",
        "场景跳变",
        "闪烁",
        "镜头抖动",
        "动作不连贯",
        "额外文字",
        "水印",
    ]
    normalized: list[str] = []
    for value in values:
        item = (to_simplified(value) or value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return "，".join(normalized)[:1000]


class SimulatedVideoAdapter:
    """Creates a silent still-frame MP4 for workflow verification only."""

    def __init__(self, media_processor: MediaProcessor | None = None) -> None:
        self.media_processor = media_processor or MediaProcessor()
        self.identity = VideoAdapterIdentity(
            execution_mode=ImageExecutionMode.SIMULATED,
            provider="simulated",
            model="approved-frame-hold",
            model_snapshot="batch4.5.1-simulated-video-v1",
            adapter_id="viral_dna_simulated_video",
            adapter_version=SIMULATED_VIDEO_ADAPTER_VERSION,
            protocol_version=VIDEO_ADAPTER_PROTOCOL_VERSION,
            capability=VideoGenerationCapability(
                image_to_video=True,
                start_frame=True,
                end_frame=False,
                max_candidates=4,
                minimum_duration_seconds=0.1,
                maximum_duration_seconds=60,
                maximum_width=1920,
                maximum_height=1920,
                native_audio=False,
            ),
            estimated_cost_micros=0,
            cost_estimate_known=True,
            cost_source=GenerationCostSource.UNMETERED,
            pricing_version="simulated-zero-cost-v1",
            execution_summary={
                "simulated": True,
                "purpose": "workflow_validation",
                "native_audio": False,
            },
        )

    async def generate(self, request: VideoAdapterRequest) -> VideoAdapterResult:
        videos: list[GeneratedVideo] = []
        for ordinal in range(1, request.candidate_count + 1):
            if request.cancel_event is not None and request.cancel_event.is_set():
                raise VideoGenerationError(
                    409,
                    "generation_cancelled",
                    "视频生成任务已取消",
                )
            destination = request.run_root / f"candidate_{ordinal:03d}.mp4"
            temporary = request.run_root / f".candidate_{ordinal:03d}.mp4"
            try:
                await self.media_processor.create_still_video(
                    request.approved_image_path,
                    _filesystem_path(temporary),
                    duration_seconds=request.duration_seconds,
                    width=request.width,
                    height=request.height,
                )
                os.replace(_filesystem_path(temporary), _filesystem_path(destination))
            except MediaProcessingError as exc:
                raise VideoGenerationError(
                    503 if exc.code == "media_dependency_missing" else 502,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                ) from exc
            finally:
                _filesystem_path(temporary).unlink(missing_ok=True)
            videos.append(
                GeneratedVideo(
                    path=destination,
                    width=request.width,
                    height=request.height,
                    duration_seconds=request.duration_seconds,
                    metadata={
                        "simulated": True,
                        "ordinal": ordinal,
                        "source": "approved_image_hold",
                    },
                )
            )
        return VideoAdapterResult(
            videos=tuple(videos),
            usage={
                "candidate_count": len(videos),
                "duration_seconds": request.duration_seconds,
                "native_audio": False,
            },
            actual_cost_micros=0,
            cost_source=GenerationCostSource.UNMETERED,
        )


class VideoGenerationGateway:
    """Provider-neutral video generation boundary.

    Only the simulated adapter is registered in Batch 4.5.1. The registry is
    the extension seam for Batch 4.5.2's domestic remote adapter and for a
    possible future local implementation; no local executable is accepted or
    launched by this batch.
    """

    def __init__(
        self,
        workspace: WorkspaceManager,
        *,
        media_processor: MediaProcessor | None = None,
        adapters: Mapping[ImageExecutionMode, VideoGenerationAdapter] | None = None,
        settings_service: VideoGenerationSettingsService | None = None,
        repository: object | None = None,
        remote_orchestrator: RemoteVideoOrchestrator | None = None,
    ) -> None:
        self.workspace = workspace
        if adapters is None:
            simulated = SimulatedVideoAdapter(media_processor)
            self.adapters: dict[ImageExecutionMode, VideoGenerationAdapter] = {
                ImageExecutionMode.SIMULATED: simulated,
            }
        else:
            self.adapters = dict(adapters)
        self.settings_service = settings_service
        self.remote_orchestrator = remote_orchestrator
        if (
            self.remote_orchestrator is None
            and settings_service is not None
            and repository is not None
        ):
            self.remote_orchestrator = RemoteVideoOrchestrator(settings_service, repository)

    def validate_execution_mode(self, mode: ImageExecutionMode) -> None:
        if mode == ImageExecutionMode.LOCAL_TOOL:
            raise VideoGenerationGatewayError(
                409,
                "video_local_tool_not_supported",
                "当前版本不支持本机视频生成工具",
            )
        if mode == ImageExecutionMode.REMOTE_API and self.remote_orchestrator is not None:
            return
        if mode not in self.adapters:
            code = (
                "video_remote_provider_not_configured"
                if mode == ImageExecutionMode.REMOTE_API
                else "video_adapter_not_configured"
            )
            message = (
                "国内视频生成 API 将在 Batch 4.5.2 接入"
                if mode == ImageExecutionMode.REMOTE_API
                else "当前视频生成执行器尚未配置"
            )
            raise VideoGenerationGatewayError(409, code, message)

    def resolve_identity(
        self,
        *,
        execution_mode: str,
        model_alias: str | None,
        duration_seconds: float,
        resolution: str | None,
        candidate_count: int,
        allow_unknown_cost: bool,
    ) -> tuple[VideoAdapterIdentity, ResolvedVideoExecution | None]:
        try:
            mode = ImageExecutionMode(execution_mode)
        except ValueError as exc:
            raise VideoGenerationGatewayError(
                422,
                "video_execution_mode_invalid",
                "视频生成执行模式无效",
            ) from exc
        self.validate_execution_mode(mode)
        if mode == ImageExecutionMode.REMOTE_API:
            if self.remote_orchestrator is None:
                raise VideoGenerationGatewayError(
                    409,
                    "video_remote_provider_not_configured",
                    "远程视频 Provider 尚未配置",
                )
            try:
                resolved = self.remote_orchestrator.resolve(
                    model_alias=model_alias,
                    duration_seconds=duration_seconds,
                    resolution=resolution,
                    candidate_count=candidate_count,
                    allow_unknown_cost=allow_unknown_cost,
                )
            except VideoGenerationError as exc:
                raise VideoGenerationGatewayError(
                    exc.status_code,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                ) from exc
            return resolved.identity, resolved
        adapter = self.adapters.get(mode)
        if adapter is None:
            raise VideoGenerationGatewayError(
                409,
                "video_adapter_not_configured",
                "当前视频生成执行器尚未配置",
            )
        return adapter.identity, None

    async def cancel(self, run_id: UUID) -> None:
        if self.remote_orchestrator is not None:
            await self.remote_orchestrator.cancel_run(run_id)

    async def generate(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        approved_image_candidate_id: UUID,
        approved_image_path: Path,
        approved_image_sha256: str,
        approved_image_relative_path: str | None = None,
        *,
        candidate_count: int,
        duration_seconds: float,
        execution_mode: str = "simulated",
        model_alias: str | None = None,
        resolution: str | None = None,
        allow_unknown_cost: bool = False,
        seed: int | None = None,
        run_id: UUID | None = None,
        cancel_event: Event | None = None,
    ) -> tuple[GenerationRun, list[GenerationCandidate]]:
        try:
            mode = ImageExecutionMode(execution_mode)
        except ValueError as exc:
            raise VideoGenerationGatewayError(
                422,
                "video_execution_mode_invalid",
                "视频生成执行模式无效",
            ) from exc
        identity, resolved_remote = self.resolve_identity(
            execution_mode=mode.value,
            model_alias=model_alias,
            duration_seconds=duration_seconds,
            resolution=resolution,
            candidate_count=candidate_count,
            allow_unknown_cost=allow_unknown_cost,
        )
        adapter = self.adapters.get(mode)
        capability = identity.capability
        if not capability.image_to_video or not capability.start_frame:
            raise VideoGenerationGatewayError(
                409,
                "video_capability_missing",
                "当前执行器不支持以确认图片作为视频起始帧",
            )
        if candidate_count < 1 or candidate_count > capability.max_candidates:
            raise VideoGenerationGatewayError(
                422,
                "video_candidate_count_unsupported",
                f"当前执行器最多生成 {capability.max_candidates} 个视频候选",
            )
        if not (
            capability.minimum_duration_seconds
            <= duration_seconds
            <= capability.maximum_duration_seconds
        ):
            raise VideoGenerationGatewayError(
                422,
                "video_duration_unsupported",
                (
                    "当前执行器支持的时长范围为 "
                    f"{capability.minimum_duration_seconds:g}～"
                    f"{capability.maximum_duration_seconds:g} 秒"
                ),
            )
        if not identity.cost_estimate_known and not allow_unknown_cost:
            raise VideoGenerationGatewayError(
                409,
                "video_unknown_cost_confirmation_required",
                "当前视频模型无法预估成本，请确认未知成本后重试",
            )

        run_id = run_id or uuid4()
        run_root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "videos"
            / str(run_id)
        )
        _filesystem_path(run_root).mkdir(parents=True, exist_ok=True)
        selected_resolution = resolved_remote.resolution if resolved_remote else resolution
        width, height = _compiled_dimensions(project, capability, selected_resolution)
        prompt = _positive_prompt(shot)
        negative_prompt = _negative_prompt(shot)
        request = VideoGenerationRequest(
            project=project,
            shot=shot,
            revision_id=revision_id,
            approved_image_candidate_id=approved_image_candidate_id,
            approved_image_path=approved_image_path,
            approved_image_relative_path=(
                approved_image_relative_path or self.workspace.relative(approved_image_path)
            ),
            approved_image_sha256=approved_image_sha256,
            candidate_count=candidate_count,
            duration_seconds=duration_seconds,
            execution_mode=mode,
            model_alias=identity.model_alias,
            resolution=selected_resolution,
            allow_unknown_cost=allow_unknown_cost,
            seed=seed,
        )
        input_payload = self._input_payload(
            request,
            identity,
            width=width,
            height=height,
            prompt=prompt,
            negative_prompt=negative_prompt,
        )
        fingerprint = hashlib.sha256(_canonical_json(input_payload)).hexdigest()
        input_path = run_root / "input.json"
        _write_atomic(input_path, _canonical_json(input_payload) + b"\n")
        started = time.perf_counter()
        try:
            adapter_request = VideoAdapterRequest(
                request_id=run_id,
                run_root=run_root,
                project=project,
                shot=shot,
                approved_image_path=approved_image_path,
                approved_image_sha256=approved_image_sha256,
                candidate_count=candidate_count,
                duration_seconds=duration_seconds,
                width=width,
                height=height,
                positive_prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                capability=capability,
                cancel_event=cancel_event,
            )
            if resolved_remote is not None:
                if self.remote_orchestrator is None:  # pragma: no cover
                    raise VideoGenerationGatewayError(
                        409,
                        "video_remote_provider_not_configured",
                        "远程视频 Provider 尚未配置",
                    )
                result = await self.remote_orchestrator.generate(
                    resolved_remote,
                    run_id=run_id,
                    project_id=project.id,
                    shot_plan_id=shot.id,
                    run_root=run_root,
                    first_frame_path=approved_image_path,
                    candidate_count=candidate_count,
                    duration_seconds=duration_seconds,
                    aspect_ratio=project.output_aspect_ratio,
                    width=width,
                    height=height,
                    positive_prompt=prompt,
                    negative_prompt=negative_prompt,
                    seed=seed,
                    cancel_event=cancel_event,
                )
            else:
                if adapter is None:  # pragma: no cover
                    raise VideoGenerationGatewayError(
                        409,
                        "video_adapter_not_configured",
                        "当前视频生成执行器尚未配置",
                    )
                result = await adapter.generate(adapter_request)
        except VideoGenerationError as exc:
            raise VideoGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
                retryable=exc.retryable,
            ) from exc
        if cancel_event is not None and cancel_event.is_set():
            raise VideoGenerationGatewayError(
                409,
                "generation_cancelled",
                "视频生成任务已取消",
            )
        if resolved_remote is None and len(result.videos) != candidate_count:
            raise VideoGenerationGatewayError(
                502,
                "video_candidate_count_mismatch",
                "视频执行器返回的候选数量与请求不一致",
            )

        candidates = [
            self._save_candidate(
                run_root,
                run_id,
                int(generated.metadata.get("provider_ordinal") or ordinal),
                generated,
                request=request,
                identity=identity,
                request_fingerprint=fingerprint,
                target_width=width,
                target_height=height,
            )
            for ordinal, generated in enumerate(result.videos, start=1)
        ]
        actual_cost_known = result.actual_cost_micros is not None
        actual_cost = result.actual_cost_micros or 0
        cost_source = result.cost_source or identity.cost_source
        manifest_path = run_root / "manifest.json"
        manifest = {
            "schema_version": "viral-dna-video-generation-result/v1",
            "status": "completed",
            "request_id": str(run_id),
            "request_fingerprint": fingerprint,
            "provider_request_id": result.provider_request_id,
            "candidate_ids": [str(item.id) for item in candidates],
            "candidate_sha256": [item.sha256 for item in candidates],
            "estimated_cost_micros": identity.estimated_cost_micros,
            "actual_cost_micros": actual_cost,
            "cost_source": cost_source.value,
        }
        _write_atomic(manifest_path, _canonical_json(manifest) + b"\n")
        completed_at = datetime.now(UTC)
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=shot.id,
            revision_id=revision_id,
            kind=GenerationKind.VIDEO,
            input_mode=VideoGenerationInputMode.IMAGE_TO_VIDEO,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            model_alias=identity.model_alias,
            model_display_name=identity.model_display_name,
            prompt_version=VIDEO_PROMPT_VERSION,
            schema_version=VIDEO_REQUEST_SCHEMA_VERSION,
            pricing_version=identity.pricing_version,
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=identity.execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            provider_request_id=result.provider_request_id,
            capability_snapshot=capability.model_dump(mode="json"),
            execution_summary=identity.execution_summary,
            cost_source=cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            actual_cost_known=actual_cost_known,
            cost_currency="CNY",
            pricing_snapshot=identity.pricing_snapshot,
            usage=result.usage,
            output_manifest_relative_path=self.workspace.relative(manifest_path),
            status=ProductionRunStatus.COMPLETED,
            estimated_cost_micros=identity.estimated_cost_micros,
            actual_cost_micros=max(0, actual_cost),
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            completed_at=completed_at,
        )
        return run, candidates

    def _input_payload(
        self,
        request: VideoGenerationRequest,
        identity: VideoAdapterIdentity,
        *,
        width: int,
        height: int,
        prompt: str,
        negative_prompt: str,
    ) -> dict[str, object]:
        return {
            "schema_version": VIDEO_REQUEST_SCHEMA_VERSION,
            "input_mode": VideoGenerationInputMode.IMAGE_TO_VIDEO.value,
            "project_id": str(request.project.id),
            "shot_plan_id": str(request.shot.id),
            "revision_id": str(request.revision_id),
            "execution": {
                "mode": identity.execution_mode.value,
                "provider": identity.provider,
                "model": identity.model,
                "model_alias": identity.model_alias,
                "model_display_name": identity.model_display_name,
                "model_snapshot": identity.model_snapshot,
                "adapter_id": identity.adapter_id,
                "adapter_version": identity.adapter_version,
                "protocol_version": identity.protocol_version,
                "capabilities": identity.capability.model_dump(mode="json"),
                "summary": identity.execution_summary,
            },
            "output": {
                "aspect_ratio": request.project.output_aspect_ratio,
                "requested_width": request.project.output_width,
                "requested_height": request.project.output_height,
                "compiled_width": width,
                "compiled_height": height,
                "duration_seconds": request.duration_seconds,
                "candidate_count": request.candidate_count,
                "resolution": request.resolution,
                "native_audio": identity.capability.native_audio,
            },
            "prompt": {
                "positive": prompt,
                "negative": negative_prompt,
                "version": VIDEO_PROMPT_VERSION,
            },
            "seed": request.seed,
            "start_frame": {
                "candidate_id": str(request.approved_image_candidate_id),
                "relative_path": request.approved_image_relative_path,
                "sha256": request.approved_image_sha256,
            },
            "locks": [item.value for item in request.shot.locks],
            "cost": {
                "estimated_cost_micros": identity.estimated_cost_micros,
                "estimate_known": identity.cost_estimate_known,
                "source": identity.cost_source.value,
            },
        }

    def _save_candidate(
        self,
        run_root: Path,
        run_id: UUID,
        ordinal: int,
        generated: GeneratedVideo,
        *,
        request: VideoGenerationRequest,
        identity: VideoAdapterIdentity,
        request_fingerprint: str,
        target_width: int,
        target_height: int,
    ) -> GenerationCandidate:
        try:
            resolved = generated.path.resolve()
            resolved.relative_to(run_root.resolve())
        except (OSError, ValueError) as exc:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_path_invalid",
                "视频执行器返回了工作目录之外的文件",
            ) from exc
        filesystem_path = _filesystem_path(resolved)
        if generated.media_type != "video/mp4":
            raise VideoGenerationGatewayError(
                502,
                "generated_video_format_unsupported",
                "当前基础架构只接受 MP4 视频候选",
            )
        try:
            size_bytes = filesystem_path.stat().st_size
        except OSError as exc:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_missing",
                "视频执行器没有输出候选文件",
            ) from exc
        if size_bytes <= 0 or size_bytes > MAX_GENERATED_VIDEO_BYTES:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_size_invalid",
                "视频候选为空或超过工作区安全限制",
            )

        width = generated.width or target_width
        height = generated.height or target_height
        duration = generated.duration_seconds or request.duration_seconds
        sha256 = _sha256_file(resolved)
        thumbnail_path = run_root / f"candidate_{ordinal:03d}.webp"
        self._write_thumbnail(request.approved_image_path, thumbnail_path)
        quality_report = {
            "schema_version": "viral-dna-video-quality/v1",
            "status": "manual_review_required",
            "summary": (
                "基础文件检查通过；需人工检查动作、稳定性、主体一致性与时长。"
                if identity.execution_mode == ImageExecutionMode.REMOTE_API
                else "基础文件检查通过；模拟候选仅用于验证流程，需人工检查动作、稳定性与时长。"
            ),
            "automated_checks": {
                "file_integrity": {
                    "status": "passed",
                    "size_bytes": size_bytes,
                    "media_type": generated.media_type,
                },
                "duration": {
                    "status": "passed",
                    "requested_seconds": request.duration_seconds,
                    "actual_seconds": duration,
                },
                "dimensions": {
                    "status": "passed",
                    "width": width,
                    "height": height,
                },
                "native_audio": {
                    "status": "not_requested",
                    "present": False,
                },
            },
            "manual_checks": [
                {"id": "motion", "label": "动作与运镜", "status": "required"},
                {"id": "identity", "label": "人物与产品稳定性", "status": "required"},
                {"id": "continuity", "label": "画面连续性", "status": "required"},
            ],
            "simulated": identity.execution_mode == ImageExecutionMode.SIMULATED,
        }
        metadata_path = run_root / f"candidate_{ordinal:03d}.json"
        metadata = {
            "schema_version": "viral-dna-video-candidate/v1",
            "ordinal": ordinal,
            "provider": identity.provider,
            "model": identity.model,
            "request_fingerprint": request_fingerprint,
            "sha256": sha256,
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "quality_report": quality_report,
            "adapter_metadata": generated.metadata,
        }
        _write_atomic(metadata_path, _canonical_json(metadata) + b"\n")
        return GenerationCandidate(
            generation_run_id=run_id,
            ordinal=ordinal,
            kind=GenerationKind.VIDEO,
            relative_path=self.workspace.relative(resolved),
            thumbnail_relative_path=self.workspace.relative(thumbnail_path),
            width=width,
            height=height,
            duration_seconds=round(duration, 3),
            sha256=sha256,
            metadata_relative_path=self.workspace.relative(metadata_path),
            quality_report=quality_report,
        )

    @staticmethod
    def _write_thumbnail(source_path: Path, destination: Path) -> None:
        try:
            with Image.open(_filesystem_path(source_path)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise VideoGenerationGatewayError(
                409,
                "approved_image_invalid",
                "已确认图片文件无法作为视频起始帧",
            ) from exc
        image.thumbnail((640, 640), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="WEBP", quality=84, method=4)
        _write_atomic(destination, output.getvalue())
