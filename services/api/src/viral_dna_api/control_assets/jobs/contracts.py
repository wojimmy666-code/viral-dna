from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ...models import ProductionProject, ShotPlan
from ..domain import DepthControlAsset
from .domain import DepthControlJob


@dataclass(frozen=True, slots=True)
class DepthControlJobContext:
    project: ProductionProject
    shot: ShotPlan
    source_path: Path
    source_relative_path: str
    source_video_id: UUID
    source_fingerprint: str


class DepthControlProjectGateway(Protocol):
    async def prepare_depth_control_job(
        self,
        shot_plan_id: UUID,
        expected_revision_id: UUID | None,
    ) -> DepthControlJobContext: ...

    async def commit_depth_control_job(
        self,
        job: DepthControlJob,
        asset: DepthControlAsset,
    ) -> UUID: ...


class DepthControlJobRepository(Protocol):
    async def save_depth_control_job(self, job: DepthControlJob) -> DepthControlJob: ...

    async def get_depth_control_job(self, job_id: UUID) -> DepthControlJob | None: ...

    async def list_depth_control_jobs(
        self,
        *,
        project_id: UUID | None = None,
        shot_plan_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[DepthControlJob]: ...

    async def claim_depth_control_job(
        self,
        job_id: UUID,
    ) -> DepthControlJob | None: ...
