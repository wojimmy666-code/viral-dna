from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from viral_dna_api.models import (
    EditingHandoffClip,
    EditingHandoffManifest,
    ProductionProject,
    ProductionProjectStatus,
    ProductionStep,
    TimelineClipUpdate,
    TimelinePreviewCreate,
    TimelineRenderStatus,
    TimelineRestoreRequest,
    TimelineTransition,
    TimelineTransitionKind,
    TimelineUpdateRequest,
    VideoClipAudioMode,
    VideoMappedTextCue,
    VideoQualityStatus,
)
from viral_dna_api.timeline import TimelineService, TimelineServiceError
from viral_dna_api.workspace import WorkspaceManager


class FakeRepository:
    def __init__(self, project: ProductionProject) -> None:
        self.project = project
        self.candidates = {
            UUID("00000000-0000-0000-0000-000000000101"): SimpleNamespace(
                duration_seconds=5.0
            ),
            UUID("00000000-0000-0000-0000-000000000102"): SimpleNamespace(
                duration_seconds=5.0
            ),
        }

    async def get_production_project(self, project_id):
        return self.project if project_id == self.project.id else None

    async def get_generation_candidate(self, candidate_id):
        return self.candidates.get(candidate_id)


class FakeHandoffProvider:
    def __init__(self, manifest: EditingHandoffManifest) -> None:
        self.manifest = manifest

    async def get_editing_handoff(self, project_id):
        assert project_id == self.manifest.project_id
        return self.manifest

    async def resolve_candidate_content(self, candidate_id, *, thumbnail=False):
        raise AssertionError("测试渲染器不应解析候选媒体")


class FakeRenderer:
    async def render(
        self,
        timeline,
        output_root: Path,
        *,
        source_audio_path,
        progress,
        is_cancelled,
    ):
        assert source_audio_path is not None
        assert not is_cancelled()
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        await progress(45)
        output = output_root / "preview.mp4"
        subtitles = output_root / "preview.vtt"
        output.write_bytes(b"preview")
        subtitles.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n字幕\n", "utf-8")
        await progress(100)
        return output, subtitles


class FakeNotifications:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, **payload):
        self.events.append(payload)
        return SimpleNamespace(**payload)


@pytest.fixture
def timeline_context(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_STORE", "memory")
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))
    workspace = WorkspaceManager()
    project = ProductionProject(
        record_id=uuid4(),
        video_id=uuid4(),
        base_analysis_id=uuid4(),
        source_prompt_package_id=uuid4(),
        name="时间线测试",
        status=ProductionProjectStatus.ACTIVE,
        active_step=ProductionStep.EDITING,
        current_revision_id=uuid4(),
        output_aspect_ratio="16:9",
        output_width=1920,
        output_height=1080,
    )
    audio_path = workspace.analysis_root(project.record_id, project.base_analysis_id) / "audio.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"test-audio")
    first_id = UUID("00000000-0000-0000-0000-000000000101")
    second_id = UUID("00000000-0000-0000-0000-000000000102")
    cue = VideoMappedTextCue(
        id="cue-1",
        kind="subtitle",
        text="第一句字幕",
        language="zh",
        source_start_seconds=0.5,
        source_end_seconds=1.5,
        clip_start_seconds=0.5,
        clip_end_seconds=1.5,
    )
    manifest = EditingHandoffManifest(
        project_id=project.id,
        revision_id=project.current_revision_id,
        source_analysis_id=project.base_analysis_id,
        source_audio_url="/api/v1/analyses/source/artifacts/audio.wav",
        audio_strategy="continuous_source_track",
        timeline_duration_seconds=8,
        clips=[
            EditingHandoffClip(
                shot_plan_id=uuid4(),
                shot_index=1,
                candidate_id=first_id,
                candidate_content_url=f"/candidates/{first_id}",
                cover_url="/covers/1",
                timeline_start_seconds=0,
                timeline_end_seconds=4,
                timeline_duration_seconds=4,
                trim_in_seconds=0,
                trim_out_seconds=4,
                video_playback_rate=1,
                audio_mode=VideoClipAudioMode.SOURCE,
                source_audio_start_seconds=0,
                source_audio_end_seconds=4,
                subtitle_cues=[cue],
                quality_status=VideoQualityStatus.PASSED,
            ),
            EditingHandoffClip(
                shot_plan_id=uuid4(),
                shot_index=2,
                candidate_id=second_id,
                candidate_content_url=f"/candidates/{second_id}",
                cover_url="/covers/2",
                timeline_start_seconds=4,
                timeline_end_seconds=8,
                timeline_duration_seconds=4,
                trim_in_seconds=0,
                trim_out_seconds=4,
                video_playback_rate=1,
                audio_mode=VideoClipAudioMode.SOURCE,
                source_audio_start_seconds=4,
                source_audio_end_seconds=8,
                quality_status=VideoQualityStatus.PASSED,
            ),
        ],
    )
    notifications = FakeNotifications()
    service = TimelineService(
        FakeRepository(project),
        workspace,
        FakeHandoffProvider(manifest),
        renderer=FakeRenderer(),
        notification_publisher=notifications,
    )
    return service, workspace, project, notifications


@pytest.mark.asyncio
async def test_timeline_initializes_from_handoff_and_persists_revision(timeline_context):
    service, workspace, project, _ = timeline_context

    timeline = await service.get_timeline(project.id)
    loaded = await service.get_timeline(project.id)
    revisions = await service.list_revisions(project.id)

    assert loaded.revision_id == timeline.revision_id
    assert timeline.revision_number == 1
    assert timeline.duration_seconds == 8
    assert [clip.order for clip in timeline.clips] == [1, 2]
    assert timeline.subtitle_cues[0].clip_id == timeline.clips[0].id
    assert timeline.subtitle_cues[0].start_seconds == 0.5
    assert len(revisions.items) == 1
    root = workspace.production_paths(project.record_id, project.id).timelines
    assert (root / "timeline.json").is_file()
    assert workspace.resolve(revisions.items[0].snapshot_relative_path).is_file()


@pytest.mark.asyncio
async def test_timeline_update_reorders_clips_and_creates_restorable_revision(
    timeline_context,
):
    service, _, project, _ = timeline_context
    original = await service.get_timeline(project.id)
    first, second = original.clips

    updated = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=original.revision_id,
            clip_order=[second.id, first.id],
            clip_updates=[
                TimelineClipUpdate(
                    clip_id=second.id,
                    transition_after=TimelineTransition(
                        kind=TimelineTransitionKind.CROSSFADE,
                        duration_seconds=0.5,
                    ),
                )
            ],
            summary="交换两个分镜并增加叠化",
        ),
    )

    assert updated.revision_number == 2
    assert [clip.shot_index for clip in updated.clips] == [2, 1]
    assert updated.duration_seconds == 7.5
    assert updated.clips[1].timeline_start_seconds == 3.5
    with pytest.raises(TimelineServiceError) as conflict:
        await service.update_timeline(
            project.id,
            TimelineUpdateRequest(
                expected_revision_id=original.revision_id,
                summary="过期写入",
            ),
        )
    assert conflict.value.code == "timeline_revision_conflict"

    restored = await service.restore_revision(
        project.id,
        original.revision_id,
        TimelineRestoreRequest(expected_revision_id=updated.revision_id),
    )
    assert restored.revision_number == 3
    assert [clip.shot_index for clip in restored.clips] == [1, 2]
    assert restored.duration_seconds == 8


@pytest.mark.asyncio
async def test_timeline_rejects_transition_after_last_enabled_clip(timeline_context):
    service, _, project, _ = timeline_context
    timeline = await service.get_timeline(project.id)
    last = timeline.clips[-1]

    with pytest.raises(TimelineServiceError) as invalid:
        await service.update_timeline(
            project.id,
            TimelineUpdateRequest(
                expected_revision_id=timeline.revision_id,
                clip_updates=[
                    TimelineClipUpdate(
                        clip_id=last.id,
                        transition_after=TimelineTransition(
                            kind=TimelineTransitionKind.FADE,
                            duration_seconds=0.5,
                        ),
                    )
                ],
                summary="非法片尾转场",
            ),
        )
    assert invalid.value.code == "timeline_invalid"


@pytest.mark.asyncio
async def test_preview_job_persists_output_and_publishes_account_notification(
    timeline_context,
):
    service, _, project, notifications = timeline_context
    timeline = await service.get_timeline(project.id)
    queued = await service.create_preview(
        project.id,
        TimelinePreviewCreate(expected_revision_id=timeline.revision_id),
    )

    job = queued
    for _ in range(50):
        await asyncio.sleep(0.01)
        job = await service.get_render_job(project.id, queued.id)
        if job.status not in {TimelineRenderStatus.QUEUED, TimelineRenderStatus.RUNNING}:
            break

    assert job.status == TimelineRenderStatus.SUCCEEDED
    assert job.progress_percent == 100
    output_path, media_type = await service.resolve_render_content(project.id, job.id)
    subtitle_path, subtitle_type = await service.resolve_render_content(
        project.id,
        job.id,
        subtitles=True,
    )
    assert output_path.read_bytes() == b"preview"
    assert media_type == "video/mp4"
    assert subtitle_path.is_file()
    assert subtitle_type == "text/vtt; charset=utf-8"
    assert notifications.events[-1]["status"] == "succeeded"
    await service.shutdown()
