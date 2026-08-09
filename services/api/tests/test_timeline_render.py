from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from viral_dna_api.media import MediaProcessor
from viral_dna_api.models import (
    ProductionTimeline,
    TimelineAudioTrack,
    TimelineClip,
    TimelineSubtitleCue,
    TimelineTransition,
    TimelineTransitionKind,
    VideoClipAudioMode,
)
from viral_dna_api.timeline_render import (
    TimelinePreviewRenderer,
    atempo_filters,
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


def test_timeline_render_helpers_cover_dimensions_timestamps_and_audio_rates() -> None:
    assert preview_dimensions(1080, 1920) == (540, 960)
    assert preview_dimensions(1920, 1080) == (960, 540)
    assert format_vtt_timestamp(3661.234) == "01:01:01.234"
    assert atempo_filters(4) == ["atempo=2", "atempo=2.000000"]
    assert atempo_filters(0.25) == ["atempo=0.5", "atempo=0.500000"]


@pytest.mark.asyncio
async def test_real_ffmpeg_preview_renders_video_audio_subtitles_and_crossfade(tmp_path) -> None:
    media = MediaProcessor()
    first_id, second_id = uuid4(), uuid4()
    first_path = tmp_path / "first.mp4"
    second_path = tmp_path / "second.mp4"
    audio_path = tmp_path / "source.wav"
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
    first_clip = TimelineClip(
        shot_plan_id=uuid4(),
        shot_index=1,
        candidate_id=first_id,
        candidate_content_url="/first",
        cover_url="/first-cover",
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
        cover_url="/second-cover",
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
