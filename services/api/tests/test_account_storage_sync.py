import io

import httpx
import pytest
from PIL import Image
from test_account_storage_http import PASSWORD, account_sandbox, durable  # noqa: F401

from viral_dna_api.access_context import account_access
from viral_dna_api.accounts.repository import AccountError
from viral_dna_api.asset_library import Asset, AssetFolder
from viral_dna_api.storage_objects import StorageObjectType


class MemorySecrets:
    available = True

    def __init__(self):
        self.values = {}

    async def save(self, account_id, endpoint, token):
        self.values[account_id] = endpoint, token

    async def read(self, account_id):
        return self.values.get(account_id)

    async def delete(self, account_id):
        self.values.pop(account_id, None)


@pytest.mark.asyncio
async def test_real_connector_asset_metadata_incremental_and_server_edits_win(durable, monkeypatch):  # noqa: F811
    box = durable
    target = box.auth.create_account(
        kind="enterprise",
        name="目标企业",
        username="13800000009",
        display_name="负责人",
        actor="admin",
    )
    box.auth.activate(target["activation_token"], PASSWORD)
    target_access = box.auth.session(
        box.auth.login("13800000009", PASSWORD, admin=False, remote="test")
    )["access"]
    sync, service = box.sync, box.durable
    sync.secrets = MemorySecrets()
    sync.client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=box.app), **kwargs
    )
    monkeypatch.setattr(sync, "configured_url", lambda: "https://testserver")
    monkeypatch.setattr(sync, "ensure_worker", lambda: None)
    context = account_access.set(box.owner)
    try:
        service.storage.bind_local_location(box.owner.storage_location_id)
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "gold").save(image, "PNG")
        content = await service.storage.save_object(
            account_id=box.owner.account_id,
            workspace_id=box.owner.workspace_id,
            storage_location_id=box.owner.storage_location_id,
            object_type=StorageObjectType.ASSET_IMAGE,
            original_filename="product.png",
            mime_type="image/png",
            payload=image.getvalue(),
        )
        folder = AssetFolder(
            workspace_id=box.owner.workspace_id, account_id=box.owner.account_id, name="产品目录"
        )
        await box.repository.save_asset_folder(folder)
        asset = Asset(
            workspace_id=box.owner.workspace_id,
            account_id=box.owner.account_id,
            folder_id=folder.id,
            type="product",
            name="滤芯",
            tags=["黄色"],
            description="产品细节",
            content_object_id=content.id,
            thumbnail_object_id=content.id,
            width=8,
            height=8,
        )
        await box.repository.save_asset(asset)
        prepared = await sync.prepare("13800000009", PASSWORD)
        assert not prepared["confirmed"]
        with pytest.raises(AccountError, match="确认"):
            await sync.credentials()
        sync.confirm(str(target_access.account_id))
        with pytest.raises(AccountError, match="断开"):
            await sync.prepare("13800000009", PASSWORD)
        await sync.start()
        source_catalog = service.catalog
        assert len(source_catalog.pending_entries()) == 1
        await sync.send(sync.manifest(source_catalog.pending_entries()))
        assert source_catalog.pending_entries() == []

        target_context = account_access.set(target_access)
        try:
            target_catalog = service.catalog
            assert target_catalog.entries(kind="asset")["total"] == 1
            assert target_catalog.usage()["used_bytes"] == len(image.getvalue())
            received = (await box.repository.list_assets())[0]
            assert received.name == asset.name and received.tags == asset.tags
            assert received.id != asset.id
            assert (await box.repository.get_asset_folder(received.folder_id)).name == folder.name
        finally:
            account_access.reset(target_context)

        asset = asset.model_copy(update={"name": "滤芯特写", "version": asset.version + 1})
        await box.repository.save_asset(asset)
        await sync.send(sync.manifest(source_catalog.pending_entries()))
        target_context = account_access.set(target_access)
        try:
            received = await box.repository.get_asset(received.id)
            assert received.name == "滤芯特写"
            received = received.model_copy(
                update={"name": "服务器人工命名", "version": received.version + 1}
            )
            await box.repository.save_asset(received)
        finally:
            account_access.reset(target_context)
        asset = asset.model_copy(update={"name": "本地再次改名", "version": asset.version + 1})
        await box.repository.save_asset(asset)
        await sync.send(sync.manifest(source_catalog.pending_entries()))
        assert source_catalog.setting("retained_on_server") == [f"asset:{asset.id}"]
        target_context = account_access.set(target_access)
        try:
            assert (await box.repository.get_asset(received.id)).name == "服务器人工命名"
            assert target_catalog.entries(kind="asset")["total"] == 1
            entry = target_catalog.entries(kind="asset")["items"][0]
            await service.set_trash(entry)
            await service.purge(target_catalog.entry(entry["key"]))
            assert target_catalog.usage()["used_bytes"] == 0
        finally:
            account_access.reset(target_context)
        asset = asset.model_copy(update={"description": "新增说明"})
        await box.repository.save_asset(asset)
        await sync.send(sync.manifest(source_catalog.pending_entries()))
        assert target_catalog.entries(kind="asset")["total"] == 0
        assert target_catalog.usage()["used_bytes"] == 0  # no resurrection or orphan upload
        assert source_catalog.usage()["used_bytes"] == len(image.getvalue())
        await sync.disconnect()
        assert not source_catalog.setting("connection")
    finally:
        account_access.reset(context)


@pytest.mark.asyncio
async def test_remote_auth_failure_does_not_expire_local_login(durable):  # noqa: F811
    response = httpx.Response(
        401, json={"detail": {"code": "storage_device_expired", "message": "服务器连接失效"}}
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: response), base_url="https://testserver"
    ) as client:
        with pytest.raises(AccountError) as failed:
            await durable.sync.request(client, "GET", "/account/storage/transfer/usage")
        assert failed.value.status == 409
