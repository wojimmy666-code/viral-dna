from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from PIL import Image

from viral_dna_api.image_generation import ImageGenerationGateway
from viral_dna_api.image_generation.gateway import _filesystem_path
from viral_dna_api.models import (
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ImageGenerationCreate,
    ProductionChangeKind,
    ProductionProject,
    ProductionRevision,
    ProductionRunStatus,
    ShotPlan,
    WorkflowItemStatus,
)
from viral_dna_api.production import ProductionService
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceManager:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    return WorkspaceManager()


def _project() -> ProductionProject:
    return ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="任务测试",
        current_revision_id=uuid4(),
    )


def _shot(project: ProductionProject) -> ShotPlan:
    assert project.current_revision_id is not None
    return ShotPlan(
        project_id=project.id,
        revision_id=project.current_revision_id,
        source_shot_id="shot-1",
        index=1,
        start_seconds=0,
        end_seconds=2,
        duration_seconds=2,
        image_prompt="写实产品画面",
        image_status=WorkflowItemStatus.READY,
    )


def _run(
    project: ProductionProject,
    shot: ShotPlan,
    status: ProductionRunStatus,
    *,
    request_payload: dict[str, object] | None = None,
) -> GenerationRun:
    assert project.current_revision_id is not None
    run_id = uuid4()
    return GenerationRun(
        id=run_id,
        project_id=project.id,
        shot_plan_id=shot.id,
        revision_id=project.current_revision_id,
        kind=GenerationKind.IMAGE,
        provider="pending",
        model="pending",
        model_snapshot="pending",
        prompt_version="shot-image-v2",
        schema_version="viral-dna-image-job/v1",
        pricing_version="pending",
        request_fingerprint="a" * 64,
        input_snapshot_relative_path=f"jobs/{run_id}.json",
        execution_mode=ImageExecutionMode.REMOTE_API,
        adapter_id="pending",
        adapter_version="batch4.2.4",
        cost_source=GenerationCostSource.UNKNOWN,
        request_payload=request_payload or {},
        status=status,
    )


@pytest.mark.asyncio
async def test_sqlite_claims_a_queued_run_only_once_across_store_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch)
    first = SQLiteStore(workspace.database_path)
    second = SQLiteStore(workspace.database_path)
    project = _project()
    shot = _shot(project)
    queued = _run(project, shot, ProductionRunStatus.QUEUED)
    await first.save_generation_run(queued)

    claimed_at = datetime.now(UTC)
    results = await asyncio.gather(
        first.claim_generation_run(queued.id, claimed_at),
        second.claim_generation_run(queued.id, claimed_at),
    )
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0].status == ProductionRunStatus.RUNNING
    assert (await first.get_generation_run(queued.id)).status == ProductionRunStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_and_retry_preserve_request_and_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch)
    repository = InMemoryStore()
    project = _project()
    shot = _shot(project)
    await repository.save_production_project(project)
    await repository.save_shot_plan(shot)
    payload = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
        candidate_count=2,
        execution_mode=ImageExecutionMode.REMOTE_API,
    )
    queued = _run(
        project,
        shot,
        ProductionRunStatus.QUEUED,
        request_payload=payload.model_dump(mode="json"),
    )
    await repository.save_generation_run(queued)
    settings = SimpleNamespace(
        enabled=True,
        execution_mode=ImageExecutionMode.REMOTE_API,
    )
    gateway = SimpleNamespace(settings_service=SimpleNamespace(get=lambda: settings))
    service = ProductionService(repository, workspace, image_gateway=gateway)
    scheduled: list[UUID] = []
    monkeypatch.setattr(service, "_schedule_image_run", scheduled.append)

    cancelled = await service.cancel_generation_run(queued.id)
    assert cancelled.status == ProductionRunStatus.CANCELLED
    assert cancelled.cancellation_requested is True

    retried = await service.retry_generation_run(queued.id)
    assert retried.status == ProductionRunStatus.QUEUED
    assert retried.retry_of_run_id == queued.id
    assert retried.retry_count == 1
    assert retried.id in scheduled
    stored = await repository.get_generation_run(retried.id)
    assert stored is not None
    assert stored.request_payload["candidate_count"] == 2
    assert stored.request_payload["expected_revision_id"] == str(project.current_revision_id)


@pytest.mark.asyncio
async def test_recover_image_output_imports_existing_artifact_without_new_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch)
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    repository = InMemoryStore()
    project = _project()
    shot = _shot(project)
    workspace.initialize_production(project.record_id, project.id)
    await repository.save_production_project(project)
    await repository.save_shot_plan(shot)

    run_id = uuid4()
    run_root = (
        workspace.production_shot_root(project.record_id, project.id, shot.id)
        / "images"
        / str(run_id)
    )
    input_path = run_root / "input.json"
    _filesystem_path(input_path.parent).mkdir(parents=True, exist_ok=True)
    _filesystem_path(input_path).write_text(
        json.dumps({"output": {"width": 720, "height": 1280}, "references": []}),
        "utf-8",
    )
    artifact = codex_home / "generated_images" / "session-1" / "result.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (720, 1280), (70, 110, 170)).save(artifact, "PNG")
    now = datetime.now(UTC)
    failed = GenerationRun(
        id=run_id,
        project_id=project.id,
        shot_plan_id=shot.id,
        visual_beat_id=shot.visual_beats[0].id,
        revision_id=project.current_revision_id,
        kind=GenerationKind.IMAGE,
        provider="local_tool",
        model="gpt-5.6-sol",
        model_snapshot="gpt-5.6-sol@1.1.0",
        prompt_version="shot-image-v3",
        schema_version="viral-dna-image-generation/v2",
        pricing_version="local-tool-cost-v1",
        request_fingerprint="b" * 64,
        input_snapshot_relative_path=workspace.relative(input_path),
        execution_mode=ImageExecutionMode.LOCAL_TOOL,
        adapter_id="codex_imagegen_v1",
        adapter_version="1.1.0",
        cost_source=GenerationCostSource.SUBSCRIPTION_QUOTA,
        request_payload={"candidate_count": 1},
        status=ProductionRunStatus.FAILED,
        error_code="local_tool_failed",
        error_message="图片已生成但没有导入",
        started_at=now,
        completed_at=now,
    )
    await repository.save_generation_run(failed)
    service = ProductionService(
        repository,
        workspace,
        image_gateway=ImageGenerationGateway(workspace, repository=repository),
    )

    async def prepare_revision(
        next_project: ProductionProject,
        change_kind: ProductionChangeKind,
        change_summary: str,
        *,
        revision_id,
        **_kwargs,
    ):
        revision = ProductionRevision(
            id=revision_id,
            project_id=next_project.id,
            parent_revision_id=next_project.current_revision_id,
            revision_number=2,
            change_kind=change_kind,
            change_summary=change_summary,
            snapshot_relative_path=f"revisions/{revision_id}.json",
        )
        return (
            next_project.model_copy(update={"current_revision_id": revision.id}),
            revision,
        )

    monkeypatch.setattr(service, "_prepare_revision", prepare_revision)

    before_revision = project.current_revision_id
    recovered = await service.recover_image_generation_output(failed.id)

    assert recovered.status == ProductionRunStatus.COMPLETED
    assert recovered.actual_cost_micros == 0
    assert len(recovered.candidates) == 1
    assert recovered.usage["recovery_quota_consumed"] is False
    updated_project = await repository.get_production_project(project.id)
    updated_shot = await repository.get_shot_plan(shot.id)
    assert updated_project is not None
    assert updated_project.current_revision_id != before_revision
    assert updated_shot is not None
    assert updated_shot.visual_beats[0].image_status == WorkflowItemStatus.REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_recovery_reschedules_queued_and_safely_terminates_unknown_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path, monkeypatch)
    repository = InMemoryStore()
    project = _project()
    shot = _shot(project)
    await repository.save_production_project(project)
    await repository.save_shot_plan(shot)
    request = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
    ).model_dump(mode="json")
    queued = _run(project, shot, ProductionRunStatus.QUEUED, request_payload=request)
    running = _run(project, shot, ProductionRunStatus.RUNNING, request_payload=request)
    cancelling = _run(
        project,
        shot,
        ProductionRunStatus.CANCELLATION_REQUESTED,
        request_payload=request,
    )
    for run in (queued, running, cancelling):
        await repository.save_generation_run(run)
    service = ProductionService(repository, workspace)
    scheduled: list[UUID] = []
    monkeypatch.setattr(service, "_schedule_image_run", scheduled.append)

    result = await service.recover_generation_runs()
    assert result == {"recovered": 1, "interrupted": 1, "cancelled": 1}
    assert scheduled == [queued.id]
    interrupted = await repository.get_generation_run(running.id)
    cancelled = await repository.get_generation_run(cancelling.id)
    assert interrupted is not None
    assert interrupted.status == ProductionRunStatus.FAILED
    assert interrupted.error_code == "generation_interrupted"
    assert cancelled is not None
    assert cancelled.status == ProductionRunStatus.CANCELLED
