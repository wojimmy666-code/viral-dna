"""Phase-one visual direction. All media/model providers below are test doubles."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from viral_dna_api.account_preferences import UserPreferences, UserPreferencesRepository, UserPreferencesUpdate, UserPreferencesConflict
from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.models import AnalysisRecord, Video, VideoGenerationCreate
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.production_prompt_documents import ProductionPromptDocuments
from viral_dna_api.project_prompts import ProjectPromptRevision, ProjectPromptService, ProjectPromptUpdate, PromptRevisionConflict, prompt_snapshot
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.visual_styles import PRESETS, VisualStyle, freeze_style, style_catalog
from viral_dna_api.viral_insights.contracts import CreativeActionRequest, CreativeGenerateRequest, ViralConceptPublishRequest
from viral_dna_api.viral_insights.publisher import ProductionConceptPublisher
from viral_dna_api.viral_insights.prompt_language_service import concept_document


def update(context, **changes):
    return ProjectPromptUpdate(expected_revision_id=context.id, common_image_prompt=context.common_image_prompt,
                               common_video_prompt=context.common_video_prompt, **changes)


def test_presets_are_deterministic_chinese_content_preserving_and_static():
    assert freeze_style(None) == freeze_style({"preset": "original"}) == {}
    assert len(style_catalog()["items"]) == len(PRESETS)
    for preset in PRESETS:
        if preset in {"original", "custom"}:
            continue
        snapshot = freeze_style({"preset": preset, "motion": "慢速横移，保持人物居中"})
        assert snapshot == freeze_style(snapshot["selection"])
        assert "服装款式" in snapshot["image_prompt"]
        assert "慢速横移" not in snapshot["image_prompt"]
        assert "慢速横移" in snapshot["video_prompt"]
    custom = freeze_style({"preset": "custom", "description": "自然光。镜头快速横移。真实面料。"})
    assert "快速横移" not in custom["image_prompt"]
    assert "真实面料" in custom["image_prompt"]
    for value in ({"preset": "missing"}, {"preset": "custom"}, {"preset": "natural", "model": "test"}):
        with pytest.raises(ValidationError):
            VisualStyle.model_validate(value)


def test_travel_vlog_freezes_general_rules_without_inheriting_sample_content():
    snapshot = freeze_style({"preset": "travel_vlog"})
    assert snapshot == freeze_style(snapshot["selection"])
    assert snapshot["label"] == "旅行 Vlog"
    image = snapshot["image_prompt"]
    assert "45%–55%" in image and "未明确指定" in image
    assert "已有的特写、人物位置、构图、机位和主体比例要求优先" in image
    assert "不强制阴天、灰调或低饱和" in image
    assert "不改变任务实际分辨率和质量设置" in image
    assert "小脸不增加特写级毛孔" in image
    for sample_content in ("巴黎", "埃菲尔", "JK", "24岁", "右腿在前", "头顶在图高40%"):
        assert sample_content not in snapshot["image_prompt"] + snapshot["video_prompt"]
    context = ProjectPromptRevision(project_id=uuid4(), visual_style=VisualStyle(preset="travel_vlog"), visual_style_snapshot=snapshot)
    authored = "【画面】人物垂直居中，半身特写，雪山环境，保留蓝色制服。"
    frozen = prompt_snapshot(authored, context, "image")
    assert frozen["local_prompt"] == authored
    assert authored in frozen["compiled_prompt"]
    assert "旅行 Vlog" in frozen["compiled_prompt"]
    assert "旅行 Vlog 动态" not in frozen["compiled_prompt"]
    assert "不为了人物占比默认值重新构图" in snapshot["video_prompt"]


@pytest.mark.asyncio
async def test_revisions_keep_manual_text_overrides_and_frozen_history_on_restart(tmp_path):
    store = SQLiteStore(tmp_path / "style.db")
    service = ProjectPromptService(store)
    initial = await service.current(uuid4(), image="人工全局 @服装", video="人工动作要求")
    assert not await store.list_project_prompt_revisions(initial.project_id)
    natural = await service.save(initial, update(initial, visual_style={"preset": "natural"}, shot_styles={"shot_b": {"preset": "anime"}, "shot_c": {"preset": "original"}}))
    local = "【主体】JK 制服的完整款式，手写场景与构图 @服装"
    frozen = prompt_snapshot(local, natural, "image", shot_key="shot_a")
    assert frozen["local_prompt"] == local and "自然实拍" in frozen["compiled_prompt"]
    assert "二维动漫" in prompt_snapshot(local, natural, "image", shot_key="shot_b")["compiled_prompt"]
    assert "画面风格" not in prompt_snapshot(local, natural, "image", shot_key="shot_c")["compiled_prompt"]
    reopened = ProjectPromptService(SQLiteStore(tmp_path / "style.db"))
    current = await reopened.current(initial.project_id)
    assert current.shot_styles == natural.shot_styles
    # Legacy clients editing prose must not remove new style fields.
    preserved = await reopened.save(current, ProjectPromptUpdate(expected_revision_id=current.id, common_image_prompt="新的手写全局", common_video_prompt=current.common_video_prompt))
    assert preserved.visual_style == natural.visual_style
    assert preserved.shot_style_snapshots == natural.shot_style_snapshots
    changed = await reopened.save(preserved, update(preserved, visual_style={"preset": "watercolor"}))
    assert "水彩" in prompt_snapshot(local, changed, "image")["compiled_prompt"]
    assert "自然实拍" in frozen["compiled_prompt"] and "水彩" not in frozen["compiled_prompt"]
    assert changed.common_video_prompt == initial.common_video_prompt
    with pytest.raises(PromptRevisionConflict):
        await reopened.save(changed, update(initial, visual_style={"preset": "anime"}))


@pytest.mark.asyncio
async def test_batch_freezes_style_per_shot_and_changes_do_not_rewrite_media(tmp_path, monkeypatch):
    from test_image_batches import environment, finish, until
    env = await environment(tmp_path, monkeypatch, count=3, durable=True)
    prompts = []
    generate = env.gateway.generate
    async def capture(project, shot, *args, **kwargs):
        prompts.append((shot.id, shot.image_prompt))
        return await generate(project, shot, *args, **kwargs)
    env.gateway.generate = capture
    before = [p.model_dump(mode="json") for p in await env.store.list_shot_plans(env.project.id)]
    context = await env.service.get_prompt_context(env.project.id)
    overridden = str(env.shots[1].id)
    first = await env.service.update_prompt_context(env.project.id, update(context, visual_style={"preset": "natural"}, shot_styles={overridden: {"preset": "anime"}}))
    assert before == [p.model_dump(mode="json") for p in await env.store.list_shot_plans(env.project.id)]
    batch = await env.batch.create(env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id))
    try:
        await until(lambda: env.gateway.active == 3)
        await env.service.update_prompt_context(env.project.id, update(first, visual_style={"preset": "watercolor"}))
        result = await finish(env, batch)
        assert result.status == "completed"
        assert len(prompts) == 3
        for identifier, text in prompts:
            assert ("二维动漫" if identifier == env.shots[1].id else "自然实拍") in text
            assert "手绘水彩" not in text
        assert all(item.prompt_snapshot["global_revision_id"] == str(first.id) for item in result.items)
        with pytest.raises(ProductionServiceError, match="不属于"):
            await env.service.update_prompt_context(env.project.id, update(await env.service.get_prompt_context(env.project.id), shot_styles={"foreign": {"preset": "natural"}}))
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_grouped_video_deduplicates_styles_but_keeps_each_segment_and_export(tmp_path, monkeypatch):
    from test_video_groups import setup_group
    env, groups, group, _ = await setup_group(tmp_path, monkeypatch)
    context = await env.service.get_prompt_context(env.project.id)
    key = str(env.shots[1].id)
    natural = await env.service.update_prompt_context(env.project.id, update(context, visual_style={"preset": "natural"}, shot_styles={key: {"preset": "anime"}}))
    project = await env.store.get_production_project(env.project.id)
    _, members, aggregate, _, fingerprint = await groups.projection(project, group.id)
    assert aggregate.video_prompt.count("【画面风格：自然实拍】") == 1
    assert aggregate.video_prompt.count("【画面风格：二维动漫】") == 1
    assert "本分段应用风格配置 2" in aggregate.video_prompt
    payload = VideoGenerationCreate(expected_revision_id=project.current_revision_id, generation_group_id=group.id, expected_group_fingerprint=fingerprint, duration_seconds=10)
    scaled, _ = await env.service._group_video_plan(project, members[0], payload)
    assert "自然实拍" in scaled.video_prompt and "二维动漫" in scaled.video_prompt
    document = await ProductionPromptDocuments(env.service).get(project.id)
    assert document["shots"][1]["visual_style_snapshot"]["label"] == "二维动漫"
    assert "二维动漫" in document["video_groups"][0]["compiled_prompt"]
    await env.service.update_prompt_context(project.id, update(natural, visual_style={"preset": "cinematic"}))
    assert fingerprint != (await groups.projection(project, group.id))[-1]
    assert "电影写实" not in aggregate.video_prompt


@pytest.mark.asyncio
async def test_creative_style_inherits_category_survives_single_rewrite_expand_and_publish(tmp_path, monkeypatch):
    from test_creative_concepts import setup, finish
    from test_generation_jobs import _workspace
    repo, report, categories, provider, creative = await setup()
    categories.profile.default_visual_style = VisualStyle(preset="natural")
    first = await finish(creative, await creative.generate(report.analysis_id, CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id)))
    assert first.status == "completed"
    assert all(i.visual_style_snapshot["label"] == "自然实拍" for i in first.ideas)
    assert "自然实拍" in provider.requests[-1].user_prompt
    original = first.model_dump(mode="json")
    rewritten = await finish(creative, await creative.act(first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4(), visual_style={"preset": "anime"}), expand=False))
    assert rewritten.ideas[0].visual_style_snapshot["label"] == "二维动漫"
    assert rewritten.ideas[1:] == first.ideas[1:]
    expanded = await finish(creative, await creative.act(rewritten.id, rewritten.ideas[1].id, CreativeActionRequest(request_id=uuid4()), expand=True))
    assert expanded.status == "completed"
    assert expanded.visual_style_snapshot["label"] == "自然实拍"
    assert concept_document(expanded)["shots"][0]["visual_style_snapshot"] == expanded.visual_style_snapshot
    assert first.model_dump(mode="json") == original
    record_id = uuid4()
    await repo.save_video(Video(id=report.video_id, record_id=record_id, source_type="upload", filename="test.mp4", title="测试", width=1080, height=1920, duration_seconds=8.5, status="ready"))
    await repo.save_record(AnalysisRecord(id=record_id, video_id=report.video_id, name="测试", source_type="upload", latest_analysis_id=report.analysis_id))
    production = ProductionService(repo, _workspace(tmp_path, monkeypatch))
    creative.insights.publisher = ProductionConceptPublisher(production)
    published = await creative.insights.publish_concept(expanded.id, expanded.concepts[0].id, ViralConceptPublishRequest(record_id=record_id))
    current = await production.get_prompt_context(published.project_id)
    assert current.visual_style_snapshot == expanded.visual_style_snapshot
    assert current.visual_style.preset == "natural"
    assert len(await repo.list_shot_plans(published.project_id)) == 5


@pytest.mark.asyncio
async def test_account_presets_are_scoped_revision_checked_and_legacy_updates_preserve(tmp_path):
    repo = UserPreferencesRepository(tmp_path / "preferences.json")
    account, other = uuid4(), uuid4()
    initial = await repo.get(account)
    saved = await repo.update(account, UserPreferencesUpdate(revision=initial.revision, settings=UserPreferences(visual_style_presets=[{"name": "街拍", "style": {"preset": "natural"}}])))
    assert not (await repo.get(other)).settings.visual_style_presets
    preserved = await repo.update(account, UserPreferencesUpdate(revision=saved.revision, settings=UserPreferences(image_candidate_count=2)))
    assert preserved.settings.visual_style_presets == saved.settings.visual_style_presets
    with pytest.raises(UserPreferencesConflict):
        await repo.update(account, UserPreferencesUpdate(revision=saved.revision, settings=UserPreferences(visual_style_presets=[])))
    removed = await repo.update(account, UserPreferencesUpdate(revision=preserved.revision, settings=UserPreferences(visual_style_presets=[])))
    assert not removed.settings.visual_style_presets


@pytest.mark.asyncio
async def test_style_catalog_and_preview_are_authenticated_context_reads_without_preferences(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from viral_dna_api.account_preferences import UserPreferencesService, create_user_preferences_router
    from viral_dna_api import style_library
    library = style_library.StyleLibrary(tmp_path / "catalog.db")
    monkeypatch.setattr(style_library, "get_style_library", lambda: library)
    context = SimpleNamespace(current_account=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    path = tmp_path / "not-created.json"
    app = FastAPI()
    app.include_router(create_user_preferences_router(UserPreferencesService(context, UserPreferencesRepository(path))))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        catalog = await client.get("/me/settings/visual-styles")
        assert catalog.status_code == 200 and catalog.json()["version"] == "visual-style-library-v1"
        preview = await client.post("/me/settings/visual-styles/preview", json={"preset": "natural"})
        assert preview.status_code == 200 and preview.json()["label"] == "自然实拍"
        assert (await client.post("/me/settings/visual-styles/preview", json={"preset": "custom"})).status_code == 422
    assert context.current_account.await_count == 2
    assert not path.exists()


@pytest.mark.asyncio
async def test_category_default_is_frozen_and_survives_legacy_client_updates(tmp_path):
    from test_category_profiles import FakeAccountContext, profile_create
    from viral_dna_api.category_profiles.repository import CategoryProfileRepository
    from viral_dna_api.category_profiles.service import CategoryProfileService
    from viral_dna_api.category_profiles.contracts import CategoryProfileCreate, CategoryProfileUpdate
    service = CategoryProfileService(FakeAccountContext(), CategoryProfileRepository(tmp_path / "categories.json"))
    payload = {**profile_create().model_dump(), "default_visual_style": {"preset": "natural"}}
    current = await service.create(CategoryProfileCreate.model_validate(payload))
    frozen = await service.snapshot(current.id)
    legacy = profile_create().model_dump(exclude={"default_visual_style"})
    changed = await service.update(current.id, CategoryProfileUpdate(revision=current.revision, **legacy))
    assert (await service.snapshot(changed.id)).default_visual_style.preset == "natural"
    cleared = await service.update(changed.id, CategoryProfileUpdate(revision=changed.revision, **legacy, default_visual_style=None))
    assert cleared.default_visual_style is None
    assert frozen.default_visual_style.preset == "natural"
