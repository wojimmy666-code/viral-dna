from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from .contracts import (
    ProjectBatchDeleteRequest,
    ProjectBatchLifecycleRequest,
    ProjectBatchMutationResponse,
    ProjectCreate,
    ProjectKind,
    ProjectLifecycle,
    ProjectLifecycleRequest,
    ProjectListResponse,
    ProjectSummary,
    ProjectUpdate,
)
from .service import ProjectService, ProjectServiceError


def _raise_http(exc: ProjectServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def create_project_router(service: ProjectService) -> APIRouter:
    router = APIRouter(tags=["projects"])

    @router.get("/projects", response_model=ProjectListResponse)
    async def list_projects(
        lifecycle: Annotated[ProjectLifecycle, Query()] = ProjectLifecycle.ACTIVE,
        kind: Annotated[ProjectKind | None, Query()] = None,
        query: Annotated[str | None, Query(alias="q", max_length=120)] = None,
        folder_id: Annotated[str | None, Query(max_length=80)] = None,
        project_status: Annotated[
            str | None,
            Query(
                alias="status",
                max_length=40,
                pattern="^(draft|ready|analyzing|running|completed|blocked|failed)$",
            ),
        ] = None,
        sort: Annotated[str, Query(pattern="^(updated_desc|created_desc|name_asc)$")] = (
            "updated_desc"
        ),
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> ProjectListResponse:
        return await service.list(
            lifecycle=lifecycle,
            kind=kind,
            query=query,
            folder_id=folder_id,
            status=project_status,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    @router.post(
        "/projects",
        response_model=ProjectSummary,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_project(payload: ProjectCreate) -> ProjectSummary:
        try:
            return await service.create(payload)
        except ProjectServiceError as exc:
            _raise_http(exc)

    # Fixed batch paths must precede UUID parameters: otherwise "batch" is
    # consumed as project_id and rejected before the batch handler can run.
    @router.post("/projects/batch/lifecycle", response_model=ProjectBatchMutationResponse)
    async def batch_lifecycle(
        payload: ProjectBatchLifecycleRequest,
    ) -> ProjectBatchMutationResponse:
        try:
            return await service.batch_lifecycle(payload.project_ids, payload.action)
        except ProjectServiceError as exc:
            _raise_http(exc)

    @router.delete("/projects/batch", response_model=ProjectBatchMutationResponse)
    async def batch_delete_projects(
        payload: ProjectBatchDeleteRequest,
    ) -> ProjectBatchMutationResponse:
        try:
            return await service.batch_delete_permanently(payload.project_ids)
        except ProjectServiceError as exc:
            _raise_http(exc)

    @router.get("/projects/{project_id}", response_model=ProjectSummary)
    async def get_project(project_id: UUID) -> ProjectSummary:
        try:
            return await service.get(project_id)
        except ProjectServiceError as exc:
            _raise_http(exc)

    @router.patch("/projects/{project_id}", response_model=ProjectSummary)
    async def update_project(project_id: UUID, payload: ProjectUpdate) -> ProjectSummary:
        try:
            return await service.update(project_id, payload)
        except ProjectServiceError as exc:
            _raise_http(exc)

    @router.post("/projects/{project_id}/lifecycle", response_model=ProjectSummary)
    async def mutate_lifecycle(
        project_id: UUID,
        payload: ProjectLifecycleRequest,
    ) -> ProjectSummary:
        try:
            return await service.mutate_lifecycle(project_id, payload.action)
        except ProjectServiceError as exc:
            _raise_http(exc)

    @router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_project(project_id: UUID) -> Response:
        try:
            await service.delete_permanently(project_id)
        except ProjectServiceError as exc:
            _raise_http(exc)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
