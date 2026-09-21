"""Generation grouping preserves film shots and never repeats whole clips."""

from uuid import uuid4

import pytest
from test_image_batches import environment
from test_upstream_changes import adopt

from viral_dna_api.models import CandidateApprovalRequest, VideoGenerationCreate, ProductionStep
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.video_group_models import VideoGenerationGroup, VideoGroupUpdate, VideoGroupAdopt
from viral_dna_api.video_groups import VideoGroups, execution_plan


async def setup_group(tmp_path, monkeypatch, durable=False):
    env = await environment(tmp_path, monkeypatch, count=3, durable=durable)
    for shot in env.shots:
        await adopt(env, shot)
    env.project = env.project.model_copy(update={"active_step": ProductionStep.SHOT_VIDEOS})
    await env.store.save_production_project(env.project)
    service = VideoGroups(env.service)
    group = VideoGenerationGroup(shot_plan_ids=[p.id for p in env.shots[:2]])
    state = await service.update(env.project.id, VideoGroupUpdate(expected_revision_id=env.project.current_revision_id, groups=[group]))
    return env, service, group, state


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_group_is_explicit_persistent_and_does_not_merge_film_shots(tmp_path, monkeypatch, durable):
    env, service, group, state = await setup_group(tmp_path, monkeypatch, durable)
    assert len(await env.store.list_shot_plans(env.project.id)) == 3
    row = state["groups"][0]
    assert len(row["images"]) == 2
    assert "硬切" in row["compiled_prompt"]
    assert len(row["input_plan"]["references"]) == 2
    project = await env.store.get_production_project(env.project.id)
    _, members, aggregate, owners, fingerprint = await service.projection(project, group.id)
    assert len(aggregate.visual_beats) == 2
    assert aggregate.duration_seconds == sum(p.duration_seconds for p in members)
    assert aggregate.visual_beats[0].transition_to_next_type == "cut"
    assert aggregate.visual_beats[0].transition_to_next_duration_seconds == 0
    assert len({p.id for p in owners.values()}) == 2
    original = await env.store.get_shot_plan(members[0].id)
    assert len(original.visual_beats) == 1
    assert original.duration_seconds != aggregate.duration_seconds
    payload = VideoGenerationCreate(expected_revision_id=project.current_revision_id, generation_group_id=group.id, expected_group_fingerprint=fingerprint)
    projected, _ = await env.service._group_video_plan(project, original, payload)
    assert projected.video_prompt == aggregate.video_prompt
    with pytest.raises(ProductionServiceError, match="生成组"):
        await env.service._group_video_plan(project, original, VideoGenerationCreate(expected_revision_id=project.current_revision_id))
    with pytest.raises(ProductionServiceError, match="费用"):
        await env.service._group_video_plan(project, original, payload.model_copy(update={"expected_group_fingerprint": "0" * 64}))
    with pytest.raises(ProductionServiceError, match="短于"):
        await env.service._group_video_plan(project, original, payload.model_copy(update={"duration_seconds": 0.5}))


@pytest.mark.asyncio
async def test_group_membership_and_revision_are_checked(tmp_path, monkeypatch):
    env, service, group, _ = await setup_group(tmp_path, monkeypatch)
    project = await env.store.get_production_project(env.project.id)
    for ids in ([env.shots[0].id, env.shots[2].id], [env.shots[0].id, uuid4()], [env.shots[1].id, env.shots[0].id]):
        with pytest.raises(ProductionServiceError):
            await service.update(project.id, VideoGroupUpdate(expected_revision_id=project.current_revision_id, groups=[VideoGenerationGroup(shot_plan_ids=ids)]))
    with pytest.raises(ProductionServiceError):
        await service.update(project.id, VideoGroupUpdate(expected_revision_id=uuid4(), groups=[]))
    with pytest.raises(ProductionServiceError, match="同时属于"):
        await service.update(project.id, VideoGroupUpdate(expected_revision_id=project.current_revision_id, groups=[group, VideoGenerationGroup(shot_plan_ids=group.shot_plan_ids)]))
    assert (await env.store.get_production_project(project.id)).video_generation_groups == [group]


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_reviewed_ranges_use_one_file_without_retiming_and_stale_inputs_block(tmp_path, monkeypatch, durable):
    env, service, group, _ = await setup_group(tmp_path, monkeypatch, durable)
    project = await env.store.get_production_project(env.project.id)
    _, members, _, _, fingerprint = await service.projection(project, group.id)
    _, candidate, path = await adopt(env, members[0], "video")
    run = await env.store.get_generation_run(candidate.generation_run_id)
    await env.store.save_generation_run(run.model_copy(update={"request_payload": {"generation_group_id": str(group.id), "expected_group_fingerprint": fingerprint}}))
    candidate = candidate.model_copy(update={"duration_seconds": 5})
    await env.store.save_generation_candidate(candidate)
    request = VideoGroupAdopt(expected_revision_id=project.current_revision_id, candidate_id=candidate.id,
        cuts=[{"shot_plan_id": members[0].id, "trim_in_seconds": 0.2, "trim_out_seconds": 1.2},
              {"shot_plan_id": members[1].id, "trim_in_seconds": 2.1, "trim_out_seconds": 3.4}], content_reviewed=True)
    with pytest.raises(ProductionServiceError, match="切点"):
        await env.service.approve_candidate(candidate.id, CandidateApprovalRequest(expected_revision_id=project.current_revision_id, decision="approved"))
    overlap = request.model_copy(deep=True)
    overlap.cuts[1].trim_in_seconds = 0.8
    with pytest.raises(ProductionServiceError, match="重叠"):
        await service.adopt(project.id, group.id, overlap)
    await service.adopt(project.id, group.id, request)
    project = await env.store.get_production_project(project.id)
    plans = await env.store.list_shot_plans(project.id)
    assert await env.service._has_valid_approved_video_output(project, plans[1])
    manifest = await env.service._build_editing_handoff(project, project.current_revision_id)
    assert len(manifest.clips) == 2
    assert {c.candidate_id for c in manifest.clips} == {candidate.id}
    assert [c.trim_in_seconds for c in manifest.clips] == [0.2, 2.1]
    assert [c.video_playback_rate for c in manifest.clips] == [1, 1]
    assert manifest.timeline_duration_seconds == pytest.approx(2.3)
    assert path.is_file()
    await env.store.save_shot_plan(plans[1].model_copy(update={"video_prompt": "新的动作要求"}))
    assert not await env.service._has_valid_approved_video_output(project, plans[0])


def test_group_clip_ranges_remain_separate_from_logical_durations():
    from pydantic import ValidationError
    from viral_dna_api.video_group_models import VideoGroupClip
    with pytest.raises(ValidationError):
        VideoGroupClip(group_id=uuid4(), candidate_id=uuid4(), input_fingerprint="a"*64, trim_in_seconds=2, trim_out_seconds=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_invalid_group_keeps_running_tasks_and_readonly_history(tmp_path, monkeypatch, durable):
    from viral_dna_api.models import ProductionRunStatus
    env, service, group, _ = await setup_group(tmp_path, monkeypatch, durable)
    _, candidate, _ = await adopt(env, env.shots[0], "video")
    run = await env.store.get_generation_run(candidate.generation_run_id)
    run = run.model_copy(update={"request_payload": {"generation_group_id": str(group.id)}})
    await env.store.save_generation_run(run)
    active = run.model_copy(update={"id": uuid4(), "status": ProductionRunStatus.RUNNING})
    await env.store.save_generation_run(active)
    shot = await env.store.get_shot_plan(env.shots[1].id)
    invalid = shot.model_copy(deep=True)
    for beat in invalid.visual_beats:
        beat.approved_image_candidate_id = None
    await env.store.save_shot_plan(invalid)
    row = (await service.state(env.project.id))["groups"][0]
    assert row["error"]
    assert {str(r.id) for r in row["runs"]} == {str(run.id), str(active.id)}
    assert set(row["stale_run_ids"]) == {str(run.id), str(active.id)}
    historical = next(r for r in row["runs"] if str(r.id) == str(run.id))
    assert historical.candidates


@pytest.mark.asyncio
async def test_group_requires_ordered_complete_images_and_real_owner_validation(tmp_path, monkeypatch):
    from viral_dna_api.video_generation.catalog import load_video_model_catalog
    env, service, group, state = await setup_group(tmp_path, monkeypatch)
    project = await env.store.get_production_project(env.project.id)
    _, _, aggregate, _, fingerprint = await service.projection(project, group.id)
    cap = load_video_model_catalog().option("minimax_h3").capability.model_copy(update={
        "multi_image_reference": True, "ordered_reference_images": True, "image_to_video": True,
        "maximum_reference_images": 20})
    payload = VideoGenerationCreate(expected_revision_id=project.current_revision_id,
        generation_group_id=group.id, expected_group_fingerprint=fingerprint,
        input_plan=state["groups"][0]["input_plan"], audio_strategy="muted")
    await env.service._validate_video_input_plan(project, aggregate, payload, cap)
    reversed_payload = payload.model_copy(deep=True)
    for index, ref in enumerate(reversed(reversed_payload.input_plan.references), 1):
        ref.order = index
    with pytest.raises(ProductionServiceError, match="倒序"):
        await env.service._validate_video_input_plan(project, aggregate, reversed_payload, cap)
    incomplete = payload.model_copy(deep=True)
    incomplete.input_plan.references.pop()
    with pytest.raises(ProductionServiceError, match="省略"):
        await env.service._validate_video_input_plan(project, aggregate, incomplete, cap)
    with pytest.raises(ProductionServiceError, match="有序多图"):
        await env.service._validate_video_input_plan(project, aggregate, payload, cap.model_copy(update={"ordered_reference_images": False}))
    with pytest.raises(ProductionServiceError, match="最多支持"):
        await env.service._validate_video_input_plan(project, aggregate, payload, cap.model_copy(update={"maximum_reference_images": 1}))


@pytest.mark.asyncio
async def test_group_prompt_document_is_live_projection(tmp_path, monkeypatch):
    from viral_dna_api.production_prompt_documents import ProductionPromptDocuments, PromptDocumentUpdate, document_bodies
    env, service, group, state = await setup_group(tmp_path, monkeypatch)
    documents = ProductionPromptDocuments(env.service)
    doc = await documents.get(env.project.id)
    assert doc["shots"][0]["video_group_id"] == str(group.id)
    assert doc["shots"][2]["video_group_id"] is None
    assert doc["video_groups"][0]["compiled_prompt"] == state["groups"][0]["compiled_prompt"]
    body = document_bodies(doc)
    body["shots"][1]["video_prompt"] = "人物居中向左行走，背景移向右侧"
    saved = await documents.save(env.project.id, PromptDocumentUpdate(expected_token=doc["token"], **body))
    assert "背景移向右侧" in saved["video_groups"][0]["compiled_prompt"]
    assert (await service.state(env.project.id))["groups"][0]["input_fingerprint"] != state["groups"][0]["input_fingerprint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("policy,rate", [("legacy", 4), ("trim", 1)])
async def test_new_film_short_independent_clips_trim_without_changing_legacy(tmp_path, monkeypatch, policy, rate):
    env = await environment(tmp_path, monkeypatch, count=1)
    project = env.project.model_copy(update={"active_step": ProductionStep.SHOT_VIDEOS, "clip_timing_policy": policy})
    await env.store.save_production_project(project)
    _, candidate, _ = await adopt(env, env.shots[0], "video")
    await env.store.save_generation_candidate(candidate.model_copy(update={"duration_seconds": env.shots[0].duration_seconds * 4}))
    manifest = await env.service._build_editing_handoff(project, project.current_revision_id)
    assert manifest.clips[0].video_playback_rate == rate
    assert manifest.clips[0].timeline_duration_seconds == env.shots[0].duration_seconds


@pytest.mark.asyncio
async def test_execution_passes_cross_shot_reference_files_without_persisting_synthetic_shot(tmp_path, monkeypatch):
    from asyncio import Event
    from types import SimpleNamespace
    from viral_dna_api.video_generation.catalog import load_video_model_catalog
    env, service, group, state = await setup_group(tmp_path, monkeypatch)
    project = await env.store.get_production_project(env.project.id)
    _, members, aggregate, _, fingerprint = await service.projection(project, group.id)
    _, candidate, _ = await adopt(env, members[0], "video")
    run = await env.store.get_generation_run(candidate.generation_run_id)
    payload = VideoGenerationCreate(expected_revision_id=project.current_revision_id,
        generation_group_id=group.id, expected_group_fingerprint=fingerprint,
        input_plan=state["groups"][0]["input_plan"], audio_strategy="muted")
    run = run.model_copy(update={"request_payload": payload.model_dump(mode="json")})
    cap = load_video_model_catalog().option("minimax_h3").capability.model_copy(update={
        "multi_image_reference": True, "ordered_reference_images": True, "image_to_video": True,
        "maximum_reference_images": 20})
    calls = []

    async def generate(project_arg, plan, revision, references, **options):
        calls.append(plan)
        assert len(references) == 2
        assert all(reference.path.is_file() for reference in references)
        assert references[0].visual_beat_id == members[0].visual_beats[0].id
        assert references[1].visual_beat_id == members[1].visual_beats[0].id
        assert plan.duration_seconds == sum(p.duration_seconds for p in members)
        assert "硬切" in plan.video_prompt
        return run, [candidate]

    env.service.video_gateway = SimpleNamespace(resolve_identity=lambda **_: (SimpleNamespace(capability=cap), None), generate=generate)
    await env.service._execute_video_run_request(members[0].id, payload, run_id=run.id, cancellation=Event(), queued_run=run)
    assert len(calls) == 1
    persisted = await env.store.get_shot_plan(members[0].id)
    assert len(persisted.visual_beats) == 1
    assert persisted.duration_seconds == members[0].duration_seconds
    assert persisted.video_prompt == members[0].video_prompt
