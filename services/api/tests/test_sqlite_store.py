from __future__ import annotations

import asyncio
from pathlib import Path

from viral_dna_api.models import AnalysisJob, AnalysisMode, SourceType, Video
from viral_dna_api.sqlite_store import SQLiteStore


def test_sqlite_store_survives_repository_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "viral-dna.db"
    stored_path = tmp_path / "source.mp4"

    async def scenario() -> None:
        first = SQLiteStore(database_path)
        video = Video(
            source_type=SourceType.UPLOAD,
            original_filename="source.mp4",
            stored_path=str(stored_path),
            title="持久化测试",
        )
        analysis = AnalysisJob(
            video_id=video.id,
            analysis_mode=AnalysisMode.MEDIA_EVIDENCE,
            simulated=False,
        )
        await first.add_video(video)
        await first.add_analysis(analysis)

        restarted = SQLiteStore(database_path)
        restored_video = await restarted.get_video(video.id)
        restored_analysis = await restarted.get_analysis(analysis.id)
        assert restored_video is not None
        assert restored_video.stored_path == str(stored_path)
        assert restored_analysis is not None
        assert restored_analysis.analysis_mode == AnalysisMode.MEDIA_EVIDENCE

    asyncio.run(scenario())
