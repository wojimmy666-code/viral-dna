from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from viral_dna_api.main import app
from viral_dna_api.schema import WORKSPACE_SCHEMA_VERSION
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import (
    AccountCatalogError,
    AccountContextService,
    LocalAccountCatalogRepository,
)


@pytest.mark.asyncio
async def test_local_account_catalog_persists_stable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "主工作區"
    env_file = tmp_path / ".env.local"
    catalog_path = tmp_path / "app-data" / "account-catalog.json"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_file))

    first_manager = WorkspaceManager()
    first_service = AccountContextService(
        LocalAccountCatalogRepository(catalog_path),
        first_manager,
    )
    first = await first_service.ensure_current()

    second_manager = WorkspaceManager()
    second_service = AccountContextService(
        LocalAccountCatalogRepository(catalog_path),
        second_manager,
    )
    second = await second_service.ensure_current()

    assert first.account.id == second.account.id
    assert first.device.id == second.device.id
    assert first.active_workspace.id == second.active_workspace.id
    assert first.registration.id == second.registration.id
    assert first.storage_locations[0].id == second.storage_locations[0].id
    assert first.active_workspace.name == "主工作区"
    assert first.active_workspace.catalog_mode == "local"
    assert first.active_workspace.default_storage_policy == "local_only"
    assert first.storage_locations[0].provider_type == "local_filesystem"
    assert first.storage_locations[0].capabilities == ["read", "write"]

    manifest = json.loads((workspace_root / ".viraldna" / "workspace.json").read_text("utf-8"))
    assert manifest["schema_version"] == WORKSPACE_SCHEMA_VERSION
    assert manifest["workspace_id"] == str(first.active_workspace.id)
    assert manifest["account_id"] == str(first.account.id)
    assert manifest["name"] == "主工作区"

    persisted = json.loads(catalog_path.read_text("utf-8"))
    assert persisted["active_account_id"] == str(first.account.id)
    assert persisted["active_workspace_id"] == str(first.active_workspace.id)
    assert len(persisted["accounts"]) == 1
    assert len(persisted["devices"]) == 1
    assert len(persisted["workspaces"]) == 1
    assert len(persisted["registrations"]) == 1
    assert len(persisted["storage_locations"]) == 1


@pytest.mark.asyncio
async def test_registering_same_workspace_is_idempotent_and_rejects_other_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_root = tmp_path / "current"
    target_root = tmp_path / "素材工作區"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(current_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    manager = WorkspaceManager()
    service = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "catalog.json"),
        manager,
    )
    context = await service.ensure_current()

    first = await service.register_local(str(target_root), name="品牌素材庫")
    second = await service.register_local(str(target_root), name="品牌素材庫")
    assert first.workspace.id == second.workspace.id
    assert first.registration is not None
    assert second.registration is not None
    assert first.registration.id == second.registration.id
    assert first.storage_locations[0].id == second.storage_locations[0].id
    assert first.workspace.name == "品牌素材库"
    assert first.active is False

    manifest_path = target_root / ".viraldna" / "workspace.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["account_id"] = str(uuid4())
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AccountCatalogError, match="另一个账户") as raised:
        await service.register_local(str(target_root))
    assert raised.value.status_code == 409
    assert str(context.account.id) != manifest["account_id"]


def test_workspace_context_api_registers_and_activates_local_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_root = tmp_path / "初始工作区"
    target_root = tmp_path / "素材工作区"
    env_file = tmp_path / ".env.local"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(initial_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_file))

    with TestClient(app) as client:
        context_response = client.get("/api/v1/context")
        assert context_response.status_code == 200
        context = context_response.json()
        assert context["account"]["display_name"] == "默认账户"
        assert context["active_workspace"]["catalog_mode"] == "local"
        assert Path(context["registration"]["local_root"]) == initial_root.resolve()

        validation = client.post(
            "/api/v1/workspaces/validate-local",
            json={"path": str(target_root)},
        )
        assert validation.status_code == 200
        assert validation.json()["valid"] is True

        registered = client.post(
            "/api/v1/workspaces/register-local",
            json={"path": str(target_root), "name": "商品素材工作區"},
        )
        assert registered.status_code == 201
        registered_payload = registered.json()
        workspace_id = registered_payload["workspace"]["id"]
        assert registered_payload["workspace"]["name"] == "商品素材工作区"
        assert registered_payload["active"] is False

        repeated = client.post(
            "/api/v1/workspaces/register-local",
            json={"path": str(target_root), "name": "商品素材工作區"},
        )
        assert repeated.status_code == 201
        assert repeated.json()["workspace"]["id"] == workspace_id
        assert repeated.json()["registration"]["id"] == registered_payload["registration"]["id"]

        activated = client.put(
            "/api/v1/context/active-workspace",
            json={"workspace_id": workspace_id},
        )
        assert activated.status_code == 200
        assert activated.json()["active_workspace"]["id"] == workspace_id
        assert activated.json()["active_workspace"]["name"] == "商品素材工作区"
        assert Path(activated.json()["registration"]["local_root"]) == target_root.resolve()

        legacy = client.get("/api/v1/workspace")
        assert legacy.status_code == 200
        assert Path(legacy.json()["root_path"]) == target_root.resolve()
        assert legacy.json()["schema_version"] == WORKSPACE_SCHEMA_VERSION

        workspaces = client.get("/api/v1/workspaces")
        assert workspaces.status_code == 200
        selected = next(
            item for item in workspaces.json() if item["workspace"]["id"] == workspace_id
        )
        assert selected["active"] is True

        locations = client.get(f"/api/v1/workspaces/{workspace_id}/storage-locations")
        assert locations.status_code == 200
        assert len(locations.json()) == 1
        assert locations.json()[0]["provider_type"] == "local_filesystem"
        assert "local_root" not in locations.json()[0]

        current_account = client.get("/api/v1/accounts/current")
        assert current_account.status_code == 200
        assert current_account.json()["id"] == activated.json()["account"]["id"]

    manifest = json.loads((target_root / ".viraldna" / "workspace.json").read_text("utf-8"))
    assert manifest["workspace_id"] == workspace_id
    assert manifest["account_id"] == context["account"]["id"]
    assert "VIRAL_DNA_WORKSPACE_ROOT=" in env_file.read_text("utf-8")
