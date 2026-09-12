"""Real authentication, SQLite, project/asset routers; no live workspace or generators."""

import asyncio
import io
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from PIL import Image

from viral_dna_api.access_context import account_access, request_edit_fence
from viral_dna_api.accounts.authorization import create_project_authorizer
from viral_dna_api.accounts.http import (
    AccountAuthenticationMiddleware,
    create_account_router,
    error_response,
)
from viral_dna_api.accounts.repository import AccountError
from viral_dna_api.accounts.runtime import account_repository
from viral_dna_api.asset_library import AssetLibraryService
from viral_dna_api.asset_routes import create_asset_router
from viral_dna_api.identity import create_identity_router
from viral_dna_api.models import ProductionProject, ShotPlan
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import ProjectCreate, ProjectService, create_project_router
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.store import WorkspaceStore
from viral_dna_api.workspace import workspace_manager
from viral_dna_api.workspace_catalog import create_account_context_service

PASSWORD = "isolated-test-password-456"
ORIGIN = "http://testserver"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_AUTH_MODE", "password")
    monkeypatch.setenv("VIRAL_DNA_AUTH_DB_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.setenv("VIRAL_DNA_ACCOUNTS_ROOT", str(tmp_path / "tenants"))
    auth = account_repository()
    auth.bootstrap(
        admin_password=PASSWORD,
        owner_password=PASSWORD,
        kind="enterprise",
        name="企业甲",
        username="13800000001",
        display_name="甲负责人",
        legacy_root=tmp_path / "legacy",
        account_id=uuid4(),
        workspace_id=uuid4(),
        location_id=uuid4(),
    )
    owner_token = auth.login("13800000001", PASSWORD, admin=False, remote="seed")
    owner = auth.session(owner_token)["access"]
    member = auth.invite(
        str(owner.account_id),
        username="13800000002",
        display_name="甲成员",
        actor=str(owner.user_id),
    )
    auth.activate(member["activation_token"], PASSWORD)
    person = auth.create_account(
        kind="personal", name="个人乙", username="13900000001", display_name="乙", actor="admin"
    )
    auth.activate(person["activation_token"], PASSWORD)
    repository = WorkspaceStore()  # default legacy backend remains test-only memory
    repository._memory_mode = False  # every verified account uses its own temporary SQLite
    context = create_account_context_service(workspace_manager)
    catalog = PlatformSkillCatalogService(None)
    projects = ProjectService(repository, catalog, context)
    storage = StorageManager(repository, workspace_manager)
    assets = AssetLibraryService(repository, storage, context)
    app = FastAPI(dependencies=[Depends(create_project_authorizer(repository))])
    app.add_middleware(AccountAuthenticationMiddleware)
    app.add_exception_handler(AccountError, lambda request, exc: error_response(exc))
    app.include_router(create_account_router(context, repository), prefix="/api/v1")
    app.include_router(create_identity_router(context), prefix="/api/v1")
    app.include_router(create_project_router(projects), prefix="/api/v1")
    app.include_router(create_asset_router(assets), prefix="/api/v1")

    @app.put("/api/v1/production-shots/{shot_plan_id}/test-draft")
    async def edit_shot(shot_plan_id: UUID, request: Request):
        shot = await repository.get_shot_plan(shot_plan_id)
        body = await request.json()
        if body.get("expire_before_write"):
            with auth.connect(write=True) as db:
                db.execute("UPDATE project_edit_leases SET expires_at=0")
        await repository.save_shot_plan(shot.model_copy(update={"image_prompt": body["text"]}))
        return {"saved": True}

    @app.put("/api/v1/productions/{project_id}/test-submit")
    async def submit_job(project_id: UUID):
        async def worker():
            await asyncio.sleep(0.03)
            project = await repository.get_production_project(project_id)
            await repository.save_production_project(
                project.model_copy(update={"name": "后台任务已完成"})
            )

        app.state.worker = asyncio.create_task(worker())
        return {"submitted": True}

    async def seed():
        token = account_access.set(owner)
        try:
            skill = (await catalog.list_catalog()).items[0]
            project = await projects.create(
                ProjectCreate(
                    kind="skill", name="甲项目", skill_version_id=skill.current_version.id
                )
            )
            production = ProductionProject(
                record_id=project.id,
                name="甲分镜",
                origin_type="skill_run",
                origin_id=uuid4(),
                production_seed_id=uuid4(),
                style_bible_revision_id=uuid4(),
            )
            await repository.save_production_project(production)
            shot = ShotPlan(
                project_id=production.id,
                revision_id=uuid4(),
                source_shot_id="shot-1",
                index=1,
                start_seconds=0,
                end_seconds=2,
                duration_seconds=2,
                image_prompt="原始提示词",
            )
            await repository.save_shot_plan(shot)
            return project, production, shot
        finally:
            account_access.reset(token)

    project, production, shot = asyncio.run(seed())
    return SimpleNamespace(
        app=app,
        auth=auth,
        repository=repository,
        owner=owner,
        project=project,
        production=production,
        shot=shot,
    )


def client_for(sandbox):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sandbox.app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


def test_only_admin_with_csrf_and_confirmation_can_change_phone(sandbox):
    async def scenario():
        path = (
            f"/api/v1/admin/accounts/{sandbox.owner.account_id}"
            f"/members/{sandbox.owner.user_id}/phone"
        )
        payload = {
            "current_username": "13800000001",
            "username": "13900000009",
            "confirm_change": True,
        }
        async with (
            client_for(sandbox) as owner,
            client_for(sandbox) as admin,
            client_for(sandbox) as member,
        ):
            assert (await admin.patch(path, json=payload)).status_code == 401
            await login(owner)
            await login(member, "13800000002")
            assert (await owner.patch(path, json=payload)).status_code == 401
            await login(admin, "admin", admin=True)
            csrf = admin.headers.pop("X-CSRF-Token")
            assert (await admin.patch(path, json=payload)).status_code == 403
            admin.headers["X-CSRF-Token"] = csrf
            rejected = await admin.patch(path, json={**payload, "confirm_change": False})
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "phone_confirmation_required"
            assert (
                await admin.patch(path, json={**payload, "username": "13900000001"})
            ).status_code == 409
            assert (await owner.get("/api/v1/session")).status_code == 200
            response = await admin.patch(path, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["username"] == "13900000009"
            assert "password" not in response.text
            assert (await owner.get("/api/v1/session")).status_code == 401
            assert (await member.get("/api/v1/session")).status_code == 200
            assert (await admin.get("/api/v1/admin/session")).status_code == 200
            assert (await admin.patch(path, json=payload)).json()["detail"][
                "code"
            ] == "username_changed"
            await login(owner, "13900000009")
            projects = await owner.get("/api/v1/projects")
            assert projects.status_code == 200
            assert str(sandbox.project.id) in projects.text

    asyncio.run(scenario())


async def login(client, name="13800000001", admin=False):
    response = await client.post(
        "/api/v1/admin/auth/login" if admin else "/api/v1/auth/login",
        json={"username": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


async def acquire(client, project_id, editor="editor-tab-one-123", token="first-lease-token-" * 3):
    body = {"editor_id": editor, "token": token}
    response = await client.post(f"/api/v1/projects/{project_id}/edit-lease/acquire", json=body)
    assert response.status_code == 200, response.text
    if response.json()["editable"]:
        client.headers.update({"X-Editor-Id": editor, "X-Edit-Token": token})
    return response.json(), body


def test_authentication_csrf_and_independent_admin(sandbox):
    async def scenario():
        async with client_for(sandbox) as client:
            assert (await client.get("/api/v1/projects")).status_code == 401
            await login(client)
            assert (await client.get("/api/v1/admin/accounts")).status_code == 401
            client.headers.pop("X-CSRF-Token")
            assert (await client.post("/api/v1/auth/logout")).status_code == 403
            await login(client)
            client.headers["Origin"] = "https://untrusted.example"
            assert (await client.post("/api/v1/auth/logout")).status_code == 403
        async with client_for(sandbox) as admin:
            await login(admin, "admin", True)
            assert (await admin.get("/api/v1/admin/accounts")).status_code == 200
            assert (await admin.get("/api/v1/projects")).status_code == 401
            assert (await admin.get("/api/v1/session")).status_code == 401

    asyncio.run(scenario())


def test_enterprise_sharing_and_cross_account_asset_media_isolation(sandbox):
    async def scenario():
        original_root = workspace_manager.root
        async with (
            client_for(sandbox) as owner,
            client_for(sandbox) as member,
            client_for(sandbox) as person,
        ):
            a, _, b = await asyncio.gather(
                login(owner), login(member, "13800000002"), login(person, "13900000001")
            )
            lists = await asyncio.gather(
                *(client.get("/api/v1/projects") for client in [owner, member, person])
            )
            assert [[p["name"] for p in response.json()["items"]] for response in lists] == [
                ["甲项目"],
                ["甲项目"],
                [],
            ]
            assert a["account_id"] != b["account_id"]
            assert (
                await person.get(f"/api/v1/projects/{sandbox.project.id}/readonly")
            ).status_code == 404
            assert (
                await person.post(
                    f"/api/v1/projects/{sandbox.project.id}/edit-lease/acquire",
                    json={"editor_id": "bad-tab-identifier", "token": "x" * 40},
                )
            ).status_code == 404
            png = io.BytesIO()
            Image.new("RGB", (32, 32), "yellow").save(png, format="PNG")
            response = await owner.post(
                f"/api/v1/workspaces/{sandbox.owner.workspace_id}/assets",
                data={"type": "product", "name": "甲的产品", "rights_confirmed": "true"},
                files={"file": ("fixture.png", png.getvalue(), "image/png")},
            )
            assert response.status_code == 201, response.text
            asset_id = response.json()["id"]
            assert (
                await member.get(f"/api/v1/assets/{asset_id}/content")
            ).content == png.getvalue()
            assert (await person.get(f"/api/v1/assets/{asset_id}/content")).status_code == 404
            assert (
                await person.get(f"/api/v1/workspaces/{sandbox.owner.workspace_id}/assets")
            ).status_code in {403, 404}
            assert (
                await owner.put(
                    "/api/v1/context/active-workspace", json={"workspace_id": str(uuid4())}
                )
            ).status_code in {403, 404}
        assert workspace_manager.root == original_root
        assert account_access.get() is None
        assert request_edit_fence.get() is None

    asyncio.run(scenario())


def test_only_one_editor_fenced_writes_and_readonly_does_not_write(sandbox):
    async def scenario():
        async with client_for(sandbox) as owner, client_for(sandbox) as member:
            await asyncio.gather(login(owner), login(member, "13800000002"))
            state, body = await acquire(owner, sandbox.project.id)
            assert state["editable"]
            other, _ = await acquire(
                member, sandbox.project.id, "editor-tab-two-123", "second-token-" * 4
            )
            assert not other["editable"] and other["display_name"] == "甲负责人"
            shot_path = f"/api/v1/production-shots/{sandbox.shot.id}/test-draft"
            assert (await member.put(shot_path, json={"text": "越权"})).status_code == 423
            readonly = await member.get(f"/api/v1/projects/{sandbox.project.id}/readonly")
            assert readonly.status_code == 200, readonly.text
            assert readonly.json()["productions"][0]["shots"][0]["image_prompt"] == "原始提示词"
            assert (
                await member.patch(f"/api/v1/projects/{sandbox.project.id}", json={"name": "越权"})
            ).status_code == 423
            assert (await owner.put(shot_path, json={"text": "首次保存"})).status_code == 200
            denied = await owner.put(
                shot_path, json={"text": "锁过期后的写入", "expire_before_write": True}
            )
            assert denied.status_code == 423, denied.text
            state, second_body = await acquire(
                member, sandbox.project.id, "editor-tab-two-123", "second-token-" * 4
            )
            assert state["editable"]
            await owner.post(f"/api/v1/projects/{sandbox.project.id}/edit-lease/release", json=body)
            assert (await member.put(shot_path, json={"text": "新编辑者保存"})).status_code == 200
            assert (await owner.put(shot_path, json={"text": "旧编辑者"})).status_code == 423
            await member.post(
                f"/api/v1/projects/{sandbox.project.id}/edit-lease/release", json=second_body
            )
            assert (
                await owner.patch(
                    f"/api/v1/projects/{sandbox.project.id}", json={"name": "列表重命名"}
                )
            ).status_code == 200
            state = await owner.get(f"/api/v1/projects/{sandbox.project.id}/edit-lease")
            assert not state.json()["occupied"]

    asyncio.run(scenario())


def test_background_job_keeps_tenant_after_release(sandbox):
    async def scenario():
        async with client_for(sandbox) as owner, client_for(sandbox) as person:
            await asyncio.gather(login(owner), login(person, "13900000001"))
            _, body = await acquire(owner, sandbox.project.id)
            result = await owner.put(f"/api/v1/productions/{sandbox.production.id}/test-submit")
            assert result.status_code == 200, result.text
            await owner.post(f"/api/v1/projects/{sandbox.project.id}/edit-lease/release", json=body)
            await person.get("/api/v1/projects")
            await sandbox.app.state.worker
            response = await owner.get(f"/api/v1/projects/{sandbox.project.id}/readonly")
            assert response.json()["productions"][0]["name"] == "后台任务已完成"
            assert (await person.get("/api/v1/projects")).json()["items"] == []

    asyncio.run(scenario())


def test_revoked_member_cannot_reacquire_with_captured_access(sandbox):
    token = sandbox.auth.login("13800000002", PASSWORD, admin=False, remote="captured")
    access = sandbox.auth.session(token)["access"]
    sandbox.auth.remove_member(
        str(access.account_id), str(access.user_id), str(sandbox.owner.user_id)
    )
    with pytest.raises(AccountError) as failure:
        sandbox.auth.lease(
            access, str(sandbox.project.id), editor_id="stale", token="stale", action="acquire"
        )
    assert failure.value.status == 401
