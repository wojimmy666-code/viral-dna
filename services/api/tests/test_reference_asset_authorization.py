"""Reference mutations with real login, edit leases, SQLite and production handlers."""

import asyncio
import io
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from test_account_isolation_http import acquire, client_for, login
from test_account_isolation_http import sandbox as sandbox

from viral_dna_api.access_context import account_access
from viral_dna_api.accounts.authorization import reference_owner_project
from viral_dna_api.accounts.repository import AccountError
from viral_dna_api.models import (
    ProductionChangeKind,
    ReferenceAsset,
    ReferenceAssetCreate,
    ReferenceBinding,
    WorkflowItemStatus,
)
from viral_dna_api.production import ProductionService, _filesystem_path
from viral_dna_api.production_seeds import (
    ProductionSeedAudioIntent,
    ProductionSeedShot,
    ProductionSeedSubtitleIntent,
    SkillProductionSeedBuilder,
    canonical_digest,
)
from viral_dna_api.project_assets import ProjectAssetService
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.workspace import workspace_manager
from viral_dna_api.workspace_catalog import create_account_context_service


@contextmanager
def as_owner(env):
    token = account_access.set(env.owner)
    try:
        yield
    finally:
        account_access.reset(token)


@pytest.fixture
def references(sandbox, monkeypatch):
    from viral_dna_api import main

    repo = sandbox.repository
    context = create_account_context_service(workspace_manager)
    bridge = ProjectAssetService(
        repo, workspace_manager, StorageManager(repo, workspace_manager), context
    )
    service = ProductionService(
        repo,
        workspace_manager,
        project_assets=bridge,
        image_gateway=SimpleNamespace(),
        video_gateway=SimpleNamespace(),
    )
    monkeypatch.setattr(main, "production_service", service)
    # Register the production handlers themselves, not look-alike test endpoints.
    for path, handler, method in (
        ("/productions/{project_id}/references", main.list_production_references, "GET"),
        ("/references/{asset_id}", main.update_production_reference, "PATCH"),
        ("/references/{asset_id}", main.archive_production_reference, "DELETE"),
    ):
        sandbox.app.add_api_route(f"/api/v1{path}", handler, methods=[method])

    png = io.BytesIO()
    Image.new("RGB", (64, 48), "navy").save(png, format="PNG")

    async def seed():
        with as_owner(sandbox):
            other_owner = sandbox.project.model_copy(update={"id": uuid4(), "name": "复用项目"})
            await repo.save_project(other_owner)
            other = sandbox.production.model_copy(
                update={
                    "id": uuid4(),
                    "record_id": other_owner.id,
                    "owner_project_id": other_owner.id,
                    "name": "复用方案",
                }
            )
            productions = []
            for project in (sandbox.production, other):
                shot_data = {
                    "stable_shot_key": "shot_reference01",
                    "order": 1,
                    "start_frame": 0,
                    "duration_frames": 60,
                    "description": "测试画面",
                    "image_prompt": "静态画面",
                    "video_prompt": "缓慢移动",
                }
                shot_data["input_hash"] = canonical_digest(shot_data)
                seed = SkillProductionSeedBuilder().build(
                    owner_project_id=project.owner_project_id,
                    skill_run_id=project.origin_id,
                    name=project.name,
                    output_aspect_ratio="9:16",
                    output_width=1080,
                    output_height=1920,
                    fps=30,
                    style_bible_revision_id=project.style_bible_revision_id,
                    style_bible_snapshot={},
                    shots=[ProductionSeedShot.model_validate(shot_data)],
                    reference_assets=[],
                    audio_intent=ProductionSeedAudioIntent(),
                    subtitle_intent=ProductionSeedSubtitleIntent(),
                )
                await repo.save_production_seed(seed)
                project = project.model_copy(update={"production_seed_id": seed.id})
                await repo.save_production_project(project)
                productions.append(project)

            asset = await bridge.create_reference(
                productions[0],
                ReferenceAssetCreate(
                    expected_revision_id=uuid4(),
                    type="prop",
                    name="共享参考资产",
                    rights_confirmed=True,
                ),
                png.getvalue(),
                "reference.png",
                "image/png",
            )
            await bridge.link_asset(productions[1], asset.id)
            approved_id = uuid4()
            shot = sandbox.shot.model_copy(
                update={
                    "approved_image_candidate_id": approved_id,
                    "image_status": WorkflowItemStatus.APPROVED,
                    "visual_beats": [
                        sandbox.shot.visual_beats[0].model_copy(
                            update={
                                "approved_image_candidate_id": approved_id,
                                "image_status": WorkflowItemStatus.APPROVED,
                            }
                        )
                    ],
                }
            )
            await repo.save_shot_plan(shot)
            await repo.save_reference_binding(
                ReferenceBinding(
                    shot_plan_id=shot.id,
                    reference_asset_id=asset.id,
                    role="product",
                )
            )
            revisions = []
            for index, project in enumerate(productions):
                project, revision = await service._prepare_revision(
                    project,
                    ProductionChangeKind.PROJECT_CREATED,
                    "隔离测试初始版本",
                )
                await repo.save_production_bundle(project, revision)
                productions[index] = project
                revisions.append(revision)
            return other_owner, productions, asset, revisions, approved_id

    other_owner, productions, asset, revisions, approved_id = asyncio.run(seed())
    sandbox.production, sandbox.other_production = productions
    sandbox.other_project = other_owner
    sandbox.reference = asset
    sandbox.bridge = bridge
    sandbox.service = service
    sandbox.revisions = revisions
    sandbox.approved_id = approved_id
    sandbox.png = png.getvalue()
    return sandbox


async def mutate(client, env, method, *, project_id=None, revision_id=None, asset_id=None):
    project_id = env.production.id if project_id is None else project_id
    params = {"project_id": str(project_id)}
    revision_id = revision_id or env.production.current_revision_id
    kwargs = {"params": params}
    if method == "DELETE":
        params["expected_revision_id"] = str(revision_id)
    else:
        kwargs["json"] = {"expected_revision_id": str(revision_id), "description": "更新说明"}
    return await client.request(
        method, f"/api/v1/references/{asset_id or env.reference.id}", **kwargs
    )


def test_remove_reference_only_unlinks_current_project_and_preserves_history(references):
    env = references

    async def scenario():
        with as_owner(env):
            assert await env.repository.get_reference_asset(env.reference.id) is None
            history_path = _filesystem_path(
                workspace_manager.resolve(env.revisions[0].snapshot_relative_path)
            )
            history = history_path.read_bytes()
        async with client_for(env) as client:
            await login(client)
            await acquire(client, env.project.id)
            response = await client.get(f"/api/v1/productions/{env.production.id}/references")
            assert response.status_code == 200, response.text
            assert [item["id"] for item in response.json()] == [str(env.reference.id)]
            response = await mutate(client, env, "DELETE")
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["archived_at"] and result["project_id"] == str(env.production.id)
            assert result["current_revision_id"] != str(env.production.current_revision_id)
            assert (
                await client.get(f"/api/v1/productions/{env.production.id}/references")
            ).json() == []
            assert (await client.get(result["content_url"])).content == env.png
            repeated = await mutate(
                client,
                env,
                "DELETE",
                revision_id=result["current_revision_id"],
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["current_revision_id"] == result["current_revision_id"]
        with as_owner(env):
            assert (await env.repository.get_asset(env.reference.id)).archived_at is None
            assert [
                item.id for item in await env.bridge.list_references(env.other_production.id)
            ] == [env.reference.id]
            assert history_path.read_bytes() == history
            shot = await env.repository.get_shot_plan(env.shot.id)
            assert shot.approved_image_candidate_id == env.approved_id
            assert shot.visual_beats[0].approved_image_candidate_id == env.approved_id
            assert shot.image_status == "approved"
            assert (
                await env.repository.get_production_project(env.other_production.id)
            ).current_revision_id == env.other_production.current_revision_id

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_reference_uses_selected_project_not_legacy_owner(references, method):
    env = references

    async def scenario():
        with as_owner(env):
            # Migrated assets can retain a legacy owner different from today's target.
            await env.repository.save_reference_asset(
                ReferenceAsset.model_validate(
                    {
                        **env.reference.model_dump(),
                        "project_id": env.production.id,
                    }
                )
            )
        async with client_for(env) as client:
            await login(client)
            await acquire(client, env.other_project.id)
            response = await mutate(
                client,
                env,
                method,
                project_id=env.other_production.id,
                revision_id=env.other_production.current_revision_id,
            )
            assert response.status_code == 200, response.text
            assert response.json()["project_id"] == str(env.other_production.id)
            if method == "PATCH":
                assert response.json()["description"] == "更新说明"
        with as_owner(env):
            assert (
                await env.repository.get_production_project(env.production.id)
            ).current_revision_id == env.production.current_revision_id
            assert len(await env.bridge.list_references(env.production.id)) == 1

    asyncio.run(scenario())


def test_edit_library_reference_without_a_legacy_record(references):
    env = references

    async def scenario():
        with as_owner(env):
            assert await env.repository.get_reference_asset(env.reference.id) is None
        async with client_for(env) as client:
            await login(client)
            await acquire(client, env.project.id)
            response = await mutate(client, env, "PATCH")
            assert response.status_code == 200, response.text
            assert response.json()["description"] == "更新说明"
            assert response.json()["current_revision_id"] != str(env.production.current_revision_id)
        with as_owner(env):
            assert (await env.repository.get_asset(env.reference.id)).description == "更新说明"
            assert len(await env.bridge.list_references(env.production.id)) == 1
            assert len(await env.bridge.list_references(env.other_production.id)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_reference_write_rechecks_lease_inside_sqlite_transaction(references, monkeypatch, method):
    env = references
    operation = "save_asset" if method == "PATCH" else "save_project_asset_link"
    with as_owner(env):
        backend = env.repository.backend.repository
        original = getattr(backend, operation)

    async def expire_before_write(value):
        with env.auth.connect(write=True) as db:
            db.execute("UPDATE project_edit_leases SET expires_at=0")
        return await original(value)

    monkeypatch.setattr(backend, operation, expire_before_write)

    async def scenario():
        async with client_for(env) as client:
            await login(client)
            await acquire(client, env.project.id)
            response = await mutate(client, env, method)
            assert response.status_code == 423, response.text
            assert response.json()["detail"]["code"] == "edit_lease_lost"
        with as_owner(env):
            assert len(await env.bridge.list_references(env.production.id)) == 1
            assert (await env.repository.get_asset(env.reference.id)).description == ""
            assert (
                await env.repository.get_production_project(env.production.id)
            ).current_revision_id == env.production.current_revision_id

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_reference_mutations_require_target_lease_and_own_account(references, method):
    env = references

    async def scenario():
        async with (
            client_for(env) as owner,
            client_for(env) as member,
            client_for(env) as outsider,
        ):
            assert (await mutate(owner, env, method)).status_code == 401
            await login(owner)
            await login(member, "13800000002")
            await login(outsider, "13900000001")
            assert (await mutate(owner, env, method)).status_code == 423
            await acquire(owner, env.other_project.id)
            assert (await mutate(owner, env, method)).status_code == 423
            await acquire(owner, env.project.id)
            assert (await mutate(member, env, method)).status_code == 423
            response = await mutate(outsider, env, method)
            assert response.status_code == 404, response.text
            # Stolen headers do not turn a different account into the project owner.
            outsider.headers.update(
                {
                    name: owner.headers[name]
                    for name in (
                        "X-Editor-Id",
                        "X-Edit-Token",
                    )
                }
            )
            assert (await mutate(outsider, env, method)).status_code == 404
            assert (await mutate(owner, env, method, revision_id=uuid4())).status_code == 409
        with as_owner(env):
            assert (
                await env.repository.get_production_project(env.production.id)
            ).current_revision_id == env.production.current_revision_id
            assert len(await env.bridge.list_references(env.production.id)) == 1
            assert (await env.repository.get_asset(env.reference.id)).description == ""

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_reference_cannot_borrow_an_unrelated_project_or_omit_project(references, method):
    env = references

    async def scenario():
        with as_owner(env):
            unrelated = env.production.model_copy(update={"id": uuid4(), "name": "无关联方案"})
            await env.repository.save_production_project(unrelated)
        async with client_for(env) as client:
            await login(client)
            await acquire(client, env.project.id)
            for project_id in (unrelated.id, env.project.id, uuid4()):
                response = await mutate(client, env, method, project_id=project_id)
                assert response.status_code == 404, response.text
            response = await mutate(client, env, method, asset_id=uuid4())
            assert response.status_code == 404, response.text
            response = await mutate(client, env, method, project_id="not-a-uuid")
            assert response.status_code == 422, response.text
            params = {"expected_revision_id": str(env.production.current_revision_id)}
            kwargs = {"params": params}
            if method == "PATCH":
                kwargs["json"] = {**params, "description": "不得更新"}
            response = await client.request(
                method,
                f"/api/v1/references/{env.reference.id}",
                **kwargs,
            )
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["code"] == "reference_project_required"
        with as_owner(env):
            assert (await env.repository.get_asset(env.reference.id)).description == ""
            assert len(await env.bridge.list_references(env.production.id)) == 1
            assert len(await env.bridge.list_references(env.other_production.id)) == 1

    asyncio.run(scenario())


def test_unmigrated_legacy_reference_keeps_its_single_project_scope(sandbox):
    async def scenario():
        with as_owner(sandbox):
            legacy = ReferenceAsset(
                project_id=sandbox.production.id,
                name="旧版参考资产",
                type="person",
                relative_path="references/legacy.png",
                mime_type="image/png",
                width=64,
                height=48,
                sha256="a" * 64,
            )
            await sandbox.repository.save_reference_asset(legacy)
            for selected_project in (None, str(sandbox.production.id)):
                assert await reference_owner_project(
                    sandbox.repository,
                    str(legacy.id),
                    selected_project,
                ) == str(sandbox.project.id)
            with pytest.raises(AccountError) as error:
                await reference_owner_project(
                    sandbox.repository,
                    str(legacy.id),
                    str(uuid4()),
                )
            assert error.value.status == 404

    asyncio.run(scenario())
