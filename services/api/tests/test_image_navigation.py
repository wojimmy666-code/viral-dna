from datetime import timedelta
from uuid import uuid4

import pytest
from test_generation_jobs import _run
from test_image_batches import environment

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationCandidateStatus,
    ImageExecutionMode,
    ProductionRunStatus,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_navigation_uses_adopted_then_latest_generated_not_preview_selection(
    tmp_path, monkeypatch, durable
):
    env = await environment(tmp_path, monkeypatch, count=2, durable=durable)
    plans = await env.store.list_shot_plans(env.project.id)
    plan = plans[0]
    run = _run(env.project, plan, ProductionRunStatus.COMPLETED)
    await env.store.save_generation_run(run)
    original = GenerationCandidate(
        generation_run_id=run.id,
        ordinal=1,
        kind="image",
        relative_path="old.png",
        thumbnail_relative_path="old.webp",
        metadata_relative_path="old.json",
        sha256="a" * 64,
        status=GenerationCandidateStatus.SELECTED,
    )
    latest = original.model_copy(
        update={
            "id": uuid4(),
            "ordinal": 2,
            "created_at": original.created_at + timedelta(seconds=1),
            "status": GenerationCandidateStatus.READY,
        }
    )
    await env.store.save_generation_candidate(original)
    await env.store.save_generation_candidate(latest)

    # The navigation path must not fall back to the expensive detail/history APIs.
    async def forbidden(*args, **kwargs):
        pytest.fail("navigation loaded full generation history")

    monkeypatch.setattr(env.store, "list_generation_runs", forbidden)
    monkeypatch.setattr(env.store, "list_generation_candidates_by_run_ids", forbidden)
    view = await env.service.shot_navigation(env.project.id)
    assert view[0]["image_preview"]["candidate_id"] == str(latest.id)
    assert view[0]["image_preview"]["kind"] == "candidate_image"
    assert view[1]["image_preview"] is None
    assert "generation_runs" not in view[0]

    # Adoption beats a newer result, even while a later attempt fails/runs.
    await env.store.save_shot_plan(
        plan.model_copy(update={"approved_image_candidate_id": original.id})
    )
    assert (await env.service.shot_navigation(env.project.id))[0]["image_preview"][
        "candidate_id"
    ] == str(original.id)
    assert (await env.service.shot_navigation(env.project.id))[0]["image_preview"][
        "kind"
    ] == "approved_image"
    await env.store.save_shot_plan(plan)
    await env.store.save_generation_candidate(
        latest.model_copy(update={"status": GenerationCandidateStatus.ARCHIVED})
    )
    assert (await env.service.shot_navigation(env.project.id))[0]["image_preview"][
        "candidate_id"
    ] == str(original.id)

    # An unrelated project's image and a source/reference frame cannot fill an empty Skill shot.
    alien_run = run.model_copy(
        update={"id": uuid4(), "project_id": uuid4(), "shot_plan_id": plans[1].id}
    )
    await env.store.save_generation_run(alien_run)
    await env.store.save_generation_candidate(
        original.model_copy(update={"id": uuid4(), "generation_run_id": alien_run.id})
    )
    source_run = run.model_copy(
        update={
            "id": uuid4(),
            "shot_plan_id": plans[1].id,
            "execution_mode": ImageExecutionMode.SOURCE_FRAME,
        }
    )
    await env.store.save_generation_run(source_run)
    await env.store.save_generation_candidate(
        original.model_copy(update={"id": uuid4(), "generation_run_id": source_run.id})
    )
    assert (await env.service.shot_navigation(env.project.id))[1]["image_preview"] is None
