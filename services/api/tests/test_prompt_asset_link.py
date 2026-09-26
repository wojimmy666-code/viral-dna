"""Library image selection must link before per-use spatial roles are saved."""

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from test_production_api import seed_completed_analysis
from test_storyboard_prompt_editor import runtime

from viral_dna_api.asset_library import AssetLibraryService, AssetMediaKind, AssetType
from viral_dna_api.asset_routes import create_asset_router
from viral_dna_api.models import ProductionProjectCreate, ReferenceAssetType
from viral_dna_api.production import ProductionService
from viral_dna_api.project_assets import ASSET_TO_REFERENCE_TYPE, ProjectAssetService
from viral_dna_api.skill_workflow.contracts import GateDecisionRequest, SkillGate
from viral_dna_api.skill_workflow.routes import create_skill_workflow_router
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import AccountContextService, LocalAccountCatalogRepository


async def environment(tmp_path, monkeypatch, origin="analysis"):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    workspace = WorkspaceManager()
    store = SQLiteStore(workspace.database_path)
    context = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "account-catalog.json"), workspace
    )
    storage = StorageManager(store, workspace)
    bridge = ProjectAssetService(store, workspace, storage, context)
    library = AssetLibraryService(store, storage, context)
    service = ProductionService(
        store, workspace, project_assets=bridge,
        image_gateway=SimpleNamespace(), video_gateway=SimpleNamespace(),
    )
    skill = None
    if origin == "skill_run":
        skill = await runtime(store)
        skill.service.production_service = service
        skill.service.asset_library = library
        await skill.service.decide_gate(
            skill.run.id, SkillGate.STORYBOARD_APPROVED,
            GateDecisionRequest(
                decision="approve", related_revision_ids=[skill.outline.id, skill.manifest.id]
            ),
        )
        owner = await store.get_project(skill.project.id)
        project = await store.get_production_project(owner.source_binding.production_project_id)
    else:
        record, _, analysis, _ = await seed_completed_analysis(store)
        detail = await service.create_project(
            record.id, ProductionProjectCreate(base_analysis_id=analysis.id)
        )
        project = detail.project

    from viral_dna_api import main

    monkeypatch.setattr(main, "production_service", service)
    app = FastAPI()
    app.include_router(create_asset_router(library), prefix="/api/v1")
    if skill:
        app.include_router(create_skill_workflow_router(skill.service), prefix="/api/v1")
    for path, handler, method, status in (
        ("/productions/{project_id}/assets/{asset_id}/link",
         main.link_production_asset, "POST", 201),
        ("/productions/{project_id}/references", main.list_production_references, "GET", 200),
        ("/production-shots/{shot_plan_id}/visual-beats/{visual_beat_id}",
         main.update_production_visual_beat, "PATCH", 200),
    ):
        app.add_api_route(f"/api/v1{path}", handler, methods=[method], status_code=status)
    active = await context.ensure_current()
    return SimpleNamespace(
        app=app, store=store, workspace=workspace, service=service, bridge=bridge,
        workspace_id=active.active_workspace.id, project=project, skill=skill,
    )


def client_for(env):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def upload(client, env, asset_type):
    png = BytesIO()
    Image.new("RGB", (96, 54), "navy").save(png, format="PNG")
    response = await client.post(
        f"/api/v1/workspaces/{env.workspace_id}/assets",
        data={"type": asset_type, "name": "人物横向走动", "rights_confirmed": "true"},
        files={"file": ("spatial.png", png.getvalue(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json(), png.getvalue()


def test_every_library_classification_has_an_image_reference_mapping():
    assert set(ASSET_TO_REFERENCE_TYPE) == set(AssetType)
    assert all(isinstance(value, ReferenceAssetType) for value in ASSET_TO_REFERENCE_TYPE.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["analysis", "skill_run"])
@pytest.mark.parametrize("asset_type", ["motion_reference", "spatial_depth"])
async def test_library_image_links_and_saves_spatial_use_without_reclassifying(
    tmp_path, monkeypatch, origin, asset_type
):
    env = await environment(tmp_path, monkeypatch, origin)
    async with client_for(env) as client:
        asset, original = await upload(client, env, asset_type)
        asset_id = UUID(asset["id"])
        before = await env.store.get_asset(asset_id)
        objects_before = await env.store.list_storage_objects()
        listing = await client.get(
            f"/api/v1/workspaces/{env.workspace_id}/assets",
            params={"prompt_images_only": "true"},
        )
        assert listing.status_code == 200, listing.text
        assert [item["id"] for item in listing.json()["items"]] == [asset["id"]]

        response = await client.post(
            f"/api/v1/productions/{env.project.id}/assets/{asset_id}/link",
            json={"expected_revision_id": str(env.project.current_revision_id)},
        )
        assert response.status_code == 201, response.text
        revision_id = response.json()["current_revision_id"]
        assert response.json()["type"] == "prop"
        assert revision_id != str(env.project.current_revision_id)

        # The shared picker registers the selection with Skill after the project link.
        if env.skill:
            selected = await client.post(
                f"/api/v1/projects/{env.skill.project.id}/prompt-assets/{asset_id}"
            )
            assert selected.status_code == 200, selected.text
            facts = next(item for item in selected.json() if item["asset_id"] == str(asset_id))
            assert facts["image_eligible"]

        shot = (await env.store.list_shot_plans(env.project.id))[0]
        beat = shot.visual_beats[0]
        saved = await client.patch(
            f"/api/v1/production-shots/{shot.id}/visual-beats/{beat.id}",
            json={
                "expected_revision_id": revision_id,
                "image_prompt": "旅行随拍，空间关系参考 @人物横向走动",
                "image_prompt_mentions": [{
                    "reference_asset_id": str(asset_id),
                    "label": "人物横向走动", "role": "spatial",
                }],
                "reference_bindings": [{"reference_asset_id": str(asset_id), "role": "spatial"}],
            },
        )
        assert saved.status_code == 200, saved.text
        reloaded = SQLiteStore(env.workspace.database_path)
        persisted = await reloaded.get_shot_plan(shot.id)
        mention = persisted.visual_beats[0].image_prompt_mentions[0]
        assert mention.reference_asset_id == asset_id
        assert mention.role == "spatial"
        bindings = await reloaded.list_reference_bindings(shot.id)
        assert env.service._image_bindings_for_beat(
            persisted, persisted.visual_beats[0], bindings
        )[0].role == "spatial"
        assert await reloaded.get_asset(asset_id) == before
        assert await reloaded.list_storage_objects() == objects_before
        assert (await client.get(asset["content_url"])).content == original
        assert len(await reloaded.list_project_asset_links(env.project.id)) == 1
        assert not await reloaded.list_generation_runs(env.project.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("media_kind", [AssetMediaKind.VIDEO, AssetMediaKind.DEPTH_VIDEO])
@pytest.mark.parametrize("reference_type", [None, "scene"])
async def test_non_image_is_rejected_even_with_explicit_reference_type(
    tmp_path, monkeypatch, media_kind, reference_type
):
    env = await environment(tmp_path, monkeypatch)
    async with client_for(env) as client:
        asset, _ = await upload(client, env, "motion_reference")
        asset_id = UUID(asset["id"])
        record = await env.store.get_asset(asset_id)
        # Simulate a video record with an image thumbnail: media kind, not thumbnail,
        # determines eligibility. No video decoder or paid generation is invoked.
        record = record.model_copy(update={"media_kind": media_kind})
        await env.store.save_asset(record)
        revisions_before = await env.store.list_production_revisions(env.project.id)
        request = {"expected_revision_id": str(env.project.current_revision_id)}
        if reference_type:
            request["type"] = reference_type
        response = await client.post(
            f"/api/v1/productions/{env.project.id}/assets/{asset_id}/link", json=request,
        )
        assert response.status_code == 422, response.text
        assert "图片资产" in response.json()["detail"]
        assert not await env.store.list_project_asset_links(env.project.id)
        assert await env.store.get_asset(asset_id) == record
        assert await env.store.list_production_revisions(env.project.id) == revisions_before
        assert await env.store.get_production_project(env.project.id) == env.project


@pytest.mark.asyncio
async def test_missing_type_mapping_returns_actionable_error_without_link(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with client_for(env) as client:
        asset, _ = await upload(client, env, "scene")
        # Protect the bridge if a future library classification is added without a mapping.
        monkeypatch.delitem(ASSET_TO_REFERENCE_TYPE, AssetType.SCENE)
        response = await client.post(
            f"/api/v1/productions/{env.project.id}/assets/{asset['id']}/link",
            json={"expected_revision_id": str(env.project.current_revision_id)},
        )
        assert response.status_code == 422, response.text
        assert "资产分类" in response.json()["detail"]
        assert not await env.store.list_project_asset_links(env.project.id)
        assert await env.store.get_production_project(env.project.id) == env.project
