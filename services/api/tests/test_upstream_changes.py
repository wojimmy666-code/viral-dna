from __future__ import annotations

from uuid import uuid4

import pytest
from test_generation_jobs import _run
from test_image_batches import environment

from viral_dna_api.models import (
    ApprovalEvent,
    GenerationCandidate,
    GenerationCandidateStatus,
    GenerationKind,
    ImageGenerationCreate,
    ProductionRunStatus,
    ShotPlanUpdate,
    ShotVisualBeatUpdate,
    WorkflowItemStatus,
)
from viral_dna_api.production import (
    ProductionServiceError,
    _filesystem_path,
    _sync_shot_visual_beats,
)
from viral_dna_api.project_prompts import ProjectPromptUpdate, prompt_snapshot
from viral_dna_api.skill_workflow.contracts import GateDecision, SkillRun
from viral_dna_api.skill_workflow.service import SkillWorkflowService
from viral_dna_api.upstream_changes import changed_plan


async def adopt(env, shot, kind="image"):
    run = _run(env.project, shot, ProductionRunStatus.COMPLETED).model_copy(
        update={
            "kind": GenerationKind(kind),
            "provider": "real_provider",
            "model": "real_model",
            "visual_beat_id": shot.visual_beats[0].id if kind == "image" else None,
        }
    )
    path = (
        env.service.workspace.production_shot_root(env.project.record_id, env.project.id, shot.id)
        / ("images" if kind == "image" else "videos")
        / str(run.id)
        / "result.png"
    )
    _filesystem_path(path).parent.mkdir(parents=True, exist_ok=True)
    _filesystem_path(path).write_bytes(b"test generated media")
    candidate = GenerationCandidate(
        generation_run_id=run.id,
        ordinal=1,
        kind=kind,
        status="selected",
        relative_path=env.service.workspace.relative(path),
        sha256="a" * 64,
        metadata_relative_path=env.service.workspace.relative(path.with_suffix(".json")),
    )
    await env.store.save_generation_run(run)
    await env.store.save_generation_candidate(candidate)
    await env.store.save_approval_event(
        ApprovalEvent(
            project_id=env.project.id,
            revision_id=shot.revision_id,
            shot_plan_id=shot.id,
            candidate_id=candidate.id,
            target_kind=kind,
            decision="approved",
        )
    )
    if kind == "image":
        beats = [
            shot.visual_beats[0].model_copy(
                update={
                    "image_status": WorkflowItemStatus.APPROVED,
                    "approved_image_candidate_id": candidate.id,
                }
            )
        ]
        shot = _sync_shot_visual_beats(shot, beats, revision_id=shot.revision_id)
    else:
        shot = shot.model_copy(
            update={
                "video_status": WorkflowItemStatus.APPROVED,
                "approved_video_candidate_id": candidate.id,
            }
        )
    await env.store.save_shot_plan(shot)
    return shot, candidate, _filesystem_path(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_edit_keeps_adoptions_and_gate_open_without_confirmation(
    tmp_path, monkeypatch, durable
):
    env = await environment(tmp_path, monkeypatch, count=1, durable=durable)
    shot, image, _ = await adopt(env, env.shots[0])
    shot, video, _ = await adopt(env, shot, "video")
    old_snapshot = shot.model_dump(mode="json")
    updated = await env.service.update_visual_beat(
        shot.id,
        shot.visual_beats[0].id,
        ShotVisualBeatUpdate(
            expected_revision_id=env.project.current_revision_id, image_prompt="新的局部画面描述"
        ),
    )
    assert updated.plan.image_status == "approved"
    assert updated.plan.video_status == "approved"
    assert updated.plan.approved_image_candidate_id == image.id
    assert updated.plan.approved_video_candidate_id == video.id
    assert updated.plan.image_inputs_changed and updated.plan.video_inputs_changed
    gate = await env.service.gate_status(env.project.id)
    assert gate.allowed and not gate.blocker_messages
    assert gate.stale_shot_count == 1
    assert shot.model_dump(mode="json") == old_snapshot
    with pytest.raises(ProductionServiceError) as conflict:
        await env.service.update_shot(
            shot.id,
            ShotPlanUpdate(
                expected_revision_id=uuid4(),
                video_prompt="不能覆盖并发修改",
            ),
        )
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_legacy_stale_recovers_only_existing_human_adoption(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot, candidate, path = await adopt(env, env.shots[0])
    legacy = shot.model_copy(update={"image_status": WorkflowItemStatus.STALE})
    await env.store.save_shot_plan(legacy)
    view = await env.service.get_shot(shot.id)
    assert view.plan.image_status == "approved"
    assert view.plan.image_inputs_changed
    assert view.plan.approved_image_candidate_id == candidate.id
    assert (await env.store.get_shot_plan(shot.id)).image_status == "stale"
    assert (await env.service.gate_status(env.project.id)).allowed

    path.unlink()
    assert not (await env.service.gate_status(env.project.id)).allowed
    assert (await env.service.get_shot(shot.id)).plan.image_status != "approved"


@pytest.mark.asyncio
async def test_global_edit_is_part_specific_and_regeneration_preserves_adoption(
    tmp_path, monkeypatch
):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot, image, _ = await adopt(env, env.shots[0])
    shot, video, _ = await adopt(env, shot, "video")
    original = await env.service.get_prompt_context(env.project.id)
    for candidate, part in [(image, "image"), (video, "video")]:
        run = await env.store.get_generation_run(candidate.generation_run_id)
        await env.store.save_generation_run(
            run.model_copy(
                update={
                    "request_payload": {
                        "prompt_snapshot": prompt_snapshot("局部内容", original, part),
                    }
                }
            )
        )
    old_image_run = await env.store.get_generation_run(image.generation_run_id)
    stored_before = (await env.store.get_shot_plan(shot.id)).model_dump(mode="json")
    changed = await env.service.update_prompt_context(
        env.project.id,
        ProjectPromptUpdate(
            expected_revision_id=original.id,
            common_image_prompt="全片使用柔和暖光",
            common_video_prompt=original.common_video_prompt,
        ),
    )
    detail = await env.service.get_shot(shot.id)
    assert detail.plan.image_inputs_changed
    assert not detail.plan.video_inputs_changed
    assert detail.plan.approved_image_candidate_id == image.id
    assert detail.plan.approved_video_candidate_id == video.id
    assert (await env.store.get_shot_plan(shot.id)).model_dump(mode="json") == stored_before
    assert await env.store.get_generation_run(image.generation_run_id) == old_image_run
    assert (await env.service.gate_status(env.project.id)).allowed
    try:
        queued = await env.service.create_image_run(
            shot.id,
            ImageGenerationCreate(
                expected_revision_id=env.project.current_revision_id,
                input_mode="text_to_image",
                generation_intent="new_variation",
                candidate_count=1,
            ),
        )
        run = await env.store.get_generation_run(queued.id)
        assert run.request_payload["preserve_approval"] is True
        assert (
            run.request_payload["prompt_snapshot"]["global_prompt"] == changed.common_image_prompt
        )
        assert (await env.store.get_shot_plan(shot.id)).approved_image_candidate_id == image.id
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_legacy_gate_advisories_never_undo_human_approvals(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    service = SkillWorkflowService(env.store, None, None)
    run = SkillRun(
        project_id=uuid4(), skill_version_snapshot_id=uuid4(), run_contract_revision_id=uuid4()
    )
    human = GateDecision(
        project_id=run.project_id,
        skill_run_id=run.id,
        gate="brief_approved",
        decision="approve",
        actor_type="user",
    )
    system = human.model_copy(
        update={
            "id": uuid4(),
            "actor_type": "system",
            "decision": "request_revision",
            "note": "创作简报已更新",
        }
    )
    await env.store.save_gate_decision(human)
    await env.store.save_gate_decision(system)
    restored, effective = await service._upstream_compatible_run(run)
    assert restored.current_stage == "style_confirmation"
    assert service._gate_is_approved(effective, human.gate)
    assert len(await env.store.list_gate_decisions(run.id)) == 2  # Preserve the historical record.
    revoked = system.model_copy(update={"id": uuid4(), "actor_type": "user"})
    assert not revoked.is_upstream_advisory
    assert not service._gate_is_approved([revoked], human.gate)


@pytest.mark.asyncio
async def test_unadopted_or_explicitly_revoked_results_stay_unadopted(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot = env.shots[0]
    legacy = changed_plan(
        shot.model_copy(update={"image_status": WorkflowItemStatus.STALE}), image=True
    )
    assert legacy.image_status != "approved"
    shot, candidate, _ = await adopt(env, shot)
    await env.store.save_approval_event(
        ApprovalEvent(
            project_id=env.project.id,
            revision_id=shot.revision_id,
            shot_plan_id=shot.id,
            candidate_id=candidate.id,
            target_kind="image",
            decision="rejected",
            reason="人工取消采用",
        )
    )
    await env.store.save_shot_plan(
        shot.model_copy(update={"image_status": WorkflowItemStatus.STALE})
    )
    assert not (await env.service.gate_status(env.project.id)).allowed


@pytest.mark.asyncio
async def test_legacy_preview_recovers_last_adoption_not_the_newest_candidate(
    tmp_path, monkeypatch
):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot, original, _ = await adopt(env, env.shots[0])
    await env.store.save_generation_candidate(
        original.model_copy(update={"status": GenerationCandidateStatus.READY})
    )
    preview = original.model_copy(
        update={"id": uuid4(), "ordinal": 2, "status": GenerationCandidateStatus.SELECTED}
    )
    await env.store.save_generation_candidate(preview)
    legacy = shot.model_dump(mode="python")
    legacy.pop("image_inputs_changed")
    legacy.pop("video_inputs_changed")
    legacy.update(image_status="review_required", approved_image_candidate_id=None)
    for beat in legacy["visual_beats"]:
        beat.update(image_status="review_required", approved_image_candidate_id=None)
    legacy = type(shot).model_validate(legacy)
    await env.store.save_shot_plan(legacy)
    recovered = await env.service.get_shot(shot.id)
    assert recovered.plan.approved_image_candidate_id == original.id
    assert recovered.plan.approved_image_candidate_id != preview.id
    assert (await env.store.get_shot_plan(shot.id)).approved_image_candidate_id is None
    # Rejecting an unrelated preview is not the same as revoking the adopted image.
    await env.store.save_approval_event(
        ApprovalEvent(
            project_id=env.project.id,
            revision_id=shot.revision_id,
            shot_plan_id=shot.id,
            candidate_id=preview.id,
            target_kind="image",
            decision="rejected",
            reason="不采用新的预览，保留原先采用的图片",
        )
    )
    assert (await env.service.get_shot(shot.id)).plan.approved_image_candidate_id == original.id
    await env.store.save_approval_event(
        ApprovalEvent(
            project_id=env.project.id,
            revision_id=shot.revision_id,
            shot_plan_id=shot.id,
            candidate_id=original.id,
            target_kind="image",
            decision="revoked",
            reason="人工取消原先的采用",
        )
    )
    assert (await env.service.get_shot(shot.id)).plan.approved_image_candidate_id is None
