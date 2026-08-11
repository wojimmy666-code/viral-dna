from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from .models import (
    EditingHandoffClip,
    EditingHandoffManifest,
    ProductionProject,
    ProductionStep,
    ProductionTimeline,
    TimelineAudioTrack,
    TimelineBackgroundAudioTrack,
    TimelineChangeKind,
    TimelineClip,
    TimelineClipInspectionRequest,
    TimelinePreviewCreate,
    TimelineRenderJob,
    TimelineRenderStatus,
    TimelineRestoreRequest,
    TimelineRevision,
    TimelineRevisionList,
    TimelineSubtitleCue,
    TimelineTransitionKind,
    TimelineUpdateRequest,
    TimelineValidationResponse,
    utc_now,
)
from .notifications import NotificationPublisher
from .production_media import ProductionVideoInspectionError, ProductionVideoInspector
from .timeline_render import TimelinePreviewRenderer, TimelineRenderError, preview_dimensions
from .workspace import WorkspaceError, WorkspaceManager


class TimelineRepository(Protocol):
    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...

    async def get_generation_candidate(self, candidate_id: UUID): ...


class EditingHandoffProvider(Protocol):
    async def get_editing_handoff(self, project_id: UUID) -> EditingHandoffManifest: ...

    async def resolve_candidate_content(
        self,
        candidate_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]: ...


class PreviewRenderer(Protocol):
    async def render(
        self,
        timeline: ProductionTimeline,
        output_root: Path,
        *,
        source_audio_path: Path | None,
        background_audio_path: Path | None,
        progress: Callable[[int], Awaitable[None]],
        is_cancelled: Callable[[], bool],
    ) -> tuple[Path, Path | None]: ...


class TimelineServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> TimelineServiceError:
    return TimelineServiceError(status_code, code, message)


class TimelineService:
    def __init__(
        self,
        repository: TimelineRepository,
        workspace: WorkspaceManager,
        handoff_provider: EditingHandoffProvider,
        *,
        renderer: PreviewRenderer | None = None,
        video_inspector: ProductionVideoInspector | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.handoff_provider = handoff_provider
        self.renderer = renderer or TimelinePreviewRenderer(handoff_provider)
        self.video_inspector = video_inspector or ProductionVideoInspector()
        self.notification_publisher = notification_publisher
        self._project_locks: dict[UUID, asyncio.Lock] = {}
        self._render_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._render_cancellations: set[UUID] = set()

    async def shutdown(self) -> None:
        tasks = list(self._render_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._render_tasks.clear()

    async def get_timeline(self, project_id: UUID) -> ProductionTimeline:
        project = await self._require_project(project_id)
        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            timeline = await asyncio.to_thread(self._read_current_timeline, project)
            if timeline is not None:
                return await self._synchronize_timeline_with_handoff(project, timeline)
            return await self._initialize_timeline(project)

    async def update_timeline(
        self,
        project_id: UUID,
        payload: TimelineUpdateRequest,
    ) -> ProductionTimeline:
        project = await self._require_project(project_id)
        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            current = await self._require_current_timeline(project)
            self._require_revision(current, payload.expected_revision_id)
            next_timeline = self._apply_update(current, payload)
            validation = self.validate_timeline(next_timeline)
            if not validation.valid:
                raise _fail(422, "timeline_invalid", "；".join(validation.errors))
            next_timeline = next_timeline.model_copy(
                update={
                    "validation_messages": validation.errors,
                    "warning_messages": validation.warnings,
                }
            )
            return await asyncio.to_thread(
                self._save_revision,
                project,
                next_timeline,
                TimelineChangeKind.CLIPS_UPDATED,
                payload.summary,
                current.revision_id,
            )

    async def validate_current(self, project_id: UUID) -> TimelineValidationResponse:
        timeline = await self.get_timeline(project_id)
        return self.validate_timeline(timeline)

    async def inspect_clip(
        self,
        project_id: UUID,
        clip_id: UUID,
        payload: TimelineClipInspectionRequest,
    ) -> ProductionTimeline:
        project = await self._require_project(project_id)
        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            current = await self._require_current_timeline(project)
            self._require_revision(current, payload.expected_revision_id)
            source_clip = next((item for item in current.clips if item.id == clip_id), None)
            if source_clip is None:
                raise _fail(404, "timeline_clip_missing", "要质检的时间线片段不存在")

            candidate = await self.repository.get_generation_candidate(source_clip.candidate_id)
            source_path, _ = await self.handoff_provider.resolve_candidate_content(
                source_clip.candidate_id
            )
            revision_id = uuid4()
            cover_path = (
                self._timeline_root(project)
                / "covers"
                / str(source_clip.id)
                / str(revision_id)
                / "cover.webp"
            )
            cover_timestamp = (
                source_clip.cover_timestamp_seconds
                if source_clip.cover_timestamp_seconds is not None
                else source_clip.trim_in_seconds
                + (source_clip.trim_out_seconds - source_clip.trim_in_seconds) / 2
            )
            try:
                inspection = await self.video_inspector.inspect(
                    source_path,
                    cover_path,
                    cover_timestamp_seconds=cover_timestamp,
                    expected_width=getattr(candidate, "width", None),
                    expected_height=getattr(candidate, "height", None),
                    expected_duration_seconds=getattr(candidate, "duration_seconds", None),
                )
            except ProductionVideoInspectionError as exc:
                raise _fail(409, exc.code, str(exc)) from exc

            warnings = [
                str(item)
                for item in inspection.quality_report.get("warnings", [])
                if str(item).strip()
            ]
            next_clips = [
                item.model_copy(
                    update={
                        "cover_url": (
                            f"/api/v1/productions/{project.id}/timeline/clips/"
                            f"{item.id}/cover?v={revision_id}"
                        ),
                        "cover_relative_path": self.workspace.relative(cover_path),
                        "cover_timestamp_seconds": inspection.cover_timestamp_seconds,
                        "quality_status": inspection.quality_status,
                        "quality_report": inspection.quality_report,
                        "blocker_messages": [],
                        "warning_messages": warnings,
                    }
                )
                if item.id == source_clip.id
                else item
                for item in current.clips
            ]
            next_timeline = current.model_copy(
                update={
                    "revision_id": revision_id,
                    "revision_number": current.revision_number + 1,
                    "clips": next_clips,
                    "last_preview_job_id": None,
                    "last_export_job_id": None,
                    "updated_at": utc_now(),
                }
            )
            validation = self.validate_timeline(next_timeline)
            next_timeline = next_timeline.model_copy(
                update={
                    "validation_messages": validation.errors,
                    "warning_messages": validation.warnings,
                }
            )
            return await asyncio.to_thread(
                self._save_revision,
                project,
                next_timeline,
                TimelineChangeKind.CLIPS_UPDATED,
                f"更新分镜 {source_clip.shot_index} 的封面与基础质检",
                current.revision_id,
            )

    async def resolve_clip_cover(
        self,
        project_id: UUID,
        clip_id: UUID,
    ) -> tuple[Path, str]:
        project = await self._require_project(project_id)
        timeline = await self.get_timeline(project_id)
        clip = next((item for item in timeline.clips if item.id == clip_id), None)
        if clip is None or not clip.cover_relative_path:
            raise _fail(404, "timeline_clip_cover_missing", "当前片段尚未生成剪辑封面")
        try:
            path = self.workspace.resolve(clip.cover_relative_path).resolve()
            path.relative_to(self._timeline_root(project).resolve())
        except (WorkspaceError, ValueError) as exc:
            raise _fail(409, "timeline_clip_cover_invalid", "片段封面路径无效") from exc
        if not path.is_file():
            raise _fail(404, "timeline_clip_cover_missing", "片段封面文件不存在")
        return path, "image/webp"

    async def set_background_audio(
        self,
        project_id: UUID,
        expected_revision_id: UUID,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> ProductionTimeline:
        project = await self._require_project(project_id)
        suffix = Path(filename or "background-audio").suffix.lower()
        allowed_suffixes = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        if suffix not in allowed_suffixes:
            raise _fail(
                415,
                "background_audio_type_invalid",
                "仅支持 MP3、WAV、M4A、AAC、OGG 或 FLAC 音频",
            )
        if content_type and not (
            content_type.startswith("audio/")
            or content_type in {"application/ogg", "application/octet-stream"}
        ):
            raise _fail(415, "background_audio_type_invalid", "上传文件不是受支持的音频")
        if not content:
            raise _fail(422, "background_audio_empty", "上传的音频文件为空")
        if len(content) > 100 * 1024 * 1024:
            raise _fail(413, "background_audio_too_large", "附加音频不能超过 100 MB")

        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            current = await self._require_current_timeline(project)
            self._require_revision(current, expected_revision_id)
            revision_id = uuid4()
            destination = (
                self._timeline_root(project)
                / "audio"
                / f"{revision_id}{suffix}"
            )
            await asyncio.to_thread(self._write_bytes_atomic, destination, content)
            track = TimelineBackgroundAudioTrack(
                source_relative_path=self.workspace.relative(destination),
                source_url=(
                    f"/api/v1/productions/{project.id}/timeline/background-audio"
                    f"?v={revision_id}"
                ),
                name=Path(filename).name[:240] or f"背景音频{suffix}",
                enabled=True,
                volume=current.background_audio_track.volume,
                loop=True,
            )
            next_timeline = current.model_copy(
                update={
                    "revision_id": revision_id,
                    "revision_number": current.revision_number + 1,
                    "background_audio_track": track,
                    "last_preview_job_id": None,
                    "last_export_job_id": None,
                    "updated_at": utc_now(),
                }
            )
            return await asyncio.to_thread(
                self._save_revision,
                project,
                next_timeline,
                TimelineChangeKind.TRACKS_UPDATED,
                f"添加附加音轨：{track.name}",
                current.revision_id,
            )

    async def resolve_background_audio(self, project_id: UUID) -> tuple[Path, str]:
        project = await self._require_project(project_id)
        timeline = await self.get_timeline(project_id)
        path = self._background_audio_path(project, timeline)
        if path is None:
            raise _fail(404, "background_audio_missing", "当前时间线没有可用的附加音轨")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path, media_type

    def validate_timeline(self, timeline: ProductionTimeline) -> TimelineValidationResponse:
        enabled = sorted(
            (clip for clip in timeline.clips if clip.enabled),
            key=lambda clip: clip.order,
        )
        errors: list[str] = []
        warnings: list[str] = []
        if not enabled:
            errors.append("时间线至少需要保留一个视频片段")
        clip_ids = [clip.id for clip in timeline.clips]
        if len(clip_ids) != len(set(clip_ids)):
            errors.append("时间线存在重复片段")
        orders = [clip.order for clip in timeline.clips]
        if len(orders) != len(set(orders)):
            errors.append("时间线片段顺序重复")
        for index, clip in enumerate(enabled):
            if clip.blocker_messages:
                errors.extend(
                    f"分镜 {clip.shot_index}：{message}"
                    for message in clip.blocker_messages
                )
            if clip.trim_out_seconds > clip.candidate_duration_seconds + 0.05:
                errors.append(f"分镜 {clip.shot_index} 的出点超过候选视频时长")
            if clip.playback_rate < 0.5 or clip.playback_rate > 2:
                warnings.append(
                    f"分镜 {clip.shot_index} 的播放速率为 {clip.playback_rate:.2f}x，"
                    "预览节奏可能不自然"
                )
            transition = clip.transition_after
            if transition.kind != TimelineTransitionKind.NONE:
                if index == len(enabled) - 1:
                    errors.append(f"最后一个分镜 {clip.shot_index} 不能设置片尾转场")
                else:
                    next_clip = enabled[index + 1]
                    maximum = min(
                        2,
                        clip.timeline_duration_seconds / 2,
                        next_clip.timeline_duration_seconds / 2,
                    )
                    if transition.duration_seconds > maximum + 0.001:
                        errors.append(
                            f"分镜 {clip.shot_index} 的转场时长不能超过 {maximum:.2f} 秒"
                        )
        if timeline.audio_track.strategy != "muted" and not timeline.audio_track.source_audio_url:
            errors.append("原音轨已启用，但音频来源不存在")
        enabled_clip_ids = {clip.id for clip in enabled}
        for cue in timeline.subtitle_cues:
            if not cue.enabled:
                continue
            if cue.clip_id is not None and cue.clip_id not in enabled_clip_ids:
                continue
            if cue.end_seconds > timeline.duration_seconds + 0.05:
                warnings.append(f"字幕“{cue.text[:18]}”超出当前时间线范围")
        return TimelineValidationResponse(
            project_id=timeline.project_id,
            revision_id=timeline.revision_id,
            valid=not errors,
            duration_seconds=timeline.duration_seconds,
            errors=errors,
            warnings=list(dict.fromkeys(warnings)),
        )

    async def list_revisions(self, project_id: UUID) -> TimelineRevisionList:
        project = await self._require_project(project_id)
        items = await asyncio.to_thread(self._read_revision_index, project)
        return TimelineRevisionList(items=items)

    async def get_revision(
        self,
        project_id: UUID,
        revision_id: UUID,
    ) -> ProductionTimeline:
        project = await self._require_project(project_id)
        revisions = await asyncio.to_thread(self._read_revision_index, project)
        revision = next((item for item in revisions if item.id == revision_id), None)
        if revision is None:
            raise _fail(404, "timeline_revision_missing", "时间线版本不存在")
        try:
            path = self.workspace.resolve(revision.snapshot_relative_path)
            return ProductionTimeline.model_validate_json(path.read_text("utf-8-sig"))
        except (OSError, ValidationError, WorkspaceError) as exc:
            raise _fail(409, "timeline_revision_invalid", "时间线版本快照损坏") from exc

    async def restore_revision(
        self,
        project_id: UUID,
        revision_id: UUID,
        payload: TimelineRestoreRequest,
    ) -> ProductionTimeline:
        project = await self._require_project(project_id)
        lock = self._project_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            current = await self._require_current_timeline(project)
            self._require_revision(current, payload.expected_revision_id)
            source = await self.get_revision(project_id, revision_id)
            restored = source.model_copy(
                update={
                    "revision_id": uuid4(),
                    "revision_number": current.revision_number + 1,
                    "last_preview_job_id": None,
                    "last_export_job_id": None,
                    "created_at": current.created_at,
                    "updated_at": utc_now(),
                }
            )
            restored = self._recompute_timeline(restored)
            saved = await asyncio.to_thread(
                self._save_revision,
                project,
                restored,
                TimelineChangeKind.RESTORED,
                f"恢复时间线版本 {source.revision_number}",
                source.revision_id,
            )
            return await self._synchronize_timeline_with_handoff(project, saved)

    async def create_preview(
        self,
        project_id: UUID,
        payload: TimelinePreviewCreate,
    ) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        timeline = await self.get_timeline(project_id)
        self._require_revision(timeline, payload.expected_revision_id)
        validation = self.validate_timeline(timeline)
        if not validation.valid:
            raise _fail(422, "timeline_invalid", "；".join(validation.errors))
        width, height = preview_dimensions(timeline.output_width, timeline.output_height)
        job = TimelineRenderJob(
            project_id=project.id,
            timeline_revision_id=timeline.revision_id,
            preview_width=width,
            preview_height=height,
        )
        await asyncio.to_thread(self._write_render_job, project, job)
        timeline = timeline.model_copy(update={"last_preview_job_id": job.id})
        await asyncio.to_thread(
            self._write_json_atomic,
            self._timeline_root(project) / "timeline.json",
            timeline.model_dump(mode="json"),
        )
        await self._publish_render_notification(project, job)
        task = asyncio.create_task(self._run_preview(project, timeline, job))
        self._render_tasks[job.id] = task
        task.add_done_callback(lambda _task, job_id=job.id: self._render_tasks.pop(job_id, None))
        return job

    async def get_render_job(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        job = await asyncio.to_thread(self._read_render_job, project, job_id)
        if job is None:
            raise _fail(404, "render_job_missing", "预览渲染任务不存在")
        if (
            job.status in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}
            and job.id not in self._render_tasks
        ):
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.FAILED,
                    "error_code": "render_interrupted",
                    "error_message": "服务重启导致预览任务中断，请重新生成",
                    "completed_at": utc_now(),
                }
            )
            await asyncio.to_thread(self._write_render_job, project, job)
        return job

    async def cancel_render_job(self, project_id: UUID, job_id: UUID) -> TimelineRenderJob:
        project = await self._require_project(project_id)
        job = await self.get_render_job(project_id, job_id)
        if job.status not in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}:
            raise _fail(409, "render_job_not_cancellable", "当前预览任务已结束，不能取消")
        self._render_cancellations.add(job_id)
        job = job.model_copy(update={"cancellation_requested": True})
        await asyncio.to_thread(self._write_render_job, project, job)
        return job

    async def resolve_render_content(
        self,
        project_id: UUID,
        job_id: UUID,
        *,
        subtitles: bool = False,
    ) -> tuple[Path, str]:
        project = await self._require_project(project_id)
        job = await self.get_render_job(project_id, job_id)
        relative_path = job.subtitle_relative_path if subtitles else job.output_relative_path
        if job.status != TimelineRenderStatus.SUCCEEDED or relative_path is None:
            raise _fail(404, "render_output_missing", "预览渲染产物尚不可用")
        try:
            resolved = self.workspace.resolve(relative_path).resolve()
            root = self.workspace.production_paths(project.record_id, project.id).renders.resolve()
            resolved.relative_to(root)
        except (WorkspaceError, ValueError) as exc:
            raise _fail(409, "render_output_invalid", "预览渲染产物路径无效") from exc
        if not resolved.is_file():
            raise _fail(404, "render_output_missing", "预览渲染产物不存在")
        return resolved, "text/vtt; charset=utf-8" if subtitles else "video/mp4"

    async def _timeline_clip_from_handoff(
        self,
        source: EditingHandoffClip,
        order: int,
        *,
        clip_id: UUID | None = None,
    ) -> TimelineClip:
        candidate = await self.repository.get_generation_candidate(source.candidate_id)
        candidate_duration = (
            float(candidate.duration_seconds)
            if candidate is not None and candidate.duration_seconds is not None
            else source.trim_out_seconds
        )
        return TimelineClip(
            id=clip_id or uuid4(),
            shot_plan_id=source.shot_plan_id,
            shot_index=source.shot_index,
            candidate_id=source.candidate_id,
            candidate_content_url=source.candidate_content_url,
            cover_url=source.cover_url,
            cover_timestamp_seconds=source.cover_timestamp_seconds,
            order=order,
            candidate_duration_seconds=max(candidate_duration, source.trim_out_seconds),
            trim_in_seconds=source.trim_in_seconds,
            trim_out_seconds=source.trim_out_seconds,
            playback_rate=source.video_playback_rate,
            timeline_start_seconds=source.timeline_start_seconds,
            timeline_end_seconds=source.timeline_end_seconds,
            timeline_duration_seconds=source.timeline_duration_seconds,
            audio_mode=source.audio_mode,
            source_audio_start_seconds=source.source_audio_start_seconds,
            source_audio_end_seconds=source.source_audio_end_seconds,
            quality_status=source.quality_status,
            quality_report=source.quality_report,
            blocker_messages=source.blocker_messages,
            warning_messages=source.warning_messages,
        )

    @staticmethod
    def _timeline_cues_from_handoff(
        source: EditingHandoffClip,
        clip: TimelineClip,
        existing_ids: set[str],
    ) -> list[TimelineSubtitleCue]:
        cues: list[TimelineSubtitleCue] = []
        for cue in source.subtitle_cues or source.transcript_cues:
            cue_id = f"{clip.id.hex[:8]}-{cue.id}"[:120]
            if cue_id in existing_ids:
                continue
            existing_ids.add(cue_id)
            cues.append(
                TimelineSubtitleCue(
                    id=cue_id,
                    source_cue_id=cue.id,
                    clip_id=clip.id,
                    text=cue.text,
                    language=cue.language,
                    start_seconds=round(
                        source.timeline_start_seconds + cue.clip_start_seconds,
                        3,
                    ),
                    end_seconds=round(
                        source.timeline_start_seconds + cue.clip_end_seconds,
                        3,
                    ),
                    clip_start_seconds=cue.clip_start_seconds,
                    clip_end_seconds=cue.clip_end_seconds,
                )
            )
        return cues

    async def _synchronize_timeline_with_handoff(
        self,
        project: ProductionProject,
        current: ProductionTimeline,
    ) -> ProductionTimeline:
        handoff = await self.handoff_provider.get_editing_handoff(project.id)
        if current.source_handoff_revision_id == handoff.revision_id:
            return current

        sources_by_shot = {item.shot_plan_id: item for item in handoff.clips}
        current_by_shot = {item.shot_plan_id: item for item in current.clips}
        next_clips: list[TimelineClip] = []
        added_sources: list[tuple[EditingHandoffClip, TimelineClip]] = []
        replaced_count = 0
        removed_count = 0

        for existing in sorted(current.clips, key=lambda item: item.order):
            source = sources_by_shot.get(existing.shot_plan_id)
            if source is None:
                removed_count += 1
                continue
            order = len(next_clips) + 1
            if existing.candidate_id == source.candidate_id:
                next_clips.append(
                    existing.model_copy(
                        update={
                            "order": order,
                            "shot_index": source.shot_index,
                            "candidate_content_url": source.candidate_content_url,
                            "source_audio_start_seconds": source.source_audio_start_seconds,
                            "source_audio_end_seconds": source.source_audio_end_seconds,
                        }
                    )
                )
                continue

            replacement = await self._timeline_clip_from_handoff(
                source,
                order,
                clip_id=existing.id,
            )
            trimmed_duration = replacement.trim_out_seconds - replacement.trim_in_seconds
            timeline_duration = max(
                existing.timeline_duration_seconds,
                round(trimmed_duration / 8, 3),
            )
            replacement = replacement.model_copy(
                update={
                    "enabled": existing.enabled,
                    "timeline_duration_seconds": timeline_duration,
                    "playback_rate": round(trimmed_duration / timeline_duration, 6),
                    "audio_mode": existing.audio_mode,
                    "audio_volume": existing.audio_volume,
                    "transition_after": existing.transition_after,
                }
            )
            next_clips.append(replacement)
            replaced_count += 1

        for source in handoff.clips:
            if source.shot_plan_id in current_by_shot:
                continue
            clip = await self._timeline_clip_from_handoff(source, len(next_clips) + 1)
            next_clips.append(clip)
            added_sources.append((source, clip))

        enabled_indexes = [index for index, clip in enumerate(next_clips) if clip.enabled]
        if enabled_indexes:
            last_index = enabled_indexes[-1]
            last_clip = next_clips[last_index]
            if last_clip.transition_after.kind != TimelineTransitionKind.NONE:
                next_clips[last_index] = last_clip.model_copy(
                    update={
                        "transition_after": last_clip.transition_after.model_copy(
                            update={
                                "kind": TimelineTransitionKind.NONE,
                                "duration_seconds": 0,
                            }
                        )
                    }
                )

        retained_clip_ids = {clip.id for clip in next_clips}
        next_cues = [
            cue
            for cue in current.subtitle_cues
            if cue.clip_id is None or cue.clip_id in retained_clip_ids
        ]
        cue_ids = {cue.id for cue in next_cues}
        for source, clip in added_sources:
            next_cues.extend(self._timeline_cues_from_handoff(source, clip, cue_ids))

        audio_track = current.audio_track
        if audio_track.strategy != "muted":
            if handoff.audio_strategy == "muted" or not handoff.source_audio_url:
                audio_track = audio_track.model_copy(
                    update={
                        "strategy": "muted",
                        "source_audio_url": None,
                        "enabled": False,
                    }
                )
            else:
                audio_track = audio_track.model_copy(
                    update={
                        "strategy": handoff.audio_strategy,
                        "source_audio_url": handoff.source_audio_url,
                    }
                )

        next_timeline = current.model_copy(
            update={
                "source_handoff_revision_id": handoff.revision_id,
                "revision_id": uuid4(),
                "revision_number": current.revision_number + 1,
                "clips": next_clips,
                "audio_track": audio_track,
                "subtitle_cues": next_cues,
                "last_preview_job_id": None,
                "last_export_job_id": None,
                "updated_at": utc_now(),
            }
        )
        next_timeline = self._recompute_timeline(next_timeline)
        validation = self.validate_timeline(next_timeline)
        next_timeline = next_timeline.model_copy(
            update={
                "validation_messages": validation.errors,
                "warning_messages": validation.warnings,
            }
        )
        summary = (
            "同步最新分段视频交接："
            f"替换 {replaced_count} 个，新增 {len(added_sources)} 个，"
            f"移除 {removed_count} 个"
        )
        return await asyncio.to_thread(
            self._save_revision,
            project,
            next_timeline,
            TimelineChangeKind.HANDOFF_SYNCED,
            summary,
            current.revision_id,
        )

    async def _initialize_timeline(self, project: ProductionProject) -> ProductionTimeline:
        handoff = await self.handoff_provider.get_editing_handoff(project.id)
        clips: list[TimelineClip] = []
        subtitles: list[TimelineSubtitleCue] = []
        seen_cues: set[str] = set()
        for order, source in enumerate(handoff.clips, start=1):
            clip = await self._timeline_clip_from_handoff(source, order)
            clips.append(clip)
            subtitles.extend(self._timeline_cues_from_handoff(source, clip, seen_cues))
        timeline = ProductionTimeline(
            project_id=project.id,
            source_handoff_revision_id=handoff.revision_id,
            revision_id=uuid4(),
            revision_number=1,
            output_aspect_ratio=project.output_aspect_ratio,
            output_width=project.output_width,
            output_height=project.output_height,
            duration_seconds=handoff.timeline_duration_seconds,
            clips=clips,
            audio_track=TimelineAudioTrack(
                strategy=handoff.audio_strategy,
                source_audio_url=handoff.source_audio_url,
                enabled=handoff.audio_strategy != "muted",
            ),
            subtitle_cues=subtitles,
        )
        timeline = self._recompute_timeline(timeline)
        validation = self.validate_timeline(timeline)
        timeline = timeline.model_copy(
            update={
                "validation_messages": validation.errors,
                "warning_messages": validation.warnings,
            }
        )
        return await asyncio.to_thread(
            self._save_revision,
            project,
            timeline,
            TimelineChangeKind.INITIALIZED,
            "从剪辑交接清单创建初始时间线",
            None,
        )

    def _apply_update(
        self,
        current: ProductionTimeline,
        payload: TimelineUpdateRequest,
    ) -> ProductionTimeline:
        current_by_id = {clip.id: clip for clip in current.clips}
        if payload.clip_order is not None:
            if len(payload.clip_order) != len(set(payload.clip_order)):
                raise _fail(422, "timeline_order_duplicate", "片段顺序中存在重复项")
            if set(payload.clip_order) != set(current_by_id):
                raise _fail(422, "timeline_order_mismatch", "片段顺序必须包含全部时间线片段")
            ordered = [current_by_id[clip_id] for clip_id in payload.clip_order]
        else:
            ordered = sorted(current.clips, key=lambda clip: clip.order)
        updates = {item.clip_id: item for item in payload.clip_updates}
        if len(updates) != len(payload.clip_updates):
            raise _fail(422, "timeline_update_duplicate", "同一片段不能重复更新")
        unknown = set(updates) - set(current_by_id)
        if unknown:
            raise _fail(404, "timeline_clip_missing", "要更新的时间线片段不存在")
        next_clips: list[TimelineClip] = []
        for order, clip in enumerate(ordered, start=1):
            update = updates.get(clip.id)
            values = clip.model_dump(mode="python")
            values["order"] = order
            if update is not None:
                for field in (
                    "enabled",
                    "trim_in_seconds",
                    "trim_out_seconds",
                    "cover_timestamp_seconds",
                    "timeline_duration_seconds",
                    "audio_mode",
                    "audio_volume",
                    "transition_after",
                ):
                    value = getattr(update, field)
                    if value is not None:
                        values[field] = value
            cover_timestamp = values.get("cover_timestamp_seconds")
            if cover_timestamp is not None:
                values["cover_timestamp_seconds"] = min(
                    max(float(cover_timestamp), float(values["trim_in_seconds"])),
                    float(values["trim_out_seconds"]),
                )
            trimmed_duration = values["trim_out_seconds"] - values["trim_in_seconds"]
            if trimmed_duration <= 0:
                raise _fail(422, "timeline_trim_invalid", f"分镜 {clip.shot_index} 的裁剪范围无效")
            values["playback_rate"] = round(
                trimmed_duration / values["timeline_duration_seconds"],
                6,
            )
            try:
                next_clips.append(TimelineClip.model_validate(values))
            except ValidationError as exc:
                raise _fail(422, "timeline_clip_invalid", str(exc.errors()[0]["msg"])) from exc
        next_timeline = current.model_copy(
            update={
                "revision_id": uuid4(),
                "revision_number": current.revision_number + 1,
                "clips": next_clips,
                "audio_track": payload.audio_track or current.audio_track,
                "background_audio_track": (
                    payload.background_audio_track
                    or current.background_audio_track
                ),
                "subtitle_cues": (
                    payload.subtitle_cues
                    if payload.subtitle_cues is not None
                    else current.subtitle_cues
                ),
                "last_preview_job_id": None,
                "last_export_job_id": None,
                "updated_at": utc_now(),
            }
        )
        return self._recompute_timeline(next_timeline)

    def _recompute_timeline(self, timeline: ProductionTimeline) -> ProductionTimeline:
        ordered = sorted(timeline.clips, key=lambda clip: clip.order)
        next_clips: list[TimelineClip] = []
        cursor = 0.0
        enabled_positions: dict[UUID, TimelineClip] = {}
        for clip in ordered:
            if clip.enabled:
                start = round(cursor, 3)
                end = round(start + clip.timeline_duration_seconds, 3)
                updated = clip.model_copy(
                    update={
                        "timeline_start_seconds": start,
                        "timeline_end_seconds": end,
                    }
                )
                enabled_positions[clip.id] = updated
                cursor = end
                if clip.transition_after.kind == TimelineTransitionKind.CROSSFADE:
                    cursor = max(start, cursor - clip.transition_after.duration_seconds)
            else:
                updated = clip.model_copy(
                    update={
                        "timeline_start_seconds": round(cursor, 3),
                        "timeline_end_seconds": round(
                            cursor + clip.timeline_duration_seconds,
                            3,
                        ),
                    }
                )
            next_clips.append(updated)
        duration = round(max(cursor, 0.001), 3)
        next_cues: list[TimelineSubtitleCue] = []
        for cue in timeline.subtitle_cues:
            clip = enabled_positions.get(cue.clip_id) if cue.clip_id is not None else None
            if (
                clip is not None
                and cue.clip_start_seconds is not None
                and cue.clip_end_seconds is not None
            ):
                start = min(cue.clip_start_seconds, clip.timeline_duration_seconds)
                end = min(cue.clip_end_seconds, clip.timeline_duration_seconds)
                if end <= start:
                    end = min(clip.timeline_duration_seconds, start + 0.05)
                next_cues.append(
                    cue.model_copy(
                        update={
                            "start_seconds": round(clip.timeline_start_seconds + start, 3),
                            "end_seconds": round(clip.timeline_start_seconds + end, 3),
                        }
                    )
                )
            else:
                next_cues.append(cue)
        return timeline.model_copy(
            update={
                "clips": next_clips,
                "subtitle_cues": next_cues,
                "duration_seconds": duration,
                "updated_at": utc_now(),
            }
        )

    async def _run_preview(
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
        await asyncio.to_thread(self._write_render_job, project, job)
        await self._publish_render_notification(project, job)

        async def update_progress(value: int) -> None:
            nonlocal job
            if value <= job.progress_percent:
                return
            job = job.model_copy(update={"progress_percent": min(99, value)})
            await asyncio.to_thread(self._write_render_job, project, job)

        try:
            output_root = (
                self.workspace.production_paths(project.record_id, project.id).renders
                / "previews"
                / str(job.id)
            )
            audio_path = self._source_audio_path(project, timeline)
            background_audio_path = self._background_audio_path(project, timeline)
            if (
                timeline.audio_track.enabled
                and timeline.audio_track.strategy != "muted"
                and audio_path is None
            ):
                raise TimelineRenderError(
                    "source_audio_missing",
                    "原视频音轨文件不存在，请切换为静音或重新分析源视频",
                )
            if timeline.background_audio_track.enabled and background_audio_path is None:
                raise TimelineRenderError(
                    "background_audio_missing",
                    "附加音轨文件不存在，请重新上传或关闭该轨道",
                )
            output_path, subtitle_path = await self.renderer.render(
                timeline,
                output_root,
                source_audio_path=audio_path,
                background_audio_path=background_audio_path,
                progress=update_progress,
                is_cancelled=lambda: job.id in self._render_cancellations,
            )
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.SUCCEEDED,
                    "progress_percent": 100,
                    "output_relative_path": self.workspace.relative(output_path),
                    "subtitle_relative_path": (
                        self.workspace.relative(subtitle_path) if subtitle_path else None
                    ),
                    "output_url": (
                        f"/api/v1/productions/{project.id}/render-jobs/{job.id}/content"
                    ),
                    "subtitle_url": (
                        f"/api/v1/productions/{project.id}/render-jobs/{job.id}/subtitles"
                        if subtitle_path
                        else None
                    ),
                    "completed_at": utc_now(),
                }
            )
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
                    "error_message": "服务关闭，预览渲染已停止",
                    "completed_at": utc_now(),
                }
            )
        except Exception as exc:  # pragma: no cover - final async safety boundary
            job = job.model_copy(
                update={
                    "status": TimelineRenderStatus.FAILED,
                    "error_code": "preview_render_failed",
                    "error_message": f"低清预览生成失败：{exc}",
                    "completed_at": utc_now(),
                }
            )
        finally:
            self._render_cancellations.discard(job.id)
            await asyncio.to_thread(self._write_render_job, project, job)
            await self._publish_render_notification(project, job)

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

    def _background_audio_path(
        self,
        project: ProductionProject,
        timeline: ProductionTimeline,
    ) -> Path | None:
        relative_path = timeline.background_audio_track.source_relative_path
        if not relative_path:
            return None
        try:
            path = self.workspace.resolve(relative_path).resolve()
            path.relative_to(self._timeline_root(project).resolve())
        except (WorkspaceError, ValueError):
            return None
        return path if path.is_file() else None

    async def _publish_render_notification(
        self,
        project: ProductionProject,
        job: TimelineRenderJob,
    ) -> None:
        if self.notification_publisher is None:
            return
        if job.status == TimelineRenderStatus.QUEUED:
            level, status = "info", "in_progress"
            title, message = "低清预览已排队", "时间线预览正在等待渲染。"
        elif job.status == TimelineRenderStatus.RUNNING:
            level, status = "info", "in_progress"
            title, message = "正在生成低清预览", "完成后会在消息中心通知你。"
        elif job.status == TimelineRenderStatus.SUCCEEDED:
            level, status = "success", "succeeded"
            title, message = "低清预览已生成", "可以返回视频剪辑页面播放并审核预览。"
        elif job.status == TimelineRenderStatus.CANCELLED:
            level, status = "warning", "cancelled"
            title, message = "低清预览已取消", "本次渲染没有生成可用产物。"
        else:
            level, status = "error", "failed"
            title, message = "低清预览生成失败", job.error_message or "请稍后重试。"
        try:
            await self.notification_publisher.publish(
                category="export",
                level=level,
                status=status,
                title=title,
                message=message,
                event_key=f"timeline-preview:{job.id}",
                action_kind="production_shot",
                action_label="查看时间线",
                action_payload={
                    "record_id": str(project.record_id),
                    "project_id": str(project.id),
                    "step": "editing",
                    "render_job_id": str(job.id),
                },
            )
        except Exception:
            return

    async def _require_project(self, project_id: UUID) -> ProductionProject:
        project = await self.repository.get_production_project(project_id)
        if project is None:
            raise _fail(404, "production_missing", "创作方案不存在")
        if project.active_step not in {ProductionStep.EDITING, ProductionStep.EXPORT}:
            raise _fail(409, "timeline_not_available", "请先完成分段视频并进入视频剪辑")
        return project

    async def _require_current_timeline(
        self,
        project: ProductionProject,
    ) -> ProductionTimeline:
        timeline = await asyncio.to_thread(self._read_current_timeline, project)
        if timeline is None:
            return await self._initialize_timeline(project)
        return await self._synchronize_timeline_with_handoff(project, timeline)

    @staticmethod
    def _require_revision(timeline: ProductionTimeline, expected_revision_id: UUID) -> None:
        if timeline.revision_id != expected_revision_id:
            raise _fail(
                409,
                "timeline_revision_conflict",
                "时间线已在其他操作中更新，请刷新后重试",
            )

    def _timeline_root(self, project: ProductionProject) -> Path:
        return self.workspace.production_paths(project.record_id, project.id).timelines

    def _read_current_timeline(self, project: ProductionProject) -> ProductionTimeline | None:
        path = self._timeline_root(project) / "timeline.json"
        if not path.is_file():
            return None
        try:
            timeline = ProductionTimeline.model_validate_json(path.read_text("utf-8-sig"))
        except (OSError, ValidationError) as exc:
            raise _fail(409, "timeline_invalid", "当前时间线文件损坏") from exc
        if timeline.project_id != project.id:
            raise _fail(409, "timeline_project_mismatch", "当前时间线不属于该创作方案")
        return timeline

    def _read_revision_index(self, project: ProductionProject) -> list[TimelineRevision]:
        path = self._timeline_root(project) / "revisions.json"
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text("utf-8-sig"))
            items = [TimelineRevision.model_validate(item) for item in payload.get("items", [])]
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise _fail(409, "timeline_revision_index_invalid", "时间线版本索引损坏") from exc
        return sorted(items, key=lambda item: item.revision_number)

    def _save_revision(
        self,
        project: ProductionProject,
        timeline: ProductionTimeline,
        change_kind: TimelineChangeKind,
        summary: str,
        source_revision_id: UUID | None,
    ) -> ProductionTimeline:
        root = self._timeline_root(project)
        snapshot = (
            root
            / "revisions"
            / f"{timeline.revision_number:04d}-{timeline.revision_id}.json"
        )
        revision = TimelineRevision(
            id=timeline.revision_id,
            project_id=project.id,
            revision_number=timeline.revision_number,
            change_kind=change_kind,
            summary=summary,
            snapshot_relative_path=self.workspace.relative(snapshot),
            source_revision_id=source_revision_id,
        )
        revisions = self._read_revision_index(project)
        if any(item.id == revision.id for item in revisions):
            raise _fail(409, "timeline_revision_duplicate", "时间线版本已存在")
        revisions.append(revision)
        self._write_json_atomic(snapshot, timeline.model_dump(mode="json"))
        self._write_json_atomic(root / "timeline.json", timeline.model_dump(mode="json"))
        self._write_json_atomic(
            root / "revisions.json",
            {"schema_version": "viral-dna-timeline-revisions/v1", "items": [
                item.model_dump(mode="json") for item in revisions
            ]},
        )
        return timeline

    def _render_job_path(self, project: ProductionProject, job_id: UUID) -> Path:
        return (
            self.workspace.production_paths(project.record_id, project.id).renders
            / "jobs"
            / f"{job_id}.json"
        )

    def _write_render_job(self, project: ProductionProject, job: TimelineRenderJob) -> None:
        self._write_json_atomic(
            self._render_job_path(project, job.id),
            job.model_dump(mode="json"),
        )

    def _read_render_job(
        self,
        project: ProductionProject,
        job_id: UUID,
    ) -> TimelineRenderJob | None:
        path = self._render_job_path(project, job_id)
        if not path.is_file():
            return None
        try:
            return TimelineRenderJob.model_validate_json(path.read_text("utf-8-sig"))
        except (OSError, ValidationError) as exc:
            raise _fail(409, "render_job_invalid", "预览渲染任务记录损坏") from exc

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
            raise _fail(507, "workspace_write_failed", "无法写入时间线工作区文件") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_bytes_atomic(destination: Path, payload: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".tmp-{uuid4().hex[:8]}"
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        except OSError as exc:
            raise _fail(507, "workspace_write_failed", "无法写入时间线音频文件") from exc
        finally:
            temporary.unlink(missing_ok=True)
