from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    ApprovalEvent,
    ExportArtifact,
    GenerationCandidate,
    GenerationRun,
    ModelRun,
    ModelRunStatus,
    PriceSnapshot,
    ProductionProject,
    ProductionRevision,
    RecordFolder,
    ReferenceAsset,
    ReferenceBinding,
    ReplacementVersion,
    ShotPlan,
    Video,
)
from .schema import WORKSPACE_SCHEMA_VERSION

ModelT = TypeVar("ModelT", bound=BaseModel)

DATABASE_SCHEMA_VERSION = WORKSPACE_SCHEMA_VERSION

_LEGACY_TABLES = frozenset(
    {
        "videos",
        "analyses",
        "reports",
        "report_versions",
        "replacements",
        "model_runs",
        "price_snapshots",
        "folders",
        "records",
        "exports",
    }
)

_PRODUCTION_TABLES = frozenset(
    {
        "production_projects",
        "production_revisions",
        "reference_assets",
        "shot_plans",
        "reference_bindings",
        "generation_runs",
        "generation_candidates",
        "approval_events",
    }
)

_PRODUCTION_INDEXES = (
    ("idx_production_projects_record_id", "production_projects", "record_id"),
    ("idx_production_revisions_project_id", "production_revisions", "project_id"),
    ("idx_reference_assets_project_id", "reference_assets", "project_id"),
    ("idx_shot_plans_project_id", "shot_plans", "project_id"),
    ("idx_reference_bindings_shot_plan_id", "reference_bindings", "shot_plan_id"),
    ("idx_generation_runs_project_id", "generation_runs", "project_id"),
    ("idx_generation_runs_shot_plan_id", "generation_runs", "shot_plan_id"),
    (
        "idx_generation_candidates_generation_run_id",
        "generation_candidates",
        "generation_run_id",
    ),
    ("idx_approval_events_project_id", "approval_events", "project_id"),
    ("idx_approval_events_shot_plan_id", "approval_events", "shot_plan_id"),
)


class SQLiteSchemaError(RuntimeError):
    """Raised when the durable database schema cannot be migrated safely."""


class SQLiteStore:
    """Durable single-node repository using versioned Pydantic JSON records."""

    _allowed_tables = _LEGACY_TABLES | _PRODUCTION_TABLES

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version INTEGER PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
                applied_versions = {
                    int(row[0])
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                }
                future_versions = {
                    version for version in applied_versions if version > DATABASE_SCHEMA_VERSION
                }
                if future_versions:
                    newest = max(future_versions)
                    raise SQLiteSchemaError(
                        f"数据库版本 {newest} 高于当前支持版本 {DATABASE_SCHEMA_VERSION}"
                    )

                self._create_json_tables(connection, _LEGACY_TABLES)
                if 1 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")

                self._create_json_tables(connection, _PRODUCTION_TABLES)
                self._create_production_indexes(connection)
                if 2 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (2)")

                if 3 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (3)")
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _create_json_tables(
        connection: sqlite3.Connection,
        tables: frozenset[str],
    ) -> None:
        for table in sorted(tables):
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("  # noqa: S608 - internal allowlist
                "record_key TEXT PRIMARY KEY, "
                "payload TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )

    @staticmethod
    def _create_production_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _PRODUCTION_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608 - internal allowlist
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @classmethod
    def _table(cls, table: str) -> str:
        if table not in cls._allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        return table

    def _upsert(self, table: str, key: str, payload: str) -> None:
        safe_table = self._table(table)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {safe_table} (record_key, payload, updated_at) "  # noqa: S608
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(record_key) DO UPDATE SET "
                "payload = excluded.payload, updated_at = CURRENT_TIMESTAMP",
                (key, payload),
            )

    def _upsert_many(
        self,
        entries: list[tuple[str, str, str]],
        deletions: list[tuple[str, str]] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for table, key, payload in entries:
                    safe_table = self._table(table)
                    connection.execute(
                        f"INSERT INTO {safe_table} "  # noqa: S608 - internal allowlist
                        "(record_key, payload, updated_at) "
                        "VALUES (?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(record_key) DO UPDATE SET "
                        "payload = excluded.payload, updated_at = CURRENT_TIMESTAMP",
                        (key, payload),
                    )
                for table, key in deletions or []:
                    safe_table = self._table(table)
                    connection.execute(
                        f"DELETE FROM {safe_table} WHERE record_key = ?",  # noqa: S608
                        (key,),
                    )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _read(self, table: str, key: str) -> str | None:
        safe_table = self._table(table)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {safe_table} WHERE record_key = ?",  # noqa: S608
                (key,),
            ).fetchone()
        return str(row[0]) if row else None

    def _read_all(self, table: str) -> list[str]:
        safe_table = self._table(table)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM {safe_table} ORDER BY updated_at, record_key"  # noqa: S608
            ).fetchall()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _serialize(model: BaseModel) -> str:
        payload = model.model_dump(mode="json")
        if isinstance(model, Video):
            payload["stored_path"] = model.stored_path
            payload["stored_relative_path"] = model.stored_relative_path
        if isinstance(model, ExportArtifact):
            payload["relative_path"] = model.relative_path
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def _save(self, table: str, key: UUID | str, model: ModelT) -> ModelT:
        async with self._lock:
            await asyncio.to_thread(self._upsert, table, str(key), self._serialize(model))
        return model

    async def _get(
        self,
        table: str,
        key: UUID | str,
        model_type: type[ModelT],
    ) -> ModelT | None:
        payload = await asyncio.to_thread(self._read, table, str(key))
        return model_type.model_validate_json(payload) if payload else None

    async def add_video(self, video: Video) -> Video:
        return await self._save("videos", video.id, video)

    async def get_video(self, video_id: UUID) -> Video | None:
        return await self._get("videos", video_id, Video)

    async def save_video(self, video: Video) -> Video:
        return await self._save("videos", video.id, video)

    async def list_videos(self) -> list[Video]:
        payloads = await asyncio.to_thread(self._read_all, "videos")
        return [Video.model_validate_json(payload) for payload in payloads]

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None:
        return await self._get("analyses", analysis_id, AnalysisJob)

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        return await self._save("analyses", analysis.id, analysis)

    async def list_analyses(self) -> list[AnalysisJob]:
        payloads = await asyncio.to_thread(self._read_all, "analyses")
        return [AnalysisJob.model_validate_json(payload) for payload in payloads]

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        await self._save("report_versions", report.analysis_id, report)
        return await self._save("reports", report.video_id, report)

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return await self._get("reports", video_id, AnalysisReport)

    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None:
        versioned = await self._get("report_versions", analysis_id, AnalysisReport)
        if versioned is not None:
            return versioned
        # Compatibility for reports written before report_versions existed.
        payloads = await asyncio.to_thread(self._read_all, "reports")
        return next(
            (
                report
                for report in (AnalysisReport.model_validate_json(payload) for payload in payloads)
                if report.analysis_id == analysis_id
            ),
            None,
        )

    async def list_report_versions(self) -> list[AnalysisReport]:
        payloads = await asyncio.to_thread(self._read_all, "report_versions")
        return [AnalysisReport.model_validate_json(payload) for payload in payloads]

    async def save_folder(self, folder: RecordFolder) -> RecordFolder:
        return await self._save("folders", folder.id, folder)

    async def get_folder(self, folder_id: UUID) -> RecordFolder | None:
        return await self._get("folders", folder_id, RecordFolder)

    async def list_folders(self) -> list[RecordFolder]:
        payloads = await asyncio.to_thread(self._read_all, "folders")
        return [RecordFolder.model_validate_json(payload) for payload in payloads]

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord:
        return await self._save("records", record.id, record)

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None:
        return await self._get("records", record_id, AnalysisRecord)

    async def list_records(self) -> list[AnalysisRecord]:
        payloads = await asyncio.to_thread(self._read_all, "records")
        return [AnalysisRecord.model_validate_json(payload) for payload in payloads]

    async def save_export(self, artifact: ExportArtifact) -> ExportArtifact:
        return await self._save("exports", artifact.id, artifact)

    async def get_export(self, export_id: UUID) -> ExportArtifact | None:
        return await self._get("exports", export_id, ExportArtifact)

    async def list_exports(self, record_id: UUID | None = None) -> list[ExportArtifact]:
        payloads = await asyncio.to_thread(self._read_all, "exports")
        artifacts = [ExportArtifact.model_validate_json(payload) for payload in payloads]
        if record_id is None:
            return artifacts
        return [artifact for artifact in artifacts if artifact.record_id == record_id]

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        return await self._save("replacements", version.id, version)

    async def get_replacement(self, version_id: UUID) -> ReplacementVersion | None:
        return await self._get("replacements", version_id, ReplacementVersion)

    async def save_model_run(self, run: ModelRun) -> ModelRun:
        return await self._save("model_runs", run.id, run)

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]:
        payloads = await asyncio.to_thread(self._read_all, "model_runs")
        runs = [ModelRun.model_validate_json(payload) for payload in payloads]
        return [run for run in runs if run.analysis_id == analysis_id]

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None:
        payloads = await asyncio.to_thread(self._read_all, "model_runs")
        candidates = [
            run
            for run in (ModelRun.model_validate_json(payload) for payload in payloads)
            if run.request_fingerprint == request_fingerprint
            and run.status == ModelRunStatus.COMPLETED
            and run.result_payload is not None
        ]
        return max(candidates, key=lambda run: run.completed_at or run.created_at, default=None)

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot:
        return await self._save("price_snapshots", snapshot.id, snapshot)

    async def get_price_snapshot(self, snapshot_id: str) -> PriceSnapshot | None:
        return await self._get("price_snapshots", snapshot_id, PriceSnapshot)

    async def save_production_project(
        self,
        project: ProductionProject,
    ) -> ProductionProject:
        return await self._save("production_projects", project.id, project)

    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None:
        return await self._get("production_projects", project_id, ProductionProject)

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]:
        payloads = await asyncio.to_thread(self._read_all, "production_projects")
        projects = [ProductionProject.model_validate_json(payload) for payload in payloads]
        if record_id is not None:
            projects = [project for project in projects if project.record_id == record_id]
        return sorted(projects, key=lambda project: project.created_at)

    async def save_production_revision(
        self,
        revision: ProductionRevision,
    ) -> ProductionRevision:
        return await self._save("production_revisions", revision.id, revision)

    async def get_production_revision(
        self,
        revision_id: UUID,
    ) -> ProductionRevision | None:
        return await self._get("production_revisions", revision_id, ProductionRevision)

    async def list_production_revisions(
        self,
        project_id: UUID,
    ) -> list[ProductionRevision]:
        payloads = await asyncio.to_thread(self._read_all, "production_revisions")
        revisions = [ProductionRevision.model_validate_json(payload) for payload in payloads]
        return sorted(
            (revision for revision in revisions if revision.project_id == project_id),
            key=lambda revision: revision.revision_number,
        )

    async def save_reference_asset(self, asset: ReferenceAsset) -> ReferenceAsset:
        return await self._save("reference_assets", asset.id, asset)

    async def get_reference_asset(self, asset_id: UUID) -> ReferenceAsset | None:
        return await self._get("reference_assets", asset_id, ReferenceAsset)

    async def list_reference_assets(self, project_id: UUID) -> list[ReferenceAsset]:
        payloads = await asyncio.to_thread(self._read_all, "reference_assets")
        assets = [ReferenceAsset.model_validate_json(payload) for payload in payloads]
        return sorted(
            (asset for asset in assets if asset.project_id == project_id),
            key=lambda asset: asset.created_at,
        )

    async def save_production_bundle(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        *,
        reference_assets: list[ReferenceAsset] | None = None,
        shot_plans: list[ShotPlan] | None = None,
        reference_bindings: list[ReferenceBinding] | None = None,
        remove_reference_binding_ids: list[UUID] | None = None,
        generation_runs: list[GenerationRun] | None = None,
        generation_candidates: list[GenerationCandidate] | None = None,
        approval_events: list[ApprovalEvent] | None = None,
    ) -> tuple[ProductionProject, ProductionRevision]:
        entries = [
            (
                "production_projects",
                str(project.id),
                self._serialize(project),
            ),
            (
                "production_revisions",
                str(revision.id),
                self._serialize(revision),
            ),
        ]
        entries.extend(
            ("reference_assets", str(asset.id), self._serialize(asset))
            for asset in reference_assets or []
        )
        entries.extend(
            ("shot_plans", str(shot_plan.id), self._serialize(shot_plan))
            for shot_plan in shot_plans or []
        )
        entries.extend(
            ("reference_bindings", str(binding.id), self._serialize(binding))
            for binding in reference_bindings or []
        )
        entries.extend(
            ("generation_runs", str(run.id), self._serialize(run)) for run in generation_runs or []
        )
        entries.extend(
            ("generation_candidates", str(candidate.id), self._serialize(candidate))
            for candidate in generation_candidates or []
        )
        entries.extend(
            ("approval_events", str(event.id), self._serialize(event))
            for event in approval_events or []
        )
        deletions = [
            ("reference_bindings", str(binding_id))
            for binding_id in remove_reference_binding_ids or []
        ]
        async with self._lock:
            await asyncio.to_thread(self._upsert_many, entries, deletions)
        return project, revision

    async def save_shot_plan(self, shot_plan: ShotPlan) -> ShotPlan:
        return await self._save("shot_plans", shot_plan.id, shot_plan)

    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None:
        return await self._get("shot_plans", shot_plan_id, ShotPlan)

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]:
        payloads = await asyncio.to_thread(self._read_all, "shot_plans")
        shot_plans = [ShotPlan.model_validate_json(payload) for payload in payloads]
        return sorted(
            (shot_plan for shot_plan in shot_plans if shot_plan.project_id == project_id),
            key=lambda shot_plan: shot_plan.index,
        )

    async def save_reference_binding(
        self,
        binding: ReferenceBinding,
    ) -> ReferenceBinding:
        return await self._save("reference_bindings", binding.id, binding)

    async def get_reference_binding(
        self,
        binding_id: UUID,
    ) -> ReferenceBinding | None:
        return await self._get("reference_bindings", binding_id, ReferenceBinding)

    async def list_reference_bindings(
        self,
        shot_plan_id: UUID,
    ) -> list[ReferenceBinding]:
        payloads = await asyncio.to_thread(self._read_all, "reference_bindings")
        bindings = [ReferenceBinding.model_validate_json(payload) for payload in payloads]
        return sorted(
            (binding for binding in bindings if binding.shot_plan_id == shot_plan_id),
            key=lambda binding: binding.created_at,
        )

    async def save_generation_run(self, run: GenerationRun) -> GenerationRun:
        return await self._save("generation_runs", run.id, run)

    async def get_generation_run(self, run_id: UUID) -> GenerationRun | None:
        return await self._get("generation_runs", run_id, GenerationRun)

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]:
        payloads = await asyncio.to_thread(self._read_all, "generation_runs")
        runs = [GenerationRun.model_validate_json(payload) for payload in payloads]
        filtered = [run for run in runs if run.project_id == project_id]
        if shot_plan_id is not None:
            filtered = [run for run in filtered if run.shot_plan_id == shot_plan_id]
        return sorted(filtered, key=lambda run: run.created_at)

    async def save_generation_candidate(
        self,
        candidate: GenerationCandidate,
    ) -> GenerationCandidate:
        return await self._save("generation_candidates", candidate.id, candidate)

    async def get_generation_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate | None:
        return await self._get(
            "generation_candidates",
            candidate_id,
            GenerationCandidate,
        )

    async def list_generation_candidates(
        self,
        generation_run_id: UUID,
    ) -> list[GenerationCandidate]:
        payloads = await asyncio.to_thread(self._read_all, "generation_candidates")
        candidates = [GenerationCandidate.model_validate_json(payload) for payload in payloads]
        return sorted(
            (
                candidate
                for candidate in candidates
                if candidate.generation_run_id == generation_run_id
            ),
            key=lambda candidate: candidate.ordinal,
        )

    async def save_approval_event(self, event: ApprovalEvent) -> ApprovalEvent:
        return await self._save("approval_events", event.id, event)

    async def get_approval_event(self, event_id: UUID) -> ApprovalEvent | None:
        return await self._get("approval_events", event_id, ApprovalEvent)

    async def list_approval_events(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[ApprovalEvent]:
        payloads = await asyncio.to_thread(self._read_all, "approval_events")
        events = [ApprovalEvent.model_validate_json(payload) for payload in payloads]
        filtered = [event for event in events if event.project_id == project_id]
        if shot_plan_id is not None:
            filtered = [event for event in filtered if event.shot_plan_id == shot_plan_id]
        return sorted(filtered, key=lambda event: event.created_at)
