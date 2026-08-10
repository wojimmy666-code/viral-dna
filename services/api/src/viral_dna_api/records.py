from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from .chinese import simplify_model, to_simplified
from .exports import archive_report
from .models import (
    AnalysisError,
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
    RecordFolder,
    Video,
    VideoStatus,
)
from .workspace import WorkspaceError, workspace_manager

DEFAULT_LINK_RECORD_NAMES = frozenset({"抖音链接视频", "小红书链接视频"})


class RecordRepository(Protocol):
    async def list_videos(self) -> list[Video]: ...

    async def save_video(self, video: Video) -> Video: ...

    async def list_analyses(self) -> list[AnalysisJob]: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...

    async def list_report_versions(self) -> list[AnalysisReport]: ...

    async def save_report(self, report: AnalysisReport) -> AnalysisReport: ...

    async def list_records(self) -> list[AnalysisRecord]: ...

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord: ...

    async def list_folders(self) -> list[RecordFolder]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_record_name(value: str | None, *, fallback: str = "未命名视频") -> str:
    normalized = " ".join((to_simplified(value) or "").split()).strip()
    return normalized[:120] or fallback


def resolve_record_name_from_video(current_name: str, video_title: str | None) -> str:
    """Replace only a generated link placeholder; never overwrite a user name."""

    normalized_current = normalize_record_name(current_name)
    normalized_video = normalize_record_name(video_title, fallback="")
    if (
        normalized_current in DEFAULT_LINK_RECORD_NAMES
        and normalized_video
        and normalized_video not in DEFAULT_LINK_RECORD_NAMES
    ):
        return normalized_video
    return normalized_current


def _stable_record_id(video_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://viral-dna.local/videos/{video_id}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_video_path(video: Video) -> Path:
    if video.stored_relative_path:
        candidate = workspace_manager.resolve(video.stored_relative_path)
        if candidate.is_file():
            return candidate
    if video.stored_path:
        candidate = Path(video.stored_path).expanduser().resolve()
        try:
            candidate.relative_to(workspace_manager.root)
        except ValueError as exc:
            raise WorkspaceError("视频源文件不在当前工作区内") from exc
        if candidate.is_file():
            return candidate
    raise WorkspaceError("视频源文件尚未准备完成")


async def write_source_metadata(video: Video) -> None:
    if video.record_id is None:
        return
    source_root = workspace_manager.source_root(video.record_id)
    await asyncio.to_thread(source_root.mkdir, parents=True, exist_ok=True)
    payload = video.model_dump(mode="json")
    payload["stored_relative_path"] = video.stored_relative_path
    destination = source_root / "metadata.json"
    temporary = source_root / ".metadata.json.tmp"

    def write() -> None:
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    await asyncio.to_thread(write)


class RecordService:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository
        self._bootstrap_lock = asyncio.Lock()

    async def bootstrap(self, *, recover_interrupted: bool = False) -> None:
        """Backfill legacy rows and copy legacy files without deleting their sources."""

        async with self._bootstrap_lock:
            videos = await self.repository.list_videos()
            analyses = await self.repository.list_analyses()
            reports = await self.repository.list_report_versions()
            records = await self.repository.list_records()
            by_video = {record.video_id: record for record in records}
            analyses_by_video: dict[UUID, list[AnalysisJob]] = {}
            for analysis in analyses:
                analyses_by_video.setdefault(analysis.video_id, []).append(analysis)
            reports_by_analysis = {report.analysis_id: report for report in reports}

            for video in videos:
                record_changed = False
                record = by_video.get(video.id)
                if record is None:
                    record_id = video.record_id or _stable_record_id(video.id)
                    record = AnalysisRecord(
                        id=record_id,
                        name=normalize_record_name(video.title),
                        video_id=video.id,
                        source_type=video.source_type,
                        source_url=video.source_url,
                        status=video.status,
                        created_at=video.created_at,
                        updated_at=video.created_at,
                    )
                    record_changed = True
                    by_video[video.id] = record
                else:
                    resolved_name = resolve_record_name_from_video(record.name, video.title)
                    if resolved_name != record.name:
                        record.name = resolved_name
                        record_changed = True

                video.record_id = record.id
                migrated_video = await asyncio.to_thread(self._migrate_video_file, video, record.id)
                await self.repository.save_video(migrated_video)
                await write_source_metadata(migrated_video)

                versions = sorted(
                    analyses_by_video.get(video.id, []),
                    key=lambda item: item.created_at,
                )
                for analysis in versions:
                    analysis_changed = analysis.record_id != record.id
                    analysis.record_id = record.id
                    if recover_interrupted and analysis.stage not in {
                        AnalysisStage.COMPLETED,
                        AnalysisStage.FAILED,
                    }:
                        analysis.stage = AnalysisStage.FAILED
                        analysis.progress = 100
                        analysis.message = "服务重启导致分析中断，请手动重新分析"
                        analysis.error = AnalysisError(
                            code="analysis_interrupted",
                            message="服务在分析完成前重启",
                            retryable=True,
                        )
                        analysis.updated_at = _utc_now()
                        analysis.completed_at = _utc_now()
                        analysis_changed = True
                    await asyncio.to_thread(self._migrate_analysis_files, record.id, analysis.id)
                    if analysis_changed:
                        await self.repository.save_analysis(analysis)
                    report = reports_by_analysis.get(analysis.id)
                    if report is not None:
                        simplified = simplify_model(report)
                        await self.repository.save_report(simplified)
                        await archive_report(record.id, simplified)

                if versions:
                    latest = versions[-1]
                    if latest.stage == AnalysisStage.COMPLETED:
                        next_status = VideoStatus.COMPLETED
                    elif latest.stage == AnalysisStage.FAILED:
                        next_status = VideoStatus.FAILED
                    else:
                        next_status = VideoStatus.ANALYZING
                    if record.latest_analysis_id != latest.id:
                        record.latest_analysis_id = latest.id
                        record_changed = True
                    if record.status != next_status:
                        record.status = next_status
                        record_changed = True
                else:
                    if record.status != video.status:
                        record.status = video.status
                        record_changed = True
                if record_changed:
                    latest_updated_at = versions[-1].updated_at if versions else video.created_at
                    record.updated_at = max(record.updated_at, latest_updated_at)
                    await self.repository.save_record(record)

    @staticmethod
    def _migrate_video_file(video: Video, record_id: UUID) -> Video:
        if video.stored_relative_path:
            try:
                existing = workspace_manager.resolve(video.stored_relative_path)
            except WorkspaceError:
                existing = None
            if existing is not None and existing.is_file():
                return video
        if not video.stored_path:
            return video
        source = Path(video.stored_path).expanduser().resolve()
        if not source.is_file():
            return video
        suffix = source.suffix.lower() or ".mp4"
        destination = workspace_manager.source_root(record_id) / f"original{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source != destination.resolve():
            if not destination.exists() or _sha256(destination) != _sha256(source):
                temporary = destination.with_name(f".{destination.name}.migration.tmp")
                try:
                    shutil.copy2(source, temporary)
                    if _sha256(temporary) != _sha256(source):
                        raise WorkspaceError("旧视频迁移校验失败")
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        video.stored_relative_path = workspace_manager.relative(destination)
        return video

    @staticmethod
    def _migrate_analysis_files(record_id: UUID, analysis_id: UUID) -> None:
        source = workspace_manager.root / "analyses" / str(analysis_id)
        destination = workspace_manager.analysis_root(record_id, analysis_id)
        if not source.is_dir() or source.resolve() == destination.resolve():
            return
        destination.mkdir(parents=True, exist_ok=True)
        for source_file in source.rglob("*"):
            if not source_file.is_file():
                continue
            relative = source_file.relative_to(source)
            destination_file = destination / relative
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            if destination_file.exists() and _sha256(destination_file) == _sha256(source_file):
                continue
            temporary = destination_file.with_name(f".{destination_file.name}.migration.tmp")
            try:
                shutil.copy2(source_file, temporary)
                if _sha256(temporary) != _sha256(source_file):
                    raise WorkspaceError(f"旧分析产物迁移校验失败：{relative.as_posix()}")
                os.replace(temporary, destination_file)
            finally:
                temporary.unlink(missing_ok=True)
