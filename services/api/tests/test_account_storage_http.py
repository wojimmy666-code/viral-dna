"""Real account middleware, SQLite and sync receiver, using only temporary files."""

import hashlib
from uuid import uuid4

import httpx
import pytest
from test_account_isolation_http import PASSWORD
from test_account_isolation_http import sandbox as account_sandbox  # noqa: F401

from viral_dna_api.access_context import account_access
from viral_dna_api.account_storage.routes import create_storage_router
from viral_dna_api.account_storage.service import AccountStorageService
from viral_dna_api.account_storage.sync import ServerSyncService
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.workspace import workspace_manager


@pytest.fixture
def durable(account_sandbox, monkeypatch):  # noqa: F811
    box = account_sandbox
    storage = StorageManager(box.repository, workspace_manager)
    service = AccountStorageService(box.repository, workspace_manager, storage)
    sync = ServerSyncService(service)
    monkeypatch.setattr(sync, "configured_url", lambda: "")
    service.sync = sync
    box.repository.durable_storage = service
    storage.durable_storage = service
    box.app.include_router(create_storage_router(service, sync), prefix="/api/v1")
    box.durable = service
    box.sync = sync
    return box


def client(box, *, token=None, https=True):
    origin = ("https" if https else "http") + "://testserver"
    headers = {"Origin": origin}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=box.app), base_url=origin, headers=headers
    )


async def login(http, username="13800000001", *, admin=False):
    path = "/api/v1/admin/auth/login" if admin else "/api/v1/auth/login"
    response = await http.post(
        path, json={"username": "admin" if admin else username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    http.headers["x-csrf-token"] = response.json()["csrf_token"]
    return response.json()


@pytest.mark.asyncio
async def test_quota_shared_by_enterprise_and_isolated_from_personal(durable):
    async with (
        client(durable) as owner,
        client(durable) as member,
        client(durable) as personal,
        client(durable) as admin,
    ):
        await login(owner)
        await login(member, "13800000002")
        await login(personal, "13900000001")
        await login(admin, admin=True)
        path = f"/api/v1/admin/accounts/{durable.owner.account_id}/storage"
        assert (await owner.get(path)).status_code in {401, 403}
        result = await admin.patch(path, json={"limit_bytes": 12_000_000_000, "note": "人工升级"})
        assert result.status_code == 200, result.text
        for http in (owner, member):
            assert (await http.get("/api/v1/account/storage")).json()[
                "limit_bytes"
            ] == 12_000_000_000
        assert (await personal.get("/api/v1/account/storage")).json()[
            "limit_bytes"
        ] == 2_000_000_000
        assert len((await admin.get(path)).json()["audit"]) == 1
        admin.headers.pop("x-csrf-token")
        assert (await admin.patch(path, json={"limit_bytes": 1})).status_code == 403


@pytest.mark.asyncio
async def test_scoped_transfer_upload_private_file_and_revocation(durable):
    device_id = uuid4()
    async with client(durable) as owner:
        await login(owner)
        issued = await owner.post(
            "/api/v1/account/storage/devices", json={"device_id": str(device_id)}
        )
        assert issued.status_code == 200, issued.text
        token = issued.json()["token"]
    payload = b"isolated-generated-content"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "id": str(uuid4()),
        "source_workspace_id": str(device_id),
        "entries": [
            {
                "key": "candidate:test",
                "kind": "image",
                "sha256": digest,
                "updated_at": 1,
                "metadata": {
                    "filename": "image.png",
                    "mime_type": "image/png",
                    "prompt_snapshot": "产品特写",
                },
            }
        ],
        "files": [
            {
                "sha256": digest,
                "size_bytes": len(payload),
                "filename": "image.png",
                "mime_type": "image/png",
            }
        ],
    }
    async with (
        client(durable, token=token) as device,
        client(durable, token=token, https=False) as insecure,
    ):
        assert (await insecure.get("/api/v1/account/storage/transfer/usage")).status_code == 403
        assert (await device.get("/api/v1/projects")).status_code == 401
        assert (await device.get("/api/v1/admin/accounts")).status_code in {401, 403}
        started = await device.post("/api/v1/account/storage/transfer/batches", json=manifest)
        assert started.status_code == 200, started.text
        upload = started.json()["uploads"][0]["id"]
        route = f"/api/v1/account/storage/transfer/uploads/{upload}"
        assert (
            await device.put(route, params={"offset": 0}, content=payload[:7])
        ).status_code == 200
        assert (await device.get(route)).json()["received"] == 7
        assert (
            await device.put(route, params={"offset": 7}, content=payload[7:])
        ).status_code == 200
        assert (await device.post(route + "/complete")).status_code == 200
        result = await device.post(
            f"/api/v1/account/storage/transfer/batches/{manifest['id']}/complete"
        )
        assert result.status_code == 200, result.text
        assert result.json()["usage"]["used_bytes"] == len(payload)
        async with client(durable) as owner, client(durable) as stranger:
            await login(owner)
            await login(stranger, "13900000001")
            history = (await owner.get("/api/v1/account/storage/history")).json()
            assert history["total"] == 1
            media = history["items"][0]["content_url"]
            response = await owner.get(media)
            assert response.content == payload
            assert "private, no-store" in response.headers["cache-control"]
            assert (await stranger.get(media)).status_code == 404
            assert (await stranger.get("/api/v1/account/storage/history")).json()["total"] == 0
        assert (await device.delete("/api/v1/account/storage/transfer/device")).status_code == 200
        assert (await device.get("/api/v1/account/storage/transfer/usage")).status_code == 401


@pytest.mark.asyncio
async def test_cannot_pair_to_self_or_member_issue_storage_device(durable):
    async with client(durable) as owner, client(durable) as member:
        await login(owner)
        await login(member, "13800000002")
        assert (
            await owner.post(
                "/api/v1/account/storage/devices",
                json={"device_id": str(durable.owner.workspace_id)},
            )
        ).status_code == 409
        assert (
            await member.post("/api/v1/account/storage/devices", json={"device_id": str(uuid4())})
        ).status_code == 403


@pytest.mark.asyncio
async def test_trash_restore_and_purge_do_not_resurrect(durable):
    context = account_access.set(durable.owner)
    try:
        path = durable.owner.workspace_root / "isolated.png"
        path.write_bytes(b"file")
        catalog = durable.durable.catalog
        blob = catalog.keep_file(path)
        catalog.put_entry(
            "candidate:detached", "image", blob["sha256"], {"filename": "isolated.png"}
        )
    finally:
        account_access.reset(context)
    endpoint = "/api/v1/account/storage/entries/candidate:detached"
    async with client(durable) as owner:
        await login(owner)
        assert (await owner.delete(endpoint + "?confirm=true")).status_code == 409
        assert (await owner.post(endpoint + "/trash")).status_code == 200
        assert (await owner.get("/api/v1/account/storage")).json()["used_bytes"] == 4
        assert (await owner.post(endpoint + "/restore")).status_code == 200
        assert (await owner.post(endpoint + "/trash")).status_code == 200
        response = await owner.delete(endpoint + "?confirm=true")
        assert response.status_code == 200, response.text
        assert response.json()["used_bytes"] == 0
        assert not path.exists()
        catalog.put_entry("candidate:detached", "image", blob["sha256"], {})
        assert catalog.entry("candidate:detached") is None
