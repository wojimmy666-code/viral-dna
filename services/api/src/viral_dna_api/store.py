from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .chinese import simplify_model
from .exports import archive_report
from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
    ExportArtifact,
    ModelRun,
    ModelRunStatus,
    PriceSnapshot,
    RecordFolder,
    ReplacementVersion,
    Video,
    VideoStatus,
)
from .workspace import WorkspaceError, workspace_manager


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryStore:
    """Repository used by tests while preserving the durable-store contract."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.videos: dict[UUID, Video] = {}
        self.analyses: dict[UUID, AnalysisJob] = {}
        self.reports: dict[UUID, AnalysisReport] = {}
        self.reports_by_analysis: dict[UUID, AnalysisReport] = {}
        self.replacements: dict[UUID, ReplacementVersion] = {}
        self.model_runs: dict[UUID, ModelRun] = {}
        self.price_snapshots: dict[str, PriceSnapshot] = {}
        self.folders: dict[UUID, RecordFolder] = {}
        self.records: dict[UUID, AnalysisRecord] = {}
        self.exports: dict[UUID, ExportArtifact] = {}

    async def add_video(self, video: Video) -> Video:
        async with self._lock:
            self.videos[video.id] = video
        return video

    async def get_video(self, video_id: UUID) -> Video | None:
        return self.videos.get(video_id)

    async def save_video(self, video: Video) -> Video:
        async with self._lock:
            self.videos[video.id] = video
        return video

    async def list_videos(self) -> list[Video]:
        return list(self.videos.values())

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        async with self._lock:
            self.analyses[analysis.id] = analysis
        return analysis

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None:
        return self.analyses.get(analysis_id)

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        async with self._lock:
            self.analyses[analysis.id] = analysis
        return analysis

    async def list_analyses(self) -> list[AnalysisJob]:
        return list(self.analyses.values())

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        async with self._lock:
            self.reports[report.video_id] = report
            self.reports_by_analysis[report.analysis_id] = report
        return report

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return self.reports.get(video_id)

    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None:
        return self.reports_by_analysis.get(analysis_id)

    async def list_report_versions(self) -> list[AnalysisReport]:
        return list(self.reports_by_analysis.values())

    async def save_folder(self, folder: RecordFolder) -> RecordFolder:
        async with self._lock:
            self.folders[folder.id] = folder
        return folder

    async def get_folder(self, folder_id: UUID) -> RecordFolder | None:
        return self.folders.get(folder_id)

    async def list_folders(self) -> list[RecordFolder]:
        return list(self.folders.values())

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord:
        async with self._lock:
            self.records[record.id] = record
        return record

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None:
        return self.records.get(record_id)

    async def list_records(self) -> list[AnalysisRecord]:
        return list(self.records.values())

    async def save_export(self, artifact: ExportArtifact) -> ExportArtifact:
        async with self._lock:
            self.exports[artifact.id] = artifact
        return artifact

    async def get_export(self, export_id: UUID) -> ExportArtifact | None:
        return self.exports.get(export_id)

    async def list_exports(self, record_id: UUID | None = None) -> list[ExportArtifact]:
        artifacts = list(self.exports.values())
        if record_id is None:
            return artifacts
        return [artifact for artifact in artifacts if artifact.record_id == record_id]

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        async with self._lock:
            self.replacements[version.id] = version
        return version

    async def get_replacement(self, version_id: UUID) -> ReplacementVersion | None:
        return self.replacements.get(version_id)

    async def save_model_run(self, run: ModelRun) -> ModelRun:
        async with self._lock:
            self.model_runs[run.id] = run
        return run

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]:
        return sorted(
            (run for run in self.model_runs.values() if run.analysis_id == analysis_id),
            key=lambda run: run.created_at,
        )

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None:
        candidates = [
            run
            for run in self.model_runs.values()
            if run.request_fingerprint == request_fingerprint
            and run.status == ModelRunStatus.COMPLETED
            and run.result_payload is not None
        ]
        return max(candidates, key=lambda run: run.completed_at or run.created_at, default=None)

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot:
        async with self._lock:
            self.price_snapshots[snapshot.id] = snapshot
        return snapshot

    async def get_price_snapshot(self, snapshot_id: str) -> PriceSnapshot | None:
        return self.price_snapshots.get(snapshot_id)


class WorkspaceStore:
    """Stable repository proxy whose backend follows the active workspace."""

    def __init__(self) -> None:
        self._memory_mode = os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory"
        self._switch_lock = asyncio.Lock()
        self._backend = self._new_backend(workspace_manager.database_path)

    def _new_backend(self, database_path: Path):
        if self._memory_mode:
            return InMemoryStore()
        from .sqlite_store import SQLiteStore

        return SQLiteStore(database_path)

    @property
    def backend(self):
        return self._backend

    def __getattr__(self, name: str):
        return getattr(self._backend, name)

    async def switch_workspace(self, path: str) -> None:
        async with self._switch_lock:
            analyses = await self._backend.list_analyses()
            active = [
                analysis
                for analysis in analyses
                if analysis.stage not in {AnalysisStage.COMPLETED, AnalysisStage.FAILED}
            ]
            if active:
                raise WorkspaceError("有分析任务正在运行，完成后才能切换工作区")
            candidate = workspace_manager.normalize(path)
            prepared = workspace_manager.initialize(candidate)
            backend = self._new_backend(prepared.database)
            workspace_manager.activate(candidate, persist=True)
            self._backend = backend

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        saved = await self._backend.add_analysis(analysis)
        await self._sync_record_from_analysis(saved)
        return saved

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        saved = await self._backend.save_analysis(analysis)
        await self._sync_record_from_analysis(saved)
        return saved

    async def save_video(self, video: Video) -> Video:
        saved = await self._backend.save_video(video)
        if video.record_id is not None:
            record = await self._backend.get_record(video.record_id)
            if record is not None and record.status != video.status:
                record.status = video.status
                record.updated_at = _utc_now()
                await self._backend.save_record(record)
        return saved

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        simplified = simplify_model(report)
        saved = await self._backend.save_report(simplified)
        analysis = await self._backend.get_analysis(report.analysis_id)
        if analysis is not None and analysis.record_id is not None:
            await archive_report(analysis.record_id, simplified)
        return saved

    async def _sync_record_from_analysis(self, analysis: AnalysisJob) -> None:
        if analysis.record_id is None:
            return
        record = await self._backend.get_record(analysis.record_id)
        if record is None:
            return
        if analysis.stage == AnalysisStage.COMPLETED:
            next_status = VideoStatus.COMPLETED
        elif analysis.stage == AnalysisStage.FAILED:
            next_status = VideoStatus.FAILED
        else:
            next_status = VideoStatus.ANALYZING
        if record.latest_analysis_id == analysis.id and record.status == next_status:
            return
        record.latest_analysis_id = analysis.id
        record.status = next_status
        record.updated_at = max(record.updated_at, analysis.updated_at)
        await self._backend.save_record(record)


def create_store() -> WorkspaceStore:
    return WorkspaceStore()


store = create_store()
