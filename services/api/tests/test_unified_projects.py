from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from viral_dna_api.models import AnalysisRecord, SourceType, Video, VideoStatus
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import (
    ProjectCreate,
    ProjectLifecycle,
    ProjectLifecycleAction,
    ProjectService,
)
from viral_dna_api.store import InMemoryStore


class FakeAccountContext:
    def __init__(self) -> None:
        self.account = SimpleNamespace(id=uuid4())

    async def current_account(self):
        return self.account


def test_analysis_backfill_and_skill_project_share_one_project_catalog() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        catalog = PlatformSkillCatalogService(None)
        service = ProjectService(store, catalog, FakeAccountContext())

        record_id = uuid4()
        video = Video(
            record_id=record_id,
            source_type=SourceType.UPLOAD,
            title="Source video",
            status=VideoStatus.COMPLETED,
        )
        record = AnalysisRecord(
            id=record_id,
            name="Analysis project",
            video_id=video.id,
            source_type=SourceType.UPLOAD,
            status=VideoStatus.COMPLETED,
        )
        await store.add_video(video)
        await store.save_record(record)
        await service.bootstrap_analysis_projects()
        await service.bootstrap_analysis_projects()

        migrated = await store.get_project(record_id)
        assert migrated is not None
        assert migrated.id == record.id
        assert migrated.kind == "analysis"
        assert len(await store.list_projects()) == 1

        skill = (await catalog.list_catalog()).items[0]
        created = await service.create(
            ProjectCreate(
                kind="skill",
                name="Skill project",
                skill_version_id=skill.current_version.id,
            )
        )
        snapshot = await store.get_skill_version_snapshot(created.id)
        assert snapshot is not None
        assert snapshot.content_digest == skill.current_version.content_digest
        assert created.kind == "skill"

        listing = await service.list(lifecycle=ProjectLifecycle.ACTIVE, sort="name_asc")
        assert [item.name for item in listing.items] == ["Analysis project", "Skill project"]

        await service.mutate_lifecycle(created.id, ProjectLifecycleAction.TRASH)
        trash = await service.list(lifecycle=ProjectLifecycle.TRASHED)
        assert [item.id for item in trash.items] == [created.id]

    asyncio.run(scenario())
