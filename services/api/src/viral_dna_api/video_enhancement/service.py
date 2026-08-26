from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ..models import (
    GenerationCandidate,
    GenerationCandidateStatus,
    GenerationKind,
    WorkflowItemStatus,
)
from ..notifications import NotificationPublisher
from ..workspace import WorkspaceError, WorkspaceManager
from .domain import (
    ACTIVE_VIDEO_ENHANCEMENT_STATUSES,
    VideoEnhancementJob,
    VideoEnhancementJobStage,
    VideoEnhancementJobStatus,
    VideoEnhancementTarget,
)
from .engine import (
    RealEsrganNcnnEngine,
    VideoEnhancementCapability,
    VideoEnhancementProgress,
    VideoMediaInfo,
)
from .process_runner import (
    EnhancementProcessCancelled,
    EnhancementProcessError,
    EnhancementProcessTimeout,
)
from .settings import VideoEnhancementSettingsService


def utc_now() -> datetime:
    return datetime.now(UTC)


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


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    destination = _filesystem_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class VideoEnhancementServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(slots=True)
class VideoEnhancementInstallation:
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_percent: int
    message: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    capability: VideoEnhancementCapability | None = None


def _target_dimensions(aspect_ratio: str, target: VideoEnhancementTarget) -> tuple[int, int]:
    ratio_width, ratio_height = (int(item) for item in aspect_ratio.split(":", 1))
    short_edge = 1080 if target == VideoEnhancementTarget.FHD else 2160
    if ratio_width >= ratio_height:
        height = short_edge
        width = round(short_edge * ratio_width / ratio_height / 2) * 2
    else:
        width = short_edge
        height = round(short_edge * ratio_height / ratio_width / 2) * 2
    return width, height


def _estimate_remaining(
    job: VideoEnhancementJob,
    event: VideoEnhancementProgress,
    percent: int,
    now: datetime,
) -> int | None:
    if job.started_at is None or percent <= 3:
        return None

    if event.stage == VideoEnhancementJobStage.UPSCALING:
        processed = event.processed_frames
        total = event.total_frames or job.total_frames
        if processed is None or processed <= 0 or total is None:
            return None
        elapsed = max(0.0, (now - job.started_at).total_seconds())
        remaining_frames = max(0, total - processed)
        encode_reserve = max(10, round(job.duration_seconds * 2))
        return max(0, round(elapsed / processed * remaining_frames) + encode_reserve)

    if event.stage == VideoEnhancementJobStage.ENCODING:
        processed = event.processed_frames
        total = event.total_frames or job.total_frames
        if (
            processed is not None
            and total is not None
            and job.stage == VideoEnhancementJobStage.ENCODING
            and job.processed_frames is not None
            and processed > job.processed_frames
        ):
            elapsed = max(0.0, (now - job.updated_at).total_seconds())
            rate = elapsed / (processed - job.processed_frames)
            return max(0, round(rate * max(0, total - processed)))
        return max(5, round(job.duration_seconds * 2))

    if event.stage == VideoEnhancementJobStage.VALIDATING:
        return 1

    elapsed = max(0.0, (now - job.started_at).total_seconds())
    remaining = elapsed * (100 - percent) / max(1, percent)
    return max(0, round(remaining))


def _error_details(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, EnhancementProcessTimeout):
        return (
            "video_enhancement_timeout",
            "清晰化处理超时，可降低目标分辨率后重试。",
            exc.output_tail or str(exc),
        )
    if isinstance(exc, EnhancementProcessCancelled):
        return ("video_enhancement_cancelled", "清晰化任务已取消", exc.output_tail)
    if isinstance(exc, EnhancementProcessError):
        detail = exc.output_tail or str(exc)
        lowered = detail.lower()
        if "out of memory" in lowered or "vk_error_out_of_device_memory" in lowered:
            return (
                "video_enhancement_out_of_memory",
                "显存不足，建议改为 1080p 后重试。",
                detail,
            )
        if "vulkan" in lowered or "gpu" in lowered:
            return (
                "video_enhancement_device_unavailable",
                "未找到可用的 Vulkan 图形设备，请更新显卡驱动后重新检测。",
                detail,
            )
        return (
            "video_enhancement_process_failed",
            "本地清晰化进程未完成，请查看详情后重试。",
            detail,
        )
    if isinstance(exc, VideoEnhancementServiceError):
        return (exc.code, str(exc), str(exc))
    return ("video_enhancement_failed", "视频清晰化未完成。", str(exc))


class VideoEnhancementService:
    def __init__(
        self,
        repository,
        workspace: WorkspaceManager,
        production,
        settings: VideoEnhancementSettingsService,
        *,
        engine: RealEsrganNcnnEngine | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.production = production
        self.settings = settings
        self.engine = engine or RealEsrganNcnnEngine()
        self.notification_publisher = notification_publisher
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancellations: dict[UUID, asyncio.Event] = {}
        self._state_locks: dict[UUID, asyncio.Lock] = {}
        self._candidate_locks: dict[UUID, asyncio.Lock] = {}
        self._worker_slots = asyncio.Semaphore(1)
        self._installation_lock = asyncio.Lock()
        self._installations: dict[UUID, VideoEnhancementInstallation] = {}
        self._installation_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._source_media_cache: dict[tuple[UUID, str], VideoMediaInfo] = {}
        self._shutdown_requested = False

    def capability(self) -> VideoEnhancementCapability:
        return self.engine.capability()

    def _state_lock(self, job_id: UUID) -> asyncio.Lock:
        return self._state_locks.setdefault(job_id, asyncio.Lock())

    def _candidate_lock(self, candidate_id: UUID) -> asyncio.Lock:
        return self._candidate_locks.setdefault(candidate_id, asyncio.Lock())

    async def _probe_original_media(
        self,
        candidate: GenerationCandidate,
    ) -> tuple[dict[str, object], VideoMediaInfo]:
        original = self._original_media(candidate)
        source_sha256 = str(original.get("sha256") or candidate.sha256)
        cache_key = (candidate.id, source_sha256)
        cached = self._source_media_cache.get(cache_key)
        if cached is not None:
            return original, cached
        try:
            source_path, _ = await self.production.resolve_candidate_content(
                candidate.id,
                variant="original",
            )
            media = await asyncio.to_thread(
                self.engine.probe_source,
                _filesystem_path(source_path),
            )
        except Exception as exc:
            raise VideoEnhancementServiceError(
                422,
                "video_probe_failed",
                "无法读取原视频的真实尺寸、帧率或时长",
            ) from exc
        self._source_media_cache[cache_key] = media
        return original, media

    async def source_info(self, candidate_id: UUID) -> VideoMediaInfo:
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if candidate is None:
            raise VideoEnhancementServiceError(
                404,
                "generation_candidate_not_found",
                "视频候选不存在",
            )
        _, media = await self._probe_original_media(candidate)
        return media

    async def start_installation(self) -> VideoEnhancementInstallation:
        async with self._installation_lock:
            active = next(
                (
                    item
                    for item in self._installations.values()
                    if item.status in {"queued", "running"}
                ),
                None,
            )
            if active is not None:
                return active
            now = utc_now()
            installation = VideoEnhancementInstallation(
                id=uuid4(),
                status="queued",
                progress_percent=0,
                message="安装任务已创建",
                created_at=now,
                updated_at=now,
            )
            self._installations[installation.id] = installation
            task = asyncio.create_task(self._run_installation(installation))
            self._installation_tasks[installation.id] = task
            return installation

    def installation(self, installation_id: UUID) -> VideoEnhancementInstallation:
        installation = self._installations.get(installation_id)
        if installation is None:
            raise VideoEnhancementServiceError(
                404,
                "video_enhancement_installation_not_found",
                "未找到该清晰化引擎安装任务",
            )
        return installation

    async def _run_installation(self, installation: VideoEnhancementInstallation) -> None:
        installation.status = "running"
        installation.progress_percent = 1
        installation.message = "正在准备安装"
        installation.updated_at = utc_now()

        def update(percent: int, message: str) -> None:
            installation.progress_percent = max(0, min(100, int(percent)))
            installation.message = message[:500]
            installation.updated_at = utc_now()

        try:
            capability = await asyncio.to_thread(self.engine.install, update)
            installation.status = "succeeded"
            installation.progress_percent = 100
            installation.message = "Real-ESRGAN 快速引擎已安装并通过文件检查"
            installation.capability = capability
        except Exception as exc:
            installation.status = "failed"
            installation.error = str(exc)[-2000:] or "Real-ESRGAN 快速引擎安装失败"
            installation.message = "安装未完成，请查看原因后重试"
            installation.capability = self.engine.capability()
        finally:
            installation.updated_at = utc_now()
            self._installation_tasks.pop(installation.id, None)

    @staticmethod
    def _original_media(candidate: GenerationCandidate) -> dict[str, object]:
        enhancement = (candidate.quality_report or {}).get("video_enhancement") or {}
        original = enhancement.get("original") if isinstance(enhancement, dict) else None
        if isinstance(original, dict) and original.get("relative_path"):
            return dict(original)
        return {
            "relative_path": candidate.relative_path,
            "sha256": candidate.sha256,
            "width": candidate.width,
            "height": candidate.height,
        }

    async def submit(
        self,
        candidate_id: UUID,
        *,
        expected_revision_id: UUID,
        target: VideoEnhancementTarget | None = None,
        retry_of_job_id: UUID | None = None,
    ) -> VideoEnhancementJob:
        async with self._candidate_lock(candidate_id):
            active = await self.repository.list_video_enhancement_jobs(
                candidate_id=candidate_id,
                active_only=True,
            )
            if active:
                return active[-1]
            capability = self.capability()
            if not capability.available:
                raise VideoEnhancementServiceError(
                    409,
                    "video_enhancement_engine_required",
                    "请先安装 Real-ESRGAN 快速引擎",
                )
            candidate = await self.repository.get_generation_candidate(candidate_id)
            if candidate is None:
                raise VideoEnhancementServiceError(
                    404,
                    "generation_candidate_not_found",
                    "视频候选不存在",
                )
            run = await self.repository.get_generation_run(candidate.generation_run_id)
            if run is None:
                raise VideoEnhancementServiceError(
                    404,
                    "generation_run_not_found",
                    "生成任务不存在",
                )
            plan = await self.repository.get_shot_plan(run.shot_plan_id)
            project = await self.repository.get_production_project(run.project_id)
            if plan is None or project is None:
                raise VideoEnhancementServiceError(
                    404,
                    "production_scope_missing",
                    "创作方案不存在",
                )
            if project.current_revision_id != expected_revision_id:
                raise VideoEnhancementServiceError(
                    409,
                    "revision_conflict",
                    "创作方案已更新，请刷新后重试",
                )
            if (
                candidate.kind != GenerationKind.VIDEO
                or run.kind != GenerationKind.VIDEO
                or run.shot_plan_id != plan.id
                or plan.video_status != WorkflowItemStatus.APPROVED
                or plan.approved_video_candidate_id != candidate.id
                or candidate.status != GenerationCandidateStatus.SELECTED
            ):
                raise VideoEnhancementServiceError(
                    409,
                    "approved_video_candidate_required",
                    "只有当前已采用的视频候选可以进行 AI 清晰化",
                )
            account_id, state = await self.settings.get_current()
            selected_target = target or state.default_target
            target_width, target_height = _target_dimensions(
                project.output_aspect_ratio,
                selected_target,
            )
            original, source_media = await self._probe_original_media(candidate)
            source_width = source_media.width
            source_height = source_media.height
            if source_width >= target_width and source_height >= target_height:
                raise VideoEnhancementServiceError(
                    409,
                    "video_target_not_larger",
                    "原视频已达到或超过所选目标分辨率",
                )
            job = VideoEnhancementJob(
                account_id=account_id,
                project_id=project.id,
                shot_plan_id=plan.id,
                generation_run_id=run.id,
                candidate_id=candidate.id,
                record_id=project.record_id,
                submitted_revision_id=expected_revision_id,
                source_relative_path=str(original["relative_path"]),
                source_sha256=str(original.get("sha256") or candidate.sha256),
                source_width=source_width,
                source_height=source_height,
                duration_seconds=source_media.duration_seconds,
                target=selected_target,
                target_width=target_width,
                target_height=target_height,
                engine=capability.engine,
                engine_version=capability.version,
                model=capability.model,
                upscale_factor=self.engine.upscale_factor(
                    source_width,
                    source_height,
                    target_width,
                    target_height,
                ),
                retry_of_job_id=retry_of_job_id,
            )
            await self.repository.save_video_enhancement_job(job)
            await self._notify(job)
            self._schedule(job.id)
            return job

    async def get(self, job_id: UUID) -> VideoEnhancementJob:
        job = await self.repository.get_video_enhancement_job(job_id)
        if job is None:
            raise VideoEnhancementServiceError(
                404,
                "video_enhancement_job_not_found",
                "未找到该视频清晰化任务",
            )
        return job

    async def list_for_candidate(self, candidate_id: UUID) -> list[VideoEnhancementJob]:
        return await self.repository.list_video_enhancement_jobs(candidate_id=candidate_id)

    async def cancel(self, job_id: UUID) -> VideoEnhancementJob:
        async with self._state_lock(job_id):
            job = await self.get(job_id)
            if job.status not in ACTIVE_VIDEO_ENHANCEMENT_STATUSES:
                return job
            now = utc_now()
            if job.status == VideoEnhancementJobStatus.QUEUED:
                updated = job.model_copy(
                    update={
                        "status": VideoEnhancementJobStatus.CANCELLED,
                        "progress_message": "任务已取消",
                        "error_code": "video_enhancement_cancelled",
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
            else:
                updated = job.model_copy(
                    update={
                        "status": VideoEnhancementJobStatus.CANCELLATION_REQUESTED,
                        "progress_message": "正在停止本地清晰化进程",
                        "updated_at": now,
                    }
                )
            await self.repository.save_video_enhancement_job(updated)
        if updated.status == VideoEnhancementJobStatus.CANCELLED:
            await self._notify(updated)
        else:
            self._cancellations.setdefault(job_id, asyncio.Event()).set()
        return updated

    async def retry(self, job_id: UUID) -> VideoEnhancementJob:
        previous = await self.get(job_id)
        if previous.status in ACTIVE_VIDEO_ENHANCEMENT_STATUSES:
            return previous
        project = await self.repository.get_production_project(previous.project_id)
        if project is None or project.current_revision_id is None:
            raise VideoEnhancementServiceError(
                409,
                "revision_required",
                "当前创作方案没有可用版本",
            )
        return await self.submit(
            previous.candidate_id,
            expected_revision_id=project.current_revision_id,
            target=previous.target,
            retry_of_job_id=previous.id,
        )

    async def activate(
        self,
        job_id: UUID,
        *,
        expected_revision_id: UUID,
    ) -> GenerationCandidate:
        job = await self.get(job_id)
        if (
            job.status != VideoEnhancementJobStatus.SUCCEEDED
            or not job.result_relative_path
            or not job.result_sha256
            or not job.result_width
            or not job.result_height
        ):
            raise VideoEnhancementServiceError(
                409,
                "video_enhancement_result_unavailable",
                "清晰化结果尚不可用",
            )
        await self.resolve_result_content(job.id)
        async with self._candidate_lock(job.candidate_id):
            candidate, plan, project = await self._require_current_approval(job.candidate_id)
            if project.current_revision_id != expected_revision_id:
                raise VideoEnhancementServiceError(
                    409,
                    "revision_conflict",
                    "创作方案已更新，请刷新后重试",
                )
            quality_report = deepcopy(candidate.quality_report or {})
            current = quality_report.get("video_enhancement")
            current = dict(current) if isinstance(current, dict) else {}
            original = self._original_media(candidate)
            variants = [
                dict(item)
                for item in current.get("variants", [])
                if isinstance(item, dict) and str(item.get("job_id")) != str(job.id)
            ]
            variants.append(
                {
                    "job_id": str(job.id),
                    "target": job.target.value,
                    "relative_path": job.result_relative_path,
                    "sha256": job.result_sha256,
                    "width": job.result_width,
                    "height": job.result_height,
                }
            )
            quality_report["video_enhancement"] = {
                **current,
                "engine": job.engine,
                "model": job.model,
                "original": original,
                "variants": variants,
                "active_job_id": str(job.id),
                "active_target": job.target.value,
                "updated_at": utc_now().isoformat(),
            }
            updated_candidate = candidate.model_copy(
                update={
                    "relative_path": job.result_relative_path,
                    "sha256": job.result_sha256,
                    "width": job.result_width,
                    "height": job.result_height,
                    "quality_report": quality_report,
                }
            )
            await self.repository.save_generation_candidate(updated_candidate)
            jobs = await self.repository.list_video_enhancement_jobs(candidate_id=candidate.id)
            now = utc_now()
            for item in jobs:
                next_active = item.id == job.id
                if item.active_for_final != next_active:
                    await self.repository.save_video_enhancement_job(
                        item.model_copy(update={"active_for_final": next_active, "updated_at": now})
                    )
            del plan
            return updated_candidate

    async def use_original(
        self,
        candidate_id: UUID,
        *,
        expected_revision_id: UUID,
    ) -> GenerationCandidate:
        async with self._candidate_lock(candidate_id):
            candidate, plan, project = await self._require_current_approval(candidate_id)
            if project.current_revision_id != expected_revision_id:
                raise VideoEnhancementServiceError(
                    409,
                    "revision_conflict",
                    "创作方案已更新，请刷新后重试",
                )
            quality_report = deepcopy(candidate.quality_report or {})
            enhancement = quality_report.get("video_enhancement")
            if not isinstance(enhancement, dict) or not isinstance(
                enhancement.get("original"), dict
            ):
                return candidate
            original = dict(enhancement["original"])
            enhancement["active_job_id"] = None
            enhancement["active_target"] = None
            enhancement["updated_at"] = utc_now().isoformat()
            quality_report["video_enhancement"] = enhancement
            updated_candidate = candidate.model_copy(
                update={
                    "relative_path": str(original["relative_path"]),
                    "sha256": str(original["sha256"]),
                    "width": original.get("width"),
                    "height": original.get("height"),
                    "quality_report": quality_report,
                }
            )
            await self.repository.save_generation_candidate(updated_candidate)
            jobs = await self.repository.list_video_enhancement_jobs(candidate_id=candidate.id)
            now = utc_now()
            for item in jobs:
                if item.active_for_final:
                    await self.repository.save_video_enhancement_job(
                        item.model_copy(update={"active_for_final": False, "updated_at": now})
                    )
            del plan
            return updated_candidate

    async def _require_current_approval(self, candidate_id: UUID):
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if candidate is None:
            raise VideoEnhancementServiceError(
                404,
                "generation_candidate_not_found",
                "视频候选不存在",
            )
        run = await self.repository.get_generation_run(candidate.generation_run_id)
        if run is None:
            raise VideoEnhancementServiceError(404, "generation_run_not_found", "生成任务不存在")
        plan = await self.repository.get_shot_plan(run.shot_plan_id)
        project = await self.repository.get_production_project(run.project_id)
        if plan is None or project is None:
            raise VideoEnhancementServiceError(404, "production_scope_missing", "创作方案不存在")
        if (
            plan.video_status != WorkflowItemStatus.APPROVED
            or plan.approved_video_candidate_id != candidate.id
            or candidate.status != GenerationCandidateStatus.SELECTED
        ):
            raise VideoEnhancementServiceError(
                409,
                "approved_video_candidate_required",
                "该视频已不再是当前采用候选",
            )
        return candidate, plan, project

    async def resolve_result_content(self, job_id: UUID) -> tuple[Path, str]:
        job = await self.get(job_id)
        if job.status != VideoEnhancementJobStatus.SUCCEEDED or not job.result_relative_path:
            raise VideoEnhancementServiceError(
                404,
                "video_enhancement_result_unavailable",
                "清晰化结果尚不可用",
            )
        try:
            resolved = self.workspace.resolve(job.result_relative_path).resolve()
            resolved.relative_to(self.job_root(job).resolve())
        except (WorkspaceError, ValueError) as exc:
            raise VideoEnhancementServiceError(
                409,
                "video_enhancement_result_invalid",
                "清晰化结果路径无效",
            ) from exc
        filesystem_path = _filesystem_path(resolved)
        if not filesystem_path.is_file():
            raise VideoEnhancementServiceError(
                404,
                "video_enhancement_result_missing",
                "清晰化结果文件不存在",
            )
        return filesystem_path, "video/mp4"

    def job_root(self, job: VideoEnhancementJob) -> Path:
        return (
            self.workspace.production_shot_root(
                job.record_id,
                job.project_id,
                job.shot_plan_id,
            )
            / "videos"
            / str(job.generation_run_id)
            / "enhancements"
            / str(job.id)
        )

    def job_working_root(self, job: VideoEnhancementJob) -> Path:
        """Use a short native path for Real-ESRGAN's temporary frame files."""

        return (
            Path(tempfile.gettempdir()).resolve() / "ViralDNA" / "video-enhancement" / str(job.id)
        )

    async def recover(self) -> None:
        jobs = await self.repository.list_video_enhancement_jobs()
        now = utc_now()
        for job in jobs:
            if job.status == VideoEnhancementJobStatus.QUEUED:
                self._schedule(job.id)
            elif job.status in {
                VideoEnhancementJobStatus.RUNNING,
                VideoEnhancementJobStatus.CANCELLATION_REQUESTED,
            }:
                interrupted = job.model_copy(
                    update={
                        "status": VideoEnhancementJobStatus.INTERRUPTED,
                        "error_code": "video_enhancement_interrupted",
                        "error_message": "API 服务重启，原清晰化任务已中断，请重试。",
                        "progress_message": "任务因服务重启而中断",
                        "process_id": None,
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
                await self.repository.save_video_enhancement_job(interrupted)
                await self._notify(interrupted)

    async def shutdown(self) -> None:
        self._shutdown_requested = True
        for job_id in self._tasks:
            self._cancellations.setdefault(job_id, asyncio.Event()).set()
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _schedule(self, job_id: UUID) -> None:
        if job_id in self._tasks:
            return
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))

    async def _run(self, job_id: UUID) -> None:
        async with self._worker_slots:
            claimed = await self.repository.claim_video_enhancement_job(job_id)
            if claimed is None:
                return
            cancellation = self._cancellations.setdefault(job_id, asyncio.Event())
            heartbeat = asyncio.create_task(self._heartbeat(job_id, cancellation))
            try:
                if self._shutdown_requested or cancellation.is_set():
                    raise EnhancementProcessCancelled("API 服务正在停止")
                await self._notify(claimed)

                async def report(event: VideoEnhancementProgress) -> None:
                    async with self._state_lock(job_id):
                        latest = await self.get(job_id)
                        if latest.status not in ACTIVE_VIDEO_ENHANCEMENT_STATUSES:
                            return
                        now = utc_now()
                        progress_percent = max(latest.progress_percent, event.percent)
                        updated = latest.model_copy(
                            update={
                                "stage": event.stage,
                                "progress_percent": progress_percent,
                                "progress_message": event.message,
                                "processed_frames": (
                                    event.processed_frames
                                    if event.processed_frames is not None
                                    else latest.processed_frames
                                ),
                                "total_frames": event.total_frames or latest.total_frames,
                                "estimated_seconds_remaining": _estimate_remaining(
                                    latest,
                                    event,
                                    progress_percent,
                                    now,
                                ),
                                "process_id": event.process_id or latest.process_id,
                                "heartbeat_at": now,
                                "updated_at": now,
                            }
                        )
                        await self.repository.save_video_enhancement_job(updated)

                source_path, _ = await self.production.resolve_candidate_content(
                    claimed.candidate_id,
                    variant="original",
                )
                root = self.job_root(claimed)
                destination = root / "enhanced.mp4"
                working = self.job_working_root(claimed)
                output = await self.engine.generate(
                    source_path=_filesystem_path(source_path),
                    destination_path=_filesystem_path(destination),
                    working_root=working,
                    target_width=claimed.target_width,
                    target_height=claimed.target_height,
                    timeout_seconds=21600,
                    cancellation=cancellation,
                    progress=report,
                )
                await asyncio.to_thread(shutil.rmtree, working, True)
                manifest_path = root / "manifest.json"
                await asyncio.to_thread(
                    _write_json_atomic,
                    manifest_path,
                    {
                        "schema_version": "viral-dna-video-enhancement/v1",
                        "job_id": str(claimed.id),
                        "candidate_id": str(claimed.candidate_id),
                        "source_relative_path": claimed.source_relative_path,
                        "source_sha256": claimed.source_sha256,
                        "target": claimed.target.value,
                        "target_width": output.width,
                        "target_height": output.height,
                        "engine": claimed.engine,
                        "engine_version": claimed.engine_version,
                        "model": claimed.model,
                        "sha256": output.sha256,
                        "size_bytes": output.size_bytes,
                        "created_at": utc_now().isoformat(),
                    },
                )
                async with self._state_lock(job_id):
                    latest = await self.get(job_id)
                    now = utc_now()
                    completed = latest.model_copy(
                        update={
                            "status": VideoEnhancementJobStatus.SUCCEEDED,
                            "stage": VideoEnhancementJobStage.COMPLETED,
                            "progress_percent": 100,
                            "progress_message": "高清视频已生成，原视频仍保留",
                            "processed_frames": output.frame_count,
                            "total_frames": output.frame_count,
                            "estimated_seconds_remaining": 0,
                            "process_id": None,
                            "result_relative_path": self.workspace.relative(destination),
                            "result_sha256": output.sha256,
                            "result_width": output.width,
                            "result_height": output.height,
                            "result_size_bytes": output.size_bytes,
                            "heartbeat_at": now,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self.repository.save_video_enhancement_job(completed)
                await self._notify(completed)
            except Exception as exc:
                code, message, detail = _error_details(exc)
                async with self._state_lock(job_id):
                    latest = await self.repository.get_video_enhancement_job(job_id) or claimed
                    now = utc_now()
                    interrupted = self._shutdown_requested and (
                        code == "video_enhancement_cancelled" or cancellation.is_set()
                    )
                    cancelled = not interrupted and (
                        code == "video_enhancement_cancelled" or cancellation.is_set()
                    )
                    failed = latest.model_copy(
                        update={
                            "status": (
                                VideoEnhancementJobStatus.INTERRUPTED
                                if interrupted
                                else (
                                    VideoEnhancementJobStatus.CANCELLED
                                    if cancelled
                                    else VideoEnhancementJobStatus.FAILED
                                )
                            ),
                            "progress_message": (
                                "任务因服务停止而中断"
                                if interrupted
                                else ("任务已取消" if cancelled else "视频清晰化未完成")
                            ),
                            "error_code": (
                                "video_enhancement_interrupted" if interrupted else code
                            ),
                            "error_message": (
                                "API 服务已停止，原清晰化任务已中断，请重试。"
                                if interrupted
                                else message
                            ),
                            "technical_detail": detail[-6000:] if detail else None,
                            "process_id": None,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self.repository.save_video_enhancement_job(failed)
                work = self.job_working_root(failed)
                await asyncio.to_thread(shutil.rmtree, work, True)
                await self._notify(failed)
            finally:
                cancellation.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                self._cancellations.pop(job_id, None)

    async def _heartbeat(self, job_id: UUID, cancellation: asyncio.Event) -> None:
        while not cancellation.is_set():
            await asyncio.sleep(5)
            async with self._state_lock(job_id):
                latest = await self.repository.get_video_enhancement_job(job_id)
                if latest is None or latest.status not in ACTIVE_VIDEO_ENHANCEMENT_STATUSES:
                    return
                now = utc_now()
                await self.repository.save_video_enhancement_job(
                    latest.model_copy(update={"heartbeat_at": now, "updated_at": now})
                )

    async def _notify(self, job: VideoEnhancementJob) -> None:
        if self.notification_publisher is None:
            return
        if job.status == VideoEnhancementJobStatus.SUCCEEDED:
            level, status, title = "success", "succeeded", "视频清晰化已完成"
        elif job.status in {
            VideoEnhancementJobStatus.FAILED,
            VideoEnhancementJobStatus.INTERRUPTED,
        }:
            level, status, title = "error", "failed", "视频清晰化未完成"
        elif job.status == VideoEnhancementJobStatus.CANCELLED:
            level, status, title = "info", "cancelled", "视频清晰化已取消"
        else:
            level, status, title = "info", "in_progress", "正在进行视频清晰化"
        try:
            await self.notification_publisher.publish(
                category="video_generation",
                level=level,
                status=status,
                title=title,
                message=job.error_message or job.progress_message,
                event_key=f"video-enhancement-job:{job.id}",
                action_kind="production_shot",
                action_label="查看分镜",
                action_payload={
                    "project_id": str(job.project_id),
                    "shot_plan_id": str(job.shot_plan_id),
                    "candidate_id": str(job.candidate_id),
                },
            )
        except Exception:
            return
