"""No paid calls: adopted pixels, not their production provenance, feed video."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from test_image_batches import environment
from test_upstream_changes import adopt
from viral_dna_api.models import (ProductionStep, VideoGenerationCreate, VideoPromptMention,
                                 VideoGenerationInputPlan, ShotVideoGenerationDraft, ProductionOriginType,
                                 ShotPlanFieldsUpdate)
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.project_prompts import prompt_snapshot
from viral_dna_api.video_generation.drafts import current_default_input_plan
from viral_dna_api.video_generation.input_policy import VIDEO_INPUT_POLICY, video_prompt_snapshot, selected_video_plan
from viral_dna_api.video_group_models import VideoGenerationGroup
from viral_dna_api.video_groups import VideoGroups


async def five_images(tmp_path, monkeypatch, origin="skill_run"):
    env = await environment(tmp_path, monkeypatch, count=5)
    for shot in env.shots:
        await adopt(env, shot)
    project = env.project.model_copy(update={"active_step": ProductionStep.SHOT_VIDEOS, "origin_type": ProductionOriginType(origin),
        **({"video_id": uuid4(), "base_analysis_id": uuid4(), "source_prompt_package_id": uuid4()} if origin == "analysis" else {})})
    group = VideoGenerationGroup(shot_plan_ids=[p.id for p in env.shots])
    project = project.model_copy(update={"video_generation_groups": [group]})
    await env.store.save_production_project(project)
    service = VideoGroups(env.service)
    context = await env.service.get_prompt_context(project.id)
    context = context.model_copy(update={"shot_style_snapshots": {
        str(p.id): {"label": "旧 D" if i == 0 else "E", "applies_to": ["image", "video"],
                    "reference_image": {"asset_id": str(uuid4())} if i == 0 else None}
        for i, p in enumerate(env.shots)}})
    env.service.get_prompt_context = AsyncMock(return_value=context)
    state = await service.state(project.id)
    return env, service, group, state, context


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["analysis", "skill_run"])
async def test_five_different_image_styles_are_five_video_inputs(tmp_path, monkeypatch, origin):
    env, service, group, state, context = await five_images(tmp_path, monkeypatch, origin)
    row = state["groups"][0]
    assert row["error"] is None
    assert len(row["images"]) == len(row["input_plan"]["references"]) == 5
    assert row["input_plan"]["sources"] == ["approved_images"]
    assert row["input_plan"]["input_policy"] == VIDEO_INPUT_POLICY
    assert "风格配置" not in row["compiled_prompt"]
    before = row["input_fingerprint"]
    shot = await env.store.get_shot_plan(env.shots[0].id)
    changed = shot.model_copy(deep=True)
    changed.image_prompt = "修改上游图片提示词"
    changed.visual_beats[0].image_prompt = "改变上游构图但保留采用文件"
    changed.visual_beats[0].image_inputs_changed = True
    await env.store.save_shot_plan(changed)
    env.service.get_prompt_context.return_value = context.model_copy(update={"shot_style_snapshots": {}})
    assert (await service.state(env.project.id))["groups"][0]["input_fingerprint"] == before
    changed.visual_beats[0].approved_image_candidate_id = uuid4()
    await env.store.save_shot_plan(changed)
    assert (await service.state(env.project.id))["groups"][0]["input_fingerprint"] != before


@pytest.mark.asyncio
async def test_missing_image_and_legacy_tags_keep_repairable_image_list(tmp_path, monkeypatch):
    env, service, group, state, _ = await five_images(tmp_path, monkeypatch)
    shot = await env.store.get_shot_plan(env.shots[1].id)
    mention = VideoPromptMention(reference_kind="project_asset", reference_id=uuid4(), label="资产/人物", role="actor_identity")
    shot = shot.model_copy(update={"video_prompt": "@资产/人物 向左行走", "video_prompt_mentions": [mention]})
    await env.store.save_shot_plan(shot)
    row = (await service.state(env.project.id))["groups"][0]
    assert len(row["images"]) == 5 and "尚未确认" in row["error"]
    assert "@资产/人物" in (await env.store.get_shot_plan(shot.id)).video_prompt
    draft = ShotVideoGenerationDraft(project_id=shot.project_id, shot_plan_id=shot.id,
        model_alias="minimax_h3", resolution="720P", duration_seconds=4, video_prompt=shot.video_prompt,
        video_prompt_mentions=[mention], input_plan=VideoGenerationInputPlan(input_policy=VIDEO_INPUT_POLICY,
            sources=["project_assets"], references=[mention]))
    await env.store.compare_and_swap_video_generation_draft(draft, expected_draft_version=0)
    row = (await service.state(env.project.id))["groups"][0]
    assert row["error"] is None
    assert len(row["input_plan"]["references"]) == 6
    assert row["input_plan"]["references"][-1]["reference_id"] == str(mention.reference_id)
    for beat in shot.visual_beats:
        beat.approved_image_candidate_id = None
    await env.store.save_shot_plan(shot)
    row = (await service.state(env.project.id))["groups"][0]
    assert len(row["images"]) == 4 and "没有已采用图片" in row["error"]
    assert len(row["shots"]) == 5


@pytest.mark.asyncio
async def test_new_queue_freezes_only_visible_inputs(tmp_path, monkeypatch):
    env, service, group, state, context = await five_images(tmp_path, monkeypatch)
    row = state["groups"][0]
    env.service._validate_skill_video_contract = AsyncMock()
    gateway = env.service.video_gateway
    resolve = gateway.resolve_identity
    def resolve_identity(**kwargs):
        identity, resolved = resolve(**kwargs)
        return replace(identity, capability=identity.capability.model_copy(update={
            "multi_image_reference": True, "ordered_reference_images": True, "maximum_reference_images": 20})), resolved
    monkeypatch.setattr(gateway, "resolve_identity", resolve_identity)
    payload = VideoGenerationCreate(expected_revision_id=row.get("revision_id") or state["expected_revision_id"],
        generation_group_id=group.id, expected_group_fingerprint=row["input_fingerprint"],
        input_plan=row["input_plan"], audio_strategy="muted")
    run = await env.service._enqueue_video_run(env.shots[0].id, payload)
    frozen = run.request_payload["prompt_snapshot"]
    assert frozen["input_policy"] == VIDEO_INPUT_POLICY
    assert "visual_style_snapshot" not in frozen and "shot_style_snapshots" not in frozen
    assert len(run.request_payload["input_plan"]["references"]) == 5
    assert run.request_payload["input_plan"]["sources"] == ["approved_images"]
    # The old serializer is still available to frozen historical retries.
    legacy = prompt_snapshot("原始动作", context, "video", shot_key=str(env.shots[0].id))
    assert "visual_style_snapshot" in legacy
    assert "visual_style_snapshot" not in video_prompt_snapshot("原始动作", context, shot_key=str(env.shots[0].id))
    assert run.status == "queued"  # never scheduled and never sent to a model


@pytest.mark.asyncio
async def test_legacy_retry_enqueue_preserves_frozen_style_and_input_policy(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot, _, _ = await adopt(env, env.shots[0])
    shot = shot.model_copy(update={"video_prompt": "历史视频动作"})
    await env.store.save_shot_plan(shot)
    await env.store.save_production_project(env.project.model_copy(update={"active_step": ProductionStep.SHOT_VIDEOS}))
    env.service._validate_skill_video_contract = AsyncMock()
    context = await env.service.get_prompt_context(env.project.id)
    frozen = prompt_snapshot("历史视频动作", context, "video", shot_key=str(shot.id))
    frozen["visual_style_snapshot"] = {"label": "历史风格", "applies_to": ["video"]}
    source_id = uuid4()
    payload = VideoGenerationCreate(expected_revision_id=env.project.current_revision_id, audio_strategy="muted", duration_seconds=4)
    run = await env.service._enqueue_video_run(shot.id, payload, retry_of_run_id=source_id, retry_count=1, frozen_prompt=frozen)
    assert run.status == "queued"
    assert run.retry_of_run_id == source_id
    assert run.request_payload["prompt_snapshot"] == frozen
    assert run.request_payload["input_plan"]["input_policy"] is None


@pytest.mark.asyncio
async def test_image_only_edits_do_not_mark_existing_video_inputs_changed(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot, _, _ = await adopt(env, env.shots[0])
    shot, video, _ = await adopt(env, shot, "video")
    payload = ShotPlanFieldsUpdate(image_prompt="只调整下次制图的光照")
    updated = env.service._apply_shot_fields(shot, payload, {"image_prompt"}, uuid4(), image_changed=True, video_changed=False)
    assert updated.image_inputs_changed and not updated.video_inputs_changed
    assert updated.approved_video_candidate_id == video.id
    _, changed = await env.service._mark_plans_stale([shot], {shot.id}, uuid4())
    assert changed[0].image_inputs_changed and not changed[0].video_inputs_changed
    _, resized = await env.service._mark_plans_stale([shot], {shot.id}, uuid4(), video_changed=True)
    assert resized[0].video_inputs_changed


@pytest.mark.asyncio
async def test_defaults_and_execution_filter_image_assets_without_mutating_source(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    shot = env.shots[0]
    mention = VideoPromptMention(reference_kind="project_asset", reference_id=uuid4(), label="原图人物", role="actor_identity")
    binding = SimpleNamespace(id=uuid4())
    shot = shot.model_copy(update={"video_prompt_mentions": [mention], "managed_asset_bindings": [binding]})
    inputs = current_default_input_plan(shot)
    assert not any(r.reference_kind != "approved_image" for r in inputs.references)
    view = selected_video_plan(shot, inputs)
    assert view.managed_asset_bindings == [] and view.video_prompt_mentions == []
    assert shot.managed_asset_bindings == [binding] and shot.video_prompt_mentions == [mention]
