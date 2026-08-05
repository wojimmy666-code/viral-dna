from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from viral_dna_api.models import (
    ApprovalDecision,
    ApprovalEvent,
    GenerationCandidate,
    GenerationCandidateStatus,
    GenerationKind,
    GenerationRun,
    ProductionChangeKind,
    ProductionProject,
    ProductionRevision,
    ProductionRunStatus,
    ReferenceAsset,
    ReferenceAssetType,
    ReferenceBinding,
    ReferenceRole,
    ShotPlan,
)
from viral_dna_api.schema import WORKSPACE_SCHEMA_VERSION
from viral_dna_api.sqlite_store import SQLiteSchemaError, SQLiteStore
from viral_dna_api.workspace import WorkspaceError, WorkspaceManager


def test_production_models_validate_paths_tags_and_approval_reason() -> None:
    project_id = uuid4()

    with pytest.raises(ValidationError, match="安全的相对路径"):
        ProductionRevision(
            project_id=project_id,
            revision_number=1,
            change_kind=ProductionChangeKind.PROJECT_CREATED,
            change_summary="创建方案",
            snapshot_relative_path="../outside.json",
        )

    with pytest.raises(ValidationError, match="安全的相对路径"):
        ProductionRevision(
            project_id=project_id,
            revision_number=1,
            change_kind=ProductionChangeKind.PROJECT_CREATED,
            change_summary="创建方案",
            snapshot_relative_path=".",
        )

    with pytest.raises(ValidationError, match="退回候选时必须填写原因"):
        ApprovalEvent(
            project_id=project_id,
            revision_id=uuid4(),
            shot_plan_id=uuid4(),
            candidate_id=uuid4(),
            target_kind=GenerationKind.IMAGE,
            decision=ApprovalDecision.REJECTED,
        )

    asset = ReferenceAsset(
        project_id=project_id,
        type=ReferenceAssetType.PERSON,
        name="人物参考",
        relative_path="records\\record-id\\references\\asset-id\\original.png",
        mime_type="image/png",
        width=1024,
        height=1536,
        sha256="a" * 64,
        tags=[" 正面 ", "全身"],
        rights_confirmed=True,
    )
    assert asset.relative_path == ("records/record-id/references/asset-id/original.png")
    assert asset.tags == ["正面", "全身"]


def test_workspace_initializes_production_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
    manager = WorkspaceManager()
    record_id = uuid4()
    project_id = uuid4()
    asset_id = uuid4()
    shot_plan_id = uuid4()

    paths = manager.initialize_production(record_id, project_id)

    assert paths.root == (
        root.resolve() / "records" / str(record_id) / "productions" / str(project_id)
    )
    for directory in (
        paths.root,
        paths.references,
        paths.revisions,
        paths.shots,
        paths.timelines,
        paths.renders,
        paths.exports,
    ):
        assert directory.is_dir()
    assert not paths.project_metadata.exists()
    assert manager.reference_asset_root(record_id, project_id, asset_id) == (
        paths.references / str(asset_id)
    )
    assert manager.production_shot_root(record_id, project_id, shot_plan_id) == (
        paths.shots / str(shot_plan_id)
    )
    relative = manager.relative(paths.revisions / "revision.json")
    assert manager.resolve(relative) == paths.revisions / "revision.json"
    metadata = json.loads((root / ".viraldna" / "workspace.json").read_text("utf-8"))
    assert metadata["schema_version"] == WORKSPACE_SCHEMA_VERSION


def test_sqlite_migrates_v1_to_v2_without_losing_existing_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workspace.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        connection.execute(
            "CREATE TABLE videos ("
            "record_key TEXT PRIMARY KEY, "
            "payload TEXT NOT NULL, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        connection.execute(
            "INSERT INTO videos (record_key, payload) VALUES (?, ?)",
            ("legacy-video", '{"legacy":true}'),
        )

    SQLiteStore(database_path)

    with sqlite3.connect(database_path) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        legacy_payload = connection.execute(
            "SELECT payload FROM videos WHERE record_key = ?",
            ("legacy-video",),
        ).fetchone()

    assert versions == [1, 2, 3]
    assert {
        "production_projects",
        "production_revisions",
        "reference_assets",
        "shot_plans",
        "reference_bindings",
        "generation_runs",
        "generation_candidates",
        "approval_events",
    }.issubset(tables)
    assert "idx_production_projects_record_id" in indexes
    assert "idx_generation_runs_shot_plan_id" in indexes
    assert legacy_payload == ('{"legacy":true}',)


def test_sqlite_rejects_unknown_future_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (WORKSPACE_SCHEMA_VERSION + 1,),
        )

    with pytest.raises(SQLiteSchemaError, match="高于当前支持版本"):
        SQLiteStore(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "production_projects" not in tables


def test_workspace_metadata_does_not_downgrade_future_version(
    tmp_path: Path,
) -> None:
    root = tmp_path / "future-workspace"
    paths = WorkspaceManager.paths_for(root)
    paths.metadata_dir.mkdir(parents=True)
    future_payload = {
        "schema_version": WORKSPACE_SCHEMA_VERSION + 1,
        "created_at": "2026-08-04T00:00:00+00:00",
        "updated_at": "2026-08-04T00:00:00+00:00",
    }
    metadata_path = paths.metadata_dir / "workspace.json"
    metadata_path.write_text(
        json.dumps(future_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceError, match="高于当前支持版本"):
        WorkspaceManager._write_metadata(paths)

    assert json.loads(metadata_path.read_text("utf-8")) == future_payload


def test_sqlite_production_records_survive_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "production.db"
    record_id = uuid4()
    video_id = uuid4()
    analysis_id = uuid4()
    prompt_package_id = uuid4()
    project_id = uuid4()
    revision_id = uuid4()
    shot_plan_id = uuid4()
    run_id = uuid4()

    project = ProductionProject(
        id=project_id,
        record_id=record_id,
        video_id=video_id,
        base_analysis_id=analysis_id,
        source_prompt_package_id=prompt_package_id,
        name="人物替换版",
        current_revision_id=revision_id,
    )
    root = f"records/{record_id}/productions/{project_id}"
    revision = ProductionRevision(
        id=revision_id,
        project_id=project_id,
        revision_number=1,
        change_kind=ProductionChangeKind.PROJECT_CREATED,
        change_summary="创建创作方案",
        snapshot_relative_path=f"{root}/revisions/{revision_id}.json",
    )
    asset = ReferenceAsset(
        project_id=project_id,
        type=ReferenceAssetType.PERSON,
        name="新人物",
        relative_path=f"{root}/references/person/original.png",
        thumbnail_relative_path=f"{root}/references/person/thumbnail.webp",
        mime_type="image/png",
        width=1024,
        height=1536,
        sha256="b" * 64,
        rights_confirmed=True,
    )
    shot_plan = ShotPlan(
        id=shot_plan_id,
        project_id=project_id,
        revision_id=revision_id,
        source_shot_id="shot-001",
        index=1,
        source_keyframe_url="/api/v1/artifacts/shot-001.jpg",
        start_seconds=0,
        end_seconds=3.5,
        duration_seconds=3.5,
        image_prompt="保持构图，将主体替换为参考人物",
    )
    binding = ReferenceBinding(
        shot_plan_id=shot_plan_id,
        reference_asset_id=asset.id,
        role=ReferenceRole.IDENTITY,
    )
    run = GenerationRun(
        id=run_id,
        project_id=project_id,
        shot_plan_id=shot_plan_id,
        revision_id=revision_id,
        kind=GenerationKind.IMAGE,
        provider="simulated",
        model="source-keyframe",
        model_snapshot="batch4.1-simulated-v1",
        prompt_version="image-prompt-v1",
        schema_version="generation-result-v1",
        pricing_version="simulated-zero-v1",
        request_fingerprint="c" * 64,
        input_snapshot_relative_path=f"{root}/shots/{shot_plan_id}/input.json",
        status=ProductionRunStatus.COMPLETED,
        completed_at=project.created_at,
    )
    candidate = GenerationCandidate(
        generation_run_id=run_id,
        ordinal=1,
        kind=GenerationKind.IMAGE,
        relative_path=f"{root}/shots/{shot_plan_id}/images/{run_id}/candidate.png",
        thumbnail_relative_path=(f"{root}/shots/{shot_plan_id}/images/{run_id}/thumbnail.webp"),
        width=720,
        height=1280,
        sha256="d" * 64,
        metadata_relative_path=(f"{root}/shots/{shot_plan_id}/images/{run_id}/metadata.json"),
        status=GenerationCandidateStatus.SELECTED,
    )
    approval = ApprovalEvent(
        project_id=project_id,
        revision_id=revision_id,
        shot_plan_id=shot_plan_id,
        candidate_id=candidate.id,
        target_kind=GenerationKind.IMAGE,
        decision=ApprovalDecision.APPROVED,
    )

    async def scenario() -> None:
        first = SQLiteStore(database_path)
        await first.save_production_project(project)
        await first.save_production_revision(revision)
        await first.save_reference_asset(asset)
        await first.save_shot_plan(shot_plan)
        await first.save_reference_binding(binding)
        await first.save_generation_run(run)
        await first.save_generation_candidate(candidate)
        await first.save_approval_event(approval)

        restarted = SQLiteStore(database_path)
        assert await restarted.get_production_project(project_id) == project
        assert await restarted.list_production_revisions(project_id) == [revision]
        assert await restarted.list_reference_assets(project_id) == [asset]
        assert await restarted.list_shot_plans(project_id) == [shot_plan]
        assert await restarted.list_reference_bindings(shot_plan_id) == [binding]
        assert await restarted.list_generation_runs(
            project_id,
            shot_plan_id,
        ) == [run]
        assert await restarted.list_generation_candidates(run_id) == [candidate]
        assert await restarted.list_approval_events(
            project_id,
            shot_plan_id,
        ) == [approval]

    asyncio.run(scenario())
