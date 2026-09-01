from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from .media import MediaProcessor
from .models import (
    ProductionTimeline,
    TimelineBackgroundAudioTrack,
    TimelineClip,
    TimelineTransitionKind,
    VideoClipAudioMode,
)

ProgressCallback = Callable[[int], Awaitable[None]]
CancellationCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class TimelineRenderProfile:
    width: int
    height: int
    video_preset: str = "veryfast"
    video_crf: int = 30
    audio_bitrate: str = "128k"
    output_filename: str = "preview.mp4"
    subtitle_filename: str = "preview.vtt"
    subtitle_mode: Literal["burned", "embedded", "none"] = "embedded"
    operation_label: str = "低清预览"
    error_prefix: str = "preview"
    timeout_seconds: int = 600


class TimelineMediaResolver(Protocol):
    async def resolve_candidate_content(
        self,
        candidate_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]: ...

    async def resolve_source_video_reference(
        self,
        source_video_id: UUID,
        source_sha256: str,
    ) -> tuple[Path, str]: ...


class TimelineRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TimelineVideoUnit:
    """One independently decoded video unit.

    Consecutive untouched source ranges share one unit so there is no synthetic
    cut at their internal shot boundary.
    """

    clips: tuple[TimelineClip, ...]

    @property
    def first(self) -> TimelineClip:
        return self.clips[0]

    @property
    def last(self) -> TimelineClip:
        return self.clips[-1]

    @property
    def duration_seconds(self) -> float:
        if self.is_source_range and all(_identity_source_clip(clip) for clip in self.clips):
            source_range = self.first.source_range
            first_bounds = _source_range_bounds_pts(self.first)
            last_bounds = _source_range_bounds_pts(self.last)
            if source_range is not None and first_bounds is not None and last_bounds is not None:
                return (last_bounds[1] - first_bounds[0]) * (
                    source_range.time_base_numerator / source_range.time_base_denominator
                )
        return sum(clip.timeline_duration_seconds for clip in self.clips)

    @property
    def is_source_range(self) -> bool:
        return self.first.source_range is not None


@dataclass(frozen=True, slots=True)
class TimelineAudioUnit:
    """One independently decoded source-audio or silence unit."""

    clips: tuple[TimelineClip, ...]

    @property
    def first(self) -> TimelineClip:
        return self.clips[0]

    @property
    def last(self) -> TimelineClip:
        return self.clips[-1]

    @property
    def duration_seconds(self) -> float:
        if all(_identity_source_audio_clip(clip) for clip in self.clips):
            return self.last.source_audio_end_seconds - self.first.source_audio_start_seconds
        return sum(clip.timeline_duration_seconds for clip in self.clips)


def _source_range_bounds_pts(clip: TimelineClip) -> tuple[int, int] | None:
    source_range = clip.source_range
    if source_range is None:
        return None
    seconds_to_pts = source_range.time_base_denominator / source_range.time_base_numerator
    start_pts = (
        source_range.start_pts
        if abs(clip.trim_in_seconds) <= 1e-6
        else source_range.start_pts + round(clip.trim_in_seconds * seconds_to_pts)
    )
    end_pts = (
        source_range.end_pts
        if abs(clip.trim_out_seconds - clip.candidate_duration_seconds) <= 0.001
        else source_range.start_pts + round(clip.trim_out_seconds * seconds_to_pts)
    )
    return start_pts, end_pts


def _identity_source_clip(clip: TimelineClip) -> bool:
    if clip.source_range is None:
        return False
    source_duration = clip.trim_out_seconds - clip.trim_in_seconds
    return (
        abs(clip.playback_rate - 1) <= 1e-6
        and abs(source_duration - clip.timeline_duration_seconds) <= 0.001
    )


def _source_clips_are_contiguous(left: TimelineClip, right: TimelineClip) -> bool:
    left_range = left.source_range
    right_range = right.source_range
    left_bounds = _source_range_bounds_pts(left)
    right_bounds = _source_range_bounds_pts(right)
    return bool(
        left_range is not None
        and right_range is not None
        and left_bounds is not None
        and right_bounds is not None
        and _identity_source_clip(left)
        and _identity_source_clip(right)
        and left.transition_after.kind == TimelineTransitionKind.NONE
        and left_range.source_video_id == right_range.source_video_id
        and left_range.source_sha256 == right_range.source_sha256
        and left_range.time_base_numerator == right_range.time_base_numerator
        and left_range.time_base_denominator == right_range.time_base_denominator
        and left_bounds[1] == right_bounds[0]
    )


def build_video_render_units(clips: list[TimelineClip]) -> list[TimelineVideoUnit]:
    units: list[TimelineVideoUnit] = []
    for clip in clips:
        if units and _source_clips_are_contiguous(units[-1].last, clip):
            units[-1] = TimelineVideoUnit((*units[-1].clips, clip))
        else:
            units.append(TimelineVideoUnit((clip,)))
    return units


def _identity_source_audio_clip(clip: TimelineClip) -> bool:
    source_duration = clip.source_audio_end_seconds - clip.source_audio_start_seconds
    return (
        clip.audio_mode == VideoClipAudioMode.SOURCE
        and abs(source_duration - clip.timeline_duration_seconds) <= 0.001
    )


def _audio_clips_are_contiguous(left: TimelineClip, right: TimelineClip) -> bool:
    if left.transition_after.kind != TimelineTransitionKind.NONE:
        return False
    if left.audio_mode == VideoClipAudioMode.MUTED:
        return right.audio_mode == VideoClipAudioMode.MUTED
    return bool(
        _identity_source_audio_clip(left)
        and _identity_source_audio_clip(right)
        and abs(left.audio_volume - right.audio_volume) <= 1e-6
        and abs(left.source_audio_end_seconds - right.source_audio_start_seconds) <= 1e-6
    )


def build_audio_render_units(clips: list[TimelineClip]) -> list[TimelineAudioUnit]:
    units: list[TimelineAudioUnit] = []
    for clip in clips:
        if units and _audio_clips_are_contiguous(units[-1].last, clip):
            units[-1] = TimelineAudioUnit((*units[-1].clips, clip))
        else:
            units.append(TimelineAudioUnit((clip,)))
    return units


def preview_dimensions(width: int, height: int, max_edge: int = 960) -> tuple[int, int]:
    scale = min(1.0, max_edge / max(width, height))
    preview_width = max(2, int(width * scale) // 2 * 2)
    preview_height = max(2, int(height * scale) // 2 * 2)
    return preview_width, preview_height


def format_vtt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def atempo_filters(rate: float) -> list[str]:
    """Split arbitrary positive audio tempo into FFmpeg's supported 0.5-2.0 stages."""
    if rate <= 0:
        raise ValueError("音频速率必须大于 0")
    filters: list[str] = []
    remaining = rate
    while remaining > 2:
        filters.append("atempo=2")
        remaining /= 2
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return filters


def _concat_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def _subtitle_filter_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


class TimelinePreviewRenderer:
    """Render a low-resolution review copy from an immutable timeline revision."""

    def __init__(
        self,
        media_resolver: TimelineMediaResolver,
        media_processor: MediaProcessor | None = None,
    ) -> None:
        self.media_resolver = media_resolver
        self.media_processor = media_processor or MediaProcessor()
        self.ffmpeg = self.media_processor.ffmpeg

    async def render(
        self,
        timeline: ProductionTimeline,
        output_root: Path,
        *,
        source_audio_path: Path | None,
        background_audio_path: Path | None,
        progress: ProgressCallback,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile | None = None,
    ) -> tuple[Path, Path | None]:
        enabled_clips = [clip for clip in timeline.clips if clip.enabled]
        if not enabled_clips:
            raise TimelineRenderError("timeline_empty", "时间线没有可渲染的视频片段")

        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        intermediate_root = output_root / "intermediate"
        await asyncio.to_thread(intermediate_root.mkdir, parents=True, exist_ok=True)
        if profile is None:
            preview_width, preview_height = preview_dimensions(
                timeline.output_width,
                timeline.output_height,
            )
            profile = TimelineRenderProfile(
                width=preview_width,
                height=preview_height,
            )

        await progress(4)
        video_units = build_video_render_units(enabled_clips)
        clip_paths: list[Path] = []
        for index, unit in enumerate(video_units):
            self._require_not_cancelled(is_cancelled)
            output_path = intermediate_root / f"video-{index + 1:03d}.mp4"
            previous_transition = (
                video_units[index - 1].last.transition_after if index > 0 else None
            )
            fade_in_seconds = (
                previous_transition.duration_seconds
                if previous_transition
                and previous_transition.kind == TimelineTransitionKind.FADE
                else 0
            )
            fade_out_seconds = (
                unit.last.transition_after.duration_seconds
                if unit.last.transition_after.kind == TimelineTransitionKind.FADE
                else 0
            )
            if unit.is_source_range:
                source_range = unit.first.source_range
                assert source_range is not None
                source_path, _ = await self.media_resolver.resolve_source_video_reference(
                    source_range.source_video_id,
                    source_range.source_sha256,
                )
                await self._render_source_video_unit(
                    source_path,
                    output_path,
                    unit,
                    width=profile.width,
                    height=profile.height,
                    fps=timeline.fps,
                    fade_in_seconds=fade_in_seconds,
                    fade_out_seconds=fade_out_seconds,
                    is_cancelled=is_cancelled,
                    profile=profile,
                )
            else:
                clip = unit.first
                source_path, _ = await self.media_resolver.resolve_candidate_content(
                    clip.candidate_id
                )
                await self._render_video_clip(
                    source_path,
                    output_path,
                    clip,
                    width=profile.width,
                    height=profile.height,
                    fps=timeline.fps,
                    fade_in_seconds=fade_in_seconds,
                    fade_out_seconds=fade_out_seconds,
                    is_cancelled=is_cancelled,
                    profile=profile,
                )
            clip_paths.append(output_path)
            await progress(8 + round(37 * (index + 1) / len(video_units)))

        assembled_video = intermediate_root / "video-track.mp4"
        await self._assemble_video_track(
            clip_paths,
            video_units,
            assembled_video,
            is_cancelled,
            profile=profile,
        )
        await progress(55)

        audio_path: Path | None = None
        if (
            timeline.audio_track.enabled
            and timeline.audio_track.strategy != "muted"
        ):
            audio_units = build_audio_render_units(enabled_clips)
            audio_segments: list[Path] = []
            for index, unit in enumerate(audio_units):
                segment_path = intermediate_root / f"audio-{index + 1:03d}.m4a"
                unit_source_path: Path | None = None
                if unit.first.audio_mode == VideoClipAudioMode.SOURCE:
                    if (
                        source_audio_path is None
                        or not await asyncio.to_thread(source_audio_path.is_file)
                    ):
                        raise TimelineRenderError(
                            "timeline_source_audio_missing",
                            f"分镜 {unit.first.shot_index} 选择了原音频，但原音频文件不存在",
                        )
                    unit_source_path = source_audio_path
                elif unit.first.audio_mode == VideoClipAudioMode.CANDIDATE:
                    unit_source_path, _ = await self.media_resolver.resolve_candidate_content(
                        unit.first.candidate_id
                    )
                await self._render_audio_unit(
                    unit_source_path,
                    segment_path,
                    unit,
                    track_volume=timeline.audio_track.volume,
                    normalize_loudness=timeline.audio_track.normalize_loudness,
                    is_cancelled=is_cancelled,
                    profile=profile,
                )
                audio_segments.append(segment_path)
                await progress(57 + round(18 * (index + 1) / len(audio_units)))
            audio_path = intermediate_root / "audio-track.m4a"
            await self._assemble_audio_track(
                audio_segments,
                audio_units,
                audio_path,
                is_cancelled,
                profile=profile,
            )
            if not timeline.audio_track.linked_to_video:
                placed_audio = intermediate_root / "audio-track-placed.m4a"
                await self._render_placed_audio(
                    audio_path,
                    placed_audio,
                    duration_seconds=timeline.duration_seconds,
                    source_trim_in_seconds=timeline.audio_track.source_trim_in_seconds,
                    source_trim_out_seconds=timeline.audio_track.source_trim_out_seconds,
                    timeline_start_seconds=timeline.audio_track.timeline_start_seconds,
                    timeline_end_seconds=timeline.audio_track.timeline_end_seconds,
                    volume=1,
                    loop=False,
                    is_cancelled=is_cancelled,
                    profile=profile,
                    kind="原音轨",
                )
                audio_path = placed_audio

        if (
            timeline.background_audio_track.enabled
            and background_audio_path is not None
            and await asyncio.to_thread(background_audio_path.is_file)
        ):
            rendered_background = intermediate_root / "background-audio.m4a"
            await self._render_background_audio(
                background_audio_path,
                rendered_background,
                duration_seconds=timeline.duration_seconds,
                track=timeline.background_audio_track,
                is_cancelled=is_cancelled,
                profile=profile,
            )
            if audio_path is None:
                audio_path = rendered_background
            else:
                mixed_audio = intermediate_root / "mixed-audio.m4a"
                await self._mix_audio_tracks(
                    audio_path,
                    rendered_background,
                    mixed_audio,
                    duration_seconds=timeline.duration_seconds,
                    is_cancelled=is_cancelled,
                    profile=profile,
                )
                audio_path = mixed_audio

        subtitle_path = self._write_subtitles(
            timeline,
            output_root / profile.subtitle_filename,
        )
        await progress(82)
        output_path = output_root / profile.output_filename
        await self._mux_preview(
            assembled_video,
            output_path,
            duration_seconds=timeline.duration_seconds,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            is_cancelled=is_cancelled,
            profile=profile,
        )
        await progress(100)
        return output_path, subtitle_path

    async def _render_background_audio(
        self,
        source_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        track: TimelineBackgroundAudioTrack,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        await self._render_placed_audio(
            source_path,
            output_path,
            duration_seconds=duration_seconds,
            source_trim_in_seconds=track.source_trim_in_seconds,
            source_trim_out_seconds=track.source_trim_out_seconds,
            timeline_start_seconds=track.timeline_start_seconds,
            timeline_end_seconds=track.timeline_end_seconds,
            volume=track.volume,
            loop=track.loop,
            is_cancelled=is_cancelled,
            profile=profile,
            kind="附加音轨",
        )

    async def _render_placed_audio(
        self,
        source_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        source_trim_in_seconds: float,
        source_trim_out_seconds: float | None,
        timeline_start_seconds: float,
        timeline_end_seconds: float | None,
        volume: float,
        loop: bool,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
        kind: str,
    ) -> None:
        start = min(max(0.0, timeline_start_seconds), duration_seconds)
        end = min(
            duration_seconds,
            max(start + 0.05, timeline_end_seconds or duration_seconds),
        )
        placed_duration = max(0.05, end - start)
        source_start = max(0.0, source_trim_in_seconds)
        source_end = source_trim_out_seconds or (source_start + placed_duration)
        source_span = max(0.05, source_end - source_start)
        filters = [
            f"atrim=start={source_start:.6f}:end={source_end:.6f}",
            "asetpts=PTS-STARTPTS",
            f"volume={volume:.6f}",
        ]
        if loop:
            sample_count = max(1, round(source_span * 48000))
            filters.extend(
                [
                    "aresample=48000",
                    f"aloop=loop=-1:size={sample_count}",
                ]
            )
        filters.extend(
            [
                "apad",
                f"atrim=duration={placed_duration:.6f}",
                f"adelay={round(start * 1000)}:all=1",
                "apad",
                f"atrim=duration={duration_seconds:.6f}",
            ]
        )
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source_path),
            "-filter:a",
            ",".join(filters),
            "-t",
            f"{duration_seconds:.6f}",
            "-c:a",
            "aac",
            "-b:a",
            profile.audio_bitrate,
            str(output_path),
        ]
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_background_audio_failed",
            message=f"{profile.operation_label}{kind}处理失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _mix_audio_tracks(
        self,
        source_path: Path,
        background_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        await self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-i",
                str(background_path),
                "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[a]",
                "-map",
                "[a]",
                "-t",
                f"{duration_seconds:.6f}",
                "-c:a",
                "aac",
                "-b:a",
                profile.audio_bitrate,
                str(output_path),
            ],
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_audio_mix_failed",
            message=f"{profile.operation_label}音轨混合失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _render_source_video_unit(
        self,
        source_path: Path,
        output_path: Path,
        unit: TimelineVideoUnit,
        *,
        width: int,
        height: int,
        fps: int,
        fade_in_seconds: float,
        fade_out_seconds: float,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        first_range = unit.first.source_range
        first_bounds = _source_range_bounds_pts(unit.first)
        last_bounds = _source_range_bounds_pts(unit.last)
        if first_range is None or first_bounds is None or last_bounds is None:
            raise TimelineRenderError(
                f"{profile.error_prefix}_source_range_invalid",
                "原视频时间范围无效",
            )
        pts_to_seconds = (
            first_range.time_base_numerator / first_range.time_base_denominator
        )
        source_start = first_bounds[0] * pts_to_seconds
        source_end = last_bounds[1] * pts_to_seconds
        source_duration = source_end - source_start
        target_duration = unit.duration_seconds
        if source_duration <= 0 or target_duration <= 0:
            raise TimelineRenderError(
                f"{profile.error_prefix}_source_range_invalid",
                "原视频时间范围时长无效",
            )
        playback_rate = source_duration / target_duration
        filters = [
            f"setpts=(PTS-STARTPTS)/{playback_rate:.8f}",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            f"fps={fps}",
            "format=yuv420p",
        ]
        if fade_in_seconds > 0:
            filters.append(
                f"fade=t=in:st=0:d={min(fade_in_seconds, target_duration / 2):.6f}"
            )
        if fade_out_seconds > 0:
            duration = min(fade_out_seconds, target_duration / 2)
            filters.append(
                f"fade=t=out:st={max(0, target_duration - duration):.6f}:d={duration:.6f}"
            )
        await self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-ss",
                f"{source_start:.6f}",
                "-an",
                "-vf",
                ",".join(filters),
                "-t",
                f"{target_duration:.6f}",
                "-c:v",
                "libx264",
                "-preset",
                profile.video_preset,
                "-crf",
                str(profile.video_crf),
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_source_range_failed",
            message=(
                f"分镜 {unit.first.shot_index}–{unit.last.shot_index} 的"
                f"{profile.operation_label}原视频范围转码失败"
            ),
            timeout_seconds=profile.timeout_seconds,
        )

    async def _render_video_clip(
        self,
        source_path: Path,
        output_path: Path,
        clip: TimelineClip,
        *,
        width: int,
        height: int,
        fps: int,
        fade_in_seconds: float,
        fade_out_seconds: float,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        target_duration = clip.timeline_duration_seconds
        filters = [
            f"setpts=(PTS-STARTPTS)/{clip.playback_rate:.8f}",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            f"fps={fps}",
            "format=yuv420p",
            "tpad=stop_mode=clone:stop_duration=2",
            f"trim=duration={target_duration:.6f}",
            "setpts=PTS-STARTPTS",
        ]
        if fade_in_seconds > 0:
            filters.append(
                f"fade=t=in:st=0:d={min(fade_in_seconds, target_duration / 2):.6f}"
            )
        if fade_out_seconds > 0:
            duration = min(fade_out_seconds, target_duration / 2)
            filters.append(
                f"fade=t=out:st={max(0, target_duration - duration):.6f}:d={duration:.6f}"
            )
        await self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{clip.trim_in_seconds:.6f}",
                "-t",
                f"{clip.trim_out_seconds - clip.trim_in_seconds:.6f}",
                "-i",
                str(source_path),
                "-an",
                "-vf",
                ",".join(filters),
                "-t",
                f"{target_duration:.6f}",
                "-c:v",
                "libx264",
                "-preset",
                profile.video_preset,
                "-crf",
                str(profile.video_crf),
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_clip_failed",
            message=f"分镜 {clip.shot_index} 的{profile.operation_label}转码失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _assemble_video_track(
        self,
        inputs: list[Path],
        units: list[TimelineVideoUnit],
        output_path: Path,
        is_cancelled: CancellationCheck,
        *,
        profile: TimelineRenderProfile,
    ) -> None:
        if len(inputs) == 1:
            await self._copy_media(inputs[0], output_path, is_cancelled, profile=profile)
            return
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        current = "0:v"
        for index in range(1, len(inputs)):
            output = f"v{index}"
            transition = units[index - 1].last.transition_after
            if transition.kind == TimelineTransitionKind.CROSSFADE:
                duration_before = sum(item.duration_seconds for item in units[:index])
                overlap_before = sum(
                    item.last.transition_after.duration_seconds
                    for item in units[: index - 1]
                    if item.last.transition_after.kind == TimelineTransitionKind.CROSSFADE
                )
                offset = max(0, duration_before - overlap_before - transition.duration_seconds)
                filters.append(
                    f"[{current}][{index}:v]xfade=transition=fade:"
                    f"duration={transition.duration_seconds:.6f}:offset={offset:.6f}[{output}]"
                )
            else:
                filters.append(f"[{current}][{index}:v]concat=n=2:v=1:a=0[{output}]")
            current = output
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[{current}]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                profile.video_preset,
                "-crf",
                str(profile.video_crf),
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_video_track_failed",
            message=f"{profile.operation_label}视频轨合成失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _render_audio_unit(
        self,
        source_media_path: Path | None,
        output_path: Path,
        unit: TimelineAudioUnit,
        *,
        track_volume: float,
        normalize_loudness: bool,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        duration = unit.duration_seconds
        if unit.first.audio_mode == VideoClipAudioMode.MUTED:
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                f"{duration:.6f}",
                "-c:a",
                "aac",
                "-b:a",
                profile.audio_bitrate,
                str(output_path),
            ]
        else:
            if source_media_path is None:
                raise TimelineRenderError(
                    "timeline_audio_source_missing",
                    f"分镜 {unit.first.shot_index} 的音频来源不存在",
                )
            if unit.first.audio_mode == VideoClipAudioMode.CANDIDATE:
                source_start = unit.first.trim_in_seconds
                source_end = unit.last.trim_out_seconds
            else:
                source_start = unit.first.source_audio_start_seconds
                source_end = unit.last.source_audio_end_seconds
            source_duration = source_end - source_start
            tempo = source_duration / duration
            filters = [
                f"atrim=start={source_start:.6f}:end={source_end:.6f}",
                "asetpts=PTS-STARTPTS",
                *atempo_filters(tempo),
                f"volume={track_volume * unit.first.audio_volume:.6f}",
            ]
            if normalize_loudness:
                filters.append("loudnorm=I=-16:LRA=11:TP=-1.5")
            filters.extend(["apad", f"atrim=duration={duration:.6f}"])
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_media_path),
                "-vn",
                "-af",
                ",".join(filters),
                "-t",
                f"{duration:.6f}",
                "-c:a",
                "aac",
                "-b:a",
                profile.audio_bitrate,
                str(output_path),
            ]
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_audio_clip_failed",
            message=(
                f"分镜 {unit.first.shot_index}–{unit.last.shot_index} 的原音轨映射失败"
            ),
            timeout_seconds=profile.timeout_seconds,
        )

    async def _assemble_audio_track(
        self,
        inputs: list[Path],
        units: list[TimelineAudioUnit],
        output_path: Path,
        is_cancelled: CancellationCheck,
        *,
        profile: TimelineRenderProfile,
    ) -> None:
        if len(inputs) == 1:
            await self._copy_media(inputs[0], output_path, is_cancelled, profile=profile)
            return
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        current = "0:a"
        for index in range(1, len(inputs)):
            output = f"a{index}"
            transition = units[index - 1].last.transition_after
            if transition.kind == TimelineTransitionKind.CROSSFADE:
                filters.append(
                    f"[{current}][{index}:a]acrossfade=d={transition.duration_seconds:.6f}:"
                    f"c1=tri:c2=tri[{output}]"
                )
            else:
                filters.append(f"[{current}][{index}:a]concat=n=2:v=0:a=1[{output}]")
            current = output
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[{current}]",
                "-c:a",
                "aac",
                "-b:a",
                profile.audio_bitrate,
                str(output_path),
            ]
        )
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_audio_track_failed",
            message=f"{profile.operation_label}原音轨合成失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _copy_media(
        self,
        source_path: Path,
        output_path: Path,
        is_cancelled: CancellationCheck,
        *,
        profile: TimelineRenderProfile,
    ) -> None:
        await self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-c",
                "copy",
                str(output_path),
            ],
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_track_copy_failed",
            message=f"{profile.operation_label}轨道准备失败",
            timeout_seconds=profile.timeout_seconds,
        )

    def _write_subtitles(
        self,
        timeline: ProductionTimeline,
        output_path: Path,
    ) -> Path | None:
        enabled_clip_ids = {clip.id for clip in timeline.clips if clip.enabled}
        cues = [
            cue
            for cue in timeline.subtitle_cues
            if cue.enabled and (cue.clip_id is None or cue.clip_id in enabled_clip_ids)
        ]
        if not cues:
            return None
        blocks = ["WEBVTT\n"]
        for index, cue in enumerate(sorted(cues, key=lambda item: item.start_seconds), start=1):
            text = cue.text.replace("\r", "").strip()
            blocks.append(
                f"{index}\n{format_vtt_timestamp(cue.start_seconds)} --> "
                f"{format_vtt_timestamp(cue.end_seconds)}\n{text}\n"
            )
        output_path.write_text("\n".join(blocks), encoding="utf-8")
        return output_path

    async def _mux_preview(
        self,
        video_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        audio_path: Path | None,
        subtitle_path: Path | None,
        is_cancelled: CancellationCheck,
        profile: TimelineRenderProfile,
    ) -> None:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(video_path),
        ]
        audio_index: int | None = None
        subtitle_index: int | None = None
        next_index = 1
        if audio_path is not None:
            audio_index = next_index
            next_index += 1
            command.extend(["-i", str(audio_path)])
        if subtitle_path is not None and profile.subtitle_mode == "embedded":
            subtitle_index = next_index
            command.extend(["-i", str(subtitle_path)])
        command.extend(["-map", "0:v:0"])
        if audio_index is not None:
            command.extend(
                [
                    "-map",
                    f"{audio_index}:a:0",
                    "-c:a",
                    "aac",
                    "-b:a",
                    profile.audio_bitrate,
                ]
            )
        if subtitle_index is not None:
            command.extend(
                [
                    "-map",
                    f"{subtitle_index}:s:0",
                    "-c:s",
                    "mov_text",
                    "-metadata:s:s:0",
                    "language=chi",
                ]
            )
        if subtitle_path is not None and profile.subtitle_mode == "burned":
            escaped_path = await asyncio.to_thread(_subtitle_filter_path, subtitle_path)
            command.extend(
                [
                    "-vf",
                    "subtitles=filename='"
                    + escaped_path
                    + "':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,"
                    "OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,"
                    "MarginV=42,Alignment=2'",
                    "-c:v",
                    "libx264",
                    "-preset",
                    profile.video_preset,
                    "-crf",
                    str(profile.video_crf),
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
        else:
            command.extend(["-c:v", "copy"])
        command.extend(
            [
                "-t",
                f"{duration_seconds:.6f}",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code=f"{profile.error_prefix}_mux_failed",
            message=f"{profile.operation_label}封装失败",
            timeout_seconds=profile.timeout_seconds,
        )

    async def _run(
        self,
        command: list[str],
        *,
        is_cancelled: CancellationCheck,
        code: str,
        message: str,
        timeout_seconds: int = 600,
    ) -> None:
        self._require_not_cancelled(is_cancelled)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
        )
        communication = asyncio.create_task(process.communicate())
        started = asyncio.get_running_loop().time()
        try:
            while not communication.done():
                if is_cancelled():
                    process.terminate()
                    await communication
                    raise TimelineRenderError("render_cancelled", "渲染已取消")
                if asyncio.get_running_loop().time() - started > timeout_seconds:
                    process.kill()
                    await communication
                    raise TimelineRenderError("render_timeout", f"{message}：处理超时")
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await asyncio.shield(communication)
            raise
        _, stderr = await communication
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            detail = detail[-1200:] if detail else "FFmpeg 未返回详细信息"
            raise TimelineRenderError(code, f"{message}：{detail}")
        self._require_not_cancelled(is_cancelled)

    @staticmethod
    def _require_not_cancelled(is_cancelled: CancellationCheck) -> None:
        if is_cancelled():
            raise TimelineRenderError("render_cancelled", "渲染已取消")
