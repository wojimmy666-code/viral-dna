from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import AnalysisJob, AnalysisReport, ReplacementVersion, Video

ModelT = TypeVar("ModelT", bound=BaseModel)


class SQLiteStore:
    """Small durable repository for the single-node Phase 1 worker.

    Rows intentionally store versioned Pydantic JSON. This keeps the persistence
    boundary stable while the report schema is still changing quickly.
    """

    _allowed_tables = {"videos", "analyses", "reports", "replacements"}

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
            for table in sorted(self._allowed_tables):
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("  # noqa: S608 - internal allowlist
                    "record_key TEXT PRIMARY KEY, "
                    "payload TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
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

    @staticmethod
    def _serialize(model: BaseModel) -> str:
        payload = model.model_dump(mode="json")
        if isinstance(model, Video):
            payload["stored_path"] = model.stored_path
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def _save(self, table: str, key: UUID, model: ModelT) -> ModelT:
        async with self._lock:
            await asyncio.to_thread(self._upsert, table, str(key), self._serialize(model))
        return model

    async def _get(
        self,
        table: str,
        key: UUID,
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

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None:
        return await self._get("analyses", analysis_id, AnalysisJob)

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        return await self._save("reports", report.video_id, report)

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return await self._get("reports", video_id, AnalysisReport)

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        return await self._save("replacements", version.id, version)
