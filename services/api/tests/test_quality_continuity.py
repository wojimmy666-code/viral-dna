from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.models import (
    ProductionProject,
    ProductionStep,
    ReferenceBinding,
    ReferenceRole,
    ShotPlan,
)
from viral_dna_api.quality.continuity import impacted_boundary_keys
from viral_dna_api.quality.continuity_service import ContinuityService
from viral_dna_api.quality.contracts import (
    ContinuityBoundaryStatus,
    ContinuityDecision,
    ContinuityFindingDecisionRequest,
    ContinuityFindingSeverity,
    ContinuityFindingState,
    ContinuityReportRunRequest,
    ContinuityReportStatus,
    ContinuityVerificationState,
)
from viral_dna_api.quality.routes import create_continuity_router
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore


def _project() -> ProductionProject:
    return ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="连续性质检",
        active_step=ProductionStep.SHOT_VIDEOS,
        current_revision_id=uuid4(),
    )


def _shot(project: ProductionProject, *, index: int) -> ShotPlan:
    return ShotPlan(
        project_id=project.id,
        revision_id=project.current_revision_id,
        source_shot_id=f"shot-{index}",
        index=index,
        start_seconds=float(index - 1) * 3,
        end_seconds=float(index) * 3,
        duration_seconds=3,
        video_prompt=f"分镜 {index}",
    )


def test_continuity_report_blocks_identity_drift_and_preserves_decision() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        project = _project()
        shots = [_shot(project, index=index) for index in range(1, 4)]
        await store.save_production_project(project)
        for shot in shots:
            await store.save_shot_plan(shot)
        first_identity = uuid4()
        second_identity = uuid4()
        await store.save_reference_binding(
            ReferenceBinding(
                shot_plan_id=shots[0].id,
                reference_asset_id=first_identity,
                role=ReferenceRole.IDENTITY,
            )
        )
        await store.save_reference_binding(
            ReferenceBinding(
                shot_plan_id=shots[1].id,
                reference_asset_id=second_identity,
                role=ReferenceRole.IDENTITY,
            )
        )
        await store.save_reference_binding(
            ReferenceBinding(
                shot_plan_id=shots[2].id,
                reference_asset_id=second_identity,
                role=ReferenceRole.IDENTITY,
            )
        )

        service = ContinuityService(store)
        report = await service.run_report(
            project.id,
            ContinuityReportRunRequest(
                expected_revision_id=project.current_revision_id,
            ),
        )
        assert report.status == ContinuityReportStatus.COMPLETED
        assert report.verification_state == ContinuityVerificationState.RULE_ONLY
        assert report.blocker_count == 1
        assert report.boundaries[0].status == ContinuityBoundaryStatus.BLOCKED
        finding = report.boundaries[0].findings[0]
        assert finding.severity == ContinuityFindingSeverity.BLOCKER

        waived = await service.decide_finding(
            project.id,
            report.id,
            finding.key,
            ContinuityFindingDecisionRequest(
                expected_revision_id=project.current_revision_id,
                decision=ContinuityDecision.WAIVE,
                reason="剧情设定为不同人物",
            ),
        )
        assert waived.blocker_count == 0
        assert waived.boundaries[0].findings[0].state == ContinuityFindingState.WAIVED
        assert waived.boundaries[0].status == ContinuityBoundaryStatus.UNVERIFIED

        rerun = await service.run_report(
            project.id,
            ContinuityReportRunRequest(
                expected_revision_id=project.current_revision_id,
            ),
        )
        assert rerun.id == waived.id
        assert rerun.boundaries[0].findings[0].state == ContinuityFindingState.WAIVED

        invalidated_revision_id = uuid4()
        stale = await service.invalidate_for_shot(
            project.id,
            shots[1].id,
            invalidated_revision_id,
        )
        assert stale is not None
        assert stale.status == ContinuityReportStatus.STALE
        assert stale.invalidated_by_revision_id == invalidated_revision_id
        assert stale.stale_boundary_keys == [
            stale.boundaries[0].key,
            stale.boundaries[1].key,
        ]

    asyncio.run(scenario())


def test_impacted_boundaries_are_limited_to_neighbours() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        project = _project()
        shots = [_shot(project, index=index) for index in range(1, 5)]
        await store.save_production_project(project)
        for shot in shots:
            await store.save_shot_plan(shot)
        report = await ContinuityService(store).run_report(
            project.id,
            ContinuityReportRunRequest(
                expected_revision_id=project.current_revision_id,
            ),
        )
        keys = impacted_boundary_keys(report.snapshots, shots[2].id)
        assert keys == [report.boundaries[1].key, report.boundaries[2].key]

    asyncio.run(scenario())


def test_sqlite_continuity_report_survives_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "continuity.db"
        first = SQLiteStore(database_path)
        project = _project()
        shots = [_shot(project, index=1), _shot(project, index=2)]
        await first.save_production_project(project)
        for shot in shots:
            await first.save_shot_plan(shot)
        report = await ContinuityService(first).run_report(
            project.id,
            ContinuityReportRunRequest(
                expected_revision_id=project.current_revision_id,
            ),
        )

        restarted = SQLiteStore(database_path)
        restored = await restarted.get_continuity_report(report.id)
        assert restored is not None
        assert restored.input_fingerprint == report.input_fingerprint
        assert restored.boundaries[0].status == ContinuityBoundaryStatus.UNVERIFIED

    asyncio.run(scenario())


def test_continuity_http_api_runs_and_returns_latest_report() -> None:
    store = InMemoryStore()
    project = _project()
    shots = [_shot(project, index=1), _shot(project, index=2)]

    async def seed() -> None:
        await store.save_production_project(project)
        for shot in shots:
            await store.save_shot_plan(shot)

    asyncio.run(seed())
    app = FastAPI()
    app.include_router(
        create_continuity_router(ContinuityService(store)),
        prefix="/api/v1",
    )
    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/productions/{project.id}/continuity-reports",
            json={"expected_revision_id": str(project.current_revision_id)},
        )
        assert created.status_code == 200
        latest = client.get(
            f"/api/v1/productions/{project.id}/continuity-reports/latest"
        )
        assert latest.status_code == 200
        assert latest.json()["id"] == created.json()["id"]
        assert latest.json()["verification_state"] == "rule_only"
