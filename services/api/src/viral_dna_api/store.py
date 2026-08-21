from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .asset_library import Asset, AssetFolder
from .chinese import simplify_model
from .control_assets.jobs.domain import (
    ACTIVE_DEPTH_JOB_STATUSES,
    DepthControlJob,
    DepthControlJobStatus,
)
from .exports import archive_report
from .generated_artifacts.domain import (
    AssetProvenance,
    GeneratedArtifact,
    StorageObjectReference,
)
from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
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
    VideoStatus,
)
from .quality.contracts import ContinuityReport
from .storage_objects import ObjectReplica, StorageObject
from .viral_insights.contracts import ViralConceptSet, ViralInsightReport
from .workspace import WorkspaceError, workspace_manager


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryStore:
    """Repository used by tests while preserving the durable-store contract."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.videos: dict[UUID, Video] = {}
        self.analyses: dict[UUID, AnalysisJob] = {}
        self.reports: dict[UUID, AnalysisReport] = {}
        self.reports_by_analysis: dict[UUID, AnalysisReport] = {}
        self.replacements: dict[UUID, ReplacementVersion] = {}
        self.model_runs: dict[UUID, ModelRun] = {}
        self.price_snapshots: dict[str, PriceSnapshot] = {}
        self.folders: dict[UUID, RecordFolder] = {}
        self.records: dict[UUID, AnalysisRecord] = {}
        self.exports: dict[UUID, ExportArtifact] = {}
        self.production_projects: dict[UUID, ProductionProject] = {}
        self.production_revisions: dict[UUID, ProductionRevision] = {}
        self.reference_assets: dict[UUID, ReferenceAsset] = {}
        self.shot_plans: dict[UUID, ShotPlan] = {}
        self.reference_bindings: dict[UUID, ReferenceBinding] = {}
        self.generation_runs: dict[UUID, GenerationRun] = {}
        self.generation_candidates: dict[UUID, GenerationCandidate] = {}
        self.video_provider_tasks: dict[UUID, VideoProviderTask] = {}
        self.video_clip_preparations: dict[UUID, VideoClipPreparation] = {}
        self.approval_events: dict[UUID, ApprovalEvent] = {}
        self.storage_objects: dict[UUID, StorageObject] = {}
        self.object_replicas: dict[UUID, ObjectReplica] = {}
        self.asset_folders: dict[UUID, AssetFolder] = {}
        self.assets: dict[UUID, Asset] = {}
        self.project_asset_links: dict[UUID, ProjectAssetLink] = {}
        self.continuity_reports: dict[UUID, ContinuityReport] = {}
        self.viral_insights: dict[UUID, ViralInsightReport] = {}
        self.viral_concept_sets: dict[UUID, ViralConceptSet] = {}
        self.shot_video_generation_drafts: dict[UUID, ShotVideoGenerationDraft] = {}
        self.depth_control_jobs: dict[UUID, DepthControlJob] = {}
        self.generated_artifacts: dict[UUID, GeneratedArtifact] = {}
        self.storage_object_references: dict[UUID, StorageObjectReference] = {}
        self.asset_provenance: dict[UUID, AssetProvenance] = {}

    async def add_video(self, video: Video) -> Video:
        async with self._lock:
            self.videos[video.id] = video
        return video

    async def get_video(self, video_id: UUID) -> Video | None:
        return self.videos.get(video_id)

    async def save_video(self, video: Video) -> Video:
        async with self._lock:
            self.videos[video.id] = video
        return video

    async def list_videos(self) -> list[Video]:
        return list(self.videos.values())

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        async with self._lock:
            self.analyses[analysis.id] = analysis
        return analysis

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None:
        return self.analyses.get(analysis_id)

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        async with self._lock:
            self.analyses[analysis.id] = analysis
        return analysis

    async def list_analyses(self) -> list[AnalysisJob]:
        return list(self.analyses.values())

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        async with self._lock:
            self.reports[report.video_id] = report
            self.reports_by_analysis[report.analysis_id] = report
        return report

    async def get_report(self, video_id: UUID) -> AnalysisReport | None:
        return self.reports.get(video_id)

    async def get_report_by_analysis(self, analysis_id: UUID) -> AnalysisReport | None:
        return self.reports_by_analysis.get(analysis_id)

    async def list_report_versions(self) -> list[AnalysisReport]:
        return list(self.reports_by_analysis.values())

    async def save_folder(self, folder: RecordFolder) -> RecordFolder:
        async with self._lock:
            self.folders[folder.id] = folder
        return folder

    async def get_folder(self, folder_id: UUID) -> RecordFolder | None:
        return self.folders.get(folder_id)

    async def list_folders(self) -> list[RecordFolder]:
        return list(self.folders.values())

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord:
        async with self._lock:
            self.records[record.id] = record
        return record

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None:
        return self.records.get(record_id)

    async def list_records(self) -> list[AnalysisRecord]:
        return list(self.records.values())

    async def save_export(self, artifact: ExportArtifact) -> ExportArtifact:
        async with self._lock:
            self.exports[artifact.id] = artifact
        return artifact

    async def get_export(self, export_id: UUID) -> ExportArtifact | None:
        return self.exports.get(export_id)

    async def list_exports(self, record_id: UUID | None = None) -> list[ExportArtifact]:
        artifacts = list(self.exports.values())
        if record_id is None:
            return artifacts
        return [artifact for artifact in artifacts if artifact.record_id == record_id]

    async def save_replacement(self, version: ReplacementVersion) -> ReplacementVersion:
        async with self._lock:
            self.replacements[version.id] = version
        return version

    async def get_replacement(self, version_id: UUID) -> ReplacementVersion | None:
        return self.replacements.get(version_id)

    async def save_model_run(self, run: ModelRun) -> ModelRun:
        async with self._lock:
            self.model_runs[run.id] = run
        return run

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]:
        return sorted(
            (run for run in self.model_runs.values() if run.analysis_id == analysis_id),
            key=lambda run: run.created_at,
        )

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None:
        candidates = [
            run
            for run in self.model_runs.values()
            if run.request_fingerprint == request_fingerprint
            and run.status == ModelRunStatus.COMPLETED
            and run.result_payload is not None
        ]
        return max(candidates, key=lambda run: run.completed_at or run.created_at, default=None)

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot:
        async with self._lock:
            self.price_snapshots[snapshot.id] = snapshot
        return snapshot

    async def get_price_snapshot(self, snapshot_id: str) -> PriceSnapshot | None:
        return self.price_snapshots.get(snapshot_id)

    async def save_production_project(
        self,
        project: ProductionProject,
    ) -> ProductionProject:
        async with self._lock:
            self.production_projects[project.id] = project
        return project

    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None:
        return self.production_projects.get(project_id)

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]:
        projects = list(self.production_projects.values())
        if record_id is not None:
            projects = [project for project in projects if project.record_id == record_id]
        return sorted(projects, key=lambda project: project.created_at)

    async def delete_production_project(self, project_id: UUID) -> None:
        async with self._lock:
            shot_plan_ids = {
                item.id for item in self.shot_plans.values() if item.project_id == project_id
            }
            generation_run_ids = {
                item.id for item in self.generation_runs.values() if item.project_id == project_id
            }
            self.reference_bindings = {
                key: item
                for key, item in self.reference_bindings.items()
                if item.shot_plan_id not in shot_plan_ids
            }
            self.generation_candidates = {
                key: item
                for key, item in self.generation_candidates.items()
                if item.generation_run_id not in generation_run_ids
            }
            self.video_provider_tasks = {
                key: item
                for key, item in self.video_provider_tasks.items()
                if item.generation_run_id not in generation_run_ids
            }
            self.production_revisions = {
                key: item
                for key, item in self.production_revisions.items()
                if item.project_id != project_id
            }
            self.reference_assets = {
                key: item
                for key, item in self.reference_assets.items()
                if item.project_id != project_id
            }
            self.shot_plans = {
                key: item
                for key, item in self.shot_plans.items()
                if item.project_id != project_id
            }
            self.generation_runs = {
                key: item
                for key, item in self.generation_runs.items()
                if item.project_id != project_id
            }
            self.video_clip_preparations = {
                key: item
                for key, item in self.video_clip_preparations.items()
                if item.project_id != project_id
            }
            self.approval_events = {
                key: item
                for key, item in self.approval_events.items()
                if item.project_id != project_id
            }
            self.project_asset_links = {
                key: item
                for key, item in self.project_asset_links.items()
                if item.project_id != project_id
            }
            self.continuity_reports = {
                key: item
                for key, item in self.continuity_reports.items()
                if item.project_id != project_id
            }
            self.shot_video_generation_drafts = {
                key: item
                for key, item in self.shot_video_generation_drafts.items()
                if item.project_id != project_id
            }
            self.depth_control_jobs = {
                key: item
                for key, item in self.depth_control_jobs.items()
                if item.project_id != project_id
            }
            self.production_projects.pop(project_id, None)

    async def count_production_projects_by_record(
        self,
        record_ids: list[UUID],
    ) -> dict[UUID, int]:
        selected_ids = set(record_ids)
        counts = {record_id: 0 for record_id in selected_ids}
        for project in self.production_projects.values():
            if project.record_id in selected_ids and project.trashed_at is None:
                counts[project.record_id] += 1
        return counts

    async def save_production_revision(
        self,
        revision: ProductionRevision,
    ) -> ProductionRevision:
        async with self._lock:
            self.production_revisions[revision.id] = revision
        return revision

    async def get_production_revision(
        self,
        revision_id: UUID,
    ) -> ProductionRevision | None:
        return self.production_revisions.get(revision_id)

    async def list_production_revisions(
        self,
        project_id: UUID,
    ) -> list[ProductionRevision]:
        return sorted(
            (
                revision
                for revision in self.production_revisions.values()
                if revision.project_id == project_id
            ),
            key=lambda revision: revision.revision_number,
        )

    async def save_reference_asset(self, asset: ReferenceAsset) -> ReferenceAsset:
        async with self._lock:
            self.reference_assets[asset.id] = asset
        return asset

    async def get_reference_asset(self, asset_id: UUID) -> ReferenceAsset | None:
        return self.reference_assets.get(asset_id)

    async def save_storage_bundle(
        self,
        storage_object: StorageObject,
        replica: ObjectReplica,
    ) -> tuple[StorageObject, ObjectReplica]:
        async with self._lock:
            self.storage_objects[storage_object.id] = storage_object
            self.object_replicas[replica.id] = replica
        return storage_object, replica

    async def save_storage_object(self, storage_object: StorageObject) -> StorageObject:
        async with self._lock:
            self.storage_objects[storage_object.id] = storage_object
        return storage_object

    async def get_storage_object(self, object_id: UUID) -> StorageObject | None:
        return self.storage_objects.get(object_id)

    async def list_storage_objects(self) -> list[StorageObject]:
        return list(self.storage_objects.values())

    async def save_object_replica(self, replica: ObjectReplica) -> ObjectReplica:
        async with self._lock:
            self.object_replicas[replica.id] = replica
        return replica

    async def get_object_replica(self, replica_id: UUID) -> ObjectReplica | None:
        return self.object_replicas.get(replica_id)

    async def list_object_replicas(self, object_id: UUID) -> list[ObjectReplica]:
        return sorted(
            (
                replica
                for replica in self.object_replicas.values()
                if replica.storage_object_id == object_id
            ),
            key=lambda replica: replica.created_at,
        )

    async def save_asset_folder(self, folder: AssetFolder) -> AssetFolder:
        async with self._lock:
            self.asset_folders[folder.id] = folder
        return folder

    async def get_asset_folder(self, folder_id: UUID) -> AssetFolder | None:
        return self.asset_folders.get(folder_id)

    async def list_asset_folders(self) -> list[AssetFolder]:
        return sorted(
            self.asset_folders.values(),
            key=lambda folder: (folder.sort_order, folder.created_at),
        )

    async def save_asset(self, asset: Asset) -> Asset:
        async with self._lock:
            self.assets[asset.id] = asset
        return asset

    async def get_asset(self, asset_id: UUID) -> Asset | None:
        return self.assets.get(asset_id)

    async def list_assets(self) -> list[Asset]:
        return sorted(self.assets.values(), key=lambda asset: asset.created_at)

    async def save_generated_artifact(
        self, artifact: GeneratedArtifact
    ) -> GeneratedArtifact:
        async with self._lock:
            self.generated_artifacts[artifact.id] = artifact
        return artifact

    async def get_generated_artifact(
        self, artifact_id: UUID
    ) -> GeneratedArtifact | None:
        return self.generated_artifacts.get(artifact_id)

    async def list_generated_artifacts(self) -> list[GeneratedArtifact]:
        return sorted(self.generated_artifacts.values(), key=lambda item: item.created_at)

    async def save_storage_object_reference(
        self, reference: StorageObjectReference
    ) -> StorageObjectReference:
        async with self._lock:
            self.storage_object_references[reference.id] = reference
        return reference

    async def list_storage_object_references(
        self, object_id: UUID | None = None
    ) -> list[StorageObjectReference]:
        references = list(self.storage_object_references.values())
        if object_id is not None:
            references = [item for item in references if item.storage_object_id == object_id]
        return sorted(references, key=lambda item: item.created_at)

    async def save_asset_provenance(
        self, provenance: AssetProvenance
    ) -> AssetProvenance:
        async with self._lock:
            self.asset_provenance[provenance.asset_id] = provenance
        return provenance

    async def get_asset_provenance(self, asset_id: UUID) -> AssetProvenance | None:
        return self.asset_provenance.get(asset_id)

    async def save_project_asset_link(self, link: ProjectAssetLink) -> ProjectAssetLink:
        async with self._lock:
            self.project_asset_links[link.id] = link
        return link

    async def get_project_asset_link(self, link_id: UUID) -> ProjectAssetLink | None:
        return self.project_asset_links.get(link_id)

    async def list_project_asset_links(
        self,
        project_id: UUID | None = None,
    ) -> list[ProjectAssetLink]:
        links = list(self.project_asset_links.values())
        if project_id is not None:
            links = [item for item in links if item.project_id == project_id]
        return sorted(links, key=lambda item: item.created_at)

    async def list_reference_assets(self, project_id: UUID) -> list[ReferenceAsset]:
        return sorted(
            (asset for asset in self.reference_assets.values() if asset.project_id == project_id),
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
        async with self._lock:
            self.production_projects[project.id] = project
            self.production_revisions[revision.id] = revision
            for asset in reference_assets or []:
                self.reference_assets[asset.id] = asset
            for shot_plan in shot_plans or []:
                self.shot_plans[shot_plan.id] = shot_plan
            for binding in reference_bindings or []:
                self.reference_bindings[binding.id] = binding
            for binding_id in remove_reference_binding_ids or []:
                self.reference_bindings.pop(binding_id, None)
            for run in generation_runs or []:
                self.generation_runs[run.id] = run
            for candidate in generation_candidates or []:
                self.generation_candidates[candidate.id] = candidate
            for preparation in video_clip_preparations or []:
                self.video_clip_preparations[preparation.id] = preparation
            for event in approval_events or []:
                self.approval_events[event.id] = event
        return project, revision

    async def save_shot_plan(self, shot_plan: ShotPlan) -> ShotPlan:
        async with self._lock:
            self.shot_plans[shot_plan.id] = shot_plan
        return shot_plan

    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None:
        return self.shot_plans.get(shot_plan_id)

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]:
        return sorted(
            (
                shot_plan
                for shot_plan in self.shot_plans.values()
                if shot_plan.project_id == project_id
            ),
            key=lambda shot_plan: shot_plan.index,
        )

    async def reset_production_shot_workflow(self, project_id: UUID) -> None:
        async with self._lock:
            shot_plan_ids = {
                item.id for item in self.shot_plans.values() if item.project_id == project_id
            }
            generation_run_ids = {
                item.id for item in self.generation_runs.values() if item.project_id == project_id
            }
            self.reference_bindings = {
                key: item
                for key, item in self.reference_bindings.items()
                if item.shot_plan_id not in shot_plan_ids
            }
            self.generation_candidates = {
                key: item
                for key, item in self.generation_candidates.items()
                if item.generation_run_id not in generation_run_ids
            }
            self.video_provider_tasks = {
                key: item
                for key, item in self.video_provider_tasks.items()
                if item.generation_run_id not in generation_run_ids
            }
            self.generation_runs = {
                key: item
                for key, item in self.generation_runs.items()
                if item.project_id != project_id
            }
            self.video_clip_preparations = {
                key: item
                for key, item in self.video_clip_preparations.items()
                if item.project_id != project_id
            }
            self.approval_events = {
                key: item
                for key, item in self.approval_events.items()
                if item.project_id != project_id
            }
            self.continuity_reports = {
                key: item
                for key, item in self.continuity_reports.items()
                if item.project_id != project_id
            }
            self.shot_video_generation_drafts = {
                key: item
                for key, item in self.shot_video_generation_drafts.items()
                if item.project_id != project_id
            }
            self.depth_control_jobs = {
                key: item
                for key, item in self.depth_control_jobs.items()
                if item.project_id != project_id
            }
            self.shot_plans = {
                key: item
                for key, item in self.shot_plans.items()
                if item.project_id != project_id
            }

    async def save_reference_binding(
        self,
        binding: ReferenceBinding,
    ) -> ReferenceBinding:
        async with self._lock:
            self.reference_bindings[binding.id] = binding
        return binding

    async def get_reference_binding(
        self,
        binding_id: UUID,
    ) -> ReferenceBinding | None:
        return self.reference_bindings.get(binding_id)

    async def list_reference_bindings(
        self,
        shot_plan_id: UUID,
    ) -> list[ReferenceBinding]:
        return sorted(
            (
                binding
                for binding in self.reference_bindings.values()
                if binding.shot_plan_id == shot_plan_id
            ),
            key=lambda binding: binding.created_at,
        )

    async def save_generation_run(self, run: GenerationRun) -> GenerationRun:
        async with self._lock:
            self.generation_runs[run.id] = run
        return run

    async def save_depth_control_job(self, job: DepthControlJob) -> DepthControlJob:
        async with self._lock:
            self.depth_control_jobs[job.id] = job
        return job

    async def get_depth_control_job(self, job_id: UUID) -> DepthControlJob | None:
        return self.depth_control_jobs.get(job_id)

    async def list_depth_control_jobs(
        self,
        *,
        project_id: UUID | None = None,
        shot_plan_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[DepthControlJob]:
        jobs = list(self.depth_control_jobs.values())
        if project_id is not None:
            jobs = [item for item in jobs if item.project_id == project_id]
        if shot_plan_id is not None:
            jobs = [item for item in jobs if item.shot_plan_id == shot_plan_id]
        if active_only:
            jobs = [item for item in jobs if item.status in ACTIVE_DEPTH_JOB_STATUSES]
        return sorted(jobs, key=lambda item: item.created_at)

    async def claim_depth_control_job(
        self,
        job_id: UUID,
    ) -> DepthControlJob | None:
        async with self._lock:
            job = self.depth_control_jobs.get(job_id)
            if job is None or job.status != DepthControlJobStatus.QUEUED:
                return None
            now = _utc_now()
            claimed = job.model_copy(
                update={
                    "status": DepthControlJobStatus.RUNNING,
                    "started_at": job.started_at or now,
                    "heartbeat_at": now,
                    "updated_at": now,
                    "progress_message": "正在准备深度生成",
                }
            )
            self.depth_control_jobs[job_id] = claimed
            return claimed

    async def claim_generation_run(
        self,
        run_id: UUID,
        claimed_at: datetime,
    ) -> GenerationRun | None:
        async with self._lock:
            run = self.generation_runs.get(run_id)
            if run is None or run.status != ProductionRunStatus.QUEUED:
                return None
            claimed = run.model_copy(
                update={
                    "status": ProductionRunStatus.RUNNING,
                    "started_at": run.started_at or claimed_at,
                    "updated_at": claimed_at,
                    "last_heartbeat_at": claimed_at,
                }
            )
            self.generation_runs[run_id] = claimed
            return claimed

    async def get_generation_run(self, run_id: UUID) -> GenerationRun | None:
        return self.generation_runs.get(run_id)

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]:
        runs = [run for run in self.generation_runs.values() if run.project_id == project_id]
        if shot_plan_id is not None:
            runs = [run for run in runs if run.shot_plan_id == shot_plan_id]
        return sorted(runs, key=lambda run: run.created_at)

    async def get_video_generation_draft(
        self,
        shot_plan_id: UUID,
    ) -> ShotVideoGenerationDraft | None:
        return self.shot_video_generation_drafts.get(shot_plan_id)

    async def compare_and_swap_video_generation_draft(
        self,
        draft: ShotVideoGenerationDraft,
        expected_draft_version: int,
    ) -> bool:
        async with self._lock:
            current = self.shot_video_generation_drafts.get(draft.shot_plan_id)
            current_version = current.draft_version if current is not None else 0
            if current_version != expected_draft_version:
                return False
            self.shot_video_generation_drafts[draft.shot_plan_id] = draft
            return True

    async def save_generation_candidate(
        self,
        candidate: GenerationCandidate,
    ) -> GenerationCandidate:
        async with self._lock:
            self.generation_candidates[candidate.id] = candidate
        return candidate

    async def get_generation_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate | None:
        return self.generation_candidates.get(candidate_id)

    async def list_generation_candidates(
        self,
        generation_run_id: UUID,
    ) -> list[GenerationCandidate]:
        return sorted(
            (
                candidate
                for candidate in self.generation_candidates.values()
                if candidate.generation_run_id == generation_run_id
            ),
            key=lambda candidate: candidate.ordinal,
        )

    async def list_generation_candidates_by_run_ids(
        self,
        generation_run_ids: set[UUID],
    ) -> list[GenerationCandidate]:
        return sorted(
            (
                candidate
                for candidate in self.generation_candidates.values()
                if candidate.generation_run_id in generation_run_ids
            ),
            key=lambda candidate: (candidate.created_at, candidate.ordinal),
        )

    async def save_video_clip_preparation(
        self,
        preparation: VideoClipPreparation,
    ) -> VideoClipPreparation:
        async with self._lock:
            self.video_clip_preparations[preparation.id] = preparation
        return preparation

    async def get_video_clip_preparation(
        self,
        shot_plan_id: UUID,
    ) -> VideoClipPreparation | None:
        return next(
            (
                item
                for item in self.video_clip_preparations.values()
                if item.shot_plan_id == shot_plan_id
            ),
            None,
        )

    async def list_video_clip_preparations(
        self,
        project_id: UUID,
    ) -> list[VideoClipPreparation]:
        return sorted(
            (
                item
                for item in self.video_clip_preparations.values()
                if item.project_id == project_id
            ),
            key=lambda item: item.created_at,
        )

    async def save_video_provider_task(self, task: VideoProviderTask) -> VideoProviderTask:
        async with self._lock:
            self.video_provider_tasks[task.id] = task
        return task

    async def get_video_provider_task(self, task_id: UUID) -> VideoProviderTask | None:
        return self.video_provider_tasks.get(task_id)

    async def list_video_provider_tasks(
        self,
        generation_run_id: UUID,
    ) -> list[VideoProviderTask]:
        return sorted(
            (
                item
                for item in self.video_provider_tasks.values()
                if item.generation_run_id == generation_run_id
            ),
            key=lambda item: item.ordinal,
        )

    async def save_approval_event(self, event: ApprovalEvent) -> ApprovalEvent:
        async with self._lock:
            self.approval_events[event.id] = event
        return event

    async def get_approval_event(self, event_id: UUID) -> ApprovalEvent | None:
        return self.approval_events.get(event_id)

    async def list_approval_events(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[ApprovalEvent]:
        events = [
            event for event in self.approval_events.values() if event.project_id == project_id
        ]
        if shot_plan_id is not None:
            events = [event for event in events if event.shot_plan_id == shot_plan_id]
        return sorted(events, key=lambda event: event.created_at)

    async def save_continuity_report(
        self,
        report: ContinuityReport,
    ) -> ContinuityReport:
        async with self._lock:
            self.continuity_reports[report.id] = report
        return report

    async def get_continuity_report(
        self,
        report_id: UUID,
    ) -> ContinuityReport | None:
        return self.continuity_reports.get(report_id)

    async def list_continuity_reports(
        self,
        project_id: UUID,
    ) -> list[ContinuityReport]:
        return sorted(
            (
                report
                for report in self.continuity_reports.values()
                if report.project_id == project_id
            ),
            key=lambda report: report.created_at,
        )

    async def save_viral_insight(
        self,
        report: ViralInsightReport,
    ) -> ViralInsightReport:
        async with self._lock:
            self.viral_insights[report.analysis_id] = report
        return report

    async def get_viral_insight(
        self,
        analysis_id: UUID,
    ) -> ViralInsightReport | None:
        return self.viral_insights.get(analysis_id)

    async def save_viral_concept_set(
        self,
        concepts: ViralConceptSet,
    ) -> ViralConceptSet:
        async with self._lock:
            self.viral_concept_sets[concepts.id] = concepts
        return concepts

    async def get_viral_concept_set(
        self,
        concept_set_id: UUID,
    ) -> ViralConceptSet | None:
        return self.viral_concept_sets.get(concept_set_id)

    async def list_viral_concept_sets(
        self,
        analysis_id: UUID,
    ) -> list[ViralConceptSet]:
        return sorted(
            (
                item
                for item in self.viral_concept_sets.values()
                if item.analysis_id == analysis_id
            ),
            key=lambda item: item.created_at,
        )


class WorkspaceStore:
    """Stable repository proxy whose backend follows the active workspace."""

    def __init__(self) -> None:
        self._memory_mode = os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory"
        self._switch_lock = asyncio.Lock()
        self._backend = self._new_backend(workspace_manager.database_path)

    def _new_backend(self, database_path: Path):
        if self._memory_mode:
            return InMemoryStore()
        from .sqlite_store import SQLiteStore

        return SQLiteStore(database_path)

    @property
    def backend(self):
        return self._backend

    def __getattr__(self, name: str):
        return getattr(self._backend, name)

    async def switch_workspace(self, path: str) -> None:
        async with self._switch_lock:
            analyses = await self._backend.list_analyses()
            active = [
                analysis
                for analysis in analyses
                if analysis.stage not in {AnalysisStage.COMPLETED, AnalysisStage.FAILED}
            ]
            if active:
                raise WorkspaceError("有分析任务正在运行，完成后才能切换工作区")
            candidate = workspace_manager.normalize(path)
            prepared = workspace_manager.initialize(candidate)
            backend = self._new_backend(prepared.database)
            workspace_manager.activate(candidate, persist=True)
            self._backend = backend

    async def add_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        saved = await self._backend.add_analysis(analysis)
        await self._sync_record_from_analysis(saved)
        return saved

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob:
        saved = await self._backend.save_analysis(analysis)
        await self._sync_record_from_analysis(saved)
        return saved

    async def save_video(self, video: Video) -> Video:
        saved = await self._backend.save_video(video)
        if video.record_id is not None:
            record = await self._backend.get_record(video.record_id)
            if record is not None and record.status != video.status:
                record.status = video.status
                record.updated_at = _utc_now()
                await self._backend.save_record(record)
        return saved

    async def save_report(self, report: AnalysisReport) -> AnalysisReport:
        simplified = simplify_model(report)
        saved = await self._backend.save_report(simplified)
        analysis = await self._backend.get_analysis(report.analysis_id)
        if analysis is not None and analysis.record_id is not None:
            await archive_report(analysis.record_id, simplified)
        return saved

    async def _sync_record_from_analysis(self, analysis: AnalysisJob) -> None:
        if analysis.record_id is None:
            return
        record = await self._backend.get_record(analysis.record_id)
        if record is None:
            return
        if analysis.stage == AnalysisStage.COMPLETED:
            next_status = VideoStatus.COMPLETED
        elif analysis.stage == AnalysisStage.FAILED:
            next_status = VideoStatus.FAILED
        else:
            next_status = VideoStatus.ANALYZING
        if record.latest_analysis_id == analysis.id and record.status == next_status:
            return
        record.latest_analysis_id = analysis.id
        record.status = next_status
        record.updated_at = max(record.updated_at, analysis.updated_at)
        await self._backend.save_record(record)


def create_store() -> WorkspaceStore:
    return WorkspaceStore()


store = create_store()
