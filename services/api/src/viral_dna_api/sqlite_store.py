from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    ExportArtifact,
    ModelRun,
    ModelRunStatus,
    PriceSnapshot,
    RecordFolder,
    ReplacementVersion,
    Video,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class SQLiteStore:
    """Durable single-node repository using versioned Pydantic JSON records."""

    _allowed_tables = {
        "videos",
        "analyses",
        "reports",
        "report_versions",
        "replacements",
        "model_runs",
        "price_snapshots",
        "folders",
        "records",
        "exports",
    }

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            for table in sorted(self._allowed_tables):
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("  # noqa: S608 - internal allowlist
                    "record_key TEXT PRIMARY KEY, "
                    "payload TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)"
            )

    @classmethod
    def _table(cls, table: str) -> str:
        if table not in cls._allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        return table

    def _upsert(self, table: str, key: str, payload: str) -> None:
        safe_table = self._table(table)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {safe_table} (record_key, payload, updated_at) "  # noqa: S608
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(record_key) DO UPDATE SET "
                "payload = excluded.payload, updated_at = CURRENT_TIMESTAMP",
                (key, payload),
            )

    def _read(self, table: str, key: str) -> str | None:
        safe_table = self._table(table)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {safe_table} WHERE record_key = ?",  # noqa: S608
                (key,),
            ).fetchone()
        return str(row[0]) if row else None

    def _read_all(self, table: str) -> list[str]:
        safe_table = self._table(table)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM {safe_table} ORDER BY updated_at, record_key"  # noqa: S608
            ).fetchall()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _serialize(model: BaseModel) -> str:
        payload = model.model_dump(mode="json")
        if isinstance(model, Video):
            payload["stored_path"] = model.stored_path
            payload["stored_relative_path"] = model.stored_relative_path
        if isinstance(model, ExportArtifact):
            payload["relative_path"] = model.relative_path
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def _save(self, table: str, key: UUID | str, model: ModelT) -> ModelT:
        async with self._lock:
            await asyncio.to_thread(self._upsert, table, str(key), self._serialize(model))
        return model

    async def _get(
        self,
        table: str,
        key: UUID | str,
        model_type: type[ModelT],
    ) -> ModelT | None:
        payload = await asyncio.to_thread(self._read, table, str(key))
        return model_type.model_validate_json(payload) if payload else None

    async def add_video(self, video: Video) -> Video:
        return await self._save("videos", video.id, video)

    async def get_video(self, video_id: UUID) -> Video | None:
        return await self._get("videos", video_id, Video)

    async def save_video(self, video: Video) -> Video:
        return await self._save("videos", video.id, video)

    async def list_videos(self) -> list[Video]:
        payloads = await asyncio.to_thread(self._read_all, "videos")
        return [Video.model_validate_json(payload) for payload in payloads]

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None:
        return await self._get("analyses", analysis_id, AnalysisJob)

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def list_analyses(self) -> list[AnalysisJob]:
        payloads = await asyncio.to_thread(self._read_all, "analyses")
        return [AnalysisJob.model_validate_json(payload) for payload in payloads]

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        await self._save("report_versions", report.analysis_id, report)
        return await self._save("reports", report.video_id, report)

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return await self._get("reports", video_id, AnalysisReport)

    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None:
        versioned = await self._get("report_versions", analysis_id, AnalysisReport)
        if versioned is not None:
            return versioned
        # Compatibility for reports written before report_versions existed.
        payloads = await asyncio.to_thread(self._read_all, "reports")
        return next(
            (
                report
                for report in (AnalysisReport.model_validate_json(payload) for payload in payloads)
                if report.analysis_id == analysis_id
            ),
            None,
        )

    async def list_report_versions(self) -> list[AnalysisReport]:
        payloads = await asyncio.to_thread(self._read_all, "report_versions")
        return [AnalysisReport.model_validate_json(payload) for payload in payloads]

    async def save_folder(self, folder: RecordFolder) -> RecordFolder:
        return await self._save("folders", folder.id, folder)

    async def get_folder(self, folder_id: UUID) -> RecordFolder | None:
        return await self._get("folders", folder_id, RecordFolder)

    async def list_folders(self) -> list[RecordFolder]:
        payloads = await asyncio.to_thread(self._read_all, "folders")
        return [RecordFolder.model_validate_json(payload) for payload in payloads]

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord:
        return await self._save("records", record.id, record)

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None:
        return await self._get("records", record_id, AnalysisRecord)

    async def list_records(self) -> list[AnalysisRecord]:
        payloads = await asyncio.to_thread(self._read_all, "records")
        return [AnalysisRecord.model_validate_json(payload) for payload in payloads]

    async def save_export(self, artifact: ExportArtifact) -> ExportArtifact:
        return await self._save("exports", artifact.id, artifact)

    async def get_export(self, export_id: UUID) -> ExportArtifact | None:
        return await self._get("exports", export_id, ExportArtifact)

    async def list_exports(self, record_id: UUID | None = None) -> list[ExportArtifact]:
        payloads = await asyncio.to_thread(self._read_all, "exports")
        artifacts = [ExportArtifact.model_validate_json(payload) for payload in payloads]
        if record_id is None:
            return artifacts
        return [artifact for artifact in artifacts if artifact.record_id == record_id]

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        return await self._save("replacements", version.id, version)

    async def get_replacement(self, version_id: UUID) -> ReplacementVersion | None:
        return await self._get("replacements", version_id, ReplacementVersion)

    async def save_model_run(self, run: ModelRun) -> ModelRun:
        return await self._save("model_runs", run.id, run)

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]:
        payloads = await asyncio.to_thread(self._read_all, "model_runs")
        runs = [ModelRun.model_validate_json(payload) for payload in payloads]
        return [run for run in runs if run.analysis_id == analysis_id]

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None:
        payloads = await asyncio.to_thread(self._read_all, "model_runs")
        candidates = [
            run
            for run in (ModelRun.model_validate_json(payload) for payload in payloads)
            if run.request_fingerprint == request_fingerprint
            and run.status == ModelRunStatus.COMPLETED
            and run.result_payload is not None
        ]
        return max(candidates, key=lambda run: run.completed_at or run.created_at, default=None)

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot:
        return await self._save("price_snapshots", snapshot.id, snapshot)

    async def get_price_snapshot(self, snapshot_id: str) -> PriceSnapshot | None:
        return await self._get("price_snapshots", snapshot_id, PriceSnapshot)
