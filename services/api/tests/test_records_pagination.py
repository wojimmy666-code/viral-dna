from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

import viral_dna_api.main as main_module
from viral_dna_api.models import AnalysisRecord, SourceType, Video
from viral_dna_api.store import InMemoryStore


async def seed_records(store: InMemoryStore, count: int = 5) -> None:
    for index in range(count):
        record_id = uuid4()
        name = f"分页记录 {index:02d}"
        video = Video(
            record_id=record_id,
            source_type=SourceType.UPLOAD,
            title=name,
            duration_seconds=float(index + 1),
        )
        record = AnalysisRecord(
            id=record_id,
            name=name,
            video_id=video.id,
            source_type=SourceType.UPLOAD,
        )
        await store.add_video(video)
        await store.save_record(record)


def test_record_list_returns_server_side_pages(monkeypatch) -> None:
    test_store = InMemoryStore()
    asyncio.run(seed_records(test_store))
    monkeypatch.setattr(main_module, "store", test_store)

    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/records",
            params={"sort": "name_asc", "page": 2, "page_size": 2},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["total_pages"] == 3
    assert [item["name"] for item in payload["items"]] == [
        "分页记录 02",
        "分页记录 03",
    ]
    assert all(item["thumbnail_url"] for item in payload["items"])


def test_record_list_clamps_pages_and_validates_limits(monkeypatch) -> None:
    test_store = InMemoryStore()
    asyncio.run(seed_records(test_store))
    monkeypatch.setattr(main_module, "store", test_store)

    with TestClient(main_module.app) as client:
        last_page = client.get(
            "/api/v1/records",
            params={"sort": "name_asc", "page": 99, "page_size": 2},
        )
        invalid_page = client.get("/api/v1/records", params={"page": 0})
        invalid_page_size = client.get(
            "/api/v1/records",
            params={"page_size": 101},
        )

    assert last_page.status_code == 200
    assert last_page.json()["page"] == 3
    assert [item["name"] for item in last_page.json()["items"]] == ["分页记录 04"]
    assert invalid_page.status_code == 422
    assert invalid_page_size.status_code == 422
