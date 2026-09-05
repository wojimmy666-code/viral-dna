from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.models import WorkflowItemStatus
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.platform_skills.service import _seed_state
from viral_dna_api.production import ProductionService
from viral_dna_api.projects import ProjectCreate, ProjectService
from viral_dna_api.skill_workflow.contracts import (
    BrandSnapshot,
    CreativeBriefRevision,
    GateDecision,
    GateDecisionRequest,
    OutlineBeat,
    OutlineRevision,
    RunContractRevision,
    ShotManifestRevision,
    ShotManifestShot,
    SkillGate,
    SkillRun,
    StoryboardPromptDraftUpdate,
    StyleBibleRevision,
    content_digest,
)
from viral_dna_api.skill_workflow.routes import create_skill_workflow_router
from viral_dna_api.skill_workflow.service import SkillWorkflowService, SkillWorkflowServiceError
from viral_dna_api.skill_workflow.storyboard_authoring import (
    ReferenceStyleStoryboardAuthor,
    StoryboardAuthoringContext,
    compile_image_prompt,
    compile_video_prompt,
    creative_spec_from_authored,
)
from viral_dna_api.skill_workflow.storyboard_prompts import (
    allocate_frames,
    common_style_prompt,
    draft_issues,
    effective_prompt,
    factor_prompt_context,
)
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager


class Account:
    def __init__(self):
        self.id = uuid4()

    async def current_account(self):
        return self


async def runtime(store=None):
    store, account = store or InMemoryStore(), Account()
    catalog = PlatformSkillCatalogService(None)
    projects = ProjectService(store, catalog, account)
    skill = await catalog.get_catalog_item("cinematic-product-story")
    project = await projects.create(
        ProjectCreate(
            kind="skill", name="提示词编辑测试", skill_version_id=skill.current_version.id
        )
    )
    brand = BrandSnapshot(project_id=project.id, name="Aster", content_hash=content_digest("brand"))
    await store.save_brand_snapshot(brand)
    brief = CreativeBriefRevision(
        project_id=project.id,
        brand_snapshot_id=brand.id,
        revision_number=1,
        objective="呈现产品的材料与使用细节",
        audience="产品用户",
        distribution_channel="douyin",
        target_duration_seconds=10,
        target_duration_frames=240,
        output_aspect_ratio="16:9",
        fps=24,
        creative_basis="brand_led",
        input_hash=content_digest("brief"),
    )
    await store.save_creative_brief_revision(brief)
    bible = StyleBibleRevision(
        project_id=project.id,
        revision_number=1,
        skill_version_digest=content_digest("skill"),
        brand_snapshot_digest=brand.content_hash,
        brief_revision_id=brief.id,
        positive_lock=["保持主体与材质一致"],
        lighting={"principles": ["自然侧光"]},
        input_hash=content_digest("style"),
        content_hash=content_digest("style-output"),
    )
    await store.save_style_bible_revision(bible)
    outline = OutlineRevision(
        project_id=project.id,
        revision_number=1,
        beats=[
            OutlineBeat(
                stable_beat_key="beat_12345678",
                order=1,
                title="产品故事",
                purpose="以细节建立产品认知",
                target_duration_frames=240,
            )
        ],
        input_hash=content_digest("outline"),
        content_hash=content_digest("outline-output"),
    )
    await store.save_outline_revision(outline)
    common_image = common_style_prompt(bible, video=False)
    common_video = common_style_prompt(bible, video=True)
    shots = []
    for index in (1, 2):
        image_body = f"【主体与场景】产品的第{index}个静态细节。\n【构图与镜头】50mm近景，浅景深。"
        video_body = (
            f"【本镜头】50mm镜头缓慢推进5厘米，展示第{index}个产品细节。\n"
            "【同步音效】连续环境底噪。"
        )
        shots.append(
            ShotManifestShot(
                stable_shot_key=f"shot_test000{index}",
                order=index,
                narrative_role="产品细节",
                start_frame=(index - 1) * 120,
                duration_frames=120,
                generation_duration_seconds=5,
                description="保留的内部导演说明",
                image_prompt_body=image_body,
                video_prompt_body=video_body,
                image_prompt=effective_prompt(
                    image_body, common_image, video=False, duration=5, aspect_ratio="16:9", fps=24
                ),
                video_prompt=effective_prompt(
                    video_body, common_video, video=True, duration=5, aspect_ratio="16:9", fps=24
                ),
                input_hash=content_digest(f"shot-{index}"),
            )
        )
    manifest = ShotManifestRevision(
        project_id=project.id,
        revision_number=1,
        outline_revision_id=outline.id,
        style_bible_revision_id=bible.id,
        fps=24,
        shots=shots,
        common_image_prompt=common_image,
        common_video_prompt=common_video,
        creative_approach="以产品的静态细节引入，随后通过使用过程展现价值。",
        input_hash=content_digest("manifest"),
        content_hash=content_digest("manifest-output"),
    )
    await store.save_shot_manifest_revision(manifest)
    contract = RunContractRevision(
        project_id=project.id,
        revision_number=1,
        image_provider_connection_id="dashscope",
        image_model_id="qwen_image_2_pro",
        image_width=1024,
        image_height=576,
        video_provider_connection_id="seedance",
        video_model_id="seedance-1.5-pro",
        video_width=1920,
        video_height=1080,
        video_resolution_label="1080P",
        video_fps=24,
        video_duration_capabilities_seconds=[4, 5],
        text_model_selection="workspace_default",
        input_hash=content_digest("contract"),
    )
    await store.save_run_contract_revision(contract)
    snapshot = await store.get_skill_version_snapshot(project.id)
    run = SkillRun(
        project_id=project.id,
        skill_version_snapshot_id=snapshot.id,
        run_contract_revision_id=contract.id,
        current_stage="storyboard_design",
    )
    await store.save_skill_run(run)
    await projects.bind_skill_run(project.id, skill_run_id=run.id)
    for gate in (SkillGate.BRIEF_APPROVED, SkillGate.STYLE_APPROVED):
        await store.save_gate_decision(
            GateDecision(
                project_id=project.id,
                skill_run_id=run.id,
                gate=gate,
                decision="approve",
                actor_type="user",
                actor_id=account.id,
            )
        )
    service = SkillWorkflowService(store, projects, account)
    return SimpleNamespace(
        store=store,
        service=service,
        project=project,
        run=run,
        manifest=manifest,
        outline=outline,
        bible=bible,
    )


def payload(manifest, edits=None):
    return StoryboardPromptDraftUpdate(
        expected_revision_id=manifest.id,
        shots=edits
        if edits is not None
        else [
            {
                "stable_shot_key": shot.stable_shot_key,
                "image_prompt_body": shot.image_prompt_body,
                "video_prompt_body": shot.video_prompt_body,
            }
            for shot in manifest.shots
        ],
    )


def test_frame_allocation_is_exact_positive_and_deterministic():
    for total in (24, 240, 1001):
        for weights in ([120, 120], [120, 40, 120], [1], [5, 1, 6, 7]):
            actual = allocate_frames(weights, total)
            assert sum(actual) == total
            assert all(value > 0 for value in actual)
            assert actual == allocate_frames(weights, total)
    assert allocate_frames([120, 120], 240) == [120, 120]
    assert allocate_frames([1, 1, 1], 2) == [1, 1, 1]


def test_nonindustrial_skills_do_not_inherit_industrial_grade_camera_or_sound():
    async def scenario():
        env = await runtime()
        brief = (await env.store.list_creative_brief_revisions(env.project.id))[-1]
        brand = await env.store.get_brand_snapshot(brief.brand_snapshot_id)
        contract = (await env.store.list_run_contract_revisions(env.project.id))[-1]
        for version in _seed_state().versions:
            if version.skill_id == "platform.cinematic-product-story":
                continue
            context = StoryboardAuthoringContext(
                manifest=version.manifest,
                brand=brand,
                brief=brief,
                style_bible=env.bible,
                run_contract=contract,
                asset_facts=[],
                approved_claims=[],
            )
            authored = await ReferenceStyleStoryboardAuthor().author(context)
            assert authored.storyboard.creative_approach
            for shot in authored.storyboard.shots:
                spec = creative_spec_from_authored(shot)
                image = compile_image_prompt(
                    spec, brand_name=brand.name, exact_asset_reserved=False
                )
                video = compile_video_prompt(
                    spec, order=1, generation_duration_seconds=4, aspect_ratio="16:9", fps=24
                )
                for forbidden in ("暖琥珀", "3200", "8:1", "工业纪录", "124 BPM", "hard_cut"):
                    assert forbidden not in image + video
            assert all(
                any("\u4e00" <= char <= "\u9fff" for char in beat.title)
                for beat in authored.storyboard.beats
            )

    asyncio.run(scenario())


def test_draft_preserves_metadata_and_independent_prompts_without_outline_churn():
    async def scenario():
        env = await runtime()
        edit = payload(env.manifest)
        edit.shots[0].image_prompt_body += " 用户手写 ARRI @asset/id。"
        saved = await env.service.put_storyboard_prompt_draft(env.project.id, edit)
        assert saved.shots[0].image_prompt_body.endswith("用户手写 ARRI @asset/id。")
        assert "自然侧光" in saved.shots[0].image_prompt
        assert "自然侧光" not in saved.shots[0].image_prompt_body
        assert saved.shots[0].video_prompt == env.manifest.shots[0].video_prompt
        assert saved.shots[1].image_prompt == env.manifest.shots[1].image_prompt
        assert saved.shots[0].description == env.manifest.shots[0].description
        assert len(await env.store.list_outline_revisions(env.project.id)) == 1
        assert (
            await env.service.put_storyboard_prompt_draft(env.project.id, payload(saved))
        ).id == saved.id
        with pytest.raises(SkillWorkflowServiceError) as error:
            await env.service.put_storyboard_prompt_draft(env.project.id, edit)
        assert error.value.code == "storyboard_revision_stale"

    asyncio.run(scenario())


def test_blank_insert_delete_all_and_undo_are_durable_but_block_approval():
    async def scenario():
        env = await runtime()
        edit = payload(env.manifest)
        edit.shots.insert(1, type(edit.shots[0])(stable_shot_key="shot_new00001"))
        added = await env.service.put_storyboard_prompt_draft(env.project.id, edit)
        assert sum(shot.duration_frames for shot in added.shots) == 240
        assert added.shots[1].image_prompt == ""
        assert added.shots[1].generation_duration_seconds in (4, 5)
        with pytest.raises(SkillWorkflowServiceError) as error:
            await env.service.decide_gate(
                env.run.id,
                SkillGate.STORYBOARD_APPROVED,
                GateDecisionRequest(
                    decision="approve", related_revision_ids=[env.outline.id, added.id]
                ),
            )
        assert error.value.code == "storyboard_draft_incomplete"
        empty = await env.service.put_storyboard_prompt_draft(env.project.id, payload(added, []))
        assert empty.shots == [] and draft_issues(empty)
        restored = await env.service.put_storyboard_prompt_draft(
            env.project.id, payload(empty, payload(env.manifest).shots)
        )
        assert [shot.stable_shot_key for shot in restored.shots] == [
            shot.stable_shot_key for shot in env.manifest.shots
        ]
        assert restored.shots[0].description == "保留的内部导演说明"
        assert sum(shot.duration_frames for shot in restored.shots) == 240
        assert [shot.duration_frames for shot in restored.shots] == [120, 120]
        assert len(await env.store.list_shot_manifest_revisions(env.project.id)) == 4

    asyncio.run(scenario())


def test_concurrent_drafts_cannot_overwrite_each_other():
    async def scenario():
        env = await runtime()
        first, second = payload(env.manifest), payload(env.manifest)
        first.shots[0].image_prompt_body += " 版本甲"
        second.shots[0].image_prompt_body += " 版本乙"
        results = await asyncio.gather(
            *(
                env.service.put_storyboard_prompt_draft(env.project.id, edit)
                for edit in (first, second)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ShotManifestRevision) for result in results) == 1
        assert (
            sum(
                isinstance(result, SkillWorkflowServiceError)
                and result.code == "storyboard_revision_stale"
                for result in results
            )
            == 1
        )

    asyncio.run(scenario())


def test_http_draft_contract_accepts_empty_drafts_and_reports_revision_conflicts():
    env = asyncio.run(runtime())
    app = FastAPI()
    app.include_router(create_skill_workflow_router(env.service))
    with TestClient(app) as client:
        draft = payload(env.manifest, []).model_dump(mode="json")
        response = client.put(f"/projects/{env.project.id}/storyboard-draft", json=draft)
        assert response.status_code == 200
        assert response.json()["shots"] == []
        stale = client.put(f"/projects/{env.project.id}/storyboard-draft", json=draft)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "storyboard_revision_stale"


def test_factoring_shared_context_keeps_unique_lighting_and_all_user_content():
    async def scenario():
        env = await runtime()
        shots = [
            shot.model_copy(
                update={
                    "image_prompt_body": None,
                    "video_prompt_body": None,
                    "image_prompt": (
                        f"【连续性锁定】同一产品与材质\n【主体与场景】镜头{index}\n"
                        f"【光线与色彩】独特光线{index}"
                    ),
                    "video_prompt": (
                        f"【首帧约束】第{index}张分镜图\n【统一视觉锁定】同一色彩\n"
                        f"【本镜头】动作{index}"
                    ),
                }
            )
            for index, shot in enumerate(env.manifest.shots, 1)
        ]
        factored = factor_prompt_context(
            env.manifest.model_copy(update={"shots": shots}), env.bible
        )
        assert "同一产品与材质" in factored.common_image_prompt
        assert "同一产品与材质" not in factored.shots[0].image_prompt_body
        assert "独特光线1" in factored.shots[0].image_prompt_body
        assert "第1张" not in factored.shots[0].video_prompt_body
        assert factor_prompt_context(factored, env.bible) == factored

    asyncio.run(scenario())


def test_reapproval_syncs_existing_production_and_only_stales_changed_shots(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    async def scenario():
        env = await runtime()
        production = ProductionService(env.store, WorkspaceManager())
        env.service.production_service = production
        await env.service.decide_gate(
            env.run.id,
            SkillGate.STORYBOARD_APPROVED,
            GateDecisionRequest(
                decision="approve", related_revision_ids=[env.outline.id, env.manifest.id]
            ),
        )
        project = await env.store.get_project(env.project.id)
        production_id = project.source_binding.production_project_id
        before = await env.store.list_shot_plans(production_id)
        for plan in before:
            await env.store.save_shot_plan(
                plan.model_copy(
                    update={
                        "image_status": WorkflowItemStatus.APPROVED,
                        "video_status": WorkflowItemStatus.APPROVED,
                        "approved_image_candidate_id": uuid4(),
                        "approved_video_candidate_id": uuid4(),
                    }
                )
            )
        before = await env.store.list_shot_plans(production_id)
        edit = payload(env.manifest)
        edit.shots[0].video_prompt_body += " 结尾停稳。"
        changed = await env.service.put_storyboard_prompt_draft(env.project.id, edit)
        await env.service.decide_gate(
            env.run.id,
            SkillGate.STORYBOARD_APPROVED,
            GateDecisionRequest(
                decision="approve", related_revision_ids=[env.outline.id, changed.id]
            ),
        )
        after = await env.store.list_shot_plans(production_id)
        assert [plan.id for plan in after] == [plan.id for plan in before]
        assert after[0].image_status == WorkflowItemStatus.APPROVED
        assert after[0].video_status == WorkflowItemStatus.STALE
        assert after[1].video_status == WorkflowItemStatus.APPROVED
        assert after[1].approved_video_candidate_id == before[1].approved_video_candidate_id
        assert after[0].video_prompt == changed.shots[0].video_prompt
        assert (
            await env.store.get_project(env.project.id)
        ).source_binding.production_project_id == production_id
        assert len(await env.store.list_production_projects(env.project.id)) == 1
        removed = await env.service.put_storyboard_prompt_draft(
            env.project.id,
            payload(changed, payload(changed).shots[1:]),
        )
        await env.service.decide_gate(
            env.run.id,
            SkillGate.STORYBOARD_APPROVED,
            GateDecisionRequest(
                decision="approve", related_revision_ids=[removed.outline_revision_id, removed.id]
            ),
        )
        removed_plans = await env.store.list_shot_plans(production_id)
        discarded = next(plan for plan in removed_plans if plan.id == before[0].id)
        assert discarded.lifecycle_status.value == "discarded"
        assert not discarded.required
        assert discarded.approved_video_candidate_id == before[0].approved_video_candidate_id
        restored = await env.service.put_storyboard_prompt_draft(
            env.project.id,
            payload(removed, payload(changed).shots),
        )
        await env.service.decide_gate(
            env.run.id,
            SkillGate.STORYBOARD_APPROVED,
            GateDecisionRequest(
                decision="approve", related_revision_ids=[restored.outline_revision_id, restored.id]
            ),
        )
        restored_plans = await env.store.list_shot_plans(production_id)
        assert [plan.id for plan in restored_plans] == [plan.id for plan in before]
        assert all(plan.lifecycle_status.value == "active" for plan in restored_plans)
        assert [shot.duration_frames for shot in restored.shots] == [120, 120]

    asyncio.run(scenario())
