import asyncio
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_creative_brief import BRIEF, landmark_response
from test_creative_concepts import finish, setup
from test_creative_responses import install_real_adapter, mock_model_http

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeGenerateRequest, ViralConceptSet
from viral_dna_api.viral_insights.creative_recovery import recover_saved_ideas, repair_database


def saved_failure(monkeypatch, tmp_path):
    response = landmark_response()
    for idea in response["ideas"]:
        idea["brief_checks"][0]["evidence"][0]["quote"] = (
            "巴黎埃菲尔铁塔下...画面以硬切转往下一地点。"
        )
    calls = mock_model_http(monkeypatch, [(json.dumps(response), "stop")])
    database = tmp_path / "workspace.db"

    async def seed():
        repo, report, categories, _, service = await setup(SQLiteStore(database))
        install_real_adapter(service)
        completed = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id, feedback=BRIEF
                ),
            ),
        )
        assert completed.status == "completed"
        # Reproduce exactly the pre-fix rejection, retaining the saved model response.
        failed = completed.model_copy(
            update={
                "status": "failed",
                "ideas": [],
                "error_code": "creative_brief_unmet",
                "error_message": "引用必须来自实际关键画面或分镜正文",
            }
        )
        await repo.save_viral_concept_set(failed)
        (run,) = await repo.list_model_runs(report.analysis_id)
        return failed, run

    failed, run = asyncio.run(seed())
    return database, failed, run, calls


def raw_rows(database, table):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY record_key").fetchall()  # noqa: S608


def test_recovery_previews_then_backs_up_one_batch_without_model_call(monkeypatch, tmp_path):
    database, failed, run, calls = saved_failure(monkeypatch, tmp_path)
    batches_before = raw_rows(database, "viral_concept_sets")
    ledger_before = raw_rows(database, "model_runs")
    backup = tmp_path / "backup" / "workspace.db"
    preview = repair_database(database, failed.id)
    assert preview["preview"] and len(preview["ideas"]) == 3
    assert not backup.exists()
    assert raw_rows(database, "viral_concept_sets") == batches_before
    result = repair_database(database, failed.id, apply=True, backup=backup)
    assert result["recovered"] and result["additional_model_calls"] == 0
    assert raw_rows(backup, "viral_concept_sets") == batches_before
    assert raw_rows(database, "model_runs") == ledger_before
    repaired = ViralConceptSet.model_validate_json(raw_rows(database, "viral_concept_sets")[0][1])
    assert repaired.status == "completed" and repaired.error_code is None
    assert repaired.recovery.source_model_run_id == run.id
    assert repaired.recovery.previous_error_message == failed.error_message
    assert repaired.recovery.previous_error_code == failed.error_code
    for key in (
        "id",
        "input_snapshot",
        "request_id",
        "created_at",
        "completed_at",
        "started_at",
        "model_runs",
        "model_cost_micros",
        "cost_status",
        "model_elapsed_ms",
        "revision",
    ):
        assert getattr(repaired, key) == getattr(failed, key), key
    assert repaired.ideas[0].summary == run.result_payload["ideas"][0]["summary"]
    assert repaired.ideas[0].key_scenes == run.result_payload["ideas"][0]["key_scenes"]
    stable = raw_rows(database, "viral_concept_sets")
    assert repair_database(database, failed.id, apply=True, backup=backup)["unchanged"]
    assert raw_rows(database, "viral_concept_sets") == stable
    assert len(calls) == 1


@pytest.mark.parametrize("invalid", ["run", "brief", "status", "quote", "unmet"])
def test_recovery_refuses_unrelated_or_still_invalid_results(monkeypatch, tmp_path, invalid):
    database, failed, run, calls = saved_failure(monkeypatch, tmp_path)
    before = raw_rows(database, "viral_concept_sets")
    if invalid == "run":
        run.id = uuid4()
    elif invalid == "brief":
        failed.feedback = "不同的补充想法"
    elif invalid == "status":
        failed.status = "running"
    elif invalid == "quote":
        run.result_payload["ideas"][0]["brief_checks"][0]["evidence"][0]["quote"] += "虚构画面"
    elif invalid == "unmet":
        run.result_payload["ideas"][0]["brief_checks"][1]["satisfied"] = False
    with pytest.raises(ValueError):
        recover_saved_ideas(failed, run)
    assert raw_rows(database, "viral_concept_sets") == before and len(calls) == 1


def test_recovery_requires_new_backup_and_refuses_active_creative_tasks(monkeypatch, tmp_path):
    database, failed, _, _ = saved_failure(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="备份"):
        repair_database(database, failed.id, apply=True)
    with pytest.raises(ValueError, match="备份"):
        repair_database(database, failed.id, apply=True, backup=database)
    active = failed.model_copy(update={"id": uuid4(), "status": "queued"})
    asyncio.run(SQLiteStore(database).save_viral_concept_set(active))
    before = raw_rows(database, "viral_concept_sets")
    backup = tmp_path / "before.db"
    with pytest.raises(ValueError, match="运行中"):
        repair_database(database, failed.id, apply=True, backup=backup)
    assert raw_rows(database, "viral_concept_sets") == before
    assert raw_rows(backup, "viral_concept_sets") == before
