"""E-derived rules, conservative seed upgrades and real generation compilation.

All libraries and workspaces are temporary, and providers are mocks. No paid
image/video requests or existing user projects are used for this regression.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from test_image_input_modes import prepare
from test_style_library import definition

from viral_dna_api import style_library, style_reference
from viral_dna_api.image_generation.catalog import load_image_model_catalog
from viral_dna_api.image_generation.contracts import AdapterIdentity
from viral_dna_api.image_generation.gateway import ImageGenerationGateway
from viral_dna_api.models import GenerationCostSource, ImageExecutionMode
from viral_dna_api.project_prompts import ProjectPromptRevision, prompt_snapshot
from viral_dna_api.prompt_engine.still_image import contains_video_directives
from viral_dna_api.style_library import StyleLibrary, StyleWrite
from viral_dna_api.travel_vlog import CANDID_TRAVEL_VLOG, LEGACY_TRAVEL_VLOG
from viral_dna_api.visual_styles import freeze_style

VLOG_ID = str(uuid5(NAMESPACE_URL, "viraldna:style:travel_vlog"))


def vlog(library, **kwargs):
    return next(item for item in library.catalog(**kwargs)["items"] if item["id"] == VLOG_ID)


def published_rows(library):
    with library.transaction() as db:
        return {
            (row["style_id"], row["version"]): row["payload"]
            for row in db.execute("SELECT * FROM style_versions")
        }


@pytest.fixture
def legacy_library(tmp_path, monkeypatch):
    # Simulate the previous release without rewriting/deleting published rows.
    with monkeypatch.context() as old_release:
        old_release.setattr(StyleLibrary, "_seed_vlog_candid", staticmethod(lambda db: None))
        library = StyleLibrary(tmp_path / "styles.sqlite3")
    assert vlog(library)["version"] == 2
    return library


def test_upgrade_preserves_history_media_preferences_and_is_idempotent(legacy_library, monkeypatch):
    library = legacy_library
    monkeypatch.setattr(style_library, "get_style_library", lambda: library)
    library.preference("member-a", VLOG_ID, favorite=True, used=True)
    before = library.catalog(admin=True, principal="member-a")
    frozen = freeze_style(vlog(library)["selection"])
    history = published_rows(library)
    with library.transaction() as db:
        media_before = list(db.execute("SELECT id, content FROM style_media ORDER BY id"))
        preferences = list(db.execute("SELECT * FROM style_preferences"))
    reopened = StyleLibrary(library.path)
    updated = vlog(reopened, principal="member-a")
    assert updated["version"] == updated["revision"] == 3
    assert updated["reference_image_id"] is None
    assert updated["favorite"] and updated["used_at"]
    assert updated["cover_id"] == vlog(library)["cover_id"]
    after = reopened.catalog(admin=True, principal="member-a")
    assert [item for item in before["items"] if item["id"] != VLOG_ID] == [
        item for item in after["items"] if item["id"] != VLOG_ID
    ]
    assert all(published_rows(reopened)[key] == value for key, value in history.items())
    assert len(published_rows(reopened)) == len(history) + 1
    assert freeze_style({"catalog_id": VLOG_ID, "catalog_version": 2}) == frozen
    assert StyleLibrary(library.path).catalog(admin=True, principal="member-a") == after
    with reopened.transaction() as db:
        assert list(db.execute("SELECT id, content FROM style_media ORDER BY id")) == media_before
        assert list(db.execute("SELECT * FROM style_preferences")) == preferences
    # A cached service instance reads the new version without a restart.
    assert vlog(library)["version"] == 3


@pytest.mark.parametrize("edit", [
    "draft", "published", "disabled", "metadata", "same_rules_saved", "custom_reference",
])
def test_upgrade_never_overwrites_admin_work(legacy_library, edit):
    library = legacy_library
    original = vlog(library)
    if edit == "disabled":
        library.action(VLOG_ID, original["revision"], "disable")
    else:
        changes = {
            "draft": {"image_prompt": "管理员未发布的图片规则"},
            "published": {"video_prompt": "管理员发布的视频规则"},
            "metadata": {"tags": ["管理员标签"], "sort_order": 19},
            "same_rules_saved": {},
            "custom_reference": {"reference_image_id": original["cover_id"]},
        }[edit]
        saved = library.save(VLOG_ID, StyleWrite(
            expected_revision=original["revision"], style=definition(original, **changes),
        ))
        if edit != "draft":
            library.action(VLOG_ID, saved["revision"], "publish")
    before = library.catalog(admin=True)
    history = published_rows(library)
    reopened = StyleLibrary(library.path)
    assert reopened.catalog(admin=True) == before
    assert published_rows(reopened) == history


def test_legacy_seed_remains_exact_and_latest_is_the_same_for_legacy_clients(tmp_path, monkeypatch):
    library = StyleLibrary(tmp_path / "styles.sqlite3")
    monkeypatch.setattr(style_library, "get_style_library", lambda: library)
    history = published_rows(library)
    for version in (1, 2):
        old = json.loads(history[VLOG_ID, version])
        assert old["description"] == LEGACY_TRAVEL_VLOG[1]
        assert old["image_prompt"] == LEGACY_TRAVEL_VLOG[2]
        assert old["video_prompt"] == "\n".join(LEGACY_TRAVEL_VLOG[2:])
    item = vlog(library)
    assert item["image_prompt"] == CANDID_TRAVEL_VLOG[2]
    for selection in (item["selection"], {"preset": "travel_vlog"}):
        snapshot = freeze_style(selection)
        image = snapshot["image_prompt"]
        assert "reference_image" not in snapshot
        assert not contains_video_directives(image)
        for required in (
            "不额外增强天空蓝色", "不单独提亮人脸", "远景灰霾", "有风时才允许",
            "少量浮尘", "小脸不增加特写级毛孔", "不改变任务实际分辨率和质量设置",
            "不强制阴天、灰调或低饱和", "已有的特写、人物位置、构图、机位和主体比例要求优先",
            "空间参考规定的景别和人景关系也优先", "不用重复波纹",
        ):
            assert required in image
        for leaked in ("金字塔", "巴黎", "埃菲尔", "JK", "向左", "Cait", "kontalis"):
            assert leaked not in image and leaked not in snapshot["video_prompt"]
        assert "逐帧闪烁" not in image
        assert "不逐帧闪烁" in snapshot["video_prompt"]
        assert "不为了人物占比默认值重新构图" in snapshot["video_prompt"]


def test_v1_without_reference_also_upgrades_without_rewriting_it(tmp_path, monkeypatch):
    with monkeypatch.context() as old_release:
        old_release.setattr(StyleLibrary, "_seed_vlog_reference", staticmethod(lambda db: None))
        old_release.setattr(StyleLibrary, "_seed_vlog_candid", staticmethod(lambda db: None))
        library = StyleLibrary(tmp_path / "styles.sqlite3")
    assert vlog(library)["version"] == 1
    history = published_rows(library)
    reopened = StyleLibrary(library.path)
    assert vlog(reopened)["version"] == 3
    assert all(published_rows(reopened)[key] == value for key, value in history.items())
    assert "reference_image" not in reopened.frozen(VLOG_ID, 3)


@pytest.mark.asyncio
async def test_candid_rules_reach_model_without_hidden_style_image(tmp_path, monkeypatch):
    workspace, _, project, shot, _ = await prepare(tmp_path, monkeypatch)
    library = StyleLibrary(tmp_path / "styles.sqlite3")
    monkeypatch.setattr(style_library, "get_style_library", lambda: library)
    monkeypatch.setattr(style_reference, "get_style_library", lambda: library)
    snapshot = freeze_style(vlog(library)["selection"])
    context = ProjectPromptRevision(project_id=project.id, visual_style_snapshot=snapshot)
    compiled = prompt_snapshot(shot.image_prompt, context, "image", shot_key=str(shot.id))
    # Production compiles the frozen global/local/style text before the gateway;
    # visual_style_snapshot separately supplies optional reference-image metadata.
    gateway_shot = shot.model_copy(update={"image_prompt": compiled["compiled_prompt"]})
    option = load_image_model_catalog().option("qwen_image_2_pro")
    identity = AdapterIdentity(
        execution_mode=ImageExecutionMode.REMOTE_API, provider=option.provider, model=option.model,
        model_snapshot=option.model, adapter_id="isolated", adapter_version="1",
        protocol_version="test", capability=option.capabilities.model_copy(
            update={"max_reference_images": 0}), model_option=option,
        estimated_cost_micros=0, cost_estimate_known=True,
        cost_source=GenerationCostSource.CONFIGURED_RATE,
    )
    adapter = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError("mock: never paid")))
    gateway = ImageGenerationGateway(workspace, SimpleNamespace(get=lambda: SimpleNamespace(
        enabled=True, execution_mode="remote_api", semantic_quality_enabled=False,
    )))
    gateway._adapter = AsyncMock(return_value=(identity, adapter))
    with pytest.raises(RuntimeError, match="mock: never paid"):
        await gateway.generate(
            project, gateway_shot, project.current_revision_id, [], [], candidate_count=1,
            source_path=None, input_mode="text_to_image", reuse_cache=False,
            visual_style_snapshot=snapshot,
        )
    request = adapter.generate.call_args.args[0]
    assert request.input_mode == "text_to_image"
    assert not request.references
    assert "不额外增强天空蓝色" in request.positive_prompt
    assert "有风时才允许" in request.positive_prompt
    assert "少量浮尘" in request.positive_prompt
    assert "旅行 Vlog 动态" not in request.positive_prompt
    assert shot.image_prompt == compiled["local_prompt"]
    video = prompt_snapshot("保持原有动作和镜头", context, "video")
    assert "不逐帧闪烁" in video["compiled_prompt"]
    assert video["local_prompt"] == "保持原有动作和镜头"
