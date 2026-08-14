from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from viral_dna_api.asset_library import AssetFolder
from viral_dna_api.models import (
    ProductionProject,
    ReferenceAsset,
    ReferenceAssetType,
    ReferenceAssetUpdate,
)
from viral_dna_api.project_assets import ProjectAssetService
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import (
    AccountContextService,
    LocalAccountCatalogRepository,
)


def _image_payload(image_format: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (320, 480), (94, 78, 219)).save(output, format=image_format)
    return output.getvalue()


def _project(name: str) -> ProductionProject:
    return ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name=name,
        current_revision_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_legacy_reference_migration_is_idempotent_and_zero_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    context = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "account-catalog.json"),
        workspace,
    )
    storage = StorageManager(repository, workspace)
    service = ProjectAssetService(repository, workspace, storage, context)

    first_project = _project("原项目")
    second_project = _project("复用项目")
    await repository.save_production_project(first_project)
    await repository.save_production_project(second_project)

    content_payload = _image_payload("PNG")
    thumbnail_payload = _image_payload("WEBP")
    content_relative = "records/legacy/references/person.png"
    thumbnail_relative = "records/legacy/references/person.webp"
    content_path = workspace.root / content_relative
    thumbnail_path = workspace.root / thumbnail_relative
    content_path.parent.mkdir(parents=True, exist_ok=True)
    content_path.write_bytes(content_payload)
    thumbnail_path.write_bytes(thumbnail_payload)
    legacy = ReferenceAsset(
        project_id=first_project.id,
        type=ReferenceAssetType.PERSON,
        name="旧人物资产",
        relative_path=content_relative,
        thumbnail_relative_path=thumbnail_relative,
        mime_type="image/png",
        width=320,
        height=480,
        sha256=hashlib.sha256(content_payload).hexdigest(),
        rights_confirmed=True,
    )
    await repository.save_reference_asset(legacy)

    first_result = await service.bootstrap_legacy_references()
    second_result = await service.bootstrap_legacy_references()
    assert first_result == {"migrated": 1, "linked": 1, "skipped": 0, "failures": []}
    assert second_result == {"migrated": 0, "linked": 0, "skipped": 1, "failures": []}

    asset = await repository.get_asset(legacy.id)
    assert asset is not None
    assert asset.id == legacy.id
    assert len(repository.storage_objects) == 2
    content_replicas = await repository.list_object_replicas(asset.content_object_id)
    thumbnail_replicas = await repository.list_object_replicas(asset.thumbnail_object_id)
    assert content_replicas[0].object_key == content_relative
    assert thumbnail_replicas[0].object_key == thumbnail_relative
    assert not (workspace.root / "objects").exists()

    object_count = len(repository.storage_objects)
    await service.link_asset(second_project, asset.id)
    assert len(repository.storage_objects) == object_count
    assert len(await repository.list_project_asset_links()) == 2

    renamed = await service.update_reference(
        first_project.id,
        asset.id,
        ReferenceAssetUpdate(
            expected_revision_id=first_project.current_revision_id,
            name="统一人物名称",
        ),
    )
    assert renamed.name == "统一人物名称"
    assert (await service.list_references(second_project.id))[0].name == "统一人物名称"

    folder = AssetFolder(
        workspace_id=asset.workspace_id,
        name="人物目录",
    )
    await repository.save_asset_folder(folder)
    moved = asset.model_copy(update={"folder_id": folder.id, "version": asset.version + 1})
    await repository.save_asset(moved)
    projected = (await service.list_references(first_project.id))[0]
    assert projected.folder_id == folder.id
    assert projected.folder_name == "人物目录"
    assert (await repository.list_object_replicas(asset.content_object_id))[0].object_key == (
        content_relative
    )

    snapshot = await service.snapshot_reference(first_project.id, renamed)
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["asset_id"] == str(asset.id)
    assert snapshot["content_object_id"] == str(asset.content_object_id)
    assert snapshot["folder_id"] == str(folder.id)
    assert snapshot["folder_name"] == "人物目录"
    assert "relative_path" not in serialized
    assert "object_key" not in serialized
    assert str(workspace.root) not in serialized


@pytest.mark.asyncio
async def test_unlinking_project_asset_keeps_global_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    workspace = WorkspaceManager()
    repository = InMemoryStore()
    context = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "account-catalog.json"),
        workspace,
    )
    storage = StorageManager(repository, workspace)
    service = ProjectAssetService(repository, workspace, storage, context)
    project = _project("解除关联")
    await repository.save_production_project(project)

    from viral_dna_api.models import ReferenceAssetCreate

    reference = await service.create_reference(
        project,
        ReferenceAssetCreate(
            expected_revision_id=project.current_revision_id,
            type=ReferenceAssetType.PRODUCT,
            name="产品",
            rights_confirmed=True,
        ),
        _image_payload("PNG"),
        "product.png",
        "image/png",
    )
    await service.unlink_reference(project.id, reference.id)
    assert await repository.get_asset(reference.id) is not None
    assert await service.list_references(project.id) == []
