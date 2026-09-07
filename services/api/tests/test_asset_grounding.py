from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from test_storyboard_prompt_editor import payload, runtime

from viral_dna_api.models import VideoPromptMention
from viral_dna_api.skill_workflow.asset_grounding import (
    AuthoredAssetReference,
    compile_asset_references,
    select_shot_assets,
)
from viral_dna_api.skill_workflow.contracts import AssetUsage, content_digest
from viral_dna_api.skill_workflow.service import SkillWorkflowServiceError
from viral_dna_api.video_generation.drafts import current_default_input_plan


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_bindings_survive_outline_seed_production_remove_and_restore(
    tmp_path, monkeypatch, durable
):
    from viral_dna_api.models import PromptAssetMention, ReferenceAsset, ShotVideoGenerationDraft
    from viral_dna_api.production import ProductionService
    from viral_dna_api.skill_workflow.contracts import GateDecisionRequest, SkillGate
    from viral_dna_api.workspace import WorkspaceManager

    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    from viral_dna_api.sqlite_store import SQLiteStore

    env = await runtime(SQLiteStore(tmp_path / "bindings.db") if durable else None)
    usage, asset, _ = await attach_selected(env)

    class Bridge:
        async def link_asset(self, project, asset_id, reference_type):
            ref = ReferenceAsset(
                id=asset_id,
                project_id=project.id,
                type="product",
                name=asset.name,
                folder_name=asset.folder_name,
                rights_confirmed=True,
                relative_path="fixtures/image.png",
                mime_type="image/png",
                width=320,
                height=480,
                sha256=asset.sha256,
            )
            await env.store.save_reference_asset(ref)
            return ref

        async def list_references(self, project_id, include_archived=False):
            return await env.store.list_reference_assets(project_id)

        async def get_reference(self, asset_id, project_id=None):
            return await env.store.get_reference_asset(asset_id)

        async def snapshot_reference(self, project_id, reference):
            return reference.model_dump(mode="json")

    production = ProductionService(env.store, WorkspaceManager(), project_assets=Bridge())
    env.service.production_service = production
    image_ref = PromptAssetMention(reference_asset_id=asset.id, label="品牌产品/滤芯正面")
    video_ref = VideoPromptMention(
        reference_kind="project_asset",
        reference_id=asset.id,
        label="资产/品牌产品/滤芯正面",
        role="product",
        order=1,
    )
    edit = payload(env.manifest)
    edit.shots[0].image_prompt_body += "\n参考 @品牌产品/滤芯正面。"
    edit.shots[0].image_prompt_mentions = [image_ref]
    edit.shots[0].video_prompt_body += "\n参考 @资产/品牌产品/滤芯正面。"
    edit.shots[0].video_prompt_mentions = [video_ref]
    saved = await env.service.put_storyboard_prompt_draft(env.project.id, edit)
    await env.service.decide_gate(
        env.run.id,
        SkillGate.STORYBOARD_APPROVED,
        GateDecisionRequest(
            decision="approve", related_revision_ids=[saved.outline_revision_id, saved.id]
        ),
    )
    owner = await env.store.get_project(env.project.id)
    plans = await env.store.list_shot_plans(owner.source_binding.production_project_id)
    plan = plans[0]
    assert plan.image_prompt_mentions == [image_ref]
    assert plan.video_prompt_mentions == [video_ref]
    assert [
        item.reference_asset_id for item in await env.store.list_reference_bindings(plan.id)
    ] == [asset.id]
    assert plans[1].image_prompt_mentions == []
    seed = await env.store.get_production_seed(
        (await env.store.get_production_project(plan.project_id)).production_seed_id
    )
    assert len(seed.reference_assets) == 1  # no unselected library/usage entries
    assert seed.shots[0].image_asset_usage_ids == [usage.id]
    draft = ShotVideoGenerationDraft(
        project_id=plan.project_id,
        shot_plan_id=plan.id,
        model_alias="seedance-1.5-pro",
        resolution="720P",
        duration_seconds=5,
        video_prompt=plan.video_prompt,
        video_prompt_mentions=plan.video_prompt_mentions,
        input_plan=current_default_input_plan(plan),
    )
    await env.store.compare_and_swap_video_generation_draft(draft, expected_draft_version=0)
    # Subsequent outline edits must update the actual generation inputs too.
    live = (await env.service.workspace(env.project.id)).shot_manifest
    remove = payload(live)
    remove.shots[0].image_prompt_body = "黑色背景中的产品静态近景。"
    remove.shots[0].image_prompt_mentions = []
    remove.shots[0].video_prompt_body = "保持固定机位。"
    remove.shots[0].video_prompt_mentions = []
    removed = await env.service.put_storyboard_prompt_draft(env.project.id, remove)
    assert await env.store.list_reference_bindings(plan.id) == []
    assert (await env.store.get_video_generation_draft(plan.id)).input_plan.references == []
    restore = payload(removed)
    restore.shots[0].image_prompt_body = saved.shots[0].image_prompt_body
    restore.shots[0].image_prompt_mentions = [image_ref]
    restore.shots[0].video_prompt_body = saved.shots[0].video_prompt_body
    restore.shots[0].video_prompt_mentions = [video_ref]
    await env.service.put_storyboard_prompt_draft(env.project.id, restore)
    assert [
        item.reference_asset_id for item in await env.store.list_reference_bindings(plan.id)
    ] == [asset.id]
    assert (await env.store.get_video_generation_draft(plan.id)).input_plan.references[
        0
    ].reference_id == asset.id
    if durable:
        reopened = SQLiteStore(tmp_path / "bindings.db")
        assert (await reopened.get_shot_plan(plan.id)).image_prompt_mentions == [image_ref]
        assert (await reopened.get_video_generation_draft(plan.id)).video_prompt_mentions == [
            video_ref
        ]


def fact(name="滤芯正面", **kwargs):
    return dict(
        id=str(uuid4()),
        asset_id=str(uuid4()),
        name=name,
        folder_name="品牌产品",
        image_eligible=True,
        **kwargs,
    )


def choose(item, **kwargs):
    return AuthoredAssetReference(
        **{
            **dict(
                asset_usage_id=item["id"],
                asset_name=item["name"],
                purpose="准确参考产品正面结构",
                certain=True,
            ),
            **kwargs,
        }
    )


def test_only_certain_selected_named_references_are_bound_without_padding():
    first, unrelated = fact(), fact("工厂外景")
    selected = select_shot_assets([choose(first), choose(first)], [first, unrelated])
    assert [item["id"] for item, _ in selected] == [first["id"]]
    prompt, mentions = compile_asset_references("【主体与场景】滤芯静态特写。", selected)
    assert "@品牌产品/滤芯正面" in prompt
    assert mentions[0].reference_asset_id == UUID(first["asset_id"])
    assert select_shot_assets([], [first, unrelated]) == []
    assert compile_asset_references("没有参考也可以生成。", []) == ("没有参考也可以生成。", [])


@pytest.mark.parametrize(
    "change",
    [
        dict(certain=False),
        dict(purpose=""),
        dict(asset_usage_id=str(uuid4())),
        dict(asset_name="另一张图"),
    ],
)
def test_abstain_on_uncertain_missing_or_mismatched_reference(change):
    item = fact()
    assert select_shot_assets([choose(item, **change)], [item]) == []


def test_duplicate_names_generic_names_and_ineligible_material_are_not_guessed():
    a, b = fact(), fact()
    b["folder_name"] = "其他品牌"
    assert select_shot_assets([choose(a)], [a, b]) == []
    assert len(select_shot_assets([choose(a, asset_name="品牌产品/滤芯正面")], [a, b])) == 1
    b["folder_name"] = a["folder_name"]
    assert select_shot_assets([choose(a, asset_name="品牌产品/滤芯正面")], [a, b]) == []
    generic = fact("IMG_0001.jpg")
    assert select_shot_assets([choose(generic)], [generic]) == []
    a["image_eligible"] = False
    assert select_shot_assets([choose(a)], [a]) == []


async def attach_selected(env):
    snapshot = await env.store.get_skill_version_snapshot(env.project.id)
    role = next(
        item
        for item in snapshot.manifest.spec.intake.asset_roles
        if "image" in item.media_types and item.fidelity != "exact"
    )
    selected, unselected = [
        AssetUsage(
            project_id=env.project.id,
            asset_id=uuid4(),
            role=role.role,
            fidelity=role.fidelity,
            rights_status="confirmed",
            snapshot_sha256="a" * 64,
        )
        for _ in range(2)
    ]
    await env.store.replace_asset_usages(env.project.id, [selected, unselected])
    brief = (await env.store.list_creative_brief_revisions(env.project.id))[-1]
    brief = brief.model_copy(
        update={
            "id": uuid4(),
            "revision_number": 2,
            "selected_asset_usage_ids": [selected.id],
            "input_hash": content_digest("selected"),
        }
    )
    await env.store.save_creative_brief_revision(brief)
    calls = []
    asset = SimpleNamespace(
        id=selected.asset_id,
        name="滤芯正面",
        folder_name="品牌产品",
        type="product",
        media_kind="image",
        rights_confirmed=True,
        sha256="a" * 64,
        archived_at=None,
        deleted_at=None,
        thumbnail_url="/assets/selected/thumbnail",
        content_url="/assets/selected/content",
    )

    async def get_asset(asset_id):
        calls.append(asset_id)
        assert asset_id == selected.asset_id, "must never look at an unselected asset"
        return asset

    env.service.asset_library = SimpleNamespace(get_asset=get_asset)
    return selected, asset, calls


@pytest.mark.asyncio
async def test_metadata_lookup_only_fetches_selected_ids_and_detects_changed_content():
    env = await runtime()
    usage, asset, calls = await attach_selected(env)
    facts = await env.service.prompt_assets(env.project.id)
    assert calls == [usage.asset_id]
    assert len(facts) == 1 and facts[0]["image_eligible"]
    assert facts[0]["name"] == "滤芯正面"
    asset.sha256 = "b" * 64
    assert not (await env.service.prompt_assets(env.project.id))[0]["image_eligible"]


@pytest.mark.asyncio
async def test_outline_saves_ids_supports_remove_restore_and_rejects_foreign():
    env = await runtime()
    usage, asset, _ = await attach_selected(env)
    draft = payload(env.manifest)
    draft.shots[0].image_prompt_body += "\n参考 @品牌产品/滤芯正面。"
    from viral_dna_api.models import PromptAssetMention

    mention = PromptAssetMention(reference_asset_id=asset.id, label="品牌产品/滤芯正面")
    draft.shots[0].image_prompt_mentions = [mention]
    saved = await env.service.put_storyboard_prompt_draft(env.project.id, draft)
    assert saved.shots[0].image_prompt_mentions == [mention]
    assert saved.shots[0].image_asset_usage_ids == [usage.id]
    assert saved.shots[1].image_asset_usage_ids == []
    assert (
        await env.service.put_storyboard_prompt_draft(env.project.id, payload(saved))
    ).id == saved.id
    remove = payload(saved)
    remove.shots[0].image_prompt_body = "产品静态特写，不使用参考。"
    remove.shots[0].image_prompt_mentions = []
    removed = await env.service.put_storyboard_prompt_draft(env.project.id, remove)
    assert removed.shots[0].image_asset_usage_ids == []
    restore = payload(removed)
    restore.shots[0].image_prompt_body = saved.shots[0].image_prompt_body
    restore.shots[0].image_prompt_mentions = [mention]
    restored = await env.service.put_storyboard_prompt_draft(env.project.id, restore)
    assert restored.shots[0].image_asset_usage_ids == [usage.id]
    foreign = payload(restored)
    foreign.shots[0].image_prompt_mentions = [
        mention.model_copy(update={"reference_asset_id": uuid4()})
    ]
    with pytest.raises(SkillWorkflowServiceError, match="未选择或不可用"):
        await env.service.put_storyboard_prompt_draft(env.project.id, foreign)


@pytest.mark.asyncio
async def test_video_default_keeps_explicit_outline_reference_as_real_input():
    mention = VideoPromptMention(
        reference_kind="project_asset",
        reference_id=uuid4(),
        label="资产/产品/滤芯正面",
        role="product",
        order=1,
    )
    plan = SimpleNamespace(visual_beats=[], video_prompt_mentions=[mention])
    inputs = current_default_input_plan(plan)
    assert inputs.sources == ["project_assets"]
    assert inputs.references[0].reference_id == mention.reference_id
