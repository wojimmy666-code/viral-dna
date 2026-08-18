from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from uuid import UUID

from ...notifications import NotificationPublisher
from ..engines.process_runner import (
    DepthProcessCancelled,
    DepthProcessError,
    DepthProcessTimeout,
)
from ..service import DepthControlService, DepthControlServiceError, _filesystem_path
from .contracts import DepthControlJobRepository, DepthControlProjectGateway
from .domain import (
    ACTIVE_DEPTH_JOB_STATUSES,
    DepthControlJob,
    DepthControlJobStage,
    DepthControlJobStatus,
    DepthControlPreset,
)
from .progress import DepthProgressEvent, estimate_remaining_seconds


def utc_now() -> datetime:
    return datetime.now(UTC)


class DepthControlJobServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _error_details(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, DepthProcessTimeout):
        return (
            "depth_inference_timeout",
            "深度推理超时。当前设备可能只支持 CPU，请使用快速模式重试。",
            exc.output_tail or str(exc),
        )
    if isinstance(exc, DepthProcessCancelled):
        return ("depth_job_cancelled", "深度生成已取消", exc.output_tail)
    if isinstance(exc, DepthProcessError):
        detail = exc.output_tail or str(exc)
        lowered = detail.lower()
        if "out of memory" in lowered or "cannot allocate memory" in lowered:
            return ("depth_out_of_memory", "运行内存不足，请使用快速模式重试。", detail)
        return ("depth_process_crashed", "深度处理进程异常退出。", detail)
    if isinstance(exc, DepthControlServiceError):
        return (exc.code, str(exc), str(exc))
    code = str(getattr(exc, "code", "") or "")
    if code:
        return (code, str(exc), str(exc))
    return ("depth_control_generation_failed", "深度生成未完成。", str(exc))


class DepthControlJobService:
    def __init__(
        self,
        repository: DepthControlJobRepository,
        project_gateway: DepthControlProjectGateway,
        depth_controls: DepthControlService,
        *,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.project_gateway = project_gateway
        self.depth_controls = depth_controls
        self.notification_publisher = notification_publisher
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancellations: dict[UUID, asyncio.Event] = {}
        self._state_locks: dict[UUID, asyncio.Lock] = {}
        self._submission_locks: dict[UUID, asyncio.Lock] = {}
        self._worker_slots = asyncio.Semaphore(1)

    def _state_lock(self, job_id: UUID) -> asyncio.Lock:
        return self._state_locks.setdefault(job_id, asyncio.Lock())

    def _submission_lock(self, shot_plan_id: UUID) -> asyncio.Lock:
        return self._submission_locks.setdefault(shot_plan_id, asyncio.Lock())

    async def submit(
        self,
        shot_plan_id: UUID,
        *,
        expected_revision_id: UUID | None,
        preset: DepthControlPreset = DepthControlPreset.AUTO,
        retry_of_job_id: UUID | None = None,
    ) -> DepthControlJob:
        async with self._submission_lock(shot_plan_id):
            return await self._submit_locked(
                shot_plan_id,
                expected_revision_id=expected_revision_id,
                preset=preset,
                retry_of_job_id=retry_of_job_id,
            )

    async def _submit_locked(
        self,
        shot_plan_id: UUID,
        *,
        expected_revision_id: UUID | None,
        preset: DepthControlPreset,
        retry_of_job_id: UUID | None,
    ) -> DepthControlJob:
        active = await self.repository.list_depth_control_jobs(
            shot_plan_id=shot_plan_id,
            active_only=True,
        )
        if active:
            return active[-1]
        try:
            context = await self.project_gateway.prepare_depth_control_job(
                shot_plan_id,
                expected_revision_id,
            )
            profile = await self.depth_controls.generation_profile(preset)
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 422))
            code = str(getattr(exc, "code", "depth_job_submit_failed"))
            raise DepthControlJobServiceError(status_code, code, str(exc)) from exc
        revision_id = context.project.current_revision_id
        if revision_id is None:
            raise DepthControlJobServiceError(
                409,
                "revision_required",
                "当前创作方案没有可用版本",
            )
        profile_engine_id = getattr(profile, "engine_id", "")
        capability = (
            self.depth_controls.capability(profile_engine_id)
            if profile_engine_id
            else self.depth_controls.capability()
        )
        job = DepthControlJob(
            account_id=getattr(profile, "account_id", None),
            project_id=context.project.id,
            shot_plan_id=context.shot.id,
            record_id=context.project.record_id,
            submitted_revision_id=revision_id,
            source_video_id=context.source_video_id,
            source_relative_path=context.source_relative_path,
            source_start_seconds=context.shot.start_seconds,
            source_end_seconds=context.shot.end_seconds,
            source_fingerprint=context.source_fingerprint,
            engine=profile_engine_id or capability.engine,
            engine_version=capability.version,
            model_variant=capability.model_variant,
            requested_execution_preference=getattr(
                profile,
                "requested_execution_preference",
                "auto",
            ),
            selection_reason=getattr(profile, "selection_reason", ""),
            runtime_version=getattr(profile, "runtime_version", None),
            requested_preset=preset,
            effective_preset=profile.preset,
            execution_device=profile.device,
            device_name=profile.device_name,
            target_fps=profile.target_fps,
            input_size=profile.input_size,
            max_resolution=profile.max_resolution,
            timeout_seconds=profile.timeout_seconds,
            retry_of_job_id=retry_of_job_id,
        )
        await self.repository.save_depth_control_job(job)
        await self._notify(job)
        self._schedule(job.id)
        return job

    async def get(self, job_id: UUID) -> DepthControlJob:
        job = await self.repository.get_depth_control_job(job_id)
        if job is None:
            raise DepthControlJobServiceError(
                404,
                "depth_job_not_found",
                "未找到该深度生成任务",
            )
        return job

    async def list_for_shot(
        self,
        shot_plan_id: UUID,
        *,
        active_only: bool = False,
    ) -> list[DepthControlJob]:
        return await self.repository.list_depth_control_jobs(
            shot_plan_id=shot_plan_id,
            active_only=active_only,
        )

    async def cancel(self, job_id: UUID) -> DepthControlJob:
        async with self._state_lock(job_id):
            job = await self.get(job_id)
            if job.status not in ACTIVE_DEPTH_JOB_STATUSES:
                return job
            now = utc_now()
            if job.status == DepthControlJobStatus.QUEUED:
                result = job.model_copy(
                    update={
                        "status": DepthControlJobStatus.CANCELLED,
                        "progress_message": "任务已取消",
                        "error_code": "depth_job_cancelled",
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
            else:
                result = job.model_copy(
                    update={
                        "status": DepthControlJobStatus.CANCELLATION_REQUESTED,
                        "progress_message": "正在停止深度处理进程",
                        "updated_at": now,
                    }
                )
            await self.repository.save_depth_control_job(result)
        if result.status == DepthControlJobStatus.CANCELLED:
            await self._notify(result)
        else:
            self._cancellations.setdefault(job.id, asyncio.Event()).set()
        return result

    async def retry(self, job_id: UUID) -> DepthControlJob:
        previous = await self.get(job_id)
        if previous.status in ACTIVE_DEPTH_JOB_STATUSES:
            return previous
        preset = (
            DepthControlPreset.CPU_FAST
            if previous.error_code in {
                "depth_inference_timeout",
                "depth_out_of_memory",
                "depth_process_crashed",
            }
            else previous.requested_preset
        )
        return await self.submit(
            previous.shot_plan_id,
            expected_revision_id=None,
            preset=preset,
            retry_of_job_id=previous.id,
        )

    async def recover(self) -> None:
        jobs = await self.repository.list_depth_control_jobs()
        now = utc_now()
        for job in jobs:
            if job.status == DepthControlJobStatus.QUEUED:
                self._schedule(job.id)
            elif job.status in {
                DepthControlJobStatus.RUNNING,
                DepthControlJobStatus.CANCELLATION_REQUESTED,
            }:
                interrupted = job.model_copy(
                    update={
                        "status": DepthControlJobStatus.INTERRUPTED,
                        "error_code": "depth_job_interrupted",
                        "error_message": "API 服务重启，原深度任务已中断，请重试。",
                        "progress_message": "任务因服务重启而中断",
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
                await self.repository.save_depth_control_job(interrupted)
                await self._notify(interrupted)

    async def shutdown(self) -> None:
        for event in self._cancellations.values():
            event.set()
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
            claimed = await self.repository.claim_depth_control_job(job_id)
            if claimed is None:
                return
            cancellation = self._cancellations.setdefault(job_id, asyncio.Event())
            heartbeat = asyncio.create_task(self._heartbeat(job_id, cancellation))
            try:
                await self._notify(claimed)

                async def report(event: DepthProgressEvent) -> None:
                    async with self._state_lock(job_id):
                        latest = await self.get(job_id)
                        if latest.status not in ACTIVE_DEPTH_JOB_STATUSES:
                            return
                        now = utc_now()
                        processed = (
                            event.processed_frames
                            if event.processed_frames is not None
                            else latest.processed_frames
                        )
                        total = (
                            event.total_frames
                            if event.total_frames is not None
                            else latest.total_frames
                        )
                        stage_changed = latest.stage != event.stage
                        updated = latest.model_copy(
                            update={
                                "stage": event.stage,
                                "progress_percent": max(
                                    latest.progress_percent,
                                    event.percent,
                                ),
                                "progress_message": event.message,
                                "processed_frames": processed,
                                "total_frames": total,
                                "estimated_seconds_remaining": estimate_remaining_seconds(
                                    started_at=latest.started_at,
                                    processed_frames=processed,
                                    total_frames=total,
                                ),
                                "process_id": event.process_id or latest.process_id,
                                "heartbeat_at": now,
                                "updated_at": now,
                            }
                        )
                        await self.repository.save_depth_control_job(updated)
                    if stage_changed:
                        await self._notify(updated)

                asset = await self.depth_controls.generate_job(
                    claimed,
                    cancellation=cancellation,
                    progress=report,
                )
                async with self._state_lock(job_id):
                    latest = await self.get(job_id)
                    revision_id = await self.project_gateway.commit_depth_control_job(
                        latest,
                        asset,
                    )
                    now = utc_now()
                    completed = latest.model_copy(
                        update={
                            "status": DepthControlJobStatus.SUCCEEDED,
                            "stage": DepthControlJobStage.COMPLETED,
                            "progress_percent": 100,
                            "progress_message": "全场景深度视频已生成",
                            "processed_frames": latest.total_frames,
                            "estimated_seconds_remaining": 0,
                            "result_asset_id": asset.id,
                            "result_revision_id": revision_id,
                            "process_id": None,
                            "heartbeat_at": now,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self.repository.save_depth_control_job(completed)
                await self.depth_controls.write_job_diagnostics(completed)
                await self._notify(completed)
            except Exception as exc:
                code, message, detail = _error_details(exc)
                async with self._state_lock(job_id):
                    latest = await self.repository.get_depth_control_job(job_id) or claimed
                    now = utc_now()
                    cancelled = code == "depth_job_cancelled" or cancellation.is_set()
                    failed = latest.model_copy(
                        update={
                            "status": (
                                DepthControlJobStatus.CANCELLED
                                if cancelled
                                else DepthControlJobStatus.FAILED
                            ),
                            "progress_message": (
                                "任务已取消" if cancelled else "深度生成未完成"
                            ),
                            "error_code": code,
                            "error_message": message,
                            "technical_detail": detail[-6000:] if detail else None,
                            "process_id": None,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self.repository.save_depth_control_job(failed)
                await self.depth_controls.write_job_diagnostics(
                    failed,
                    technical_detail=detail,
                )
                work = self.depth_controls.job_root(failed) / "work"
                await asyncio.to_thread(shutil.rmtree, _filesystem_path(work), True)
                await self._notify(failed)
            finally:
                cancellation.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                self._cancellations.pop(job_id, None)

    async def _heartbeat(
        self,
        job_id: UUID,
        cancellation: asyncio.Event,
    ) -> None:
        while not cancellation.is_set():
            await asyncio.sleep(5)
            async with self._state_lock(job_id):
                latest = await self.repository.get_depth_control_job(job_id)
                if latest is None or latest.status not in ACTIVE_DEPTH_JOB_STATUSES:
                    return
                now = utc_now()
                await self.repository.save_depth_control_job(
                    latest.model_copy(update={"heartbeat_at": now, "updated_at": now})
                )

    async def _notify(self, job: DepthControlJob) -> None:
        if self.notification_publisher is None:
            return
        if job.status == DepthControlJobStatus.SUCCEEDED:
            level, status, title = "success", "succeeded", "全场景深度视频已生成"
        elif job.status in {
            DepthControlJobStatus.FAILED,
            DepthControlJobStatus.INTERRUPTED,
        }:
            level, status, title = "error", "failed", "全场景深度生成失败"
        elif job.status == DepthControlJobStatus.CANCELLED:
            level, status, title = "info", "cancelled", "全场景深度生成已取消"
        else:
            level, status, title = "info", "in_progress", "正在生成全场景深度"
        try:
            await self.notification_publisher.publish(
                category="video_generation",
                level=level,
                status=status,
                title=title,
                message=job.error_message or job.progress_message,
                event_key=f"depth-control-job:{job.id}",
                action_kind="production_shot",
                action_label="查看分镜",
                action_payload={
                    "project_id": str(job.project_id),
                    "shot_plan_id": str(job.shot_plan_id),
                },
            )
        except Exception:
            return
