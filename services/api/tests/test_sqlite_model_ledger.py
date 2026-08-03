from __future__ import annotations

from pathlib import Path

import pytest

from viral_dna_api.ai.billing import PriceCatalog
from viral_dna_api.models import (
    AnalysisJob,
    ModelRun,
    ModelRunStatus,
    ModelTask,
    SourceType,
    Video,
)
from viral_dna_api.pipeline import build_simulated_report
from viral_dna_api.sqlite_store import SQLiteStore


@pytest.mark.asyncio
async def test_sqlite_keeps_report_versions_and_model_ledger(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "viral-dna.db")
    video = Video(source_type=SourceType.UPLOAD, title="版本测试")
    first_analysis = AnalysisJob(video_id=video.id)
    second_analysis = AnalysisJob(video_id=video.id)
    await store.add_video(video)
    await store.add_analysis(first_analysis)
    await store.add_analysis(second_analysis)
    await store.save_report(build_simulated_report(video, first_analysis))
    await store.save_report(build_simulated_report(video, second_analysis))

    price = PriceCatalog().snapshot_for(
        "dashscope",
        "qwen3.7-plus-2026-05-26",
        1000,
    )
    await store.save_price_snapshot(price)
    run = ModelRun(
        analysis_id=second_analysis.id,
        video_id=video.id,
        task=ModelTask.SHOT_FACTS,
        shot_id="shot_001",
        provider="dashscope",
        requested_model="qwen3.7-plus-2026-05-26",
        resolved_model="qwen3.7-plus-2026-05-26",
        prompt_version="shot-facts-v1",
        schema_version="shot-visual-facts-v1",
        request_fingerprint="f" * 64,
        status=ModelRunStatus.COMPLETED,
        price_snapshot_id=price.id,
        measured_cost_micros=6000,
        result_payload={"title": "cached"},
    )
    await store.save_model_run(run)

    restarted = SQLiteStore(tmp_path / "viral-dna.db")
    latest = await restarted.get_report(video.id)
    first = await restarted.get_report_by_analysis(first_analysis.id)
    second = await restarted.get_report_by_analysis(second_analysis.id)
    runs = await restarted.list_model_runs(second_analysis.id)
    cached = await restarted.find_completed_model_run("f" * 64)
    restored_price = await restarted.get_price_snapshot(price.id)

    assert latest is not None and latest.analysis_id == second_analysis.id
    assert first is not None and first.analysis_id == first_analysis.id
    assert second is not None and second.analysis_id == second_analysis.id
    assert runs == [run]
    assert cached == run
    assert restored_price == price
