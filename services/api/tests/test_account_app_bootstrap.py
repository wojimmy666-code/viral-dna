"""Exercise the real application startup in an isolated process, including migration."""

import os
import subprocess
import sys


def test_real_app_setup_login_new_accounts_and_both_project_flows(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "VIRAL_DNA_ENV_FILE": str(tmp_path / "isolated.env"),
            "VIRAL_DNA_AUTH_MODE": "password",
            "VIRAL_DNA_ADMIN_CONSOLE_ENABLED": "true",
            "VIRAL_DNA_STORE": "sqlite",
            "VIRAL_DNA_WORKSPACE_ROOT": str(tmp_path / "legacy"),
            "VIRAL_DNA_STORAGE_ROOT": str(tmp_path / "legacy"),
            "VIRAL_DNA_ACCOUNT_CATALOG_PATH": str(tmp_path / "catalog.json"),
            "VIRAL_DNA_AUTH_DB_PATH": str(tmp_path / "accounts.sqlite3"),
            "VIRAL_DNA_ACCOUNTS_ROOT": str(tmp_path / "tenants"),
            "VIRAL_DNA_NOTIFICATION_DB_PATH": str(tmp_path / "notifications.sqlite3"),
            "VIRAL_DNA_PLATFORM_CONNECTIONS_PATH": str(tmp_path / "connections.json"),
            "VIRAL_DNA_PLATFORM_SECRET_ROOT": str(tmp_path / "secrets"),
            "VIRAL_DNA_YTDLP_COOKIE_FILE": "",
        }
    )
    script = r"""
import asyncio
import os
from uuid import uuid4
from fastapi.testclient import TestClient
from viral_dna_api.main import app, store, account_context_service
from viral_dna_api.models import Video, AnalysisRecord
from viral_dna_api.workspace import workspace_manager

password = "12345678"
legacy_root = workspace_manager.root
video = Video(source_type="upload", title="Existing analysis", record_id=uuid4())
record = AnalysisRecord(
    id=video.record_id, video_id=video.id, name="Existing analysis", source_type="upload"
)
async def seed():
    await store.add_video(video)
    await store.save_record(record)
    return await account_context_service.ensure_current()
legacy_context = asyncio.run(seed())

def checked(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()

with TestClient(app, headers={"Origin": "http://testserver"}) as client:
    setup_status = checked(client.get("/api/v1/auth/status"))
    assert setup_status["initialized"] is False
    assert setup_status["setup_allowed"] is True
    from pathlib import Path
    assert not Path(os.environ["VIRAL_DNA_AUTH_DB_PATH"]).with_suffix(".setup-token").exists()
    assert client.get("/api/v1/projects").status_code == 401
    setup = {"kind": "enterprise", "name": "Original enterprise", "username": "13800000001",
             "display_name": "Owner",
             "admin_password": password, "owner_password": password,
             "confirm_legacy_ownership": True}
    remote_setup = client.post("/api/v1/auth/setup", json=setup, headers={
        "Host": "public.example", "Origin": "http://public.example"})
    assert remote_setup.status_code == 403
    assert remote_setup.json()["detail"]["code"] == "local_setup_required"
    rejected = client.post("/api/v1/auth/setup", json={**setup, "confirm_legacy_ownership": False})
    assert rejected.status_code == 422
    invalid_phone = client.post("/api/v1/auth/setup", json={**setup, "username": "not-a-phone"})
    assert invalid_phone.status_code == 422
    assert "手机号" in invalid_phone.json()["detail"]["message"]
    assert "not-a-phone" not in invalid_phone.text
    for field in ("admin_password", "owner_password"):
        too_short = client.post("/api/v1/auth/setup", json={**setup, field: "short77"})
        assert too_short.status_code == 422
        assert "8–128" in too_short.json()["detail"]["message"]
        assert "short77" not in too_short.text
    invalid_login = client.post("/api/v1/auth/login", json={
        "username": "not-a-phone", "password": password})
    assert invalid_login.status_code == 422
    checked(client.post("/api/v1/auth/setup", json=setup))
    assert client.post("/api/v1/auth/setup", json=setup).status_code == 409
    session = checked(client.post("/api/v1/auth/login", json={
        "username": "13800000001", "password": password}))
    client.headers["X-CSRF-Token"] = session["csrf_token"]
    assert session["account_id"] == str(legacy_context.account.id)
    assert checked(client.get("/api/v1/projects"))["items"][0]["id"] == str(record.id)
    context = checked(client.get("/api/v1/context"))
    assert context["active_workspace"]["id"] == str(legacy_context.active_workspace.id)
    assert context["device"]["id"] == str(legacy_context.device.id)
    assert checked(client.get("/api/v1/me/notifications"))["items"] == []
    checked(client.post(f"/api/v1/projects/{record.id}/edit-lease/acquire", json={
        "editor_id":"test-analysis-tab-123", "token":"analysis-lock-token"*3}))
    client.headers.update({
        "X-Editor-Id":"test-analysis-tab-123", "X-Edit-Token":"analysis-lock-token"*3})
    checked(client.get(f"/api/v1/records/{record.id}"))
    checked(client.get(f"/api/v1/records/{record.id}/productions"))
    checked(client.post("/api/v1/auth/logout"))
    client.cookies.clear()

    admin = checked(client.post("/api/v1/admin/auth/login", json={
        "username":"admin", "password":password}))
    client.headers["X-CSRF-Token"] = admin["csrf_token"]
    assert client.get("/api/v1/projects").status_code == 401
    created = checked(client.post("/api/v1/admin/accounts", json={
        "kind":"personal", "name":"New account",
        "username":"13900000001", "display_name":"Second"}))
    checked(client.post("/api/v1/auth/activate", json={
        "token":created["activation_token"], "password":password}))
    personal = checked(client.post("/api/v1/auth/login", json={
        "username":"13900000001", "password":password}))
    client.headers["X-CSRF-Token"] = personal["csrf_token"]
    assert personal["account_kind"] == "personal"
    assert checked(client.get("/api/v1/projects"))["items"] == []
    assert client.get(f"/api/v1/projects/{record.id}/readonly").status_code == 404
    assert checked(client.get("/api/v1/me/notifications"))["items"] == []
    context = checked(client.get("/api/v1/context"))
    workspace_id = context["active_workspace"]["id"]
    checked(client.get(f"/api/v1/workspaces/{workspace_id}/storage-locations"))
    assert client.put("/api/v1/context/active-workspace", json={
        "workspace_id":str(legacy_context.active_workspace.id)}).status_code == 403
    assert client.post("/api/v1/account/members", json={
        "username":"13900000003", "display_name":"Invalid"}).status_code == 403
    skills = checked(client.get("/api/v1/skills"))["items"]
    version_id = skills[0]["current_version"]["id"]
    skill_project = checked(client.post("/api/v1/projects", json={
        "kind":"skill", "name":"New Skill project", "skill_version_id":version_id}), 201)
    skill_id = skill_project["id"]
    lease = checked(client.post(f"/api/v1/projects/{skill_id}/edit-lease/acquire", json={
        "editor_id":"test-skill-tab-123", "token":"skill-lock-token"*3}))
    assert lease["editable"]
    client.headers.update({"X-Editor-Id":"test-skill-tab-123", "X-Edit-Token":"skill-lock-token"*3})
    checked(client.get(f"/api/v1/projects/{skill_id}/skill-workspace"))
    assert checked(client.get("/api/v1/settings/video-generation"))["models"]
    assert client.put("/api/v1/settings/model", json={}).status_code == 403
    checked(client.get("/api/v1/admin/depth-controls/engines"))
    assert workspace_manager.root == legacy_root
print("Isolated startup, legacy ownership, account roles and Skill/analysis routes passed.")
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
