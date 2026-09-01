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
    TimelineChangeKind,
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
    def __init__(self, manifest: EditingHandoffManifest, source_path: Path | None = None) -> None:
        self.manifest = manifest
        self.source_path = source_path

    async def get_editing_handoff(self, project_id):
        assert project_id == self.manifest.project_id
        return self.manifest

    async def resolve_candidate_content(self, candidate_id, *, thumbnail=False):
        if self.source_path is not None:
            return self.source_path, "video/mp4"
        raise AssertionError("测试渲染器不应解析候选媒体")


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
    ):
        assert source_audio_path is not None
        assert background_audio_path is None
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
async def test_timeline_only_allows_verified_candidate_audio(timeline_context):
    service, _, project, _ = timeline_context
    timeline = await service.get_timeline(project.id)
    first = timeline.clips[0]

    with pytest.raises(TimelineServiceError) as unavailable:
        await service.update_timeline(
            project.id,
            TimelineUpdateRequest(
                expected_revision_id=timeline.revision_id,
                clip_updates=[
                    TimelineClipUpdate(
                        clip_id=first.id,
                        audio_mode=VideoClipAudioMode.CANDIDATE,
                    )
                ],
                summary="尝试使用不存在的候选音频",
            ),
        )
    assert unavailable.value.code == "timeline_candidate_audio_unavailable"


@pytest.mark.asyncio
async def test_timeline_initializes_with_verified_candidate_audio(timeline_context):
    service, _, project, _ = timeline_context
    handoff = service.handoff_provider.manifest
    first, second = handoff.clips
    service.handoff_provider.manifest = handoff.model_copy(
        update={
            "audio_strategy": "per_shot",
            "clips": [
                first.model_copy(
                    update={
                        "audio_mode": VideoClipAudioMode.CANDIDATE,
                        "candidate_audio_available": True,
                    }
                ),
                second,
            ],
        }
    )

    timeline = await service.get_timeline(project.id)
    initialized = timeline.clips[0]
    assert initialized.audio_mode == VideoClipAudioMode.CANDIDATE
    assert initialized.candidate_audio_available is True

    muted = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=timeline.revision_id,
            clip_updates=[
                TimelineClipUpdate(
                    clip_id=initialized.id,
                    audio_mode=VideoClipAudioMode.MUTED,
                )
            ],
            summary="暂时静音",
        ),
    )
    restored = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=muted.revision_id,
            clip_updates=[
                TimelineClipUpdate(
                    clip_id=initialized.id,
                    audio_mode=VideoClipAudioMode.CANDIDATE,
                )
            ],
            summary="恢复候选新音频",
        ),
    )
    assert restored.clips[0].audio_mode == VideoClipAudioMode.CANDIDATE


@pytest.mark.asyncio
async def test_timeline_does_not_create_per_shot_covers(timeline_context):
    service, _, project, _ = timeline_context
    timeline = await service.get_timeline(project.id)

    assert not hasattr(service, "resolve_clip_cover")
    assert not hasattr(service, "resolve_clip_preview_frame")
    assert all("cover_url" not in clip.model_fields_set for clip in timeline.clips)


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
async def test_timeline_syncs_replaced_video_without_losing_editor_choices(
    timeline_context,
):
    service, workspace, project, _ = timeline_context
    original = await service.get_timeline(project.id)
    first, second = original.clips
    customized = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=original.revision_id,
            clip_order=[second.id, first.id],
            clip_updates=[
                TimelineClipUpdate(
                    clip_id=first.id,
                    timeline_duration_seconds=3.5,
                    audio_mode=VideoClipAudioMode.MUTED,
                    audio_volume=0.35,
                )
            ],
            summary="调整分镜顺序和声音",
        ),
    )
    staged = customized.model_copy(
        update={
            "last_preview_job_id": uuid4(),
            "last_export_job_id": uuid4(),
        }
    )
    timeline_path = (
        workspace.production_paths(project.record_id, project.id).timelines
        / "timeline.json"
    )
    service._write_json_atomic(timeline_path, staged.model_dump(mode="json"))

    replacement_id = UUID("00000000-0000-0000-0000-000000000103")
    service.repository.candidates[replacement_id] = SimpleNamespace(duration_seconds=6.0)
    provider = service.handoff_provider
    first_source, second_source = provider.manifest.clips
    replacement_source = first_source.model_copy(
        update={
            "candidate_id": replacement_id,
            "candidate_content_url": f"/candidates/{replacement_id}",
            "timeline_end_seconds": 6,
            "timeline_duration_seconds": 6,
            "trim_out_seconds": 6,
            "video_playback_rate": 1,
        }
    )
    provider.manifest = provider.manifest.model_copy(
        update={
            "revision_id": uuid4(),
            "timeline_duration_seconds": 10,
            "clips": [
                replacement_source,
                second_source.model_copy(
                    update={
                        "timeline_start_seconds": 6,
                        "timeline_end_seconds": 10,
                    }
                ),
            ],
        }
    )

    synced = await service.get_timeline(project.id)
    loaded_again = await service.get_timeline(project.id)
    synced_first = next(
        clip for clip in synced.clips if clip.shot_plan_id == first.shot_plan_id
    )
    synced_second = next(
        clip for clip in synced.clips if clip.shot_plan_id == second.shot_plan_id
    )
    revisions = await service.list_revisions(project.id)

    assert synced.revision_number == 3
    assert loaded_again.revision_id == synced.revision_id
    assert synced.source_handoff_revision_id == provider.manifest.revision_id
    assert [clip.id for clip in synced.clips] == [second.id, first.id]
    assert synced_first.id == first.id
    assert synced_first.candidate_id == replacement_id
    assert synced_first.candidate_content_url == f"/candidates/{replacement_id}"
    assert synced_first.trim_in_seconds == 0
    assert synced_first.trim_out_seconds == 6
    assert synced_first.timeline_duration_seconds == 3.5
    assert synced_first.playback_rate == pytest.approx(6 / 3.5)
    assert synced_first.audio_mode == VideoClipAudioMode.MUTED
    assert synced_first.audio_volume == pytest.approx(0.35)
    assert synced_second.candidate_id == second.candidate_id
    assert synced.subtitle_cues[0].clip_id == first.id
    assert synced.last_preview_job_id is None
    assert synced.last_export_job_id is None
    assert revisions.items[-1].change_kind == TimelineChangeKind.HANDOFF_SYNCED

    restored = await service.restore_revision(
        project.id,
        original.revision_id,
        TimelineRestoreRequest(expected_revision_id=synced.revision_id),
    )
    restored_first = next(
        clip for clip in restored.clips if clip.shot_plan_id == first.shot_plan_id
    )
    assert restored.revision_number == 5
    assert restored.source_handoff_revision_id == provider.manifest.revision_id
    assert restored_first.candidate_id == replacement_id
    assert [clip.shot_plan_id for clip in restored.clips] == [
        first.shot_plan_id,
        second.shot_plan_id,
    ]


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
async def test_background_audio_is_versioned_and_can_be_adjusted(timeline_context):
    service, _, project, _ = timeline_context
    original = await service.get_timeline(project.id)

    uploaded = await service.set_background_audio(
        project.id,
        original.revision_id,
        filename="music.wav",
        content_type="audio/wav",
        content=b"RIFF-test-audio",
        duration_seconds=12.5,
    )

    assert uploaded.revision_number == 2
    assert uploaded.background_audio_track.enabled is True
    assert uploaded.background_audio_track.name == "music.wav"
    assert uploaded.background_audio_track.source_duration_seconds == pytest.approx(12.5)
    assert uploaded.background_audio_track.source_trim_out_seconds == pytest.approx(12.5)
    assert uploaded.background_audio_track.timeline_end_seconds == pytest.approx(8)
    audio_path, media_type = await service.resolve_background_audio(project.id)
    assert audio_path.read_bytes() == b"RIFF-test-audio"
    assert media_type in {"audio/wav", "audio/x-wav"}

    adjusted_track = uploaded.background_audio_track.model_copy(
        update={"volume": 0.2, "loop": False},
    )
    adjusted = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=uploaded.revision_id,
            background_audio_track=adjusted_track,
            summary="调整附加音轨",
        ),
    )

    assert adjusted.revision_number == 3
    assert adjusted.background_audio_track.volume == pytest.approx(0.2)
    assert adjusted.background_audio_track.loop is False


@pytest.mark.asyncio
async def test_timeline_normalizes_unlinked_audio_and_manual_subtitle_ranges(
    timeline_context,
):
    service, _, project, _ = timeline_context
    original = await service.get_timeline(project.id)
    detached_cue = original.subtitle_cues[0].model_copy(
        update={
            "clip_id": None,
            "clip_start_seconds": None,
            "clip_end_seconds": None,
            "start_seconds": 2.25,
            "end_seconds": 3.75,
        }
    )
    audio = original.audio_track.model_copy(
        update={
            "linked_to_video": False,
            "source_trim_in_seconds": 1,
            "source_trim_out_seconds": 5,
            "timeline_start_seconds": 2,
            "timeline_end_seconds": 6,
        }
    )

    updated = await service.update_timeline(
        project.id,
        TimelineUpdateRequest(
            expected_revision_id=original.revision_id,
            audio_track=audio,
            subtitle_cues=[detached_cue],
            summary="调整原音与字幕位置",
        ),
    )

    assert updated.audio_track.linked_to_video is False
    assert updated.audio_track.source_duration_seconds == pytest.approx(8)
    assert updated.audio_track.timeline_start_seconds == pytest.approx(2)
    assert updated.audio_track.timeline_end_seconds == pytest.approx(6)
    assert updated.subtitle_cues[0].clip_id is None
    assert updated.subtitle_cues[0].start_seconds == pytest.approx(2.25)
    assert updated.subtitle_cues[0].end_seconds == pytest.approx(3.75)


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
