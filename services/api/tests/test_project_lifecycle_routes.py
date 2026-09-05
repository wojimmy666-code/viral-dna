from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.models import AnalysisRecord, SourceType, Video
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import ProjectCreate, ProjectService, create_project_router
from viral_dna_api.store import InMemoryStore


class AccountContext:
    async def current_account(self):
        return SimpleNamespace(id=self.account_id)

    def __init__(self) -> None:
        self.account_id = uuid4()


@pytest.fixture
def project_api():
    # Use the real router/service but only an isolated in-memory repository.
    # Do not import main or start the developer's durable workspace/job runners.
    store = InMemoryStore()
    catalog = PlatformSkillCatalogService(None)
    service = ProjectService(store, catalog, AccountContext())

    async def seed():
        video = Video(record_id=uuid4(), source_type=SourceType.UPLOAD, title="路由验收原视频")
        record = AnalysisRecord(
            id=video.record_id,
            name="路由验收原视频项目",
            video_id=video.id,
            source_type=SourceType.UPLOAD,
        )
        await store.add_video(video)
        await store.save_record(record)
        await service.bootstrap_analysis_projects()
        skill = (await catalog.list_catalog()).items[0]
        created = await service.create(
            ProjectCreate(
                kind="skill",
                name="路由验收 Skill 项目",
                skill_version_id=skill.current_version.id,
            )
        )
        return {"analysis": str(record.id), "skill": str(created.id)}

    ids = asyncio.run(seed())
    app = FastAPI()
    app.include_router(create_project_router(service), prefix="/api/v1")
    with TestClient(app) as client:
        yield client, store, ids


@pytest.mark.parametrize("kind", ["analysis", "skill"])
def test_single_selection_uses_batch_http_route_and_restores_archive_origin(project_api, kind):
    client, _, ids = project_api
    project_id = ids[kind]
    for action, expected in [
        ("archive", "archived"),
        ("trash", "trashed"),
        ("restore", "archived"),
        ("activate", "active"),
        ("trash", "trashed"),
        ("restore", "active"),
    ]:
        response = client.post(
            "/api/v1/projects/batch/lifecycle",
            json={"project_ids": [project_id], "action": action},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"affected_ids": [project_id], "affected_count": 1}
        listing = client.get("/api/v1/projects", params={"lifecycle": expected}).json()
        assert project_id in {item["id"] for item in listing["items"]}


def test_mixed_batch_deduplicates_and_keeps_source_media(project_api):
    client, store, ids = project_api
    response = client.post(
        "/api/v1/projects/batch/lifecycle",
        json={"project_ids": [ids["analysis"], ids["skill"], ids["skill"]], "action": "trash"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"affected_ids": list(ids.values()), "affected_count": 2}
    listing = client.get("/api/v1/projects", params={"lifecycle": "trashed"}).json()
    assert listing["total"] == 2
    assert listing["lifecycle_counts"]["trashed"] == 2
    assert len(asyncio.run(store.list_records())) == 1
    projects = asyncio.run(store.list_projects())
    assert len(projects) == 2
    source = next(project.source_binding for project in projects if project.kind == "analysis")
    assert asyncio.run(store.get_video(source.video_id)) is not None


def test_individual_route_remains_available(project_api):
    client, _, ids = project_api
    response = client.post(
        f"/api/v1/projects/{ids['skill']}/lifecycle", json={"action": "trash"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["lifecycle"] == "trashed"


def test_missing_project_preserves_business_error_and_existing_projects(project_api):
    client, _, _ = project_api
    response = client.post(
        "/api/v1/projects/batch/lifecycle",
        json={"project_ids": [str(uuid4())], "action": "trash"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"
    assert client.get("/api/v1/projects").json()["lifecycle_counts"]["active"] == 2


@pytest.mark.parametrize(
    ("body", "expected_location"),
    [
        ({"project_ids": [], "action": "trash"}, ["body", "project_ids"]),
        ({"project_ids": ["invalid"], "action": "trash"}, ["body", "project_ids", 0]),
        ({"project_ids": [str(uuid4())], "action": "purge"}, ["body", "action"]),
    ],
)
def test_invalid_batch_reports_body_validation_not_a_batch_project_id(
    project_api, body, expected_location
):
    client, _, _ = project_api
    response = client.post("/api/v1/projects/batch/lifecycle", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == expected_location
    assert client.get("/api/v1/projects").json()["lifecycle_counts"]["active"] == 2


def test_batch_delete_still_requires_trash_and_does_not_target_dynamic_route(project_api):
    client, store, ids = project_api
    payload = {"project_ids": [ids["skill"]]}
    rejected = client.request("DELETE", "/api/v1/projects/batch", json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "project_not_trashed"
    trashed = client.post(
        "/api/v1/projects/batch/lifecycle", json={**payload, "action": "trash"}
    )
    assert trashed.status_code == 200, trashed.text
    deleted = client.request("DELETE", "/api/v1/projects/batch", json=payload)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"affected_ids": [ids["skill"]], "affected_count": 1}
    assert len(asyncio.run(store.list_projects())) == 1
