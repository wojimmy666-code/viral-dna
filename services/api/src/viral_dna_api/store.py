from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID

from .models import AnalysisJob, AnalysisReport, ReplacementVersion, Video


class InMemoryStore:
    """Phase 1 bootstrap repository.

    The service boundary mirrors the future PostgreSQL repository so the simulated
    analyzer can be replaced without changing API contracts.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.videos: dict[UUID, Video] = {}
        self.analyses: dict[UUID, AnalysisJob] = {}
        self.reports: dict[UUID, AnalysisReport] = {}
        self.replacements: dict[UUID, ReplacementVersion] = {}

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

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        async with self._lock:
            self.reports[report.video_id] = report
        return report

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return self.reports.get(video_id)

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        async with self._lock:
            self.replacements[version.id] = version
        return version


def create_store():
    if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
        return InMemoryStore()

    from .sqlite_store import SQLiteStore

    database_path = Path(os.getenv("VIRAL_DNA_DATABASE_PATH", "storage/viral_dna.db"))
    return SQLiteStore(database_path)


store = create_store()
