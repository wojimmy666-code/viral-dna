from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from .asset_library import Asset, AssetFolder
from .control_assets.jobs.domain import (
    ACTIVE_DEPTH_JOB_STATUSES,
    DepthControlJob,
    DepthControlJobStatus,
)
from .generated_artifacts.domain import (
    AssetProvenance,
    GeneratedArtifact,
    StorageObjectReference,
)
from .media_staging.domain import MediaAccessLease, MediaStagingConfig
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
    ProductionRunStatus,
    ProjectAssetLink,
    RecordFolder,
    ReferenceAsset,
    ReferenceBinding,
    ReplacementVersion,
    ShotPlan,
    ShotVideoGenerationDraft,
    Video,
    VideoClipPreparation,
    VideoProviderTask,
)
from .quality.contracts import ContinuityReport
from .schema import WORKSPACE_SCHEMA_VERSION
from .storage_errors import IncompatibleShotPlanSchemaError
from .storage_objects import ObjectReplica, StorageObject
from .viral_insights.contracts import ViralConceptSet, ViralInsightReport

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
        "video_provider_tasks",
        "video_clip_preparations",
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
    (
        "idx_video_provider_tasks_generation_run_id",
        "video_provider_tasks",
        "generation_run_id",
    ),
    (
        "idx_video_clip_preparations_project_id",
        "video_clip_preparations",
        "project_id",
    ),
    (
        "idx_video_clip_preparations_shot_plan_id",
        "video_clip_preparations",
        "shot_plan_id",
    ),
    (
        "idx_video_clip_preparations_candidate_id",
        "video_clip_preparations",
        "candidate_id",
    ),
    ("idx_approval_events_project_id", "approval_events", "project_id"),
    ("idx_approval_events_shot_plan_id", "approval_events", "shot_plan_id"),
)

_WORKSPACE_ASSET_TABLES = frozenset(
    {
        "storage_objects",
        "object_replicas",
        "asset_folders",
        "assets",
    }
)

_WORKSPACE_ASSET_INDEXES = (
    ("idx_storage_objects_workspace_id", "storage_objects", "workspace_id"),
    ("idx_object_replicas_object_id", "object_replicas", "storage_object_id"),
    ("idx_asset_folders_workspace_id", "asset_folders", "workspace_id"),
    ("idx_assets_workspace_id", "assets", "workspace_id"),
    ("idx_assets_folder_id", "assets", "folder_id"),
)

_PROJECT_ASSET_TABLES = frozenset({"project_asset_links"})

_PROJECT_ASSET_INDEXES = (
    ("idx_project_asset_links_workspace_id", "project_asset_links", "workspace_id"),
    ("idx_project_asset_links_project_id", "project_asset_links", "project_id"),
    ("idx_project_asset_links_asset_id", "project_asset_links", "asset_id"),
)

_QUALITY_TABLES = frozenset({"continuity_reports"})

_QUALITY_INDEXES = (
    ("idx_continuity_reports_project_id", "continuity_reports", "project_id"),
    ("idx_continuity_reports_revision_id", "continuity_reports", "revision_id"),
)

_VIRAL_INSIGHT_TABLES = frozenset({"viral_insights", "viral_concept_sets"})

_VIRAL_INSIGHT_INDEXES = (
    ("idx_viral_insights_analysis_id", "viral_insights", "analysis_id"),
    ("idx_viral_concept_sets_analysis_id", "viral_concept_sets", "analysis_id"),
)

_VIDEO_GENERATION_DRAFT_TABLES = frozenset({"shot_video_generation_drafts"})

_VIDEO_GENERATION_DRAFT_INDEXES = (
    (
        "idx_shot_video_generation_drafts_project_id",
        "shot_video_generation_drafts",
        "project_id",
    ),
)

_DEPTH_CONTROL_JOB_TABLES = frozenset({"depth_control_jobs"})

_DEPTH_CONTROL_JOB_INDEXES = (
    ("idx_depth_control_jobs_project_id", "depth_control_jobs", "project_id"),
    ("idx_depth_control_jobs_shot_plan_id", "depth_control_jobs", "shot_plan_id"),
    ("idx_depth_control_jobs_status", "depth_control_jobs", "status"),
)

_GENERATED_ARTIFACT_TABLES = frozenset(
    {"generated_artifacts", "storage_object_references", "asset_provenance"}
)

_GENERATED_ARTIFACT_INDEXES = (
    ("idx_generated_artifacts_account_id", "generated_artifacts", "account_id"),
    ("idx_generated_artifacts_workspace_id", "generated_artifacts", "workspace_id"),
    ("idx_generated_artifacts_source_entity_id", "generated_artifacts", "source_entity_id"),
    ("idx_storage_object_references_object_id", "storage_object_references", "storage_object_id"),
    ("idx_storage_object_references_owner_id", "storage_object_references", "owner_id"),
    ("idx_asset_provenance_asset_id", "asset_provenance", "asset_id"),
)

_MEDIA_STAGING_TABLES = frozenset({"media_staging_configs", "media_access_leases"})

_MEDIA_STAGING_INDEXES = (
    ("idx_media_staging_configs_account_id", "media_staging_configs", "account_id"),
    ("idx_media_access_leases_account_id", "media_access_leases", "account_id"),
    ("idx_media_access_leases_object_id", "media_access_leases", "storage_object_id"),
    ("idx_media_access_leases_expires_at", "media_access_leases", "expires_at"),
)


class SQLiteSchemaError(RuntimeError):
    """Raised when the durable database schema cannot be migrated safely."""


class SQLiteStore:
    """Durable single-node repository using versioned Pydantic JSON records."""

    _allowed_tables = (
        _LEGACY_TABLES
        | _PRODUCTION_TABLES
        | _WORKSPACE_ASSET_TABLES
        | _PROJECT_ASSET_TABLES
        | _QUALITY_TABLES
        | _VIRAL_INSIGHT_TABLES
        | _VIDEO_GENERATION_DRAFT_TABLES
        | _DEPTH_CONTROL_JOB_TABLES
        | _GENERATED_ARTIFACT_TABLES
        | _MEDIA_STAGING_TABLES
    )

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

                self._create_json_tables(connection, _WORKSPACE_ASSET_TABLES)
                self._create_workspace_asset_indexes(connection)
                if 3 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (3)")

                self._create_json_tables(connection, _PROJECT_ASSET_TABLES)
                self._create_project_asset_indexes(connection)
                if 4 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (4)")

                self._create_json_tables(connection, frozenset({"video_provider_tasks"}))
                self._create_production_indexes(connection)
                if 5 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (5)")

                self._create_json_tables(connection, frozenset({"video_clip_preparations"}))
                self._create_production_indexes(connection)
                if 6 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (6)")

                self._create_json_tables(connection, _QUALITY_TABLES)
                self._create_quality_indexes(connection)
                if 7 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (7)")

                self._create_json_tables(connection, _VIRAL_INSIGHT_TABLES)
                self._create_viral_insight_indexes(connection)
                if 8 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (8)")

                self._create_json_tables(connection, _VIDEO_GENERATION_DRAFT_TABLES)
                self._create_video_generation_draft_indexes(connection)
                if 9 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (9)")

                self._create_json_tables(connection, _DEPTH_CONTROL_JOB_TABLES)
                self._create_depth_control_job_indexes(connection)
                if 10 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (10)")

                self._create_json_tables(connection, _GENERATED_ARTIFACT_TABLES)
                self._create_generated_artifact_indexes(connection)
                if 11 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (11)")

                self._create_json_tables(connection, _MEDIA_STAGING_TABLES)
                self._create_media_staging_indexes(connection)
                if 12 not in applied_versions:
                    connection.execute("INSERT INTO schema_migrations (version) VALUES (12)")
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

    @staticmethod
    def _create_workspace_asset_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _WORKSPACE_ASSET_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608 - internal allowlist
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_viral_insight_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _VIRAL_INSIGHT_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608 - internal allowlist
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_project_asset_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _PROJECT_ASSET_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_quality_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _QUALITY_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_video_generation_draft_indexes(
        connection: sqlite3.Connection,
    ) -> None:
        for index_name, table, payload_field in _VIDEO_GENERATION_DRAFT_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_depth_control_job_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _DEPTH_CONTROL_JOB_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_generated_artifact_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _GENERATED_ARTIFACT_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
                f"ON {table} (json_extract(payload, '$.{payload_field}'))"
            )

    @staticmethod
    def _create_media_staging_indexes(connection: sqlite3.Connection) -> None:
        for index_name, table, payload_field in _MEDIA_STAGING_INDEXES:
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "  # noqa: S608
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
        return [payload for _, payload in self._read_all_entries(table)]

    def _read_all_entries(self, table: str) -> list[tuple[str, str]]:
        safe_table = self._table(table)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT record_key, payload FROM {safe_table} "  # noqa: S608
                "ORDER BY updated_at, record_key"
            ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    @staticmethod
    def _payload_value(payload: str, field: str) -> str | None:
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(decoded, dict):
            return None
        value = decoded.get(field)
        return str(value) if value is not None else None

    def _reset_production_shot_workflow(self, project_id: UUID) -> None:
        project_key = str(project_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                def keys_for(table: str, field: str, values: set[str]) -> set[str]:
                    if not values:
                        return set()
                    safe_table = self._table(table)
                    rows = connection.execute(
                        f"SELECT record_key, payload FROM {safe_table}"  # noqa: S608
                    ).fetchall()
                    return {
                        str(record_key)
                        for record_key, payload in rows
                        if self._payload_value(str(payload), field) in values
                    }

                shot_plan_ids = keys_for("shot_plans", "project_id", {project_key})
                generation_run_ids = keys_for(
                    "generation_runs",
                    "project_id",
                    {project_key},
                )
                deletions = {
                    "reference_bindings": keys_for(
                        "reference_bindings",
                        "shot_plan_id",
                        shot_plan_ids,
                    ),
                    "generation_candidates": keys_for(
                        "generation_candidates",
                        "generation_run_id",
                        generation_run_ids,
                    ),
                    "video_provider_tasks": keys_for(
                        "video_provider_tasks",
                        "generation_run_id",
                        generation_run_ids,
                    ),
                    "video_clip_preparations": keys_for(
                        "video_clip_preparations",
                        "project_id",
                        {project_key},
                    ),
                    "approval_events": keys_for(
                        "approval_events",
                        "project_id",
                        {project_key},
                    ),
                    "continuity_reports": keys_for(
                        "continuity_reports",
                        "project_id",
                        {project_key},
                    ),
                    "shot_video_generation_drafts": keys_for(
                        "shot_video_generation_drafts",
                        "project_id",
                        {project_key},
                    ),
                    "depth_control_jobs": keys_for(
                        "depth_control_jobs",
                        "project_id",
                        {project_key},
                    ),
                    "generation_runs": generation_run_ids,
                    "shot_plans": shot_plan_ids,
                }
                for table, record_keys in deletions.items():
                    safe_table = self._table(table)
                    connection.executemany(
                        f"DELETE FROM {safe_table} WHERE record_key = ?",  # noqa: S608
                        [(record_key,) for record_key in record_keys],
                    )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _count_production_projects_by_record(
        self,
        record_ids: list[UUID],
    ) -> dict[UUID, int]:
        if not record_ids:
            return {}
        placeholders = ", ".join("?" for _ in record_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT json_extract(payload, '$.record_id') AS record_id, COUNT(*) "
                "FROM production_projects "
                f"WHERE json_extract(payload, '$.record_id') IN ({placeholders}) "  # noqa: S608
                "GROUP BY record_id",
                tuple(str(record_id) for record_id in record_ids),
            ).fetchall()
        return {UUID(str(row[0])): int(row[1]) for row in rows}

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

    async def count_production_projects_by_record(
        self,
        record_ids: list[UUID],
    ) -> dict[UUID, int]:
        return await asyncio.to_thread(
            self._count_production_projects_by_record,
            record_ids,
        )

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

    async def save_storage_bundle(
        self,
        storage_object: StorageObject,
        replica: ObjectReplica,
    ) -> tuple[StorageObject, ObjectReplica]:
        entries = [
            ("storage_objects", str(storage_object.id), self._serialize(storage_object)),
            ("object_replicas", str(replica.id), self._serialize(replica)),
        ]
        async with self._lock:
            await asyncio.to_thread(self._upsert_many, entries)
        return storage_object, replica

    async def save_storage_object(self, storage_object: StorageObject) -> StorageObject:
        return await self._save("storage_objects", storage_object.id, storage_object)

    async def get_storage_object(self, object_id: UUID) -> StorageObject | None:
        return await self._get("storage_objects", object_id, StorageObject)

    async def list_storage_objects(self) -> list[StorageObject]:
        payloads = await asyncio.to_thread(self._read_all, "storage_objects")
        return [StorageObject.model_validate_json(payload) for payload in payloads]

    async def save_object_replica(self, replica: ObjectReplica) -> ObjectReplica:
        return await self._save("object_replicas", replica.id, replica)

    async def get_object_replica(self, replica_id: UUID) -> ObjectReplica | None:
        return await self._get("object_replicas", replica_id, ObjectReplica)

    async def list_object_replicas(self, object_id: UUID) -> list[ObjectReplica]:
        payloads = await asyncio.to_thread(self._read_all, "object_replicas")
        replicas = [ObjectReplica.model_validate_json(payload) for payload in payloads]
        return sorted(
            (item for item in replicas if item.storage_object_id == object_id),
            key=lambda item: item.created_at,
        )

    async def save_media_staging_config(
        self,
        config: MediaStagingConfig,
    ) -> MediaStagingConfig:
        return await self._save("media_staging_configs", config.account_id, config)

    async def get_media_staging_config(
        self,
        account_id: UUID,
    ) -> MediaStagingConfig | None:
        return await self._get("media_staging_configs", account_id, MediaStagingConfig)

    async def save_media_access_lease(
        self,
        lease: MediaAccessLease,
    ) -> MediaAccessLease:
        return await self._save("media_access_leases", lease.id, lease)

    async def list_media_access_leases(self) -> list[MediaAccessLease]:
        payloads = await asyncio.to_thread(self._read_all, "media_access_leases")
        leases = [MediaAccessLease.model_validate_json(payload) for payload in payloads]
        return sorted(leases, key=lambda item: item.created_at)

    async def save_asset_folder(self, folder: AssetFolder) -> AssetFolder:
        return await self._save("asset_folders", folder.id, folder)

    async def get_asset_folder(self, folder_id: UUID) -> AssetFolder | None:
        return await self._get("asset_folders", folder_id, AssetFolder)

    async def list_asset_folders(self) -> list[AssetFolder]:
        payloads = await asyncio.to_thread(self._read_all, "asset_folders")
        folders = [AssetFolder.model_validate_json(payload) for payload in payloads]
        return sorted(folders, key=lambda item: (item.sort_order, item.created_at))

    async def save_asset(self, asset: Asset) -> Asset:
        return await self._save("assets", asset.id, asset)

    async def get_asset(self, asset_id: UUID) -> Asset | None:
        return await self._get("assets", asset_id, Asset)

    async def list_assets(self) -> list[Asset]:
        payloads = await asyncio.to_thread(self._read_all, "assets")
        assets = [Asset.model_validate_json(payload) for payload in payloads]
        return sorted(assets, key=lambda item: item.created_at)

    async def save_generated_artifact(
        self, artifact: GeneratedArtifact
    ) -> GeneratedArtifact:
        return await self._save("generated_artifacts", artifact.id, artifact)

    async def get_generated_artifact(
        self, artifact_id: UUID
    ) -> GeneratedArtifact | None:
        return await self._get("generated_artifacts", artifact_id, GeneratedArtifact)

    async def list_generated_artifacts(self) -> list[GeneratedArtifact]:
        payloads = await asyncio.to_thread(self._read_all, "generated_artifacts")
        return sorted(
            (GeneratedArtifact.model_validate_json(payload) for payload in payloads),
            key=lambda item: item.created_at,
        )

    async def save_storage_object_reference(
        self, reference: StorageObjectReference
    ) -> StorageObjectReference:
        return await self._save("storage_object_references", reference.id, reference)

    async def list_storage_object_references(
        self, object_id: UUID | None = None
    ) -> list[StorageObjectReference]:
        payloads = await asyncio.to_thread(self._read_all, "storage_object_references")
        references = [StorageObjectReference.model_validate_json(item) for item in payloads]
        if object_id is not None:
            references = [item for item in references if item.storage_object_id == object_id]
        return sorted(references, key=lambda item: item.created_at)

    async def save_asset_provenance(
        self, provenance: AssetProvenance
    ) -> AssetProvenance:
        return await self._save("asset_provenance", provenance.asset_id, provenance)

    async def get_asset_provenance(self, asset_id: UUID) -> AssetProvenance | None:
        return await self._get("asset_provenance", asset_id, AssetProvenance)

    async def save_project_asset_link(self, link: ProjectAssetLink) -> ProjectAssetLink:
        return await self._save("project_asset_links", link.id, link)

    async def get_project_asset_link(self, link_id: UUID) -> ProjectAssetLink | None:
        return await self._get("project_asset_links", link_id, ProjectAssetLink)

    async def list_project_asset_links(
        self,
        project_id: UUID | None = None,
    ) -> list[ProjectAssetLink]:
        payloads = await asyncio.to_thread(self._read_all, "project_asset_links")
        links = [ProjectAssetLink.model_validate_json(payload) for payload in payloads]
        if project_id is not None:
            links = [item for item in links if item.project_id == project_id]
        return sorted(links, key=lambda item: item.created_at)

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
        video_clip_preparations: list[VideoClipPreparation] | None = None,
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
            ("video_clip_preparations", str(item.id), self._serialize(item))
            for item in video_clip_preparations or []
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
        payload = await asyncio.to_thread(self._read, "shot_plans", str(shot_plan_id))
        if payload is None:
            return None
        try:
            return ShotPlan.model_validate_json(payload)
        except ValidationError as exc:
            raw_project_id = self._payload_value(payload, "project_id")
            try:
                project_id = UUID(raw_project_id) if raw_project_id is not None else None
            except ValueError:
                project_id = None
            if project_id is None:
                raise
            raise IncompatibleShotPlanSchemaError(project_id) from exc

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]:
        entries = await asyncio.to_thread(self._read_all_entries, "shot_plans")
        payloads = [
            payload
            for _, payload in entries
            if self._payload_value(payload, "project_id") == str(project_id)
        ]
        try:
            shot_plans = [ShotPlan.model_validate_json(payload) for payload in payloads]
        except ValidationError as exc:
            raise IncompatibleShotPlanSchemaError(project_id) from exc
        return sorted(shot_plans, key=lambda shot_plan: shot_plan.index)

    async def reset_production_shot_workflow(self, project_id: UUID) -> None:
        async with self._lock:
            await asyncio.to_thread(self._reset_production_shot_workflow, project_id)

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

    async def save_depth_control_job(self, job: DepthControlJob) -> DepthControlJob:
        return await self._save("depth_control_jobs", job.id, job)

    async def get_depth_control_job(self, job_id: UUID) -> DepthControlJob | None:
        return await self._get("depth_control_jobs", job_id, DepthControlJob)

    async def list_depth_control_jobs(
        self,
        *,
        project_id: UUID | None = None,
        shot_plan_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[DepthControlJob]:
        payloads = await asyncio.to_thread(self._read_all, "depth_control_jobs")
        jobs = [DepthControlJob.model_validate_json(payload) for payload in payloads]
        if project_id is not None:
            jobs = [item for item in jobs if item.project_id == project_id]
        if shot_plan_id is not None:
            jobs = [item for item in jobs if item.shot_plan_id == shot_plan_id]
        if active_only:
            jobs = [item for item in jobs if item.status in ACTIVE_DEPTH_JOB_STATUSES]
        return sorted(jobs, key=lambda item: item.created_at)

    def _claim_depth_control_job(self, job_id: UUID) -> DepthControlJob | None:
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT payload FROM depth_control_jobs WHERE record_key = ?",
                    (str(job_id),),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                job = DepthControlJob.model_validate_json(str(row[0]))
                if job.status != DepthControlJobStatus.QUEUED:
                    connection.commit()
                    return None
                claimed = job.model_copy(
                    update={
                        "status": DepthControlJobStatus.RUNNING,
                        "started_at": job.started_at or now,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "progress_message": "正在准备深度生成",
                    }
                )
                connection.execute(
                    "UPDATE depth_control_jobs SET payload = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE record_key = ?",
                    (self._serialize(claimed), str(job_id)),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
                return claimed

    async def claim_depth_control_job(
        self,
        job_id: UUID,
    ) -> DepthControlJob | None:
        async with self._lock:
            return await asyncio.to_thread(self._claim_depth_control_job, job_id)

    def _claim_generation_run(
        self,
        run_id: UUID,
        claimed_at: datetime,
    ) -> GenerationRun | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT payload FROM generation_runs WHERE record_key = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                run = GenerationRun.model_validate_json(str(row[0]))
                if run.status != ProductionRunStatus.QUEUED:
                    connection.commit()
                    return None
                claimed = run.model_copy(
                    update={
                        "status": ProductionRunStatus.RUNNING,
                        "started_at": run.started_at or claimed_at,
                        "updated_at": claimed_at,
                        "last_heartbeat_at": claimed_at,
                    }
                )
                connection.execute(
                    "UPDATE generation_runs SET payload = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE record_key = ?",
                    (self._serialize(claimed), str(run_id)),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
                return claimed

    async def claim_generation_run(
        self,
        run_id: UUID,
        claimed_at: datetime,
    ) -> GenerationRun | None:
        async with self._lock:
            return await asyncio.to_thread(
                self._claim_generation_run,
                run_id,
                claimed_at,
            )

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

    def _compare_and_swap_video_generation_draft(
        self,
        draft: ShotVideoGenerationDraft,
        expected_draft_version: int,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT payload FROM shot_video_generation_drafts "
                    "WHERE record_key = ?",
                    (str(draft.shot_plan_id),),
                ).fetchone()
                current_version = 0
                if row is not None:
                    current = ShotVideoGenerationDraft.model_validate_json(str(row[0]))
                    current_version = current.draft_version
                if current_version != expected_draft_version:
                    connection.rollback()
                    return False
                connection.execute(
                    "INSERT INTO shot_video_generation_drafts "
                    "(record_key, payload, updated_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(record_key) DO UPDATE SET "
                    "payload = excluded.payload, updated_at = CURRENT_TIMESTAMP",
                    (str(draft.shot_plan_id), self._serialize(draft)),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
                return True

    async def get_video_generation_draft(
        self,
        shot_plan_id: UUID,
    ) -> ShotVideoGenerationDraft | None:
        return await self._get(
            "shot_video_generation_drafts",
            shot_plan_id,
            ShotVideoGenerationDraft,
        )

    async def compare_and_swap_video_generation_draft(
        self,
        draft: ShotVideoGenerationDraft,
        expected_draft_version: int,
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._compare_and_swap_video_generation_draft,
                draft,
                expected_draft_version,
            )

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

    async def list_generation_candidates_by_run_ids(
        self,
        generation_run_ids: set[UUID],
    ) -> list[GenerationCandidate]:
        if not generation_run_ids:
            return []
        payloads = await asyncio.to_thread(self._read_all, "generation_candidates")
        candidates = [GenerationCandidate.model_validate_json(payload) for payload in payloads]
        return sorted(
            (
                candidate
                for candidate in candidates
                if candidate.generation_run_id in generation_run_ids
            ),
            key=lambda candidate: (candidate.created_at, candidate.ordinal),
        )

    async def save_video_clip_preparation(
        self,
        preparation: VideoClipPreparation,
    ) -> VideoClipPreparation:
        return await self._save("video_clip_preparations", preparation.id, preparation)

    async def get_video_clip_preparation(
        self,
        shot_plan_id: UUID,
    ) -> VideoClipPreparation | None:
        payloads = await asyncio.to_thread(self._read_all, "video_clip_preparations")
        preparations = [VideoClipPreparation.model_validate_json(payload) for payload in payloads]
        return next(
            (item for item in preparations if item.shot_plan_id == shot_plan_id),
            None,
        )

    async def list_video_clip_preparations(
        self,
        project_id: UUID,
    ) -> list[VideoClipPreparation]:
        payloads = await asyncio.to_thread(self._read_all, "video_clip_preparations")
        preparations = [VideoClipPreparation.model_validate_json(payload) for payload in payloads]
        return sorted(
            (item for item in preparations if item.project_id == project_id),
            key=lambda item: item.created_at,
        )

    async def save_video_provider_task(self, task: VideoProviderTask) -> VideoProviderTask:
        return await self._save("video_provider_tasks", task.id, task)

    async def get_video_provider_task(self, task_id: UUID) -> VideoProviderTask | None:
        return await self._get("video_provider_tasks", task_id, VideoProviderTask)

    async def list_video_provider_tasks(
        self,
        generation_run_id: UUID,
    ) -> list[VideoProviderTask]:
        payloads = await asyncio.to_thread(self._read_all, "video_provider_tasks")
        tasks = [VideoProviderTask.model_validate_json(payload) for payload in payloads]
        return sorted(
            (item for item in tasks if item.generation_run_id == generation_run_id),
            key=lambda item: item.ordinal,
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

    async def save_continuity_report(
        self,
        report: ContinuityReport,
    ) -> ContinuityReport:
        return await self._save("continuity_reports", report.id, report)

    async def get_continuity_report(
        self,
        report_id: UUID,
    ) -> ContinuityReport | None:
        return await self._get("continuity_reports", report_id, ContinuityReport)

    async def list_continuity_reports(
        self,
        project_id: UUID,
    ) -> list[ContinuityReport]:
        payloads = await asyncio.to_thread(self._read_all, "continuity_reports")
        reports = [ContinuityReport.model_validate_json(payload) for payload in payloads]
        return sorted(
            (report for report in reports if report.project_id == project_id),
            key=lambda report: report.created_at,
        )

    async def save_viral_insight(
        self,
        report: ViralInsightReport,
    ) -> ViralInsightReport:
        return await self._save("viral_insights", report.analysis_id, report)

    async def get_viral_insight(
        self,
        analysis_id: UUID,
    ) -> ViralInsightReport | None:
        return await self._get("viral_insights", analysis_id, ViralInsightReport)

    async def save_viral_concept_set(
        self,
        concepts: ViralConceptSet,
    ) -> ViralConceptSet:
        return await self._save("viral_concept_sets", concepts.id, concepts)

    async def get_viral_concept_set(
        self,
        concept_set_id: UUID,
    ) -> ViralConceptSet | None:
        return await self._get("viral_concept_sets", concept_set_id, ViralConceptSet)

    async def list_viral_concept_sets(
        self,
        analysis_id: UUID,
    ) -> list[ViralConceptSet]:
        payloads = await asyncio.to_thread(self._read_all, "viral_concept_sets")
        items = [ViralConceptSet.model_validate_json(payload) for payload in payloads]
        return sorted(
            (item for item in items if item.analysis_id == analysis_id),
            key=lambda item: item.created_at,
        )
