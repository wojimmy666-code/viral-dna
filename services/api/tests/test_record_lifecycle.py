from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

import viral_dna_api.main as main_module
from viral_dna_api.models import AnalysisRecord, SourceType, Video
from viral_dna_api.store import InMemoryStore


async def seed_record(store: InMemoryStore, name: str) -> AnalysisRecord:
    record_id = uuid4()
    video = Video(
        record_id=record_id,
        source_type=SourceType.UPLOAD,
        title=name,
        duration_seconds=3.5,
    )
    record = AnalysisRecord(
        id=record_id,
        name=name,
        video_id=video.id,
        source_type=SourceType.UPLOAD,
    )
    await store.add_video(video)
    await store.save_record(record)
    return record


def test_record_lifecycle_lists_counts_and_batch_transitions(monkeypatch) -> None:
    test_store = InMemoryStore()
    active = asyncio.run(seed_record(test_store, "当前记录"))
    archived = asyncio.run(seed_record(test_store, "归档记录"))
    trashed = asyncio.run(seed_record(test_store, "回收站记录"))
    monkeypatch.setattr(main_module, "store", test_store)

    with TestClient(main_module.app) as client:
        archive_response = client.patch(
            "/api/v1/records/batch/lifecycle",
            json={"record_ids": [str(archived.id)], "action": "archive"},
        )
        trash_response = client.patch(
            f"/api/v1/records/{trashed.id}/lifecycle",
            json={"action": "trash"},
        )
        active_list = client.get("/api/v1/records", params={"lifecycle": "active"})
        archived_list = client.get("/api/v1/records", params={"lifecycle": "archived"})
        trashed_list = client.get("/api/v1/records", params={"lifecycle": "trashed"})

    assert archive_response.status_code == 200
    assert trash_response.status_code == 200
    assert [item["id"] for item in active_list.json()["items"]] == [str(active.id)]
    assert [item["id"] for item in archived_list.json()["items"]] == [str(archived.id)]
    assert [item["id"] for item in trashed_list.json()["items"]] == [str(trashed.id)]
    assert active_list.json()["lifecycle_counts"] == {
        "active": 1,
        "archived": 1,
        "trashed": 1,
    }


def test_trash_restore_keeps_archive_origin_and_purge_requires_trash(monkeypatch) -> None:
    test_store = InMemoryStore()
    archived = asyncio.run(seed_record(test_store, "稍后恢复到归档"))
    active = asyncio.run(seed_record(test_store, "不能直接永久删除"))
    monkeypatch.setattr(main_module, "store", test_store)

    with TestClient(main_module.app) as client:
        assert client.patch(
            f"/api/v1/records/{archived.id}/lifecycle",
            json={"action": "archive"},
        ).status_code == 200
        assert client.patch(
            f"/api/v1/records/{archived.id}/lifecycle",
            json={"action": "trash"},
        ).status_code == 200
        restored = client.patch(
            f"/api/v1/records/{archived.id}/lifecycle",
            json={"action": "restore"},
        )
        rejected = client.delete(f"/api/v1/records/{active.id}")
        client.patch(
            f"/api/v1/records/{archived.id}/lifecycle",
            json={"action": "trash"},
        )
        purged = client.delete(f"/api/v1/records/{archived.id}")
        archived_list = client.get("/api/v1/records", params={"lifecycle": "archived"})

    assert restored.status_code == 200
    assert restored.json()["archived_at"] is not None
    assert restored.json()["trashed_at"] is None
    assert rejected.status_code == 409
    assert purged.status_code == 200
    assert purged.json()["affected_ids"] == [str(archived.id)]
    assert archived_list.json()["items"] == []
    assert asyncio.run(test_store.get_video(archived.video_id)) is not None
