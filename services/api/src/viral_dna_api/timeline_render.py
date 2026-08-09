from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .media import MediaProcessor
from .models import (
    ProductionTimeline,
    TimelineClip,
    TimelineTransitionKind,
    VideoClipAudioMode,
)

ProgressCallback = Callable[[int], Awaitable[None]]
CancellationCheck = Callable[[], bool]


class TimelineMediaResolver(Protocol):
    async def resolve_candidate_content(
        self,
        candidate_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]: ...


class TimelineRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        progress: ProgressCallback,
        is_cancelled: CancellationCheck,
    ) -> tuple[Path, Path | None]:
        enabled_clips = [clip for clip in timeline.clips if clip.enabled]
        if not enabled_clips:
            raise TimelineRenderError("timeline_empty", "时间线没有可渲染的视频片段")

        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        intermediate_root = output_root / "intermediate"
        await asyncio.to_thread(intermediate_root.mkdir, parents=True, exist_ok=True)
        preview_width, preview_height = preview_dimensions(
            timeline.output_width,
            timeline.output_height,
        )

        await progress(4)
        clip_paths: list[Path] = []
        for index, clip in enumerate(enabled_clips):
            self._require_not_cancelled(is_cancelled)
            source_path, _ = await self.media_resolver.resolve_candidate_content(
                clip.candidate_id
            )
            output_path = intermediate_root / f"video-{index + 1:03d}.mp4"
            previous_transition = (
                enabled_clips[index - 1].transition_after if index > 0 else None
            )
            await self._render_video_clip(
                source_path,
                output_path,
                clip,
                width=preview_width,
                height=preview_height,
                fps=timeline.fps,
                fade_in_seconds=(
                    previous_transition.duration_seconds
                    if previous_transition
                    and previous_transition.kind == TimelineTransitionKind.FADE
                    else 0
                ),
                fade_out_seconds=(
                    clip.transition_after.duration_seconds
                    if clip.transition_after.kind == TimelineTransitionKind.FADE
                    else 0
                ),
                is_cancelled=is_cancelled,
            )
            clip_paths.append(output_path)
            await progress(8 + round(37 * (index + 1) / len(enabled_clips)))

        assembled_video = intermediate_root / "video-track.mp4"
        await self._assemble_video_track(
            clip_paths,
            enabled_clips,
            assembled_video,
            is_cancelled,
        )
        await progress(55)

        audio_path: Path | None = None
        if (
            timeline.audio_track.enabled
            and timeline.audio_track.strategy != "muted"
            and source_audio_path is not None
            and await asyncio.to_thread(source_audio_path.is_file)
        ):
            audio_segments: list[Path] = []
            for index, clip in enumerate(enabled_clips):
                segment_path = intermediate_root / f"audio-{index + 1:03d}.m4a"
                await self._render_audio_clip(
                    source_audio_path,
                    segment_path,
                    clip,
                    track_volume=timeline.audio_track.volume,
                    normalize_loudness=timeline.audio_track.normalize_loudness,
                    is_cancelled=is_cancelled,
                )
                audio_segments.append(segment_path)
                await progress(57 + round(18 * (index + 1) / len(enabled_clips)))
            audio_path = intermediate_root / "audio-track.m4a"
            await self._assemble_audio_track(
                audio_segments,
                enabled_clips,
                audio_path,
                is_cancelled,
            )

        subtitle_path = self._write_subtitles(timeline, output_root / "preview.vtt")
        await progress(82)
        output_path = output_root / "preview.mp4"
        await self._mux_preview(
            assembled_video,
            output_path,
            duration_seconds=timeline.duration_seconds,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            is_cancelled=is_cancelled,
        )
        await progress(100)
        return output_path, subtitle_path

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
                "veryfast",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            is_cancelled=is_cancelled,
            code="preview_clip_failed",
            message=f"分镜 {clip.shot_index} 的预览转码失败",
        )

    async def _assemble_video_track(
        self,
        inputs: list[Path],
        clips: list[TimelineClip],
        output_path: Path,
        is_cancelled: CancellationCheck,
    ) -> None:
        if len(inputs) == 1:
            await self._copy_media(inputs[0], output_path, is_cancelled)
            return
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        current = "0:v"
        for index in range(1, len(inputs)):
            output = f"v{index}"
            transition = clips[index - 1].transition_after
            if transition.kind == TimelineTransitionKind.CROSSFADE:
                duration_before = sum(item.timeline_duration_seconds for item in clips[:index])
                overlap_before = sum(
                    item.transition_after.duration_seconds
                    for item in clips[: index - 1]
                    if item.transition_after.kind == TimelineTransitionKind.CROSSFADE
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
                "veryfast",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code="preview_video_track_failed",
            message="预览视频轨合成失败",
        )

    async def _render_audio_clip(
        self,
        source_audio_path: Path,
        output_path: Path,
        clip: TimelineClip,
        *,
        track_volume: float,
        normalize_loudness: bool,
        is_cancelled: CancellationCheck,
    ) -> None:
        duration = clip.timeline_duration_seconds
        if clip.audio_mode == VideoClipAudioMode.MUTED:
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
                "128k",
                str(output_path),
            ]
        else:
            source_duration = clip.source_audio_end_seconds - clip.source_audio_start_seconds
            tempo = source_duration / duration
            filters = atempo_filters(tempo)
            filters.append(f"volume={track_volume * clip.audio_volume:.6f}")
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
                "-ss",
                f"{clip.source_audio_start_seconds:.6f}",
                "-t",
                f"{source_duration:.6f}",
                "-i",
                str(source_audio_path),
                "-vn",
                "-af",
                ",".join(filters),
                "-t",
                f"{duration:.6f}",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(output_path),
            ]
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code="preview_audio_clip_failed",
            message=f"分镜 {clip.shot_index} 的原音轨映射失败",
        )

    async def _assemble_audio_track(
        self,
        inputs: list[Path],
        clips: list[TimelineClip],
        output_path: Path,
        is_cancelled: CancellationCheck,
    ) -> None:
        if len(inputs) == 1:
            await self._copy_media(inputs[0], output_path, is_cancelled)
            return
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        current = "0:a"
        for index in range(1, len(inputs)):
            output = f"a{index}"
            transition = clips[index - 1].transition_after
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
                "128k",
                str(output_path),
            ]
        )
        await self._run(
            command,
            is_cancelled=is_cancelled,
            code="preview_audio_track_failed",
            message="预览原音轨合成失败",
        )

    async def _copy_media(
        self,
        source_path: Path,
        output_path: Path,
        is_cancelled: CancellationCheck,
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
            code="preview_track_copy_failed",
            message="预览轨道准备失败",
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
        if subtitle_path is not None:
            subtitle_index = next_index
            command.extend(["-i", str(subtitle_path)])
        command.extend(["-map", "0:v:0"])
        if audio_index is not None:
            command.extend(["-map", f"{audio_index}:a:0", "-c:a", "aac", "-b:a", "128k"])
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
        command.extend(
            [
                "-c:v",
                "copy",
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
            code="preview_mux_failed",
            message="低清预览封装失败",
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
                    raise TimelineRenderError("render_cancelled", "预览渲染已取消")
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
            raise TimelineRenderError("render_cancelled", "预览渲染已取消")
