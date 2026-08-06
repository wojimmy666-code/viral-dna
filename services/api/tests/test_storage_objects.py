from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.storage_objects import (
    FakeCloudStorageDriver,
    LocalFileStorageDriver,
    ObjectReplicaState,
    StorageManager,
    StorageObjectError,
    StorageObjectType,
)
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager


def _manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkspaceManager:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    return WorkspaceManager()


@pytest.mark.asyncio
async def test_local_driver_rejects_path_escape_and_writes_atomically(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    driver = LocalFileStorageDriver(root)

    with pytest.raises(StorageObjectError, match="相对路径"):
        driver.resolve_key("../outside.png")
    with pytest.raises(StorageObjectError, match="相对路径"):
        driver.resolve_key(str((tmp_path / "absolute.png").resolve()))

    payload = b"verified-payload"
    digest = hashlib.sha256(payload).hexdigest()
    info = await driver.put("objects/aa/item/content.bin", payload, expected_sha256=digest)
    assert info.path.read_bytes() == payload
    assert info.sha256 == digest
    assert not list(info.path.parent.glob("*.tmp"))


@pytest.mark.asyncio
async def test_storage_manager_materializes_and_marks_bad_replicas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    repository = InMemoryStore()
    storage = StorageManager(repository, manager)
    location_id = uuid4()
    workspace_id = uuid4()
    storage.bind_local_location(location_id)

    stored = await storage.save_object(
        workspace_id=workspace_id,
        storage_location_id=location_id,
        object_type=StorageObjectType.ASSET_IMAGE,
        original_filename="人物.png",
        mime_type="image/png",
        payload=b"image-payload",
    )
    path = await storage.materialize_local(stored.id)
    assert path.read_bytes() == b"image-payload"
    availability, sync_state = await storage.availability(stored.id)
    assert availability.local is True
    assert availability.cloud is False
    assert sync_state == "local_only"

    public_replicas = await storage.replica_responses(stored.id)
    assert len(public_replicas) == 1
    assert "object_key" not in public_replicas[0].model_dump()

    path.write_bytes(b"tampered")
    with pytest.raises(StorageObjectError, match="本地副本"):
        await storage.materialize_local(stored.id)
    replicas = await repository.list_object_replicas(stored.id)
    assert replicas[0].state == ObjectReplicaState.FAILED

    missing = await storage.save_object(
        workspace_id=workspace_id,
        storage_location_id=location_id,
        object_type=StorageObjectType.THUMBNAIL,
        original_filename="thumbnail.webp",
        mime_type="image/webp",
        payload=b"thumbnail-payload",
    )
    missing_path = await storage.materialize_local(missing.id)
    missing_path.unlink()
    with pytest.raises(StorageObjectError, match="本地副本"):
        await storage.materialize_local(missing.id)
    missing_replicas = await repository.list_object_replicas(missing.id)
    assert missing_replicas[0].state == ObjectReplicaState.MISSING


@pytest.mark.asyncio
async def test_fake_cloud_replica_preserves_key_and_reports_download_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    repository = InMemoryStore()
    storage = StorageManager(repository, manager)
    local_location_id = uuid4()
    cloud_location_id = uuid4()
    workspace_id = uuid4()
    cloud_driver = FakeCloudStorageDriver(tmp_path / "fake-cloud")
    storage.bind_local_location(local_location_id)
    storage.register_driver(cloud_location_id, cloud_driver)

    stored = await storage.save_object(
        workspace_id=workspace_id,
        storage_location_id=local_location_id,
        object_type=StorageObjectType.ASSET_IMAGE,
        original_filename="product.png",
        mime_type="image/png",
        payload=b"hybrid-object-payload",
    )
    local_replica = (await repository.list_object_replicas(stored.id))[0]
    cloud_replica = await storage.replicate_object(stored.id, cloud_location_id)
    repeated = await storage.replicate_object(stored.id, cloud_location_id)
    assert repeated.id == cloud_replica.id
    assert cloud_replica.object_key == local_replica.object_key
    assert cloud_replica.checksum == stored.sha256

    availability, sync_state = await storage.availability(stored.id)
    assert availability.model_dump() == {"local": True, "cloud": True}
    assert sync_state == "synced"

    local_path = await storage.materialize_local(stored.id)
    local_path.unlink()
    with pytest.raises(StorageObjectError) as download_required:
        await storage.materialize_local(stored.id)
    assert download_required.value.code == "download_required"

    cloud_missing = cloud_replica.model_copy(update={"state": ObjectReplicaState.MISSING})
    await repository.save_object_replica(cloud_missing)
    with pytest.raises(StorageObjectError) as unavailable:
        await storage.materialize_local(stored.id)
    assert unavailable.value.code == "local_replica_unavailable"
    availability, sync_state = await storage.availability(stored.id)
    assert availability.model_dump() == {"local": False, "cloud": False}
    assert sync_state == "unavailable"
