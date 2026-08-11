from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.models import (
    ProductionProject,
    ProductionProjectStatus,
    ProductionStep,
    ProductionTimeline,
    TimelineAudioTrack,
    TimelineClip,
    TimelineExportQuality,
    TimelineExportResolution,
    TimelineExportSubtitleMode,
    TimelineExportValidationSummary,
    TimelineFinalRenderCreate,
    TimelineRenderStatus,
    VideoClipAudioMode,
)
from viral_dna_api.timeline_export import TimelineExportService, export_dimensions
from viral_dna_api.workspace import WorkspaceManager


class FakeRepository:
    def __init__(self, project: ProductionProject) -> None:
        self.project = project

    async def get_production_project(self, project_id):
        return self.project if project_id == self.project.id else None


class FakeTimelineProvider:
    def __init__(self, timeline: ProductionTimeline) -> None:
        self.timeline = timeline

    async def get_timeline(self, project_id):
        assert project_id == self.timeline.project_id
        return self.timeline

    def validate_timeline(self, timeline):
        return SimpleNamespace(valid=True, errors=[])


class FakeRenderer:
    async def render(
        self,
        timeline,
        output_root: Path,
        *,
        source_audio_path,
        background_audio_path,
        progress,
        is_cancelled,
        profile,
    ):
        assert source_audio_path is None
        assert background_audio_path is None
        assert profile.width == 1920
        assert profile.height == 1080
        assert profile.subtitle_mode == "embedded"
        assert not is_cancelled()
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        await progress(50)
        output = output_root / profile.output_filename
        subtitles = output_root / profile.subtitle_filename
        output.write_bytes(b"final-video")
        subtitles.write_text("WEBVTT\n", "utf-8")
        await progress(100)
        return output, subtitles


class FakeValidator:
    async def validate(
        self,
        output_path,
        timeline,
        *,
        expected_width,
        expected_height,
        subtitle_mode,
    ):
        assert output_path.read_bytes() == b"final-video"
        assert subtitle_mode == TimelineExportSubtitleMode.EMBEDDED
        return TimelineExportValidationSummary(
            valid=True,
            expected_duration_seconds=timeline.duration_seconds,
            duration_seconds=timeline.duration_seconds,
            width=expected_width,
            height=expected_height,
            fps=timeline.fps,
            video_codec="h264",
            audio_codec=None,
            has_audio=False,
            has_subtitles=True,
            size_bytes=11,
            sha256="a" * 64,
        )


class FakeNotifications:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, **payload):
        self.events.append(payload)
        return SimpleNamespace(**payload)


class ExportServiceForTest(TimelineExportService):
    async def _extract_cover(self, source: Path, output: Path, job_id):
        assert await asyncio.to_thread(source.is_file)
        await asyncio.to_thread(output.write_bytes, b"cover")
        return output


def build_timeline(project_id) -> ProductionTimeline:
    clip = TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=1,
        candidate_id=uuid4(),
        candidate_content_url="/candidate",
        cover_url="/cover",
        order=1,
        candidate_duration_seconds=2,
        trim_in_seconds=0,
        trim_out_seconds=2,
        playback_rate=1,
        timeline_start_seconds=0,
        timeline_end_seconds=2,
        timeline_duration_seconds=2,
        audio_mode=VideoClipAudioMode.MUTED,
        source_audio_start_seconds=0,
        source_audio_end_seconds=2,
    )
    return ProductionTimeline(
        project_id=project_id,
        source_handoff_revision_id=uuid4(),
        revision_id=uuid4(),
        revision_number=4,
        output_aspect_ratio="16:9",
        output_width=1920,
        output_height=1080,
        duration_seconds=2,
        clips=[clip],
        audio_track=TimelineAudioTrack(strategy="muted", enabled=False),
    )


def test_export_dimensions_preserve_aspect_and_even_pixels() -> None:
    assert export_dimensions(1080, 1920, TimelineExportResolution.P720) == (720, 1280)
    assert export_dimensions(1920, 1080, TimelineExportResolution.P1080) == (1920, 1080)
    assert export_dimensions(1080, 1350, TimelineExportResolution.P1080) == (1080, 1350)
    assert export_dimensions(1081, 1921, TimelineExportResolution.PROJECT) == (1080, 1920)


@pytest.mark.asyncio
async def test_final_export_persists_validated_artifacts_and_notifications(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_STORE", "memory")
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))
    workspace = WorkspaceManager()
    project = ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="高清导出测试",
        status=ProductionProjectStatus.ACTIVE,
        active_step=ProductionStep.EDITING,
        current_revision_id=uuid4(),
        output_aspect_ratio="16:9",
        output_width=1920,
        output_height=1080,
    )
    timeline = build_timeline(project.id)
    notifications = FakeNotifications()
    completed: list[tuple] = []

    async def mark_completed(project_id, timeline_revision_id, job_id):
        completed.append((project_id, timeline_revision_id, job_id))

    service = ExportServiceForTest(
        FakeRepository(project),
        workspace,
        FakeTimelineProvider(timeline),
        media_resolver=SimpleNamespace(),
        renderer=FakeRenderer(),
        validator=FakeValidator(),
        notification_publisher=notifications,
        on_export_succeeded=mark_completed,
    )
    queued = await service.create_export(
        project.id,
        TimelineFinalRenderCreate(
            expected_revision_id=timeline.revision_id,
            resolution=TimelineExportResolution.P1080,
            subtitle_mode=TimelineExportSubtitleMode.EMBEDDED,
            quality=TimelineExportQuality.HIGH,
        ),
    )

    job = queued
    for _ in range(50):
        await asyncio.sleep(0.01)
        job = await service.get_export(project.id, queued.id)
        if job.status not in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}:
            break

    assert job.status == TimelineRenderStatus.SUCCEEDED
    assert job.validation_summary is not None and job.validation_summary.valid
    assert job.file_size_bytes == 11
    assert job.sha256 == "a" * 64
    assert completed == [(project.id, timeline.revision_id, job.id)]
    assert notifications.events[-1]["status"] == "succeeded"

    output_path, output_type, filename = await service.resolve_artifact(
        project.id,
        job.id,
        "content",
    )
    manifest_path, manifest_type, _ = await service.resolve_artifact(
        project.id,
        job.id,
        "manifest",
    )
    assert output_path.read_bytes() == b"final-video"
    assert output_type == "video/mp4"
    assert filename.endswith(".mp4")
    assert manifest_type.startswith("application/json")
    assert '"schema_version": "viral-dna-final-export/v1"' in manifest_path.read_text("utf-8")
    assert (await service.list_exports(project.id)).items[0].id == job.id
    await service.shutdown()
