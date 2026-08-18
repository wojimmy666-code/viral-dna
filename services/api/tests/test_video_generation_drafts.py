from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.models import (
    GenerationKind,
    ShotPlan,
    ShotVideoGenerationDraftUpdate,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
)
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore
from viral_dna_api.video_generation.drafts import (
    ShotVideoGenerationDraftError,
    ShotVideoGenerationDraftService,
)


class FakeVideoSettings:
    def __init__(self, alias: str = "bailian_wan_2_7_r2v") -> None:
        self.alias = alias

    def get(self) -> SimpleNamespace:
        return SimpleNamespace(
            default_model_alias=self.alias,
            default_resolution="720P",
        )


def make_shot() -> ShotPlan:
    return ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot_001",
        index=1,
        start_seconds=0,
        end_seconds=4,
        duration_seconds=4,
    )


def test_video_generation_draft_persists_user_choice_and_rejects_stale_updates() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        settings = FakeVideoSettings()
        service = ShotVideoGenerationDraftService(store, settings)
        shot = make_shot()
        await store.save_shot_plan(shot)

        initial = await service.get(shot.id)
        assert initial.model_alias == "bailian_wan_2_7_r2v"
        assert initial.origin == "global_default"

        actor_id = uuid4()
        updated = await service.update(
            shot.id,
            ShotVideoGenerationDraftUpdate(
                expected_draft_version=initial.draft_version,
                model_alias="seedance_2_0_fast",
                resolution="1080P",
                duration_seconds=5,
                candidate_count=2,
                input_plan=VideoGenerationInputPlan(
                    sources=[VideoGenerationInputSource.PROJECT_ASSETS]
                ),
            ),
            actor_account_id=actor_id,
        )
        assert updated.model_alias == "seedance_2_0_fast"
        assert updated.input_plan.sources == [VideoGenerationInputSource.PROJECT_ASSETS]
        assert updated.updated_by_account_id == actor_id
        assert updated.draft_version == 2

        settings.alias = "minimax_h3"
        restored = await service.get(shot.id)
        assert restored.model_alias == "seedance_2_0_fast"
        assert restored.resolution == "1080P"
        assert restored.input_plan.sources == [VideoGenerationInputSource.PROJECT_ASSETS]

        with pytest.raises(ShotVideoGenerationDraftError) as conflict:
            await service.update(
                shot.id,
                ShotVideoGenerationDraftUpdate(
                    expected_draft_version=1,
                    model_alias="minimax_h3",
                    resolution="720P",
                    duration_seconds=4,
                    candidate_count=1,
                ),
                actor_account_id=actor_id,
            )
        assert conflict.value.status_code == 409
        assert conflict.value.code == "video_draft_conflict"

    asyncio.run(scenario())


def test_video_generation_draft_backfills_latest_video_run() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        service = ShotVideoGenerationDraftService(store, FakeVideoSettings())
        shot = make_shot()
        await store.save_shot_plan(shot)
        run = SimpleNamespace(
            project_id=shot.project_id,
            shot_plan_id=shot.id,
            kind=GenerationKind.VIDEO,
            model_alias="minimax_h3",
            request_payload={
                "resolution": "1080P",
                "duration_seconds": 6,
                "candidate_count": 3,
            },
            created_at=datetime.now(UTC),
        )
        store.generation_runs[uuid4()] = run

        draft = await service.get(shot.id)
        assert draft.origin == "latest_run"
        assert draft.model_alias == "minimax_h3"
        assert draft.duration_seconds == 6
        assert draft.candidate_count == 3
        assert draft.input_plan.sources == [VideoGenerationInputSource.APPROVED_IMAGES]

    asyncio.run(scenario())


def test_sqlite_video_generation_draft_survives_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "workspace.db"
        first = SQLiteStore(database_path)
        shot = make_shot()
        await first.save_shot_plan(shot)
        first_service = ShotVideoGenerationDraftService(first, FakeVideoSettings())
        initial = await first_service.get(shot.id)
        await first_service.update(
            shot.id,
            ShotVideoGenerationDraftUpdate(
                expected_draft_version=initial.draft_version,
                model_alias="seedance_2_0_mini",
                resolution="720P",
                duration_seconds=5,
                candidate_count=1,
            ),
            actor_account_id=None,
        )

        restarted = SQLiteStore(database_path)
        restarted_service = ShotVideoGenerationDraftService(
            restarted,
            FakeVideoSettings("minimax_h3"),
        )
        restored = await restarted_service.get(shot.id)
        assert restored.model_alias == "seedance_2_0_mini"
        assert restored.origin == "user"
        assert restored.draft_version == 2

    asyncio.run(scenario())
