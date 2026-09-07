from __future__ import annotations

from uuid import uuid4

import pytest
from test_generation_jobs import _project, _shot, _workspace
from test_image_batches import environment, finish, until
from test_storyboard_prompt_editor import payload, runtime

from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.models import ShotVideoGenerationDraft
from viral_dna_api.production import ProductionService
from viral_dna_api.project_prompts import (
    ProjectPromptRevision,
    ProjectPromptService,
    ProjectPromptUpdate,
    PromptRevisionConflict,
    extract_shared,
    local_prompt,
    prompt_snapshot,
)
from viral_dna_api.skill_workflow.contracts import GateDecisionRequest, SkillGate
from viral_dna_api.skill_workflow.service import SkillWorkflowServiceError
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore


def edit_context(context, **changes):
    return ProjectPromptUpdate(
        expected_revision_id=context.id,
        common_image_prompt=changes.get("image", context.common_image_prompt),
        common_video_prompt=changes.get("video", context.common_video_prompt),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_shared_revision_is_durable_cas_scoped_and_clearable(tmp_path, durable):
    store = SQLiteStore(tmp_path / "prompts.db") if durable else InMemoryStore()
    service = ProjectPromptService(store)
    scope = uuid4()
    original = await service.current(scope, image="【全片色彩】暖色", video="缓慢运镜")
    assert await store.list_project_prompt_revisions(scope) == []  # GET never migrates history.
    saved = await service.save(original, edit_context(original, image="【全片色彩】冷色"))
    if durable:
        service = ProjectPromptService(SQLiteStore(tmp_path / "prompts.db"))
    assert (await service.current(scope)).id == saved.id
    assert (await service.current(uuid4())).common_image_prompt == ""
    with pytest.raises(PromptRevisionConflict):
        await service.save(await service.current(scope), edit_context(original, video="手持"))
    cleared = await service.save(await service.current(scope), edit_context(saved, image=""))
    latest = await service.current(scope)
    assert cleared.common_image_prompt == latest.common_image_prompt == ""
    assert latest.common_video_prompt == "缓慢运镜"
    assert local_prompt("【全片色彩】暖色\n【主体】产品近景", latest, "image") == "【主体】产品近景"
    assert local_prompt("【全片色彩】冷色\n【主体】产品近景", latest, "image") == "【主体】产品近景"
    assert len(await store.list_project_prompt_revisions(scope)) == 2


def test_conservative_extraction_preserves_manual_content_and_static_projection():
    full = ["【全片色彩】低饱和\n【主体】杯子", "【全片色彩】低饱和\n【主体】水瓶"]
    assert extract_shared(full, "image") == "【全片色彩】低饱和"
    assert extract_shared([full[0], full[1].replace("低饱和", "高饱和")], "image") == ""
    context = ProjectPromptRevision(project_id=uuid4(), common_image_prompt="【全片色彩】低饱和")
    manual = "手写 ARRI @asset/id。\n保持段落\n【主体】杯子"
    assert local_prompt(manual, context, "image") == manual
    assert local_prompt(full[0], context, "image") == "【主体】杯子"
    result = prompt_snapshot("【连续性锁定】沿用上一镜\n【主体】杯子", context, "image")
    assert "连续性" not in result["compiled_prompt"]
    assert result["compiled_prompt"] == "【全片色彩】低饱和\n\n【主体】杯子"


@pytest.mark.asyncio
async def test_analysis_legacy_globals_survive_first_local_edit_without_rewriting_history(
    tmp_path, monkeypatch
):
    store = InMemoryStore()
    service = ProductionService(store, _workspace(tmp_path, monkeypatch))
    project = _project()
    shot = _shot(project).model_copy(update={"image_prompt": "【全片色彩】暖色\n【主体】产品"})
    shot = shot.model_copy(
        update={
            "visual_beats": [
                beat.model_copy(update={"image_prompt": shot.image_prompt})
                for beat in shot.visual_beats
            ]
        }
    )
    await store.save_production_project(project)
    await store.save_shot_plan(shot)
    original = shot.model_dump(mode="json")
    context = await service.get_prompt_context(project.id)
    assert service._local_prompt_view(shot, context).image_prompt == "【主体】产品"
    assert (await store.get_shot_plan(shot.id)).model_dump(mode="json") == original
    await ProjectPromptService(store).retain_baseline(project)
    await store.save_shot_plan(shot.model_copy(update={"image_prompt": "【主体】新的产品"}))
    assert (await service.get_prompt_context(project.id)).common_image_prompt == "【全片色彩】暖色"
    updated = await service.update_prompt_context(project.id, edit_context(context, image="冷色"))
    frozen = prompt_snapshot("【主体】新的产品", updated, "image")
    await service.update_prompt_context(project.id, edit_context(updated, image="中性灰"))
    assert frozen["compiled_prompt"] == "冷色\n\n【主体】新的产品"


@pytest.mark.asyncio
async def test_batch_resume_uses_original_global_local_snapshot(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=5, durable=True)
    prompts = []
    generate = env.gateway.generate

    async def capture(project, shot, *args, **kwargs):
        prompts.append(shot.image_prompt)
        return await generate(project, shot, *args, **kwargs)

    env.gateway.generate = capture
    current = await env.service.get_prompt_context(env.project.id)
    first = await env.service.update_prompt_context(
        env.project.id, edit_context(current, image="【全片色彩】暖色")
    )
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        await until(lambda: env.gateway.active == 3)
        await env.batch.stop(env.project.id, batch.id)
        await finish(env, batch)
        await env.service.update_prompt_context(
            env.project.id, edit_context(first, image="【全片色彩】冷色")
        )
        await env.batch.resume(env.project.id, batch.id)
        result = await finish(env, batch)
        assert result.status == "completed"
        assert len(prompts) == 5
        assert all(text.startswith("【全片色彩】暖色") and "冷色" not in text for text in prompts)
        assert all(
            item.prompt_snapshot["global_revision_id"] == str(first.id) for item in result.items
        )
        preview = await env.batch.preview(
            env.project.id,
            ImageBatchRequest(
                expected_revision_id=(
                    await env.store.get_production_project(env.project.id)
                ).current_revision_id
            ),
        )
        assert all(
            item.prompt_snapshot["global_prompt"] == "【全片色彩】冷色" for item in preview.items
        )
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_outline_and_production_share_globals_and_latest_video_draft(tmp_path, monkeypatch):
    env = await runtime()
    production = ProductionService(env.store, _workspace(tmp_path, monkeypatch))
    env.service.production_service = production
    await env.service.decide_gate(
        env.run.id,
        SkillGate.STORYBOARD_APPROVED,
        GateDecisionRequest(
            decision="approve",
            related_revision_ids=[env.outline.id, env.manifest.id],
        ),
    )
    project = await env.store.get_project(env.project.id)
    production_id = project.source_binding.production_project_id
    before = (await env.service.workspace(project.id)).shot_manifest
    context = await env.service.get_prompt_context(project.id)
    updated = await production.update_prompt_context(
        production_id, edit_context(context, image="【全片色彩】冷色")
    )
    assert (await env.service.get_prompt_context(project.id)).id == updated.id
    assert (
        await env.service.workspace(project.id)
    ).shot_manifest.common_image_prompt == "【全片色彩】冷色"
    plan = (await env.store.list_shot_plans(production_id))[0]
    video_draft = ShotVideoGenerationDraft(
        project_id=production_id,
        shot_plan_id=plan.id,
        model_alias="test-video",
        resolution="720P",
        duration_seconds=3,
        video_prompt="独立修改的视频局部正文",
    )
    assert await env.store.compare_and_swap_video_generation_draft(
        video_draft, expected_draft_version=0
    )
    live = (await env.service.workspace(project.id)).shot_manifest
    assert live.shots[0].video_prompt_body == video_draft.video_prompt
    with pytest.raises(SkillWorkflowServiceError):
        await env.service.put_storyboard_prompt_draft(project.id, payload(before))
    edit = payload(live)
    edit.shots[0].video_prompt_body = "从大纲修改的局部视频正文"
    saved = await env.service.put_storyboard_prompt_draft(project.id, edit)
    assert saved.shots[0].video_prompt_body == edit.shots[0].video_prompt_body
    assert (await env.store.get_video_generation_draft(plan.id)).video_prompt == edit.shots[
        0
    ].video_prompt_body
    assert (await env.store.get_shot_plan(plan.id)).video_prompt == edit.shots[0].video_prompt_body
    assert (await env.store.list_shot_manifest_revisions(project.id))[
        0
    ].content_hash == env.manifest.content_hash
