from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from viral_dna_api.asset_library import AssetLibraryService
from viral_dna_api.asset_routes import create_asset_router
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import (
    AccountContextService,
    LocalAccountCatalogRepository,
)


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (320, 200), color).save(output, format="PNG")
    return output.getvalue()


def _test_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, str, Path]:
    workspace_root = tmp_path / "资产工作区"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    manager = WorkspaceManager()
    context = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "account-catalog.json"),
        manager,
    )
    repository = InMemoryStore()
    storage = StorageManager(repository, manager)
    service = AssetLibraryService(repository, storage, context)
    app = FastAPI()
    app.include_router(create_asset_router(service), prefix="/api/v1")
    manifest = json.loads((workspace_root / ".viraldna" / "workspace.json").read_text("utf-8"))
    return TestClient(app), manifest["workspace_id"], workspace_root


def _upload(
    client: TestClient,
    workspace_id: str,
    *,
    name: str,
    asset_type: str,
    folder_id: str | None,
    color: tuple[int, int, int],
    storage_policy: str = "local_only",
):
    data = {
        "name": name,
        "type": asset_type,
        "description": "品牌拍摄参考",
        "tags": "主视觉，夏季, 主视觉",
        "rights_confirmed": "true",
        "rights_note": "自有素材",
        "storage_policy": storage_policy,
    }
    if folder_id:
        data["folder_id"] = folder_id
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/assets",
        data=data,
        files={"file": ("asset.png", _png_bytes(color), "image/png")},
    )


def test_asset_library_crud_pagination_and_safe_content_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, workspace_id, workspace_root = _test_client(tmp_path, monkeypatch)
    with client:
        people = client.post(
            f"/api/v1/workspaces/{workspace_id}/asset-folders",
            json={"name": "人物素材庫"},
        )
        assert people.status_code == 201
        assert people.json()["name"] == "人物素材库"
        people_id = people.json()["id"]

        products = client.post(
            f"/api/v1/workspaces/{workspace_id}/asset-folders",
            json={"name": "产品"},
        )
        assert products.status_code == 201
        products_id = products.json()["id"]

        duplicate = client.post(
            f"/api/v1/workspaces/{workspace_id}/asset-folders",
            json={"name": "人物素材库"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "asset_folder_name_conflict"

        first = _upload(
            client,
            workspace_id,
            name="模特正面",
            asset_type="person",
            folder_id=people_id,
            color=(214, 174, 154),
        )
        second = _upload(
            client,
            workspace_id,
            name="產品主圖",
            asset_type="product",
            folder_id=products_id,
            color=(91, 77, 245),
        )
        third = _upload(
            client,
            workspace_id,
            name="露台場景",
            asset_type="scene",
            folder_id=None,
            color=(89, 142, 96),
        )
        assert first.status_code == second.status_code == third.status_code == 201
        assert second.json()["name"] == "产品主图"
        assert second.json()["tags"] == ["主视觉", "夏季"]
        assert second.json()["sync_state"] == "local_only"
        assert second.json()["availability"] == {"local": True, "cloud": False}

        first_page = client.get(
            f"/api/v1/workspaces/{workspace_id}/assets",
            params={"page": 1, "page_size": 2},
        )
        assert first_page.status_code == 200
        assert first_page.json()["total"] == 3
        assert first_page.json()["total_pages"] == 2
        assert len(first_page.json()["items"]) == 2

        filtered = client.get(
            f"/api/v1/workspaces/{workspace_id}/assets",
            params={"folder_id": "unfiled", "type": "scene", "query": "露台"},
        )
        assert filtered.status_code == 200
        assert [item["name"] for item in filtered.json()["items"]] == ["露台场景"]

        asset_id = first.json()["id"]
        updated = client.patch(
            f"/api/v1/assets/{asset_id}",
            json={
                "expected_version": first.json()["version"],
                "name": "品牌模特",
                "folder_id": products_id,
                "tags": ["品牌人物", "正面"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["folder_id"] == products_id
        assert updated.json()["folder_name"] == "产品"

        content = client.get(updated.json()["content_url"])
        thumbnail = client.get(updated.json()["thumbnail_url"])
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("image/png")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"].startswith("image/webp")

        object_id = updated.json()["content_object_id"]
        object_response = client.get(f"/api/v1/storage-objects/{object_id}")
        replicas = client.get(f"/api/v1/storage-objects/{object_id}/replicas")
        assert object_response.status_code == replicas.status_code == 200
        serialized = json.dumps(
            {"object": object_response.json(), "replicas": replicas.json()},
            ensure_ascii=False,
        )
        assert "object_key" not in serialized
        assert str(workspace_root.resolve()) not in serialized

        nonempty = client.delete(f"/api/v1/asset-folders/{products_id}")
        assert nonempty.status_code == 409
        assert nonempty.json()["detail"]["code"] == "folder_not_empty"
        moved = client.delete(
            f"/api/v1/asset-folders/{products_id}",
            params={"move_assets_to_unfiled": "true"},
        )
        assert moved.status_code == 204
        assert client.get(f"/api/v1/assets/{asset_id}").json()["folder_id"] is None

        archived = client.delete(f"/api/v1/assets/{asset_id}")
        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None
        active_list = client.get(f"/api/v1/workspaces/{workspace_id}/assets")
        archived_list = client.get(
            f"/api/v1/workspaces/{workspace_id}/assets",
            params={"include_archived": "true"},
        )
        assert asset_id not in {item["id"] for item in active_list.json()["items"]}
        assert asset_id in {item["id"] for item in archived_list.json()["items"]}
        restored = client.post(f"/api/v1/assets/{asset_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None


def test_asset_upload_rejects_cloud_policy_and_missing_rights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, workspace_id, _workspace_root = _test_client(tmp_path, monkeypatch)
    with client:
        unsupported = _upload(
            client,
            workspace_id,
            name="云端资产",
            asset_type="other",
            folder_id=None,
            color=(20, 20, 20),
            storage_policy="cloud_only",
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"]["code"] == "storage_policy_not_supported"

        missing_rights = client.post(
            f"/api/v1/workspaces/{workspace_id}/assets",
            data={"name": "无权利确认", "type": "other", "rights_confirmed": "false"},
            files={"file": ("asset.png", _png_bytes((10, 10, 10)), "image/png")},
        )
        assert missing_rights.status_code == 422
        assert missing_rights.json()["detail"]["code"] == "rights_confirmation_required"
