from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from ..models import AnalysisRecord, ProductionProject, Video, VideoStatus
from ..platform_skills import PlatformSkillCatalogService, PlatformSkillError
from ..platform_skills.contracts import SkillLifecycle, SkillVersionSnapshot
from ..workspace_catalog import AccountContextService
from .contracts import (
    AnalysisProjectSource,
    Project,
    ProjectBatchMutationResponse,
    ProjectCreate,
    ProjectKind,
    ProjectLifecycle,
    ProjectLifecycleAction,
    ProjectListResponse,
    ProjectStage,
    ProjectStatus,
    ProjectSummary,
    ProjectUpdate,
    SkillProjectSource,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectRepository(Protocol):
    async def save_project(self, project: Project) -> Project: ...

    async def get_project(self, project_id: UUID) -> Project | None: ...

    async def list_projects(self) -> list[Project]: ...

    async def delete_project(self, project_id: UUID) -> None: ...

    async def save_project_with_skill_snapshot(
        self,
        project: Project,
        snapshot: SkillVersionSnapshot,
    ) -> tuple[Project, SkillVersionSnapshot]: ...

    async def get_skill_version_snapshot(
        self,
        project_id: UUID,
    ) -> SkillVersionSnapshot | None: ...

    async def list_records(self) -> list[AnalysisRecord]: ...

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None: ...

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord: ...

    async def get_video(self, video_id: UUID) -> Video | None: ...

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]: ...


class ProjectServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _fail(status_code: int, code: str, message: str) -> ProjectServiceError:
    return ProjectServiceError(status_code, code, message)


def _status_from_video(status: VideoStatus) -> ProjectStatus:
    return {
        VideoStatus.READY: ProjectStatus.READY,
        VideoStatus.ANALYZING: ProjectStatus.RUNNING,
        VideoStatus.COMPLETED: ProjectStatus.COMPLETED,
        VideoStatus.FAILED: ProjectStatus.FAILED,
    }[status]


def _lifecycle_from_record(record: AnalysisRecord) -> ProjectLifecycle:
    if record.trashed_at is not None:
        return ProjectLifecycle.TRASHED
    if record.archived_at is not None:
        return ProjectLifecycle.ARCHIVED
    return ProjectLifecycle.ACTIVE


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        catalog: PlatformSkillCatalogService,
        account_context: AccountContextService,
    ) -> None:
        self.repository = repository
        self.catalog = catalog
        self.account_context = account_context

    async def bootstrap_analysis_projects(self) -> None:
        """Idempotent v14 read-model migration with AnalysisRecord UUID preservation."""

        existing = {item.id: item for item in await self.repository.list_projects()}
        for record in await self.repository.list_records():
            current = existing.get(record.id)
            source = AnalysisProjectSource(
                record_id=record.id,
                video_id=record.video_id,
                latest_analysis_id=record.latest_analysis_id,
                source_type=record.source_type.value,
                source_url=record.source_url,
            )
            lifecycle = _lifecycle_from_record(record)
            project = Project(
                id=record.id,
                owner_account_id=(current.owner_account_id if current else None),
                kind=ProjectKind.ANALYSIS,
                name=record.name,
                folder_id=record.folder_id,
                lifecycle=lifecycle,
                lifecycle_before_trash=(
                    current.lifecycle_before_trash
                    if current and lifecycle == ProjectLifecycle.TRASHED
                    else None
                ),
                status=_status_from_video(record.status),
                active_stage=(
                    ProjectStage.ANALYSIS_REPORT
                    if record.status == VideoStatus.COMPLETED
                    else ProjectStage.ANALYSIS
                ),
                source_binding=source,
                created_at=record.created_at,
                updated_at=(
                    max(record.updated_at, current.updated_at)
                    if current
                    else record.updated_at
                ),
                last_opened_at=record.last_opened_at,
                archived_at=record.archived_at,
                trashed_at=record.trashed_at,
            )
            if (
                current is None
                or project.model_dump(mode="json") != current.model_dump(mode="json")
            ):
                await self.repository.save_project(project)

    async def create(self, payload: ProjectCreate) -> ProjectSummary:
        account = await self.account_context.current_account()
        try:
            version = await self.catalog.get_version(payload.skill_version_id)
        except PlatformSkillError as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc
        if version.status != SkillLifecycle.PUBLISHED:
            raise _fail(409, "skill_version_unavailable", "只能使用已发布的 Skill 版本")
        state = await self.catalog.list_admin()
        skill = next((item for item in state.skills if item.id == version.skill_id), None)
        if skill is None or skill.lifecycle != SkillLifecycle.PUBLISHED:
            raise _fail(409, "skill_unavailable", "该 Skill 当前不能用于新项目")
        source = SkillProjectSource(
            skill_id=version.skill_id,
            skill_version_id=version.id,
            skill_version_digest=version.content_digest,
        )
        project = Project(
            owner_account_id=account.id,
            kind=ProjectKind.SKILL,
            name=payload.name,
            folder_id=payload.folder_id,
            status=ProjectStatus.DRAFT,
            active_stage=ProjectStage.CREATIVE_BRIEF,
            source_binding=source,
        )
        snapshot = SkillVersionSnapshot(
            project_id=project.id,
            skill_id=version.skill_id,
            skill_version_id=version.id,
            version=version.version,
            manifest=version.manifest,
            content_digest=version.content_digest,
            resource_digest_map={item.key: item.sha256 for item in version.manifest.resources},
        )
        await self.repository.save_project_with_skill_snapshot(project, snapshot)
        return await self._summary(project)

    async def get(self, project_id: UUID, *, include_trashed: bool = False) -> ProjectSummary:
        await self.bootstrap_analysis_projects()
        project = await self.repository.get_project(project_id)
        if project is None or (project.trashed_at is not None and not include_trashed):
            raise _fail(404, "project_not_found", "项目不存在")
        return await self._summary(project)

    async def list(
        self,
        *,
        lifecycle: ProjectLifecycle = ProjectLifecycle.ACTIVE,
        kind: ProjectKind | None = None,
        query: str | None = None,
        folder_id: UUID | str | None = None,
        status: str | None = None,
        sort: str = "updated_desc",
        page: int = 1,
        page_size: int = 20,
    ) -> ProjectListResponse:
        await self.bootstrap_analysis_projects()
        all_projects = await self.repository.list_projects()
        counts = {
            item.value: sum(1 for project in all_projects if project.lifecycle == item)
            for item in (
                ProjectLifecycle.ACTIVE,
                ProjectLifecycle.ARCHIVED,
                ProjectLifecycle.TRASHED,
            )
        }
        items = all_projects
        if lifecycle != ProjectLifecycle.ALL:
            items = [item for item in items if item.lifecycle == lifecycle]
        if kind is not None:
            items = [item for item in items if item.kind == kind]
        if folder_id == "unfiled":
            items = [item for item in items if item.folder_id is None]
        elif folder_id is not None:
            try:
                normalized_folder_id = UUID(str(folder_id))
            except ValueError as exc:
                raise _fail(422, "folder_id_invalid", "目录参数无效") from exc
            items = [item for item in items if item.folder_id == normalized_folder_id]
        if status:
            normalized_status = "running" if status == "analyzing" else status
            items = [item for item in items if item.status.value == normalized_status]
        if query:
            normalized = query.strip().casefold()
            items = [item for item in items if normalized in item.name.casefold()]
        if sort == "created_desc":
            items.sort(key=lambda item: item.created_at, reverse=True)
        elif sort == "name_asc":
            items.sort(key=lambda item: item.name.casefold())
        else:
            items.sort(key=lambda item: item.updated_at, reverse=True)
        total = len(items)
        total_pages = math.ceil(total / page_size) if total else 0
        effective_page = min(page, total_pages or 1)
        start = (effective_page - 1) * page_size
        summaries = [await self._summary(item) for item in items[start : start + page_size]]
        return ProjectListResponse(
            items=summaries,
            total=total,
            page=effective_page,
            page_size=page_size,
            total_pages=total_pages,
            lifecycle_counts=counts,
        )

    async def update(self, project_id: UUID, payload: ProjectUpdate) -> ProjectSummary:
        project = await self._require(project_id, include_trashed=True)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return await self._summary(project)
        changes["updated_at"] = utc_now()
        updated = project.model_copy(update=changes)
        await self.repository.save_project(updated)
        if updated.kind == ProjectKind.ANALYSIS:
            record = await self.repository.get_record(updated.id)
            if record is not None:
                if "name" in changes:
                    record.name = updated.name
                if "folder_id" in changes:
                    record.folder_id = updated.folder_id
                record.updated_at = updated.updated_at
                await self.repository.save_record(record)
        return await self._summary(updated)

    async def mutate_lifecycle(
        self,
        project_id: UUID,
        action: ProjectLifecycleAction,
    ) -> ProjectSummary:
        project = await self._require(project_id, include_trashed=True)
        now = utc_now()
        changes: dict[str, object] = {"updated_at": now}
        if action == ProjectLifecycleAction.ARCHIVE:
            if project.lifecycle == ProjectLifecycle.TRASHED:
                raise _fail(409, "project_trashed", "请先恢复回收站中的项目")
            changes.update(lifecycle=ProjectLifecycle.ARCHIVED, archived_at=now)
        elif action == ProjectLifecycleAction.ACTIVATE:
            if project.lifecycle == ProjectLifecycle.TRASHED:
                raise _fail(409, "project_trashed", "请先恢复回收站中的项目")
            changes.update(lifecycle=ProjectLifecycle.ACTIVE, archived_at=None)
        elif action == ProjectLifecycleAction.TRASH:
            if project.lifecycle != ProjectLifecycle.TRASHED:
                changes.update(
                    lifecycle_before_trash=project.lifecycle,
                    lifecycle=ProjectLifecycle.TRASHED,
                    trashed_at=now,
                )
        elif action == ProjectLifecycleAction.RESTORE:
            if project.lifecycle == ProjectLifecycle.TRASHED:
                target = project.lifecycle_before_trash or ProjectLifecycle.ACTIVE
                changes.update(
                    lifecycle=target,
                    lifecycle_before_trash=None,
                    archived_at=now if target == ProjectLifecycle.ARCHIVED else None,
                    trashed_at=None,
                )
        updated = project.model_copy(update=changes)
        await self.repository.save_project(updated)
        await self._sync_record_lifecycle(updated)
        return await self._summary(updated)

    async def batch_lifecycle(
        self,
        project_ids: list[UUID],
        action: ProjectLifecycleAction,
    ) -> ProjectBatchMutationResponse:
        affected: list[UUID] = []
        for project_id in dict.fromkeys(project_ids):
            await self.mutate_lifecycle(project_id, action)
            affected.append(project_id)
        return ProjectBatchMutationResponse(affected_ids=affected, affected_count=len(affected))

    async def delete_permanently(self, project_id: UUID) -> None:
        project = await self._require(project_id, include_trashed=True)
        if project.lifecycle != ProjectLifecycle.TRASHED:
            raise _fail(409, "project_not_trashed", "项目必须先移入回收站")
        if project.kind == ProjectKind.ANALYSIS:
            raise _fail(409, "use_analysis_delete", "分析项目请使用原项目清理流程")
        await self.repository.delete_project(project.id)

    async def batch_delete_permanently(
        self,
        project_ids: list[UUID],
    ) -> ProjectBatchMutationResponse:
        affected: list[UUID] = []
        for project_id in dict.fromkeys(project_ids):
            await self.delete_permanently(project_id)
            affected.append(project_id)
        return ProjectBatchMutationResponse(affected_ids=affected, affected_count=len(affected))

    async def bind_skill_run(
        self,
        project_id: UUID,
        *,
        skill_run_id: UUID | None = None,
        production_project_id: UUID | None = None,
        stage: ProjectStage | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        project = await self._require(project_id)
        if project.kind != ProjectKind.SKILL:
            raise _fail(409, "skill_project_required", "该操作只适用于 Skill 项目")
        source = project.source_binding.model_copy(
            update={
                "active_skill_run_id": skill_run_id or project.source_binding.active_skill_run_id,
                "production_project_id": (
                    production_project_id or project.source_binding.production_project_id
                ),
            }
        )
        updated = project.model_copy(
            update={
                "source_binding": source,
                "active_stage": stage or project.active_stage,
                "status": status or project.status,
                "updated_at": utc_now(),
            }
        )
        return await self.repository.save_project(updated)

    async def _require(self, project_id: UUID, *, include_trashed: bool = False) -> Project:
        project = await self.repository.get_project(project_id)
        if project is None or (project.trashed_at is not None and not include_trashed):
            raise _fail(404, "project_not_found", "项目不存在")
        return project

    async def _summary(self, project: Project) -> ProjectSummary:
        if project.kind == ProjectKind.ANALYSIS:
            source = project.source_binding
            record = await self.repository.get_record(source.record_id)
            video = await self.repository.get_video(source.video_id)
            productions = await self.repository.list_production_projects(source.record_id)
            return ProjectSummary(
                **project.model_dump(mode="python"),
                source_type=source.source_type,
                source_url=source.source_url,
                author=video.source_author if video else None,
                duration_seconds=video.duration_seconds if video else None,
                thumbnail_url=(f"/api/v1/records/{record.id}/thumbnail" if record else None),
                production_project_count=sum(item.trashed_at is None for item in productions),
            )
        source = project.source_binding
        state = await self.catalog.list_admin()
        skill = next((item for item in state.skills if item.id == source.skill_id), None)
        return ProjectSummary(
            **project.model_dump(mode="python"),
            source_type="skill",
            thumbnail_url=skill.cover_url if skill else None,
            production_project_count=int(source.production_project_id is not None),
            skill_name=skill.name if skill else source.skill_id,
            skill_slug=skill.slug if skill else None,
        )

    async def _sync_record_lifecycle(self, project: Project) -> None:
        if project.kind != ProjectKind.ANALYSIS:
            return
        record = await self.repository.get_record(project.id)
        if record is None:
            return
        record.archived_at = project.archived_at
        record.trashed_at = project.trashed_at
        record.updated_at = project.updated_at
        await self.repository.save_record(record)
