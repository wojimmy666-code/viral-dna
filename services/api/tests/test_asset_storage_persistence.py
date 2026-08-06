from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from viral_dna_api.asset_library import Asset, AssetFolder, AssetType
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.storage_objects import (
    ObjectReplica,
    ObjectReplicaState,
    StorageObject,
    StorageObjectType,
)


def test_asset_storage_entities_survive_store_reopen(tmp_path: Path) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "workspace.db"
        workspace_id = uuid4()
        location_id = uuid4()
        digest = hashlib.sha256(b"asset").hexdigest()
        storage_object = StorageObject(
            workspace_id=workspace_id,
            object_type=StorageObjectType.ASSET_IMAGE,
            original_filename="人物.png",
            mime_type="image/png",
            size_bytes=5,
            sha256=digest,
        )
        replica = ObjectReplica(
            storage_object_id=storage_object.id,
            storage_location_id=location_id,
            object_key=f"objects/{storage_object.id}/content.png",
            state=ObjectReplicaState.AVAILABLE,
            checksum=digest,
        )
        folder = AssetFolder(workspace_id=workspace_id, name="人物资产")
        asset = Asset(
            workspace_id=workspace_id,
            folder_id=folder.id,
            content_object_id=storage_object.id,
            thumbnail_object_id=storage_object.id,
            type=AssetType.PERSON,
            name="主播小夏",
            rights_confirmed=True,
            width=1080,
            height=1920,
        )

        first = SQLiteStore(database_path)
        await first.save_storage_bundle(storage_object, replica)
        await first.save_asset_folder(folder)
        await first.save_asset(asset)

        reopened = SQLiteStore(database_path)
        assert await reopened.get_storage_object(storage_object.id) == storage_object
        assert await reopened.get_object_replica(replica.id) == replica
        assert await reopened.get_asset_folder(folder.id) == folder
        assert await reopened.get_asset(asset.id) == asset

    asyncio.run(scenario())
