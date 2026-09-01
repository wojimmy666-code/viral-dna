from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from viral_dna_api.media import MediaProcessor
from viral_dna_api.models import (
    ProductionTimeline,
    SourceVideoRangeReference,
    TimelineAudioTrack,
    TimelineBackgroundAudioTrack,
    TimelineClip,
    TimelineSubtitleCue,
    TimelineTransition,
    TimelineTransitionKind,
    VideoClipAudioMode,
)
from viral_dna_api.timeline_render import (
    TimelinePreviewRenderer,
    TimelineRenderProfile,
    atempo_filters,
    build_audio_render_units,
    build_video_render_units,
    format_vtt_timestamp,
    preview_dimensions,
)


def run_ffmpeg(command: list[str]) -> None:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        creationflags=creation_flags,
        timeout=60,
    )


class CandidateResolver:
    def __init__(self, candidates: dict[UUID, Path]) -> None:
        self.candidates = candidates

    async def resolve_candidate_content(self, candidate_id, *, thumbnail=False):
        assert thumbnail is False
        return self.candidates[candidate_id], "video/mp4"


class SourceRangeResolver:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.source_calls: list[tuple[UUID, str]] = []

    async def resolve_candidate_content(self, candidate_id, *, thumbnail=False):
        raise AssertionError("连续原视频范围不应解析独立候选文件")

    async def resolve_source_video_reference(self, source_video_id, source_sha256):
        self.source_calls.append((source_video_id, source_sha256))
        return self.source_path, "video/mp4"


def source_range_clip(index: int, start_seconds: float, end_seconds: float) -> TimelineClip:
    duration = end_seconds - start_seconds
    return TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=index,
        candidate_id=uuid4(),
        candidate_content_url="/source-video",
        source_range=SourceVideoRangeReference(
            source_video_id=UUID("00000000-0000-0000-0000-000000000001"),
            source_sha256="a" * 64,
            start_pts=round(start_seconds * 1_000_000),
            end_pts=round(end_seconds * 1_000_000),
        ),
        order=index,
        candidate_duration_seconds=duration,
        trim_in_seconds=0,
        trim_out_seconds=duration,
        playback_rate=1,
        timeline_start_seconds=start_seconds,
        timeline_end_seconds=end_seconds,
        timeline_duration_seconds=duration,
        audio_mode=VideoClipAudioMode.SOURCE,
        source_audio_start_seconds=start_seconds,
        source_audio_end_seconds=end_seconds,
    )


def test_timeline_render_helpers_cover_dimensions_timestamps_and_audio_rates() -> None:
    assert preview_dimensions(1080, 1920) == (540, 960)
    assert preview_dimensions(1920, 1080) == (960, 540)
    assert format_vtt_timestamp(3661.234) == "01:01:01.234"
    assert atempo_filters(4) == ["atempo=2", "atempo=2.000000"]
    assert atempo_filters(0.25) == ["atempo=0.5", "atempo=0.500000"]


def test_adjacent_untouched_source_ranges_form_one_video_and_audio_unit() -> None:
    first = source_range_clip(1, 2.667, 4.717)
    second = source_range_clip(2, 4.717, 7.15)

    video_units = build_video_render_units([first, second])
    audio_units = build_audio_render_units([first, second])

    assert len(video_units) == 1
    assert [clip.shot_index for clip in video_units[0].clips] == [1, 2]
    assert video_units[0].duration_seconds == pytest.approx(4.483)
    assert len(audio_units) == 1
    assert [clip.shot_index for clip in audio_units[0].clips] == [1, 2]

    sub_millisecond_boundary = 1.000333
    rounded_first = source_range_clip(1, 0, sub_millisecond_boundary).model_copy(
        update={
            "trim_out_seconds": 1.0,
            "timeline_end_seconds": 1.0,
            "timeline_duration_seconds": 1.0,
        }
    )
    exact_second = source_range_clip(2, sub_millisecond_boundary, 2)
    assert len(build_video_render_units([rounded_first, exact_second])) == 1
    assert len(build_audio_render_units([rounded_first, exact_second])) == 1


def test_transition_or_source_gap_keeps_source_ranges_separate() -> None:
    first = source_range_clip(1, 0, 2)
    transitioned = first.model_copy(
        update={
            "transition_after": TimelineTransition(
                kind=TimelineTransitionKind.CROSSFADE,
                duration_seconds=0.2,
            )
        }
    )
    second = source_range_clip(2, 2, 4)
    gapped = source_range_clip(3, 4.1, 5)

    assert len(build_video_render_units([transitioned, second])) == 2
    assert len(build_audio_render_units([transitioned, second])) == 2
    assert len(build_video_render_units([second, gapped])) == 2
    assert len(build_audio_render_units([second, gapped])) == 2


@pytest.mark.asyncio
async def test_real_ffmpeg_decodes_adjacent_source_ranges_as_one_unit(tmp_path) -> None:
    media = MediaProcessor()
    source_path = tmp_path / "source.mp4"
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:d=2:r=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source_path),
        ]
    )
    first = source_range_clip(1, 0, 1)
    second = source_range_clip(2, 1, 2)
    timeline = ProductionTimeline(
        project_id=uuid4(),
        source_handoff_revision_id=uuid4(),
        revision_id=uuid4(),
        revision_number=1,
        output_aspect_ratio="16:9",
        output_width=320,
        output_height=256,
        duration_seconds=2,
        clips=[first, second],
        audio_track=TimelineAudioTrack(
            strategy="muted",
            enabled=False,
        ),
    )
    resolver = SourceRangeResolver(source_path)
    renderer = TimelinePreviewRenderer(resolver, media)

    async def progress(_value: int) -> None:
        return None

    output, _ = await renderer.render(
        timeline,
        tmp_path / "source-preview",
        source_audio_path=None,
        background_audio_path=None,
        progress=progress,
        is_cancelled=lambda: False,
        profile=TimelineRenderProfile(
            width=320,
            height=180,
            video_preset="ultrafast",
            video_crf=28,
            subtitle_mode="none",
        ),
    )

    assert len(resolver.source_calls) == 1
    assert not (tmp_path / "source-preview" / "intermediate" / "video-002.mp4").exists()
    metadata = await media.probe(output)
    assert metadata.duration_seconds == pytest.approx(2, abs=0.1)


@pytest.mark.asyncio
async def test_real_ffmpeg_preview_renders_video_audio_subtitles_and_crossfade(tmp_path) -> None:
    media = MediaProcessor()
    first_id, second_id = uuid4(), uuid4()
    first_path = tmp_path / "first.mp4"
    second_path = tmp_path / "second.mp4"
    audio_path = tmp_path / "source.wav"
    background_audio_path = tmp_path / "background.wav"
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1:r=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(first_path),
        ]
    )
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=orange:s=320x180:d=1:r=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(second_path),
        ]
    )
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=48000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ]
    )
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2:sample_rate=48000",
            "-c:a",
            "pcm_s16le",
            str(background_audio_path),
        ]
    )
    first_clip = TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=1,
        candidate_id=first_id,
        candidate_content_url="/first",
        order=1,
        candidate_duration_seconds=1,
        trim_in_seconds=0,
        trim_out_seconds=1,
        playback_rate=1,
        timeline_start_seconds=0,
        timeline_end_seconds=1,
        timeline_duration_seconds=1,
        audio_mode=VideoClipAudioMode.SOURCE,
        source_audio_start_seconds=0,
        source_audio_end_seconds=1,
        transition_after=TimelineTransition(
            kind=TimelineTransitionKind.CROSSFADE,
            duration_seconds=0.2,
        ),
    )
    second_clip = TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=2,
        candidate_id=second_id,
        candidate_content_url="/second",
        order=2,
        candidate_duration_seconds=1,
        trim_in_seconds=0,
        trim_out_seconds=1,
        playback_rate=1,
        timeline_start_seconds=0.8,
        timeline_end_seconds=1.8,
        timeline_duration_seconds=1,
        audio_mode=VideoClipAudioMode.SOURCE,
        source_audio_start_seconds=1,
        source_audio_end_seconds=2,
    )
    timeline = ProductionTimeline(
        project_id=uuid4(),
        source_handoff_revision_id=uuid4(),
        revision_id=uuid4(),
        revision_number=1,
        output_aspect_ratio="16:9",
        output_width=1920,
        output_height=1080,
        duration_seconds=1.8,
        clips=[first_clip, second_clip],
        audio_track=TimelineAudioTrack(
            strategy="per_shot",
            source_audio_url="/source.wav",
            linked_to_video=False,
            source_duration_seconds=1.8,
            source_trim_in_seconds=0.2,
            source_trim_out_seconds=1.4,
            timeline_start_seconds=0.3,
            timeline_end_seconds=1.5,
        ),
        background_audio_track=TimelineBackgroundAudioTrack(
            source_relative_path="timeline/audio/background.wav",
            source_url="/background.wav",
            name="background.wav",
            enabled=True,
            volume=0.25,
            loop=True,
            source_duration_seconds=2,
            source_trim_in_seconds=0.2,
            source_trim_out_seconds=1,
            timeline_start_seconds=0.4,
            timeline_end_seconds=1.5,
        ),
        subtitle_cues=[
            TimelineSubtitleCue(
                id="subtitle-1",
                clip_id=first_clip.id,
                text="简体中文字幕",
                language="zh-CN",
                start_seconds=0.1,
                end_seconds=0.8,
                clip_start_seconds=0.1,
                clip_end_seconds=0.8,
            )
        ],
    )
    progress_values: list[int] = []

    async def progress(value: int) -> None:
        progress_values.append(value)

    renderer = TimelinePreviewRenderer(
        CandidateResolver({first_id: first_path, second_id: second_path}),
        media,
    )
    output, subtitles = await renderer.render(
        timeline,
        tmp_path / "preview",
        source_audio_path=audio_path,
        background_audio_path=background_audio_path,
        progress=progress,
        is_cancelled=lambda: False,
    )

    metadata = await media.probe(output)
    assert metadata.has_audio is True
    assert metadata.width == 960
    assert metadata.height == 540
    assert metadata.duration_seconds == pytest.approx(1.8, abs=0.2)
    assert subtitles is not None
    assert subtitles.read_text("utf-8").startswith("WEBVTT")
    assert progress_values[-1] == 100

    final_output, final_subtitles = await renderer.render(
        timeline,
        tmp_path / "final",
        source_audio_path=audio_path,
        background_audio_path=background_audio_path,
        progress=progress,
        is_cancelled=lambda: False,
        profile=TimelineRenderProfile(
            width=320,
            height=180,
            video_preset="ultrafast",
            video_crf=26,
            audio_bitrate="128k",
            output_filename="final.mp4",
            subtitle_filename="subtitles.vtt",
            subtitle_mode="burned",
            operation_label="最终成片",
            error_prefix="final",
        ),
    )
    final_metadata = await media.probe(final_output)
    assert final_metadata.width == 320
    assert final_metadata.height == 180
    assert final_metadata.has_audio is True
    assert final_subtitles is not None


@pytest.mark.asyncio
async def test_real_ffmpeg_preview_uses_candidate_embedded_audio_without_source_track(
    tmp_path,
) -> None:
    media = MediaProcessor()
    candidate_id = uuid4()
    candidate_path = tmp_path / "candidate-with-audio.mp4"
    run_ffmpeg(
        [
            media.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=320x180:d=1:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=1:sample_rate=48000",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(candidate_path),
        ]
    )
    clip = TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=1,
        candidate_id=candidate_id,
        candidate_content_url="/candidate-with-audio",
        order=1,
        candidate_duration_seconds=1,
        trim_in_seconds=0,
        trim_out_seconds=1,
        playback_rate=1,
        timeline_start_seconds=0,
        timeline_end_seconds=1,
        timeline_duration_seconds=1,
        audio_mode=VideoClipAudioMode.CANDIDATE,
        candidate_audio_available=True,
        source_audio_start_seconds=0,
        source_audio_end_seconds=1,
    )
    timeline = ProductionTimeline(
        project_id=uuid4(),
        source_handoff_revision_id=uuid4(),
        revision_id=uuid4(),
        revision_number=1,
        output_aspect_ratio="16:9",
        output_width=1920,
        output_height=1080,
        duration_seconds=1,
        clips=[clip],
        audio_track=TimelineAudioTrack(
            strategy="per_shot",
            source_audio_url=None,
            linked_to_video=False,
            source_duration_seconds=1,
            source_trim_in_seconds=0,
            source_trim_out_seconds=1,
            timeline_start_seconds=0,
            timeline_end_seconds=1,
        ),
    )
    renderer = TimelinePreviewRenderer(
        CandidateResolver({candidate_id: candidate_path}),
        media,
    )

    async def progress(_value: int) -> None:
        return None

    output, _ = await renderer.render(
        timeline,
        tmp_path / "candidate-audio-preview",
        source_audio_path=None,
        background_audio_path=None,
        progress=progress,
        is_cancelled=lambda: False,
        profile=TimelineRenderProfile(
            width=320,
            height=180,
            video_preset="ultrafast",
            video_crf=28,
            subtitle_mode="none",
        ),
    )

    metadata = await media.probe(output)
    assert metadata.has_audio is True
    assert metadata.duration_seconds == pytest.approx(1, abs=0.15)
