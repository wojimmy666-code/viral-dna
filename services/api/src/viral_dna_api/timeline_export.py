from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from .media import MediaProcessingError, MediaProcessor
from .models import (
    ProductionProject,
    ProductionStep,
    ProductionTimeline,
    TimelineExportQuality,
    TimelineExportResolution,
    TimelineExportSubtitleMode,
    TimelineExportValidationSummary,
    TimelineFinalRenderCreate,
    TimelineRenderJob,
    TimelineRenderJobList,
    TimelineRenderKind,
    TimelineRenderStatus,
    utc_now,
)
from .notifications import NotificationPublisher
from .timeline_render import (
    TimelinePreviewRenderer,
    TimelineRenderError,
    TimelineRenderProfile,
)
from .workspace import WorkspaceError, WorkspaceManager


class ExportRepository(Protocol):
    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...


class TimelineProvider(Protocol):
    async def get_timeline(self, project_id: UUID) -> ProductionTimeline: ...

    def validate_timeline(self, timeline: ProductionTimeline): ...


class FinalRenderer(Protocol):
    async def render(
        self,
        timeline: ProductionTimeline,
        output_root: Path,
        *,
        source_audio_path: Path | None,
        progress: Callable[[int], Awaitable[None]],
        is_cancelled: Callable[[], bool],
        profile: TimelineRenderProfile,
    ) -> tuple[Path, Path | None]: ...


class TimelineExportServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> TimelineExportServiceError:
    return TimelineExportServiceError(status_code, code, message)


def _even(value: float) -> int:
    return max(2, round(value) // 2 * 2)


def export_dimensions(
    width: int,
    height: int,
    resolution: TimelineExportResolution,
) -> tuple[int, int]:
    if resolution == TimelineExportResolution.PROJECT:
        return _even(width), _even(height)
    short_edge = 720 if resolution == TimelineExportResolution.P720 else 1080
    if width == height:
        return short_edge, short_edge
    if width < height:
        return short_edge, _even(height * short_edge / width)
    return _even(width * short_edge / height), short_edge


def export_profile(
    width: int,
    height: int,
    *,
    subtitle_mode: TimelineExportSubtitleMode,
    quality: TimelineExportQuality,
) -> TimelineRenderProfile:
    high = quality == TimelineExportQuality.HIGH
    return TimelineRenderProfile(
        width=width,
        height=height,
        video_preset="slow" if high else "medium",
        video_crf=18 if high else 23,
        audio_bitrate="192k" if high else "160k",
        output_filename="final.mp4",
        subtitle_filename="subtitles.vtt",
        subtitle_mode=subtitle_mode.value,
        operation_label="最终成片",
        error_prefix="final",
        timeout_seconds=3600,
    )


def _enabled_subtitle_count(timeline: ProductionTimeline) -> int:
    enabled_clip_ids = {clip.id for clip in timeline.clips if clip.enabled}
    return sum(
        1
        for cue in timeline.subtitle_cues
        if cue.enabled and (cue.clip_id is None or cue.clip_id in enabled_clip_ids)
    )


def _safe_download_name(project: ProductionProject, timeline: ProductionTimeline) -> str:
    stem = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", project.name, flags=re.UNICODE).strip("-")
    stem = stem[:80] or "ViralDNA成片"
    return f"{stem}-时间线v{timeline.revision_number}.mp4"


class TimelineExportValidator:
    def __init__(self, media_processor: MediaProcessor | None = None) -> None:
        self.media_processor = media_processor or MediaProcessor()

    async def validate(
        self,
        output_path: Path,
        timeline: ProductionTimeline,
        *,
        expected_width: int,
        expected_height: int,
        subtitle_mode: TimelineExportSubtitleMode,
    ) -> TimelineExportValidationSummary:
        try:
            metadata = await self.media_processor.probe(output_path)
        except MediaProcessingError as exc:
            raise TimelineRenderError("final_probe_failed", f"最终成片校验失败：{exc}") from exc

        errors: list[str] = []
        warnings: list[str] = []
        duration_tolerance = max(0.25, timeline.duration_seconds * 0.02)
        if abs(metadata.duration_seconds - timeline.duration_seconds) > duration_tolerance:
            errors.append(
                "成片时长与时间线不一致："
                f"预计 {timeline.duration_seconds:.2f} 秒，实际 {metadata.duration_seconds:.2f} 秒"
            )
        if (metadata.width, metadata.height) != (expected_width, expected_height):
            errors.append(
                f"成片尺寸应为 {expected_width} × {expected_height}，"
                f"实际为 {metadata.width} × {metadata.height}"
            )
        if metadata.video_codec not in {"h264", "avc1"}:
            errors.append(f"成片视频编码不是 H.264：{metadata.video_codec}")

        expects_audio = (
            timeline.audio_track.enabled and timeline.audio_track.strategy != "muted"
        )
        if expects_audio and not metadata.has_audio:
            errors.append("时间线启用了原音轨，但成片中没有音频流")
        if not expects_audio and metadata.has_audio:
            warnings.append("时间线设置为静音，但成片中检测到音频流")

        subtitle_count = _enabled_subtitle_count(timeline)
        embedded_subtitles = bool(metadata.subtitle_streams)
        if (
            subtitle_count
            and subtitle_mode == TimelineExportSubtitleMode.EMBEDDED
            and not embedded_subtitles
        ):
            errors.append("选择了内嵌字幕，但成片中没有字幕流")
        if not subtitle_count and subtitle_mode != TimelineExportSubtitleMode.NONE:
            warnings.append("当前时间线没有启用字幕，字幕模式不会产生可见效果")

        has_subtitles = embedded_subtitles or (
            subtitle_count > 0 and subtitle_mode == TimelineExportSubtitleMode.BURNED
        )
        return TimelineExportValidationSummary(
            valid=not errors,
            expected_duration_seconds=timeline.duration_seconds,
            duration_seconds=metadata.duration_seconds,
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
            has_audio=metadata.has_audio,
            has_subtitles=has_subtitles,
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            errors=errors,
            warnings=warnings,
        )


class TimelineExportService:
    def __init__(
        self,
        repository: ExportRepository,
        workspace: WorkspaceManager,
        timeline_provider: TimelineProvider,
        media_resolver,
        *,
        renderer: FinalRenderer | None = None,
        validator: TimelineExportValidator | None = None,
        media_processor: MediaProcessor | None = None,
        notification_publisher: NotificationPublisher | None = None,
        on_export_succeeded: Callable[[UUID, UUID, UUID], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.timeline_provider = timeline_provider
        self.media_processor = media_processor or MediaProcessor()
        self.renderer = renderer or TimelinePreviewRenderer(
            media_resolver,
            self.media_processor,
        )
        self.validator = validator or TimelineExportValidator(self.media_processor)
        self.notification_publisher = notification_publisher
        self.on_export_succeeded = on_export_succeeded
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancellations: set[UUID] = set()
        self._project_locks: dict[UUID, asyncio.Lock] = {}

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def create_export(
        self,
        project_id: UUID,
        payload: TimelineFinalRenderCreate,
    ) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        timeline = await self.timeline_provider.get_timeline(project_id)
        if timeline.revision_id != payload.expected_revision_id:
            raise _fail(409, "timeline_revision_conflict", "时间线已更新，请刷新后重新导出")
        validation = self.timeline_provider.validate_timeline(timeline)
        if not validation.valid:
            raise _fail(422, "timeline_invalid", "；".join(validation.errors))

        width, height = export_dimensions(
            timeline.output_width,
            timeline.output_height,
            payload.resolution,
        )
        fingerprint = self._request_fingerprint(timeline, payload, width, height)
        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            existing = next(
                (
                    item
                    for item in (await self.list_exports(project_id)).items
                    if item.request_fingerprint == fingerprint
                    and item.status in {
                        TimelineRenderStatus.QUEUED,
                        TimelineRenderStatus.RUNNING,
                    }
                ),
                None,
            )
            if existing is not None:
                return existing
            job = TimelineRenderJob(
                project_id=project.id,
                timeline_revision_id=timeline.revision_id,
                kind=TimelineRenderKind.FINAL,
                preview_width=width,
                preview_height=height,
                resolution=payload.resolution,
                subtitle_mode=payload.subtitle_mode,
                quality=payload.quality,
                request_fingerprint=fingerprint,
                output_filename=_safe_download_name(project, timeline),
            )
            await asyncio.to_thread(self._write_job, project, job)

        await self._publish_notification(project, job)
        task = asyncio.create_task(self._run_export(project, timeline, job))
        self._tasks[job.id] = task
        task.add_done_callback(lambda _task, job_id=job.id: self._tasks.pop(job_id, None))
        return job

    async def list_exports(self, project_id: UUID) -> TimelineRenderJobList:
        project = await self._require_project(project_id)
        jobs = await asyncio.to_thread(self._read_jobs, project)
        normalized: list[TimelineRenderJob] = []
        for job in jobs:
            if (
                job.status in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}
                and job.id not in self._tasks
            ):
                job = job.model_copy(
                    update={
                        "status": TimelineRenderStatus.FAILED,
                        "error_code": "render_interrupted",
                        "error_message": "服务重启导致高清导出中断，请重新导出",
                        "completed_at": utc_now(),
                    }
                )
                await asyncio.to_thread(self._write_job, project, job)
            normalized.append(job)
        return TimelineRenderJobList(
            items=sorted(normalized, key=lambda item: item.created_at, reverse=True)
        )

    async def get_export(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        job = await asyncio.to_thread(self._read_job, project, job_id)
        if job is None or job.kind != TimelineRenderKind.FINAL:
            raise _fail(404, "export_job_missing", "高清导出任务不存在")
        if (
            job.status in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}
            and job.id not in self._tasks
        ):
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.FAILED,
                    "error_code": "render_interrupted",
                    "error_message": "服务重启导致高清导出中断，请重新导出",
                    "completed_at": utc_now(),
                }
            )
            await asyncio.to_thread(self._write_job, project, job)
        return job

    async def cancel_export(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        job = await self.get_export(project_id, job_id)
        if job.status not in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}:
            raise _fail(409, "export_job_not_cancellable", "当前导出任务已结束，不能取消")
        self._cancellations.add(job.id)
        job = job.model_copy(update={"cancellation_requested": True})
        await asyncio.to_thread(self._write_job, project, job)
        return job

    async def resolve_artifact(
        self,
        project_id: UUID,
        job_id: UUID,
        artifact: str,
    ) -> tuple[Path, str, str]:
        project = await self._require_project(project_id)
        job = await self.get_export(project_id, job_id)
        if job.status != TimelineRenderStatus.SUCCEEDED:
            raise _fail(404, "export_output_missing", "高清成片尚不可用")
        mapping = {
            "content": (job.output_relative_path, "video/mp4", job.output_filename or "成片.mp4"),
            "subtitles": (job.subtitle_relative_path, "text/vtt; charset=utf-8", "subtitles.vtt"),
            "cover": (job.cover_relative_path, "image/jpeg", "cover.jpg"),
            "manifest": (
                job.manifest_relative_path,
                "application/json; charset=utf-8",
                "manifest.json",
            ),
        }
        if artifact not in mapping:
            raise _fail(404, "export_artifact_unknown", "未知的导出产物")
        relative_path, media_type, filename = mapping[artifact]
        if relative_path is None:
            raise _fail(404, "export_artifact_missing", "导出产物不存在")
        try:
            resolved = self.workspace.resolve(relative_path).resolve()
            export_root = self.workspace.production_paths(
                project.record_id,
                project.id,
            ).exports.resolve()
            resolved.relative_to(export_root)
        except (WorkspaceError, ValueError) as exc:
            raise _fail(409, "export_artifact_invalid", "导出产物路径无效") from exc
        if not resolved.is_file():
            raise _fail(404, "export_artifact_missing", "导出产物文件不存在")
        return resolved, media_type, filename

    async def _run_export(
        self,
        project: ProductionProject,
        timeline: ProductionTimeline,
        initial_job: TimelineRenderJob,
    ) -> None:
        job = initial_job.model_copy(
            update={
                "status": TimelineRenderStatus.RUNNING,
                "progress_percent": 1,
                "started_at": utc_now(),
            }
        )
        await asyncio.to_thread(self._write_job, project, job)
        await self._publish_notification(project, job)

        async def update_progress(value: int) -> None:
            nonlocal job
            next_value = min(88, max(job.progress_percent, round(value * 0.88)))
            if next_value <= job.progress_percent:
                return
            job = job.model_copy(update={"progress_percent": next_value})
            await asyncio.to_thread(self._write_job, project, job)

        try:
            output_root = (
                self.workspace.production_paths(project.record_id, project.id).exports
                / str(job.id)
            )
            source_audio_path = self._source_audio_path(project, timeline)
            if (
                timeline.audio_track.enabled
                and timeline.audio_track.strategy != "muted"
                and source_audio_path is None
            ):
                raise TimelineRenderError(
                    "source_audio_missing",
                    "原视频音轨文件不存在，请切换为静音或重新分析源视频",
                )
            profile = export_profile(
                job.preview_width,
                job.preview_height,
                subtitle_mode=job.subtitle_mode or TimelineExportSubtitleMode.BURNED,
                quality=job.quality or TimelineExportQuality.HIGH,
            )
            output_path, subtitle_path = await self.renderer.render(
                timeline,
                output_root,
                source_audio_path=source_audio_path,
                progress=update_progress,
                is_cancelled=lambda: job.id in self._cancellations,
                profile=profile,
            )
            self._require_not_cancelled(job.id)
            job = job.model_copy(update={"progress_percent": 90})
            await asyncio.to_thread(self._write_job, project, job)
            cover_path = await self._extract_cover(output_path, output_root / "cover.jpg", job.id)
            summary = await self.validator.validate(
                output_path,
                timeline,
                expected_width=job.preview_width,
                expected_height=job.preview_height,
                subtitle_mode=job.subtitle_mode or TimelineExportSubtitleMode.BURNED,
            )
            job = job.model_copy(
                update={"progress_percent": 96, "validation_summary": summary}
            )
            await asyncio.to_thread(self._write_job, project, job)
            if not summary.valid:
                raise TimelineRenderError(
                    "final_validation_failed",
                    "；".join(summary.errors) or "最终成片校验未通过",
                )
            manifest_path = output_root / "manifest.json"
            manifest_payload = self._manifest_payload(
                project,
                timeline,
                job,
                output_path,
                subtitle_path,
                cover_path,
                summary,
            )
            await asyncio.to_thread(self._write_json_atomic, manifest_path, manifest_payload)
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.SUCCEEDED,
                    "progress_percent": 100,
                    "output_relative_path": self.workspace.relative(output_path),
                    "subtitle_relative_path": (
                        self.workspace.relative(subtitle_path) if subtitle_path else None
                    ),
                    "cover_relative_path": self.workspace.relative(cover_path),
                    "manifest_relative_path": self.workspace.relative(manifest_path),
                    "output_url": f"/api/v1/productions/{project.id}/export-jobs/{job.id}/content",
                    "subtitle_url": (
                        f"/api/v1/productions/{project.id}/export-jobs/{job.id}/subtitles"
                        if subtitle_path
                        else None
                    ),
                    "cover_url": f"/api/v1/productions/{project.id}/export-jobs/{job.id}/cover",
                    "manifest_url": (
                        f"/api/v1/productions/{project.id}/export-jobs/{job.id}/manifest"
                    ),
                    "file_size_bytes": summary.size_bytes,
                    "sha256": summary.sha256,
                    "completed_at": utc_now(),
                }
            )
            if self.on_export_succeeded is not None:
                await self.on_export_succeeded(project.id, timeline.revision_id, job.id)
        except TimelineRenderError as exc:
            cancelled = exc.code == "render_cancelled"
            job = job.model_copy(
                update={
                    "status": (
                        TimelineRenderStatus.CANCELLED
                        if cancelled
                        else TimelineRenderStatus.FAILED
                    ),
                    "error_code": exc.code,
                    "error_message": str(exc),
                    "completed_at": utc_now(),
                }
            )
        except asyncio.CancelledError:
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.CANCELLED,
                    "error_code": "service_shutdown",
                    "error_message": "服务关闭，高清导出已停止",
                    "completed_at": utc_now(),
                }
            )
        except Exception as exc:  # pragma: no cover - asynchronous safety boundary
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.FAILED,
                    "error_code": "final_render_failed",
                    "error_message": f"最终成片生成失败：{exc}",
                    "completed_at": utc_now(),
                }
            )
        finally:
            self._cancellations.discard(job.id)
            await asyncio.to_thread(self._write_job, project, job)
            await self._publish_notification(project, job)

    async def _extract_cover(self, source: Path, output: Path, job_id: UUID) -> Path:
        self._require_not_cancelled(job_id)
        media = self.media_processor
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            "0.1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise TimelineRenderError("final_cover_timeout", "成片封面提取超时") from exc
        output_exists = await asyncio.to_thread(output.is_file)
        if process.returncode != 0 or not output_exists:
            detail = stderr.decode("utf-8", errors="replace").strip()[-800:]
            raise TimelineRenderError(
                "final_cover_failed",
                f"成片封面提取失败：{detail or 'FFmpeg 未返回详细信息'}",
            )
        self._require_not_cancelled(job_id)
        return output

    async def _publish_notification(
        self,
        project: ProductionProject,
        job: TimelineRenderJob,
    ) -> None:
        if self.notification_publisher is None:
            return
        if job.status == TimelineRenderStatus.QUEUED:
            level, status = "info", "in_progress"
            title, message = "高清成片已排队", "最终导出正在等待渲染。"
        elif job.status == TimelineRenderStatus.RUNNING:
            level, status = "info", "in_progress"
            title, message = "正在导出高清成片", "完成后会在消息中心通知你。"
        elif job.status == TimelineRenderStatus.SUCCEEDED:
            level, status = "success", "succeeded"
            title, message = "高清成片已导出", "成片已经校验并归档，可以下载。"
        elif job.status == TimelineRenderStatus.CANCELLED:
            level, status = "warning", "cancelled"
            title, message = "高清导出已取消", "本次任务没有生成可用成片。"
        else:
            level, status = "error", "failed"
            title, message = "高清导出失败", job.error_message or "请稍后重试。"
        try:
            await self.notification_publisher.publish(
                category="export",
                level=level,
                status=status,
                title=title,
                message=message,
                event_key=f"timeline-export:{job.id}",
                action_kind="production_shot",
                action_label="查看导出",
                action_payload={
                    "record_id": str(project.record_id),
                    "project_id": str(project.id),
                    "step": "export",
                    "export_job_id": str(job.id),
                },
            )
        except Exception:
            return

    async def _require_project(self, project_id: UUID) -> ProductionProject:
        project = await self.repository.get_production_project(project_id)
        if project is None:
            raise _fail(404, "production_missing", "创作方案不存在")
        if project.active_step not in {ProductionStep.EDITING, ProductionStep.EXPORT}:
            raise _fail(409, "export_not_available", "请先完成剪辑合成")
        return project

    def _source_audio_path(
        self,
        project: ProductionProject,
        timeline: ProductionTimeline,
    ) -> Path | None:
        if not timeline.audio_track.source_audio_url:
            return None
        path = (
            self.workspace.analysis_root(project.record_id, project.base_analysis_id)
            / "audio.wav"
        )
        return path if path.is_file() else None

    def _request_fingerprint(
        self,
        timeline: ProductionTimeline,
        payload: TimelineFinalRenderCreate,
        width: int,
        height: int,
    ) -> str:
        serialized = json.dumps(
            {
                "timeline_revision_id": str(timeline.revision_id),
                "resolution": payload.resolution.value,
                "subtitle_mode": payload.subtitle_mode.value,
                "quality": payload.quality.value,
                "width": width,
                "height": height,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def _manifest_payload(
        self,
        project: ProductionProject,
        timeline: ProductionTimeline,
        job: TimelineRenderJob,
        output_path: Path,
        subtitle_path: Path | None,
        cover_path: Path,
        summary: TimelineExportValidationSummary,
    ) -> dict[str, object]:
        return {
            "schema_version": "viral-dna-final-export/v1",
            "export_id": str(job.id),
            "project_id": str(project.id),
            "record_id": str(project.record_id),
            "timeline_revision_id": str(timeline.revision_id),
            "timeline_revision_number": timeline.revision_number,
            "created_at": utc_now().isoformat(),
            "settings": {
                "resolution": job.resolution.value if job.resolution else None,
                "subtitle_mode": job.subtitle_mode.value if job.subtitle_mode else None,
                "quality": job.quality.value if job.quality else None,
                "width": job.preview_width,
                "height": job.preview_height,
                "fps": timeline.fps,
            },
            "artifacts": {
                "video": self.workspace.relative(output_path),
                "subtitles": (
                    self.workspace.relative(subtitle_path) if subtitle_path else None
                ),
                "cover": self.workspace.relative(cover_path),
            },
            "validation": summary.model_dump(mode="json"),
        }

    def _job_path(self, project: ProductionProject, job_id: UUID) -> Path:
        return (
            self.workspace.production_paths(project.record_id, project.id).exports
            / "jobs"
            / f"{job_id}.json"
        )

    def _write_job(self, project: ProductionProject, job: TimelineRenderJob) -> None:
        self._write_json_atomic(
            self._job_path(project, job.id),
            job.model_dump(mode="json"),
        )

    def _read_job(
        self,
        project: ProductionProject,
        job_id: UUID,
    ) -> TimelineRenderJob | None:
        path = self._job_path(project, job_id)
        if not path.is_file():
            return None
        try:
            return TimelineRenderJob.model_validate_json(path.read_text("utf-8-sig"))
        except (OSError, ValidationError) as exc:
            raise _fail(409, "export_job_invalid", "高清导出任务记录损坏") from exc

    def _read_jobs(self, project: ProductionProject) -> list[TimelineRenderJob]:
        root = self._job_path(project, uuid4()).parent
        if not root.is_dir():
            return []
        jobs: list[TimelineRenderJob] = []
        for path in root.glob("*.json"):
            try:
                job = TimelineRenderJob.model_validate_json(path.read_text("utf-8-sig"))
            except (OSError, ValidationError):
                continue
            if job.project_id == project.id and job.kind == TimelineRenderKind.FINAL:
                jobs.append(job)
        return jobs

    def _require_not_cancelled(self, job_id: UUID) -> None:
        if job_id in self._cancellations:
            raise TimelineRenderError("render_cancelled", "高清导出已取消")

    @staticmethod
    def _write_json_atomic(destination: Path, payload: object) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".tmp-{uuid4().hex[:8]}"
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        try:
            temporary.write_bytes(serialized)
            os.replace(temporary, destination)
        except OSError as exc:
            raise _fail(507, "workspace_write_failed", "无法写入高清导出文件") from exc
        finally:
            temporary.unlink(missing_ok=True)
