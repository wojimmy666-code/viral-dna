from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationCandidateStatus,
    GenerationKind,
    WorkflowItemStatus,
)
from viral_dna_api.video_enhancement.domain import (
    ACTIVE_VIDEO_ENHANCEMENT_STATUSES,
    VideoEnhancementJob,
    VideoEnhancementJobStage,
    VideoEnhancementJobStatus,
    VideoEnhancementTarget,
)
from viral_dna_api.video_enhancement.engine import (
    VideoEnhancementCapability,
    VideoEnhancementOutput,
    VideoEnhancementProgress,
)
from viral_dna_api.video_enhancement.process_runner import EnhancementProcessCancelled
from viral_dna_api.video_enhancement.service import (
    VideoEnhancementService,
    VideoEnhancementServiceError,
)


class MemoryRepository:
    def __init__(self, candidate, run, plan, project) -> None:
        self.candidate = candidate
        self.run = run
        self.plan = plan
        self.project = project
        self.jobs: dict[UUID, VideoEnhancementJob] = {}
        self.lock = asyncio.Lock()

    async def get_generation_candidate(self, candidate_id):
        return self.candidate if self.candidate.id == candidate_id else None

    async def save_generation_candidate(self, candidate):
        self.candidate = candidate
        return candidate

    async def get_generation_run(self, run_id):
        return self.run if self.run.id == run_id else None

    async def get_shot_plan(self, shot_plan_id):
        return self.plan if self.plan.id == shot_plan_id else None

    async def get_production_project(self, project_id):
        return self.project if self.project.id == project_id else None

    async def save_video_enhancement_job(self, job):
        async with self.lock:
            self.jobs[job.id] = job
        return job

    async def get_video_enhancement_job(self, job_id):
        return self.jobs.get(job_id)

    async def list_video_enhancement_jobs(
        self,
        *,
        project_id=None,
        shot_plan_id=None,
        candidate_id=None,
        active_only=False,
    ):
        jobs = list(self.jobs.values())
        if project_id is not None:
            jobs = [item for item in jobs if item.project_id == project_id]
        if shot_plan_id is not None:
            jobs = [item for item in jobs if item.shot_plan_id == shot_plan_id]
        if candidate_id is not None:
            jobs = [item for item in jobs if item.candidate_id == candidate_id]
        if active_only:
            jobs = [item for item in jobs if item.status in ACTIVE_VIDEO_ENHANCEMENT_STATUSES]
        return sorted(jobs, key=lambda item: item.created_at)

    async def claim_video_enhancement_job(self, job_id):
        async with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != VideoEnhancementJobStatus.QUEUED:
                return None
            now = datetime.now(UTC)
            claimed = job.model_copy(
                update={
                    "status": VideoEnhancementJobStatus.RUNNING,
                    "started_at": now,
                    "heartbeat_at": now,
                    "updated_at": now,
                }
            )
            self.jobs[job_id] = claimed
            return claimed


class FakeWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def production_shot_root(self, record_id, project_id, shot_plan_id):
        return self.root / str(record_id) / str(project_id) / str(shot_plan_id)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def resolve(self, relative_path: str) -> Path:
        return (self.root / relative_path).resolve()


class FakeProduction:
    def __init__(self, source: Path) -> None:
        self.source = source

    async def resolve_candidate_content(self, candidate_id, *, variant="active"):
        assert variant == "original"
        return self.source, "video/mp4"


class FakeSettings:
    def __init__(self) -> None:
        self.account_id = uuid4()

    async def get_current(self):
        return self.account_id, SimpleNamespace(default_target=VideoEnhancementTarget.FHD)


class FakeEngine:
    def capability(self):
        return VideoEnhancementCapability(
            engine="realesrgan-ncnn-vulkan",
            version="0.2.0",
            model="realesrgan-x4plus",
            available=True,
            availability_note="已就绪",
            repository_url="https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan",
            installation_path=Path("."),
            executable_path=Path("realesrgan-ncnn-vulkan.exe"),
            execution_device="自动选择 Vulkan 设备",
            license="MIT",
            installable=True,
        )

    @staticmethod
    def upscale_factor(source_width, source_height, target_width, target_height):
        del source_width, source_height, target_width, target_height
        return 3

    async def generate(
        self,
        *,
        destination_path,
        target_width,
        target_height,
        progress,
        **kwargs,
    ):
        del kwargs
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"enhanced-video")
        await progress(
            VideoEnhancementProgress(
                stage=VideoEnhancementJobStage.UPSCALING,
                percent=60,
                message="正在增强画面细节",
                processed_frames=30,
                total_frames=60,
            )
        )
        return VideoEnhancementOutput(
            path=destination_path,
            width=target_width,
            height=target_height,
            fps=30,
            duration_seconds=2,
            frame_count=60,
            sha256="b" * 64,
            size_bytes=14,
        )


class BlockingEngine(FakeEngine):
    async def generate(self, *, cancellation, **kwargs):
        del kwargs
        await cancellation.wait()
        raise EnhancementProcessCancelled("service stopping")


def make_service(tmp_path: Path, *, approved: bool = True, engine=None):
    project_id = uuid4()
    shot_id = uuid4()
    run_id = uuid4()
    candidate = GenerationCandidate(
        generation_run_id=run_id,
        ordinal=1,
        kind=GenerationKind.VIDEO,
        relative_path="source.mp4",
        width=854,
        height=480,
        duration_seconds=2,
        sha256="a" * 64,
        metadata_relative_path="source.json",
        status=GenerationCandidateStatus.SELECTED,
    )
    revision_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        project_id=project_id,
        shot_plan_id=shot_id,
        kind=GenerationKind.VIDEO,
    )
    plan = SimpleNamespace(
        id=shot_id,
        video_status=(WorkflowItemStatus.APPROVED if approved else WorkflowItemStatus.DRAFT),
        approved_video_candidate_id=candidate.id if approved else None,
    )
    project = SimpleNamespace(
        id=project_id,
        record_id=uuid4(),
        current_revision_id=revision_id,
        output_aspect_ratio="16:9",
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    repository = MemoryRepository(candidate, run, plan, project)
    service = VideoEnhancementService(
        repository,
        FakeWorkspace(tmp_path),
        FakeProduction(source),
        FakeSettings(),
        engine=engine or FakeEngine(),
    )
    return service, repository, revision_id


async def wait_terminal(repository, job_id):
    for _ in range(100):
        job = await repository.get_video_enhancement_job(job_id)
        if job is not None and job.status not in ACTIVE_VIDEO_ENHANCEMENT_STATUSES:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("video enhancement job did not finish")


def test_video_enhancement_requires_the_current_approved_candidate(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, repository, revision_id = make_service(tmp_path, approved=False)
        try:
            await service.submit(
                repository.candidate.id,
                expected_revision_id=revision_id,
            )
        except VideoEnhancementServiceError as exc:
            assert exc.code == "approved_video_candidate_required"
        else:
            raise AssertionError("unapproved candidate was accepted")

    asyncio.run(scenario())


def test_enhancement_is_a_durable_inactive_version_until_selected(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, repository, revision_id = make_service(tmp_path)
        submitted = await service.submit(
            repository.candidate.id,
            expected_revision_id=revision_id,
        )
        assert submitted.target_width == 1920
        assert submitted.target_height == 1080
        completed = await wait_terminal(repository, submitted.id)
        assert completed.status == VideoEnhancementJobStatus.SUCCEEDED
        assert completed.active_for_final is False
        assert repository.candidate.relative_path == "source.mp4"
        assert completed.result_relative_path
        await service.shutdown()

    asyncio.run(scenario())


def test_user_can_switch_between_enhanced_and_original_versions(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, repository, revision_id = make_service(tmp_path)
        submitted = await service.submit(
            repository.candidate.id,
            expected_revision_id=revision_id,
            target=VideoEnhancementTarget.UHD,
        )
        completed = await wait_terminal(repository, submitted.id)
        assert (completed.target_width, completed.target_height) == (3840, 2160)

        enhanced = await service.activate(
            completed.id,
            expected_revision_id=revision_id,
        )
        assert (enhanced.width, enhanced.height) == (3840, 2160)
        assert enhanced.relative_path == completed.result_relative_path
        metadata = enhanced.quality_report["video_enhancement"]
        assert metadata["original"]["relative_path"] == "source.mp4"
        assert metadata["active_job_id"] == str(completed.id)

        restored = await service.use_original(
            repository.candidate.id,
            expected_revision_id=revision_id,
        )
        assert restored.relative_path == "source.mp4"
        assert (restored.width, restored.height) == (854, 480)
        jobs = await repository.list_video_enhancement_jobs(candidate_id=repository.candidate.id)
        assert all(not item.active_for_final for item in jobs)
        await service.shutdown()

    asyncio.run(scenario())


def test_service_shutdown_marks_active_work_as_interrupted(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, repository, revision_id = make_service(
            tmp_path,
            engine=BlockingEngine(),
        )
        submitted = await service.submit(
            repository.candidate.id,
            expected_revision_id=revision_id,
        )
        for _ in range(100):
            running = await repository.get_video_enhancement_job(submitted.id)
            if running is not None and running.status == VideoEnhancementJobStatus.RUNNING:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("video enhancement job did not start")

        await service.shutdown()
        interrupted = await repository.get_video_enhancement_job(submitted.id)
        assert interrupted is not None
        assert interrupted.status == VideoEnhancementJobStatus.INTERRUPTED
        assert interrupted.error_code == "video_enhancement_interrupted"

    asyncio.run(scenario())
