from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Protocol
from uuid import UUID

from ..models import (
    GenerationCostSource,
    ImageExecutionMode,
    VideoGenerationAudioStrategy,
    VideoProviderTask,
    VideoProviderTaskStatus,
)
from .catalog import (
    VideoModelSpec,
    load_video_model_catalog,
    video_duration_constraint_text,
    video_duration_is_supported,
)
from .contracts import (
    DepthControlVideo,
    GeneratedVideo,
    OrderedReferenceFrame,
    ProviderManagedAssetReference,
    ProviderVideoRequest,
    VideoAdapterIdentity,
    VideoAdapterResult,
    VideoProviderAdapter,
)
from .costing import estimate_video_cost
from .errors import VideoProviderError, classify_video_provider_failure
from .media_transport import download_provider_video
from .registry import VideoProviderRegistry
from .settings import VideoGenerationSettingsService


class VideoProviderTaskRepository(Protocol):
    async def save_video_provider_task(self, task: VideoProviderTask) -> VideoProviderTask: ...

    async def list_video_provider_tasks(
        self,
        generation_run_id: UUID,
    ) -> list[VideoProviderTask]: ...


@dataclass(frozen=True, slots=True)
class ResolvedVideoExecution:
    spec: VideoModelSpec
    identity: VideoAdapterIdentity
    api_key: str
    base_url: str
    resolution: str
    poll_interval_seconds: float
    timeout_seconds: int


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RemoteVideoOrchestrator:
    def __init__(
        self,
        settings: VideoGenerationSettingsService,
        repository: VideoProviderTaskRepository,
        registry: VideoProviderRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.registry = registry or settings.registry

    def resolve(
        self,
        *,
        model_alias: str | None,
        duration_seconds: float,
        resolution: str | None,
        candidate_count: int,
        allow_unknown_cost: bool,
    ) -> ResolvedVideoExecution:
        current = self.settings.get()
        if not current.enabled:
            raise VideoProviderError(
                409, "video_generation_not_configured", "请先在模型与设置中启用视频生成"
            )
        alias = model_alias or current.default_model_alias
        spec = load_video_model_catalog().option(alias)
        selected_resolution = (resolution or current.default_resolution).upper()
        capability = spec.capability
        if selected_resolution not in capability.supported_resolutions:
            raise VideoProviderError(
                422,
                "video_resolution_unsupported",
                f"{spec.label} 不支持 {selected_resolution}",
            )
        if candidate_count > capability.max_candidates:
            raise VideoProviderError(
                422,
                "video_candidate_count_unsupported",
                f"{spec.label} 最多生成 {capability.max_candidates} 个候选",
            )
        if not video_duration_is_supported(capability, duration_seconds):
            raise VideoProviderError(
                422,
                "video_duration_unsupported",
                f"{spec.label} {video_duration_constraint_text(capability)}",
            )
        api_key = self.settings.api_key(spec.provider)
        if not api_key:
            raise VideoProviderError(
                409,
                "video_api_key_missing",
                f"尚未配置 {spec.provider} 的 API Key，请先到模型与设置中填写并校验",
            )
        estimate = estimate_video_cost(
            spec,
            duration_seconds=duration_seconds,
            resolution=selected_resolution,
            candidate_count=candidate_count,
        )
        if not estimate.known and not allow_unknown_cost:
            raise VideoProviderError(
                409,
                "video_unknown_cost_confirmation_required",
                "该模型无法在提交前可靠估算费用，请确认未知成本后再生成",
            )
        identity = VideoAdapterIdentity(
            execution_mode=ImageExecutionMode.REMOTE_API,
            provider=spec.provider,
            model=spec.model or "unavailable",
            model_snapshot=f"{spec.model}@{load_video_model_catalog().catalog_version}",
            adapter_id=f"viral_dna_{spec.provider}_video",
            adapter_version=self.registry.get(spec.provider).adapter_version,
            protocol_version="viral-dna-video-provider/v1",
            capability=capability,
            estimated_cost_micros=estimate.micros or 0,
            cost_estimate_known=estimate.known,
            cost_source=(
                GenerationCostSource.CONFIGURED_RATE
                if estimate.known
                else GenerationCostSource.UNKNOWN
            ),
            pricing_version=estimate.pricing_version,
            execution_summary={
                "remote": True,
                "resolution": selected_resolution,
                "cost_explanation": estimate.explanation,
            },
            model_alias=spec.alias,
            model_display_name=spec.label,
            pricing_snapshot=spec.pricing,
        )
        return ResolvedVideoExecution(
            spec=spec,
            identity=identity,
            api_key=api_key,
            base_url=self.settings.base_url(spec.provider),
            resolution=selected_resolution,
            poll_interval_seconds=current.poll_interval_seconds,
            timeout_seconds=current.task_timeout_seconds,
        )

    async def generate(
        self,
        execution: ResolvedVideoExecution,
        *,
        run_id: UUID,
        project_id: UUID,
        shot_plan_id: UUID,
        run_root: Path,
        reference_frames: tuple[OrderedReferenceFrame, ...],
        depth_control_videos: tuple[DepthControlVideo, ...] = (),
        candidate_count: int,
        duration_seconds: float,
        aspect_ratio: str,
        width: int,
        height: int,
        positive_prompt: str,
        negative_prompt: str,
        seed: int | None,
        cancel_event: Event | None,
        managed_asset_references: tuple[ProviderManagedAssetReference, ...] = (),
        reference_manifest: dict[str, object] | None = None,
        audio_strategy: VideoGenerationAudioStrategy = VideoGenerationAudioStrategy.REUSE_SOURCE,
    ) -> VideoAdapterResult:
        provider = self.registry.get(execution.spec.provider)
        existing = {
            item.ordinal: item for item in await self.repository.list_video_provider_tasks(run_id)
        }
        videos: list[GeneratedVideo] = []
        failures: list[VideoProviderTask] = []
        provider_request_ids: list[str] = []
        total_cost = 0
        actual_cost_known = True

        for ordinal in range(1, candidate_count + 1):
            if cancel_event is not None and cancel_event.is_set():
                await self.cancel_run(run_id)
                raise VideoProviderError(409, "generation_cancelled", "视频生成任务已取消")
            task = existing.get(ordinal)
            request_snapshot = {
                "model_alias": execution.spec.alias,
                "provider_model": execution.spec.model,
                "ordinal": ordinal,
                "duration_seconds": duration_seconds,
                "resolution": execution.resolution,
                "aspect_ratio": aspect_ratio,
                "width": width,
                "height": height,
                "prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "audio_strategy": audio_strategy.value,
                "seed": seed,
                "route_id": (reference_manifest or {}).get("route_id"),
                "effective_route_id": (reference_manifest or {}).get("effective_route_id"),
                "spatial_control_semantics": (
                    reference_manifest or {}
                ).get("spatial_control_semantics"),
                "reference_images": [
                    {
                        "visual_beat_id": str(frame.visual_beat_id),
                        "ordinal": frame.ordinal,
                        "candidate_id": str(frame.candidate_id),
                        "sha256": frame.sha256,
                        "start_ratio": frame.start_ratio,
                        "end_ratio": frame.end_ratio,
                    }
                    for frame in reference_frames
                ],
                "depth_control_videos": [
                    {
                        "control_asset_id": str(video.control_asset_id),
                        "source_video_id": str(video.source_video_id),
                        "ordinal": video.ordinal,
                        "sha256": video.sha256,
                        "kind": video.kind,
                        "depth_convention": video.depth_convention,
                    }
                    for video in depth_control_videos
                ],
                "reference_policy": reference_manifest or {},
            }
            if managed_asset_references:
                request_snapshot["managed_asset_references"] = [
                    {
                        "binding_id": str(reference.binding_id),
                        "provider": reference.provider,
                        "asset_id": reference.asset_id,
                        "group_id": reference.group_id,
                        "kind": reference.kind,
                        "role": reference.role,
                        "name": reference.name,
                        "media_type": reference.media_type,
                        "project_name": reference.project_name,
                        "uri": reference.uri,
                    }
                    for reference in managed_asset_references
                ]
            submission_fingerprint = _fingerprint(request_snapshot)
            if task is not None and task.submission_fingerprint != submission_fingerprint:
                raise VideoProviderError(
                    409,
                    "video_provider_task_input_changed",
                    "恢复上游任务时检测到输入已变化，已阻止重复计费",
                )
            if task is None:
                task = VideoProviderTask(
                    generation_run_id=run_id,
                    project_id=project_id,
                    shot_plan_id=shot_plan_id,
                    ordinal=ordinal,
                    provider=execution.spec.provider,
                    model_alias=execution.spec.alias,
                    provider_model=execution.spec.model or "unavailable",
                    submission_fingerprint=submission_fingerprint,
                    request_snapshot=request_snapshot,
                    estimated_cost_micros=(
                        estimate_video_cost(
                            execution.spec,
                            duration_seconds=duration_seconds,
                            resolution=execution.resolution,
                            candidate_count=1,
                        ).micros
                    ),
                )
                await self.repository.save_video_provider_task(task)
                try:
                    submitted = await provider.submit(
                        ProviderVideoRequest(
                            request_id=run_id,
                            ordinal=ordinal,
                            model_alias=execution.spec.alias,
                            provider_model=execution.spec.model or "",
                            prompt=positive_prompt,
                            negative_prompt=negative_prompt,
                            reference_frames=reference_frames,
                            depth_control_videos=depth_control_videos,
                            managed_asset_references=managed_asset_references,
                            reference_manifest=reference_manifest or {},
                            duration_seconds=duration_seconds,
                            resolution=execution.resolution,
                            aspect_ratio=aspect_ratio,
                            width=width,
                            height=height,
                            generate_audio=(
                                audio_strategy == VideoGenerationAudioStrategy.GENERATE_NATIVE
                            ),
                            route_id=str(
                                (reference_manifest or {}).get("route_id")
                                or "ordered_multi_image"
                            ),
                            effective_route_id=str(
                                (reference_manifest or {}).get("effective_route_id")
                                or "ordered_multi_image"
                            ),
                            spatial_control_semantics=str(
                                (reference_manifest or {}).get("spatial_control_semantics")
                                or "none"
                            ),
                            control_condition=(
                                "depth"
                                if (reference_manifest or {}).get("route_id")
                                == "wan_vace_depth_control"
                                else None
                            ),
                            seed=seed,
                        ),
                        api_key=execution.api_key,
                        base_url=execution.base_url,
                    )
                except VideoProviderError as exc:
                    now = datetime.now(UTC)
                    task = task.model_copy(
                        update={
                            "status": (
                                VideoProviderTaskStatus.UNKNOWN
                                if exc.retryable
                                else VideoProviderTaskStatus.FAILED
                            ),
                            "error_code": exc.code,
                            "error_message": str(exc),
                            "retryable": exc.retryable,
                            "provider_error_code": exc.provider_code,
                            "error_category": exc.error_category,
                            "error_title": exc.user_title,
                            "error_technical_message": exc.technical_message,
                            "error_action": exc.suggested_action,
                            "updated_at": now,
                            "completed_at": None if exc.retryable else now,
                        }
                    )
                    await self.repository.save_video_provider_task(task)
                    failures.append(task)
                    if exc.code == "video_provider_balance_insufficient":
                        raise
                    continue
                now = datetime.now(UTC)
                task = task.model_copy(
                    update={
                        "provider_task_id": submitted.task_id,
                        "status": VideoProviderTaskStatus.SUBMITTED,
                        "response_snapshot": submitted.raw,
                        "submitted_at": now,
                        "updated_at": now,
                    }
                )
                await self.repository.save_video_provider_task(task)
            elif (
                task.status == VideoProviderTaskStatus.PENDING_SUBMISSION
                and not task.provider_task_id
            ):
                raise VideoProviderError(
                    409,
                    "video_provider_submission_ambiguous",
                    "服务在提交上游任务时中断；为避免重复扣费，"
                    "未自动重提，请人工核对 Provider 控制台",
                )

            if task.provider_task_id:
                provider_request_ids.append(task.provider_task_id)
            if task.status == VideoProviderTaskStatus.SUCCEEDED and task.output_relative_path:
                output_path = run_root / f"candidate_{ordinal:03d}.mp4"
                if not output_path.is_file():
                    # The stored workspace path may already point at the same location; a missing
                    # local file requires a fresh provider URL and normal polling below.
                    task = task.model_copy(update={"status": VideoProviderTaskStatus.RUNNING})
            if task.status not in {
                VideoProviderTaskStatus.SUCCEEDED,
                VideoProviderTaskStatus.FAILED,
                VideoProviderTaskStatus.CANCELLED,
            }:
                task = await self._poll_until_terminal(
                    task,
                    provider=provider,
                    execution=execution,
                    cancel_event=cancel_event,
                )
            if task.status != VideoProviderTaskStatus.SUCCEEDED or not task.output_url:
                failures.append(task)
                actual_cost_known = False
                continue
            destination = run_root / f"candidate_{ordinal:03d}.mp4"
            if not destination.is_file():
                await download_provider_video(task.output_url, destination)
            task_cost = task.actual_cost_micros
            if task_cost is None:
                item_estimate = estimate_video_cost(
                    execution.spec,
                    duration_seconds=float(
                        task.usage.get("output_video_duration") or duration_seconds
                    ),
                    resolution=execution.resolution,
                    candidate_count=1,
                )
                task_cost = item_estimate.micros
            if task_cost is None:
                actual_cost_known = False
            else:
                total_cost += task_cost
            task = task.model_copy(
                update={
                    "actual_cost_micros": task_cost,
                    "cost_known": task_cost is not None,
                    "updated_at": datetime.now(UTC),
                }
            )
            await self.repository.save_video_provider_task(task)
            videos.append(
                GeneratedVideo(
                    path=destination,
                    width=int(task.usage.get("width") or 0) or width,
                    height=int(task.usage.get("height") or 0) or height,
                    duration_seconds=float(
                        task.usage.get("output_video_duration") or duration_seconds
                    ),
                    metadata={
                        "provider": execution.spec.provider,
                        "provider_model": execution.spec.model,
                        "model_alias": execution.spec.alias,
                        "provider_task_id": task.provider_task_id,
                        "provider_ordinal": ordinal,
                    },
                )
            )

        if not videos:
            first = failures[0] if failures else None
            error_code = (
                first.error_code
                if first and first.error_code
                else "video_provider_all_candidates_failed"
            )
            error_message = (
                first.error_message if first and first.error_message else "所有视频候选均生成失败"
            )
            raise VideoProviderError(
                502,
                error_code,
                error_message,
                retryable=bool(first and first.retryable),
                raw_code=first.provider_error_code if first else None,
                provider=first.provider if first else execution.spec.provider,
                failure=(
                    classify_video_provider_failure(
                        provider=first.provider,
                        code=first.error_code,
                        message=first.error_technical_message or first.error_message,
                        retryable=first.retryable,
                        provider_code=first.provider_error_code,
                    )
                    if first
                    else None
                ),
            )
        usage = {
            "requested_candidate_count": candidate_count,
            "succeeded_candidate_count": len(videos),
            "failed_candidate_count": len(failures),
            "provider_task_ids": provider_request_ids,
            "resolution": execution.resolution,
            "duration_seconds": duration_seconds,
        }
        return VideoAdapterResult(
            videos=tuple(videos),
            provider_request_id=provider_request_ids[0] if provider_request_ids else None,
            usage=usage,
            actual_cost_micros=total_cost if actual_cost_known else None,
            cost_source=(
                GenerationCostSource.CONFIGURED_RATE
                if actual_cost_known
                else GenerationCostSource.UNKNOWN
            ),
        )

    async def _poll_until_terminal(
        self,
        task: VideoProviderTask,
        *,
        provider: VideoProviderAdapter,
        execution: ResolvedVideoExecution,
        cancel_event: Event | None,
    ) -> VideoProviderTask:
        if not task.provider_task_id:
            return task
        deadline = time.monotonic() + execution.timeout_seconds
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                await provider.cancel(
                    task.provider_task_id,
                    api_key=execution.api_key,
                    base_url=execution.base_url,
                    provider_model=task.provider_model,
                )
                now = datetime.now(UTC)
                cancelled = task.model_copy(
                    update={
                        "status": VideoProviderTaskStatus.CANCELLED,
                        "updated_at": now,
                        "completed_at": now,
                    }
                )
                await self.repository.save_video_provider_task(cancelled)
                return cancelled
            result = await provider.poll(
                task.provider_task_id,
                api_key=execution.api_key,
                base_url=execution.base_url,
                provider_model=task.provider_model,
            )
            now = datetime.now(UTC)
            usage = dict(result.usage)
            if result.width:
                usage["width"] = result.width
            if result.height:
                usage["height"] = result.height
            if result.duration_seconds:
                usage["output_video_duration"] = result.duration_seconds
            failure = None
            if result.status == VideoProviderTaskStatus.FAILED:
                failure = classify_video_provider_failure(
                    provider=task.provider,
                    code=result.error_code,
                    message=result.error_technical_message or result.error_message,
                    retryable=result.retryable,
                    provider_code=result.provider_error_code,
                )
            task = task.model_copy(
                update={
                    "status": result.status,
                    "response_snapshot": result.raw,
                    "usage": usage,
                    "output_url": result.output_url,
                    "actual_cost_micros": result.actual_cost_micros,
                    "cost_known": result.cost_known,
                    "error_code": failure.code if failure else result.error_code,
                    "error_message": failure.message if failure else result.error_message,
                    "retryable": failure.retryable if failure else result.retryable,
                    "provider_error_code": (
                        failure.provider_code if failure else result.provider_error_code
                    ),
                    "error_category": failure.category if failure else result.error_category,
                    "error_title": failure.title if failure else result.error_title,
                    "error_technical_message": (
                        failure.technical_message
                        if failure
                        else result.error_technical_message
                    ),
                    "error_action": (
                        failure.suggested_action if failure else result.error_action
                    ),
                    "last_polled_at": now,
                    "updated_at": now,
                    "completed_at": (
                        now
                        if result.status
                        in {
                            VideoProviderTaskStatus.SUCCEEDED,
                            VideoProviderTaskStatus.FAILED,
                            VideoProviderTaskStatus.CANCELLED,
                        }
                        else None
                    ),
                }
            )
            await self.repository.save_video_provider_task(task)
            if task.status in {
                VideoProviderTaskStatus.SUCCEEDED,
                VideoProviderTaskStatus.FAILED,
                VideoProviderTaskStatus.CANCELLED,
            }:
                return task
            await asyncio.sleep(execution.poll_interval_seconds)
        timeout_failure = classify_video_provider_failure(
            provider=task.provider,
            code="video_provider_task_timeout",
            message="等待 Provider 视频任务超时；可在重启后继续轮询，不会重新提交",
            retryable=True,
        )
        timed_out = task.model_copy(
            update={
                "status": VideoProviderTaskStatus.UNKNOWN,
                "error_code": timeout_failure.code,
                "error_message": timeout_failure.message,
                "retryable": timeout_failure.retryable,
                "error_category": timeout_failure.category,
                "error_title": timeout_failure.title,
                "error_technical_message": timeout_failure.technical_message,
                "error_action": timeout_failure.suggested_action,
                "updated_at": datetime.now(UTC),
            }
        )
        await self.repository.save_video_provider_task(timed_out)
        return timed_out

    async def cancel_run(self, run_id: UUID) -> None:
        tasks = await self.repository.list_video_provider_tasks(run_id)
        for task in tasks:
            if not task.provider_task_id or task.status in {
                VideoProviderTaskStatus.SUCCEEDED,
                VideoProviderTaskStatus.FAILED,
                VideoProviderTaskStatus.CANCELLED,
            }:
                continue
            try:
                provider = self.registry.get(task.provider)
                cancelled = await provider.cancel(
                    task.provider_task_id,
                    api_key=self.settings.api_key(task.provider),
                    base_url=self.settings.base_url(task.provider),
                    provider_model=task.provider_model,
                )
            except Exception:
                cancelled = False
            now = datetime.now(UTC)
            await self.repository.save_video_provider_task(
                task.model_copy(
                    update={
                        "status": VideoProviderTaskStatus.CANCELLED if cancelled else task.status,
                        "updated_at": now,
                        "completed_at": now if cancelled else task.completed_at,
                    }
                )
            )
