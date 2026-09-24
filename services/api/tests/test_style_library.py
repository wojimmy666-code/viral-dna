"""Visual catalog boundaries; isolated databases and fake generation providers only."""
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pydantic import ValidationError

from viral_dna_api import style_library
from viral_dna_api.style_library import StyleDefinition, StyleLibrary, StyleWrite
from viral_dna_api.visual_styles import VisualStyle, freeze_style


@pytest.fixture
def library(tmp_path, monkeypatch):
    value = StyleLibrary(tmp_path / "styles.db")
    monkeypatch.setattr(style_library, "get_style_library", lambda: value)
    return value


def definition(item, **changes):
    return StyleDefinition(**{**{key: item[key] for key in StyleDefinition.model_fields}, **changes})


def test_seed_covers_versions_drafts_and_disabled_history(library):
    initial = library.catalog()["items"]
    assert len(initial) == 7
    assert all(item["cover_url"] and item["applies_to"] == ["image", "video"] for item in initial)
    first = initial[0]
    old = freeze_style(first["selection"])
    assert old["image_prompt"] and old["video_prompt"] and old["content_hash"]
    assert library.media(first["cover_id"]).headers["content-type"] == "image/jpeg"
    saved = library.save(first["id"], StyleWrite(expected_revision=first["revision"], style=definition(first, name="修改后的风格", image_prompt="新的自然光规则")))
    assert library.catalog()["items"][0]["name"] == first["name"]
    assert saved["has_unpublished_changes"]
    with pytest.raises(HTTPException) as conflict:
        library.save(first["id"], StyleWrite(expected_revision=first["revision"], style=definition(first)))
    assert conflict.value.status_code == 409
    published = library.action(first["id"], saved["revision"], "publish")
    assert published["version"] == 2
    assert freeze_style(first["selection"]) == old
    assert "新的自然光规则" in freeze_style(published["selection"])["image_prompt"]
    library.action(first["id"], published["revision"], "disable")
    assert first["id"] not in {item["id"] for item in library.catalog()["items"]}
    assert freeze_style(first["selection"]) == old
    with pytest.raises(HTTPException) as disabled:
        library.frozen(first["id"], 1, selectable=True)
    assert disabled.value.status_code == 409
    reopened = StyleLibrary(library.path)
    assert reopened.frozen(first["id"], 1) == library.frozen(first["id"], 1)
    assert first["id"] not in {item["id"] for item in reopened.catalog()["items"]}


def test_preview_media_private_until_published_and_upload_validation(library):
    data = io.BytesIO()
    Image.new("RGB", (32, 40), "navy").save(data, format="PNG")
    upload = library.upload(data.getvalue())
    assert library.media(upload["id"], admin=True).body.startswith(b"\xff\xd8")
    with pytest.raises(HTTPException) as private:
        library.media(upload["id"])
    assert private.value.status_code == 404
    draft = library.save(str(uuid4()), StyleWrite(expected_revision=0, style=StyleDefinition(name="测试", category="测试", applies_to=["image"], image_prompt="柔和阴天光", cover_id=upload["id"])))
    assert draft["id"] not in {item["id"] for item in library.catalog()["items"]}
    published = library.action(draft["id"], draft["revision"], "publish")
    assert library.media(upload["id"]).status_code == 200
    assert freeze_style(published["selection"])["video_prompt"] == ""
    for content in (b"<svg>not allowed</svg>", b"", b"0" * (10 * 1024 * 1024 + 1)):
        with pytest.raises(HTTPException):
            library.upload(content)
    with pytest.raises(ValidationError):
        StyleDefinition(name="无规则", category="测试", applies_to=[])
    with pytest.raises(ValidationError):
        StyleDefinition(name="无规则", category="测试")


def test_preferences_are_per_member_and_selection_cannot_smuggle_rules(library):
    first = library.catalog()["items"][0]
    library.preference("account:member-a", first["id"], favorite=True, used=True)
    item = library.catalog(principal="account:member-a")["items"][0]
    assert item["favorite"] and item["used_at"]
    assert not library.catalog(principal="account:member-b")["items"][0]["favorite"]
    for extra in ({"description": "覆盖管理员规则"}, {"catalog_version": None}, {"image_prompt": "伪造提示词"}):
        with pytest.raises(ValidationError):
            VisualStyle.model_validate({**first["selection"], **extra})
    snapshot = freeze_style(first["selection"])
    assert first["cover_url"] not in snapshot["image_prompt"]
    assert "参考图" not in snapshot["selection"]


def test_seed_cover_upgrade_never_rewrites_a_published_version(library):
    first = library.catalog()["items"][0]
    without_cover = definition(first, cover_id=None).model_dump_json()
    with library.transaction() as db:
        db.execute("UPDATE styles SET draft=? WHERE id=?", (without_cover, first["id"]))
        db.execute("UPDATE style_versions SET payload=? WHERE style_id=? AND version=1", (without_cover, first["id"]))
    reopened = StyleLibrary(library.path)
    updated = next(item for item in reopened.catalog()["items"] if item["id"] == first["id"])
    assert updated["cover_url"] and updated["version"] == 2
    assert reopened.frozen(first["id"], 1)["cover_url"] is None
    with reopened.transaction() as db:
        saved = db.execute("SELECT payload FROM style_versions WHERE style_id=? AND version=1", (first["id"],)).fetchone()["payload"]
        assert json.loads(saved) == json.loads(without_cover)


def test_travel_vlog_is_selectable_for_images_and_video_with_approved_cover(library):
    identifier = str(uuid5(NAMESPACE_URL, "viraldna:style:travel_vlog"))
    item = next(item for item in library.catalog()["items"] if item["id"] == identifier)
    assert item["name"] == "旅行 Vlog"
    assert item["category"] == "写实摄影"
    assert "Vlog" in item["tags"] and "日常随拍" in item["tags"]
    assert item["version"] == 1 and item["enabled"]
    assert item["applies_to"] == ["image", "video"]
    assert item["cover_url"]
    with Image.open(io.BytesIO(library.media(item["cover_id"]).body)) as cover:
        assert cover.width > cover.height
        assert abs(cover.width / cover.height - 16 / 9) < 0.01
    snapshot = freeze_style(item["selection"])
    assert snapshot["label"] == "旅行 Vlog"
    assert "共享现场光向" in snapshot["image_prompt"]
    assert "45%–55%" in snapshot["image_prompt"]
    assert "人物状态自然" in snapshot["image_prompt"]
    assert "旅行 Vlog 动态" not in snapshot["image_prompt"]
    assert "旅行 Vlog 动态" in snapshot["video_prompt"]
    assert item["cover_url"] not in snapshot["image_prompt"]
    assert library.frozen(identifier, 1, selectable=True)["selection"] == item["selection"]


def test_new_builtin_is_added_without_changing_existing_library(tmp_path, monkeypatch):
    presets = style_library.PRESETS
    monkeypatch.setattr(style_library, "PRESETS", {key: value for key, value in presets.items() if key != "travel_vlog"})
    old = StyleLibrary(tmp_path / "existing-styles.db")
    first = old.catalog()["items"][0]
    saved = old.save(first["id"], StyleWrite(expected_revision=first["revision"], style=definition(first, name="管理员已修改", image_prompt="保留管理员的自定义规则")))
    old.action(first["id"], saved["revision"], "disable")
    another = old.catalog()["items"][0]
    old.preference("member", another["id"], favorite=True, used=True)
    before = {item["id"]: item for item in old.catalog(admin=True, principal="member")["items"]}
    snapshots = {identifier: old.frozen(identifier, 1) for identifier in before}
    monkeypatch.setattr(style_library, "PRESETS", presets)
    reopened = StyleLibrary(old.path)
    after = {item["id"]: item for item in reopened.catalog(admin=True, principal="member")["items"]}
    assert len(after) == len(before) + 1
    assert {identifier: after[identifier] for identifier in before} == before
    assert {identifier: reopened.frozen(identifier, 1) for identifier in before} == snapshots
    added = next(item for identifier, item in after.items() if identifier not in before)
    assert added["name"] == "旅行 Vlog" and added["enabled"]
    assert StyleLibrary(old.path).catalog(admin=True, principal="member") == reopened.catalog(admin=True, principal="member")


@pytest.mark.asyncio
async def test_routes_enforce_real_admin_dependency_and_user_context(library, monkeypatch):
    from viral_dna_api import identity
    from viral_dna_api.account_preferences import UserPreferencesRepository, UserPreferencesService, create_user_preferences_router
    app = FastAPI()
    app.include_router(style_library.create_style_library_admin_router(identity.require_platform_admin))
    context = SimpleNamespace(current_account=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    app.include_router(style_library.create_style_library_user_router(context))
    app.include_router(create_user_preferences_router(UserPreferencesService(context, UserPreferencesRepository(library.path.with_suffix(".json")))))
    monkeypatch.setattr(identity, "current_auth_mode", lambda: identity.AuthMode.EXTERNAL)
    monkeypatch.setattr(identity, "admin_console_enabled", lambda: True)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/admin/visual-styles")).status_code == 401
        assert (await client.post("/admin/visual-styles/media", files={"file": ("x.png", b"x")})).status_code == 401
        monkeypatch.setattr(identity, "current_auth_mode", lambda: identity.AuthMode.LOCAL_BOOTSTRAP)
        assert (await client.get("/admin/visual-styles")).status_code == 200
        first = (await client.get("/me/settings/visual-styles")).json()["items"][0]
        assert (await client.post("/me/settings/visual-styles/preview", json=first["selection"])).status_code == 200
        assert (await client.put(f"/me/settings/visual-styles/{first['id']}/favorite", json={"favorite": True})).status_code == 200
        assert (await client.get(first["cover_url"].removeprefix("/api/v1"))).status_code == 200
        travel = next(item for item in (await client.get("/me/settings/visual-styles")).json()["items"] if item["name"] == "旅行 Vlog")
        preview = await client.post("/me/settings/visual-styles/preview", json=travel["selection"])
        assert preview.status_code == 200
        assert "共享现场光向" in preview.json()["image_prompt"]
        assert "旅行 Vlog 动态" in preview.json()["video_prompt"]
        assert (await client.get(travel["cover_url"].removeprefix("/api/v1"))).status_code == 200
        context.current_account.side_effect = HTTPException(401, "请先登录")
        assert (await client.get("/me/settings/visual-styles")).status_code == 401
        assert (await client.get(first["cover_url"].removeprefix("/api/v1"))).status_code == 401


@pytest.mark.asyncio
async def test_completed_plan_style_edit_preserves_generation_input_and_publishes(library, tmp_path, monkeypatch):
    from test_creative_concepts import setup, finish
    from test_generation_jobs import _workspace
    from viral_dna_api.models import Video, AnalysisRecord
    from viral_dna_api.production import ProductionService
    from viral_dna_api.viral_insights.contracts import CreativeActionRequest, CreativeGenerateRequest, ViralConceptPublishRequest
    from viral_dna_api.viral_insights.production_style import ProductionStyleUpdate, production_style
    from viral_dna_api.viral_insights.prompt_language_service import concept_document
    from viral_dna_api.viral_insights.publisher import ProductionConceptPublisher
    repo, report, categories, provider, creative = await setup()
    initial = await finish(creative, await creative.generate(report.analysis_id, CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id)))
    expanded = await finish(creative, await creative.act(initial.id, initial.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=True))
    before = expanded.model_dump(mode="json")
    selection = library.catalog()["items"][0]["selection"]
    response = await production_style(creative, expanded.id, ProductionStyleUpdate(expected_revision="0", visual_style=selection))
    assert response["revision"] == "1"
    updated = await creative.get(expanded.id)
    assert updated.visual_style_snapshot == before["visual_style_snapshot"]
    assert updated.input_snapshot == before["input_snapshot"]
    assert updated.concepts[0].model_dump(mode="json") == before["concepts"][0]
    assert concept_document(updated)["visual_style_snapshot"] == response["snapshot"]
    with pytest.raises(HTTPException) as conflict:
        await production_style(creative, expanded.id, ProductionStyleUpdate(expected_revision="0", visual_style=selection))
    assert conflict.value.status_code == 409
    record_id = uuid4()
    await repo.save_video(Video(id=report.video_id, record_id=record_id, source_type="upload", filename="test.mp4", title="测试", width=1080, height=1920, duration_seconds=8.5, status="ready"))
    await repo.save_record(AnalysisRecord(id=record_id, video_id=report.video_id, name="测试", source_type="upload", latest_analysis_id=report.analysis_id))
    production = ProductionService(repo, _workspace(tmp_path, monkeypatch))
    creative.insights.publisher = ProductionConceptPublisher(production)
    published = await creative.insights.publish_concept(expanded.id, expanded.concepts[0].id, ViralConceptPublishRequest(record_id=record_id))
    context = await production.get_prompt_context(published.project_id)
    assert context.visual_style_snapshot == response["snapshot"]
    read = await production_style(creative, expanded.id)
    assert read["revision"] == str(context.id)
    cleared = await production_style(creative, expanded.id, ProductionStyleUpdate(expected_revision=read["revision"], visual_style={"preset": "original"}))
    assert cleared["snapshot"] == {}
    assert (await production.get_prompt_context(published.project_id)).visual_style_snapshot == {}
    assert (await creative.get(expanded.id)).visual_style_snapshot == before["visual_style_snapshot"]
