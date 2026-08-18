from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from viral_dna_api.control_assets.engines.process_runner import DepthProcessCancelled
from viral_dna_api.control_assets.jobs.contracts import DepthControlJobContext
from viral_dna_api.control_assets.jobs.domain import (
    ACTIVE_DEPTH_JOB_STATUSES,
    DepthControlJob,
    DepthControlJobStage,
    DepthControlJobStatus,
    DepthControlPreset,
    DepthExecutionDevice,
)
from viral_dna_api.control_assets.jobs.progress import DepthProgressEvent
from viral_dna_api.control_assets.jobs.service import DepthControlJobService


class MemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, DepthControlJob] = {}
        self.lock = asyncio.Lock()

    async def save_depth_control_job(self, job: DepthControlJob) -> DepthControlJob:
        async with self.lock:
            self.jobs[job.id] = job
        return job

    async def get_depth_control_job(self, job_id: UUID) -> DepthControlJob | None:
        return self.jobs.get(job_id)

    async def list_depth_control_jobs(
        self,
        *,
        project_id: UUID | None = None,
        shot_plan_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[DepthControlJob]:
        jobs = list(self.jobs.values())
        if project_id is not None:
            jobs = [item for item in jobs if item.project_id == project_id]
        if shot_plan_id is not None:
            jobs = [item for item in jobs if item.shot_plan_id == shot_plan_id]
        if active_only:
            jobs = [item for item in jobs if item.status in ACTIVE_DEPTH_JOB_STATUSES]
        return sorted(jobs, key=lambda item: item.created_at)

    async def claim_depth_control_job(self, job_id: UUID) -> DepthControlJob | None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != DepthControlJobStatus.QUEUED:
                return None
            now = datetime.now(UTC)
            claimed = job.model_copy(
                update={
                    "status": DepthControlJobStatus.RUNNING,
                    "started_at": now,
                    "heartbeat_at": now,
                    "updated_at": now,
                }
            )
            self.jobs[job.id] = claimed
            return claimed


class FakeProjectGateway:
    def __init__(self) -> None:
        self.project_id = uuid4()
        self.shot_id = uuid4()
        self.record_id = uuid4()
        self.revision_id = uuid4()
        self.source_video_id = uuid4()
        self.committed_assets: list[UUID] = []

    async def prepare_depth_control_job(
        self,
        shot_plan_id: UUID,
        expected_revision_id: UUID | None,
    ) -> DepthControlJobContext:
        assert shot_plan_id == self.shot_id
        if expected_revision_id is not None:
            assert expected_revision_id == self.revision_id
        return DepthControlJobContext(
            project=SimpleNamespace(
                id=self.project_id,
                record_id=self.record_id,
                current_revision_id=self.revision_id,
            ),
            shot=SimpleNamespace(
                id=self.shot_id,
                start_seconds=0.0,
                end_seconds=3.0,
            ),
            source_video_id=self.source_video_id,
            source_relative_path="records/source.mp4",
            source_path=Path("records/source.mp4"),
            source_fingerprint="a" * 64,
        )

    async def commit_depth_control_job(self, job, asset) -> UUID:
        self.committed_assets.append(asset.id)
        return uuid4()


class FakeDepthControls:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.generated = 0

    def capability(self):
        return SimpleNamespace(
            engine="video_depth_anything",
            version="official-cli-v1",
            model_variant="vits",
        )

    async def generation_profile(self, preset: DepthControlPreset):
        return SimpleNamespace(
            preset=(
                DepthControlPreset.CPU_FAST
                if preset == DepthControlPreset.AUTO
                else preset
            ),
            device=DepthExecutionDevice.CPU,
            device_name="Test CPU",
            target_fps=12,
            input_size=392,
            max_resolution=960,
            timeout_seconds=1800,
        )

    async def generate_job(self, job, *, cancellation, progress):
        self.generated += 1
        await progress(
            DepthProgressEvent(
                stage=DepthControlJobStage.INFERRING_DEPTH,
                ratio=0.5,
                message="正在推理空间深度 · 18/36 帧",
                processed_frames=18,
                total_frames=36,
            )
        )
        await progress(
            DepthProgressEvent(
                stage=DepthControlJobStage.VALIDATING_OUTPUT,
                ratio=1,
                message="输出质量检查通过",
                processed_frames=36,
                total_frames=36,
            )
        )
        return SimpleNamespace(id=uuid4())

    def job_root(self, job: DepthControlJob) -> Path:
        return self.root / str(job.id)

    async def write_job_diagnostics(self, job, *, technical_detail=None) -> None:
        return None


class BlockingDepthControls(FakeDepthControls):
    async def generate_job(self, job, *, cancellation, progress):
        await progress(
            DepthProgressEvent(
                stage=DepthControlJobStage.INFERRING_DEPTH,
                ratio=0,
                message="正在推理空间深度 · 0/36 帧",
                processed_frames=0,
                total_frames=36,
            )
        )
        await cancellation.wait()
        raise DepthProcessCancelled("cancelled")


async def wait_terminal(repository: MemoryJobRepository, job_id: UUID) -> DepthControlJob:
    for _ in range(100):
        job = await repository.get_depth_control_job(job_id)
        if job is not None and job.status not in ACTIVE_DEPTH_JOB_STATUSES:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("depth job did not reach a terminal state")


def test_depth_job_runs_in_background_and_persists_real_progress(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = MemoryJobRepository()
        gateway = FakeProjectGateway()
        controls = FakeDepthControls(tmp_path)
        service = DepthControlJobService(repository, gateway, controls)

        submitted = await service.submit(
            gateway.shot_id,
            expected_revision_id=gateway.revision_id,
        )
        assert submitted.status == DepthControlJobStatus.QUEUED
        assert submitted.effective_preset == DepthControlPreset.CPU_FAST

        completed = await wait_terminal(repository, submitted.id)
        assert completed.status == DepthControlJobStatus.SUCCEEDED
        assert completed.stage == DepthControlJobStage.COMPLETED
        assert completed.progress_percent == 100
        assert completed.processed_frames == completed.total_frames == 36
        assert completed.result_asset_id in gateway.committed_assets
        assert controls.generated == 1
        await service.shutdown()

    asyncio.run(scenario())


def test_concurrent_submissions_share_one_active_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = MemoryJobRepository()
        gateway = FakeProjectGateway()
        controls = BlockingDepthControls(tmp_path)
        service = DepthControlJobService(repository, gateway, controls)

        first, second = await asyncio.gather(
            service.submit(
                gateway.shot_id,
                expected_revision_id=gateway.revision_id,
            ),
            service.submit(
                gateway.shot_id,
                expected_revision_id=gateway.revision_id,
            ),
        )
        assert first.id == second.id
        active = await repository.list_depth_control_jobs(
            shot_plan_id=gateway.shot_id,
            active_only=True,
        )
        assert len(active) == 1
        await service.cancel(first.id)
        await wait_terminal(repository, first.id)
        await service.shutdown()

    asyncio.run(scenario())


def test_recovery_marks_orphaned_running_job_interrupted(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = MemoryJobRepository()
        gateway = FakeProjectGateway()
        controls = FakeDepthControls(tmp_path)
        service = DepthControlJobService(repository, gateway, controls)
        now = datetime.now(UTC)
        orphaned = DepthControlJob(
            project_id=gateway.project_id,
            shot_plan_id=gateway.shot_id,
            record_id=gateway.record_id,
            submitted_revision_id=gateway.revision_id,
            source_video_id=gateway.source_video_id,
            source_relative_path="records/source.mp4",
            source_start_seconds=0,
            source_end_seconds=3,
            source_fingerprint="b" * 64,
            status=DepthControlJobStatus.RUNNING,
            started_at=now,
            heartbeat_at=now,
        )
        await repository.save_depth_control_job(orphaned)

        await service.recover()
        recovered = await repository.get_depth_control_job(orphaned.id)
        assert recovered is not None
        assert recovered.status == DepthControlJobStatus.INTERRUPTED
        assert recovered.error_code == "depth_job_interrupted"
        assert "服务重启" in (recovered.error_message or "")

    asyncio.run(scenario())


def test_retry_of_timeout_uses_cpu_fast_preset(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = MemoryJobRepository()
        gateway = FakeProjectGateway()
        controls = FakeDepthControls(tmp_path)
        service = DepthControlJobService(repository, gateway, controls)
        previous = DepthControlJob(
            project_id=gateway.project_id,
            shot_plan_id=gateway.shot_id,
            record_id=gateway.record_id,
            submitted_revision_id=gateway.revision_id,
            source_video_id=gateway.source_video_id,
            source_relative_path="records/source.mp4",
            source_start_seconds=0,
            source_end_seconds=3,
            source_fingerprint="c" * 64,
            requested_preset=DepthControlPreset.QUALITY,
            status=DepthControlJobStatus.FAILED,
            error_code="depth_inference_timeout",
            error_message="timeout",
            finished_at=datetime.now(UTC),
        )
        await repository.save_depth_control_job(previous)

        retried = await service.retry(previous.id)
        assert retried.requested_preset == DepthControlPreset.CPU_FAST
        assert retried.retry_of_job_id == previous.id
        await wait_terminal(repository, retried.id)
        await service.shutdown()

    asyncio.run(scenario())


def test_running_depth_job_can_be_cancelled_without_losing_terminal_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = MemoryJobRepository()
        gateway = FakeProjectGateway()
        controls = BlockingDepthControls(tmp_path)
        service = DepthControlJobService(repository, gateway, controls)
        submitted = await service.submit(
            gateway.shot_id,
            expected_revision_id=gateway.revision_id,
        )
        for _ in range(100):
            running = await repository.get_depth_control_job(submitted.id)
            if running is not None and running.status == DepthControlJobStatus.RUNNING:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("depth job did not start")

        requested = await service.cancel(submitted.id)
        assert requested.status == DepthControlJobStatus.CANCELLATION_REQUESTED
        cancelled = await wait_terminal(repository, submitted.id)
        assert cancelled.status == DepthControlJobStatus.CANCELLED
        assert cancelled.error_code == "depth_job_cancelled"
        await service.shutdown()

    asyncio.run(scenario())
