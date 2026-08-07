from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from math import gcd
from pathlib import Path
from uuid import UUID

from .models import (
    AnalysisStage,
    MediaEvidence,
    MediaMetadata,
    SceneBoundaryCandidate,
    SegmentationMetadata,
    ShotEvidence,
    SubtitleStream,
)
from .workspace import workspace_manager

PROCESSOR_VERSION = "ffmpeg-hybrid-candidates-v3"
MAX_VIDEO_SECONDS = 5 * 60
MAX_SHOTS = 120
MIN_SHOT_SECONDS = 0.45
SEGMENTATION_DETECTOR_VERSION = "ffmpeg-hybrid-candidates-v3"
MAX_BOUNDARY_CANDIDATES = 18
LOW_SCENE_THRESHOLD_FINE = 0.015
LOW_SCENE_THRESHOLD_STANDARD = 0.035
TEMPORAL_SCENE_THRESHOLD_FINE = 0.18
TEMPORAL_SCENE_THRESHOLD_STANDARD = 0.24
TEMPORAL_SAMPLE_FPS = 2
BOUNDARY_NMS_SECONDS = 0.65
BOUNDARY_EVIDENCE_NEAR_OFFSET_SECONDS = 0.12
BOUNDARY_EVIDENCE_FAR_OFFSET_SECONDS = 0.75
MAX_CONTEXT_FRAMES = 12
TEXT_SUBTITLE_CODECS = {"ass", "mov_text", "ssa", "srt", "subrip", "text", "webvtt"}

ProgressCallback = Callable[[AnalysisStage, int, str], Awaitable[None]]


class MediaProcessingError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class RawSceneScore:
    timestamp_seconds: float
    score: float
    method: str
    hard_boundary: bool = False


_SCENE_METADATA_PATTERN = re.compile(
    r"pts_time:(?P<timestamp>[0-9]+(?:\.[0-9]+)?)[^\r\n]*[\r\n]+"
    r"[^\r\n]*lavfi\.scene_score=(?P<score>[0-9]+(?:\.[0-9]+)?)"
)


def parse_scene_score_metadata(
    output: str,
    *,
    method: str,
    hard_threshold: float,
) -> list[RawSceneScore]:
    results: list[RawSceneScore] = []
    for match in _SCENE_METADATA_PATTERN.finditer(output):
        timestamp = round(float(match.group("timestamp")), 3)
        score = min(1.0, max(0.0, float(match.group("score"))))
        results.append(
            RawSceneScore(
                timestamp_seconds=timestamp,
                score=score,
                method=method,
                hard_boundary=(method == "adjacent_scene_score" and score >= hard_threshold),
            )
        )
    return results


def merge_scene_candidates(
    raw_candidates: list[RawSceneScore],
    *,
    duration_seconds: float,
    nms_seconds: float = BOUNDARY_NMS_SECONDS,
    max_candidates: int = MAX_BOUNDARY_CANDIDATES,
) -> list[SceneBoundaryCandidate]:
    eligible = sorted(
        (
            item
            for item in raw_candidates
            if item.timestamp_seconds >= MIN_SHOT_SECONDS
            and duration_seconds - item.timestamp_seconds >= MIN_SHOT_SECONDS
        ),
        key=lambda item: item.timestamp_seconds,
    )
    clusters: list[list[RawSceneScore]] = []
    for item in eligible:
        if not clusters or item.timestamp_seconds - clusters[-1][0].timestamp_seconds > nms_seconds:
            clusters.append([item])
        else:
            clusters[-1].append(item)

    merged: list[tuple[RawSceneScore, list[str], bool]] = []
    for cluster in clusters:
        hard_items = [item for item in cluster if item.hard_boundary]
        adjacent_items = [item for item in cluster if item.method == "adjacent_scene_score"]
        if hard_items:
            selected = max(hard_items, key=lambda item: item.score)
        elif adjacent_items:
            selected = min(adjacent_items, key=lambda item: item.timestamp_seconds)
        else:
            selected = max(cluster, key=lambda item: item.score)
        merged.append(
            (
                selected,
                sorted({item.method for item in cluster}),
                any(item.hard_boundary for item in cluster),
            )
        )

    if len(merged) > max_candidates:
        locked = [item for item in merged if item[2]]
        soft = [item for item in merged if not item[2]]
        available = max(0, max_candidates - len(locked))
        soft = sorted(soft, key=lambda item: item[0].score, reverse=True)[:available]
        merged = sorted([*locked, *soft], key=lambda item: item[0].timestamp_seconds)

    return [
        SceneBoundaryCandidate(
            id=f"candidate_{index:03d}",
            timestamp_seconds=item.timestamp_seconds,
            score=round(item.score, 6),
            methods=methods,
            hard_boundary=hard,
        )
        for index, (item, methods, hard) in enumerate(merged, 1)
    ]


def boundaries_from_candidates(
    candidates: list[SceneBoundaryCandidate],
    duration_seconds: float,
    *,
    selected_candidate_ids: set[str] | None = None,
    include_hard: bool = True,
) -> list[float]:
    selected = selected_candidate_ids or set()
    boundaries = [0.0]
    for candidate in sorted(candidates, key=lambda item: item.timestamp_seconds):
        if not ((include_hard and candidate.hard_boundary) or candidate.id in selected):
            continue
        timestamp = candidate.timestamp_seconds
        if timestamp - boundaries[-1] < MIN_SHOT_SECONDS:
            continue
        if duration_seconds - timestamp < MIN_SHOT_SECONDS:
            continue
        boundaries.append(round(timestamp, 3))
        if len(boundaries) >= MAX_SHOTS:
            break
    boundaries.append(round(duration_seconds, 3))
    return boundaries


def boundary_evidence_timestamps(
    timestamp_seconds: float,
    duration_seconds: float,
    *,
    near_offset_seconds: float = BOUNDARY_EVIDENCE_NEAR_OFFSET_SECONDS,
    far_offset_seconds: float = BOUNDARY_EVIDENCE_FAR_OFFSET_SECONDS,
) -> tuple[float, float, float, float]:
    """Return a four-frame micro timeline around one candidate boundary."""

    maximum = max(0.001, duration_seconds - 0.001)

    def clamp(value: float) -> float:
        return round(min(maximum, max(0.001, value)), 3)

    return (
        clamp(timestamp_seconds - far_offset_seconds),
        clamp(timestamp_seconds - near_offset_seconds),
        clamp(timestamp_seconds + near_offset_seconds),
        clamp(timestamp_seconds + far_offset_seconds),
    )


def get_storage_root() -> Path:
    return workspace_manager.root


def get_analysis_artifact_root(
    analysis_id: UUID,
    record_id: UUID | None = None,
) -> Path:
    if record_id is not None:
        return workspace_manager.analysis_root(record_id, analysis_id)
    return get_storage_root() / "analyses" / str(analysis_id)


def artifact_url(analysis_id: UUID, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    return f"/api/v1/analyses/{analysis_id}/artifacts/{normalized}"


def _resolve_binary(environment_key: str, default_name: str) -> str:
    configured = os.getenv(environment_key, default_name)
    resolved = shutil.which(configured)
    if resolved:
        return resolved
    candidate = Path(configured)
    if candidate.is_file():
        return str(candidate.resolve())
    raise MediaProcessingError(
        "media_dependency_missing",
        f"未找到 {default_name}，请安装 FFmpeg 并加入 PATH",
    )


async def _run_command(args: list[str], *, timeout_seconds: float) -> tuple[str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise MediaProcessingError(
            "media_process_start_failed",
            f"无法启动 {Path(args[0]).name}：{exc}",
            retryable=True,
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise MediaProcessingError(
            "media_process_timeout",
            f"{Path(args[0]).name} 处理超时",
            retryable=True,
        ) from exc

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        detail = stderr_text.strip().replace("\x00", "")[-1600:]
        raise MediaProcessingError(
            "media_process_failed",
            f"{Path(args[0]).name} 执行失败：{detail or '未知错误'}",
            retryable=True,
        )
    return stdout_text, stderr_text


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_fps(value: object) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _aspect_ratio(width: int, height: int) -> str:
    divisor = gcd(width, height) if width and height else 1
    return f"{width // divisor}:{height // divisor}"


def _rotation(video_stream: dict[str, object]) -> int:
    tags = video_stream.get("tags")
    if isinstance(tags, dict):
        rotate = _parse_int(tags.get("rotate"), default=0)
        if rotate:
            return rotate % 360
    side_data = video_stream.get("side_data_list")
    if isinstance(side_data, list):
        for entry in side_data:
            if isinstance(entry, dict) and "rotation" in entry:
                return _parse_int(entry.get("rotation"), default=0) % 360
    return 0


def _subtitle_stream(stream: dict[str, object]) -> SubtitleStream:
    tags = stream.get("tags")
    tag_values = tags if isinstance(tags, dict) else {}
    codec_name = str(stream.get("codec_name") or "unknown").lower()
    return SubtitleStream(
        index=_parse_int(stream.get("index")),
        codec_name=codec_name,
        language=str(tag_values.get("language") or "").strip()[:20] or None,
        title=str(tag_values.get("title") or "").strip()[:200] or None,
        extractable=codec_name in TEXT_SUBTITLE_CODECS,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MediaProcessor:
    def __init__(self) -> None:
        self.ffmpeg = _resolve_binary("VIRAL_DNA_FFMPEG_PATH", "ffmpeg")
        self.ffprobe = _resolve_binary("VIRAL_DNA_FFPROBE_PATH", "ffprobe")
        self.scene_threshold = float(os.getenv("VIRAL_DNA_SCENE_THRESHOLD", "0.30"))

    async def probe(self, source_path: Path) -> MediaMetadata:
        try:
            is_file, source_stat = await asyncio.gather(
                asyncio.to_thread(source_path.is_file),
                asyncio.to_thread(source_path.stat),
            )
        except FileNotFoundError:
            is_file, source_stat = False, None
        if not is_file or source_stat is None or source_stat.st_size == 0:
            raise MediaProcessingError("media_file_missing", "上传的视频文件不存在或为空")

        stdout, _ = await _run_command(
            [
                self.ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(source_path),
            ],
            timeout_seconds=30,
        )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise MediaProcessingError("media_probe_invalid", "ffprobe 返回了无效 JSON") from exc

        streams = payload.get("streams") or []
        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if not isinstance(video_stream, dict):
            raise MediaProcessingError("media_video_stream_missing", "文件中没有可分析的视频流")
        audio_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        subtitle_streams = [
            _subtitle_stream(stream)
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "subtitle"
        ]

        format_data = payload.get("format") or {}
        duration = _parse_float(format_data.get("duration")) or _parse_float(
            video_stream.get("duration")
        )
        width = _parse_int(video_stream.get("width"))
        height = _parse_int(video_stream.get("height"))
        if duration <= 0 or width <= 0 or height <= 0:
            raise MediaProcessingError("media_probe_invalid", "视频时长或画面尺寸无效")
        if duration > MAX_VIDEO_SECONDS:
            raise MediaProcessingError(
                "media_duration_exceeded",
                f"首版真实分析仅支持 {MAX_VIDEO_SECONDS // 60} 分钟以内的视频",
            )

        rotation = _rotation(video_stream)
        display_width, display_height = width, height
        if rotation in {90, 270}:
            display_width, display_height = height, width

        fps = _parse_fps(video_stream.get("avg_frame_rate")) or _parse_fps(
            video_stream.get("r_frame_rate")
        )
        return MediaMetadata(
            duration_seconds=round(duration, 3),
            width=display_width,
            height=display_height,
            rotation=rotation,
            fps=round(fps, 3),
            format_name=str(format_data.get("format_name") or "unknown"),
            video_codec=str(video_stream.get("codec_name") or "unknown"),
            audio_codec=(
                str(audio_stream.get("codec_name") or "unknown")
                if isinstance(audio_stream, dict)
                else None
            ),
            has_audio=isinstance(audio_stream, dict),
            size_bytes=_parse_int(format_data.get("size"), source_stat.st_size),
            bit_rate=_parse_int(format_data.get("bit_rate"), 0) or None,
            sha256=await asyncio.to_thread(_sha256, source_path),
            aspect_ratio=_aspect_ratio(display_width, display_height),
            subtitle_streams=subtitle_streams,
        )

    async def create_proxy(self, source_path: Path, output_path: Path) -> None:
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "scale=w='min(1080,iw)':h=-2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            timeout_seconds=600,
        )

    async def extract_audio(self, proxy_path: Path, output_path: Path) -> None:
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(proxy_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            timeout_seconds=300,
        )

    async def extract_subtitle(
        self,
        source_path: Path,
        output_path: Path,
        stream_index: int,
    ) -> None:
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-map",
                f"0:{stream_index}",
                "-c:s",
                "srt",
                str(output_path),
            ],
            timeout_seconds=120,
        )

    async def extract_frame(
        self,
        source_path: Path,
        timestamp_seconds: float,
        output_path: Path,
    ) -> None:
        if timestamp_seconds < 0:
            raise MediaProcessingError(
                "frame_timestamp_invalid",
                "关键帧时间不能小于 0",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await _run_command(
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
                f"{timestamp_seconds:.3f}",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output_path),
            ],
            timeout_seconds=120,
        )
        valid_output = await asyncio.to_thread(
            lambda: output_path.is_file() and output_path.stat().st_size > 0
        )
        if not valid_output:
            raise MediaProcessingError(
                "frame_extract_failed",
                "没有从源视频提取到关键帧",
            )

    async def create_still_video(
        self,
        image_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> None:
        if duration_seconds <= 0:
            raise MediaProcessingError(
                "video_duration_invalid",
                "视频时长必须大于 0",
            )
        target_width = max(2, int(width) // 2 * 2)
        target_height = max(2, int(height) // 2 * 2)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1,format=yuv420p"
        )
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "25",
                "-i",
                str(image_path),
                "-t",
                f"{duration_seconds:.3f}",
                "-vf",
                video_filter,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            timeout_seconds=max(120, min(600, duration_seconds * 20)),
        )
        valid_output = await asyncio.to_thread(
            lambda: output_path.is_file() and output_path.stat().st_size > 0
        )
        if not valid_output:
            raise MediaProcessingError(
                "video_render_failed",
                "没有生成可播放的视频文件",
            )

    async def detect_scene_boundaries(
        self,
        proxy_path: Path,
        duration_seconds: float,
        *,
        granularity: str,
    ) -> list[float]:
        threshold = (
            min(self.scene_threshold, 0.24) if granularity == "fine" else self.scene_threshold
        )
        _, stderr = await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostdin",
                "-i",
                str(proxy_path),
                "-vf",
                f"select=gt(scene\\,{threshold}),showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
        )
        candidates = sorted(
            {
                round(float(match), 3)
                for match in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr)
            }
        )
        boundaries = [0.0]
        for timestamp in candidates:
            if timestamp - boundaries[-1] < MIN_SHOT_SECONDS:
                continue
            if duration_seconds - timestamp < MIN_SHOT_SECONDS:
                continue
            boundaries.append(timestamp)
            if len(boundaries) >= MAX_SHOTS:
                break
        boundaries.append(round(duration_seconds, 3))
        return boundaries

    async def _detect_scene_scores(
        self,
        proxy_path: Path,
        *,
        threshold: float,
        method: str,
        hard_threshold: float,
        filter_prefix: str = "",
    ) -> list[RawSceneScore]:
        _, stderr = await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostdin",
                "-i",
                str(proxy_path),
                "-vf",
                f"{filter_prefix}select=gt(scene\\,{threshold}),metadata=print",
                "-an",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
        )
        return parse_scene_score_metadata(
            stderr,
            method=method,
            hard_threshold=hard_threshold,
        )

    async def detect_scene_candidates(
        self,
        proxy_path: Path,
        duration_seconds: float,
        *,
        granularity: str,
    ) -> list[SceneBoundaryCandidate]:
        hard_threshold = (
            min(self.scene_threshold, 0.24) if granularity == "fine" else self.scene_threshold
        )
        low_threshold = (
            LOW_SCENE_THRESHOLD_FINE if granularity == "fine" else LOW_SCENE_THRESHOLD_STANDARD
        )
        temporal_threshold = (
            TEMPORAL_SCENE_THRESHOLD_FINE
            if granularity == "fine"
            else TEMPORAL_SCENE_THRESHOLD_STANDARD
        )
        adjacent, temporal = await asyncio.gather(
            self._detect_scene_scores(
                proxy_path,
                threshold=low_threshold,
                method="adjacent_scene_score",
                hard_threshold=hard_threshold,
            ),
            self._detect_scene_scores(
                proxy_path,
                threshold=temporal_threshold,
                method="temporal_window_scene_score",
                hard_threshold=hard_threshold,
                filter_prefix=f"fps={TEMPORAL_SAMPLE_FPS},",
            ),
        )
        temporal = [
            item for item in temporal if item.timestamp_seconds > (1 / TEMPORAL_SAMPLE_FPS) + 0.01
        ]
        return merge_scene_candidates(
            [*adjacent, *temporal],
            duration_seconds=duration_seconds,
        )

    async def extract_keyframes(
        self,
        proxy_path: Path,
        boundaries: list[float],
        shots_dir: Path,
        analysis_id: UUID,
        *,
        boundary_candidates: list[SceneBoundaryCandidate] | None = None,
    ) -> list[ShotEvidence]:
        shots: list[ShotEvidence] = []
        candidates_by_timestamp = {
            round(candidate.timestamp_seconds, 3): candidate
            for candidate in boundary_candidates or []
        }
        for index, (start, end) in enumerate(pairwise(boundaries), 1):
            representative = round(start + (end - start) / 2, 3)
            duration = end - start
            offset = min(0.18, max(0.001, duration * 0.2), duration / 3)
            samples = (
                ("start", round(start + offset, 3)),
                ("middle", representative),
                ("end", round(end - offset, 3)),
            )
            frame_urls: list[str] = []
            for label, timestamp in samples:
                filename = (
                    f"shot_{index:03d}.jpg"
                    if label == "middle"
                    else f"shot_{index:03d}_{label}.jpg"
                )
                output_path = shots_dir / filename
                await _run_command(
                    [
                        self.ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-y",
                        "-ss",
                        f"{timestamp:.3f}",
                        "-i",
                        str(proxy_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=w='min(640,iw)':h=-2",
                        "-q:v",
                        "2",
                        str(output_path),
                    ],
                    timeout_seconds=60,
                )
                frame_urls.append(artifact_url(analysis_id, f"shots/{filename}"))

            keyframe_url = artifact_url(analysis_id, f"shots/shot_{index:03d}.jpg")
            boundary_candidate = candidates_by_timestamp.get(round(start, 3))
            if index == 1:
                boundary_method = "video_start"
                boundary_confidence = 1.0
                source_candidate_ids: list[str] = []
                semantic_group = None
            elif boundary_candidate is not None:
                boundary_method = (
                    "hybrid_vlm_verified"
                    if boundary_candidate.selected_by_model
                    else "hard_scene_score"
                )
                boundary_confidence = (
                    boundary_candidate.model_confidence
                    if boundary_candidate.selected_by_model
                    else boundary_candidate.score
                )
                source_candidate_ids = [boundary_candidate.id]
                semantic_group = boundary_candidate.semantic_group_after
            else:
                boundary_method = "ffmpeg_scene_score"
                boundary_confidence = None
                source_candidate_ids = []
                semantic_group = None
            shots.append(
                ShotEvidence(
                    shot_id=f"shot_{index:03d}",
                    index=index,
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                    duration_seconds=round(end - start, 3),
                    representative_timestamp=representative,
                    keyframe_url=keyframe_url,
                    evidence_frame_urls=frame_urls,
                    detection_method=(
                        "hybrid_candidate_vlm"
                        if boundary_candidates is not None
                        else "ffmpeg_scene_score"
                    ),
                    boundary_method=boundary_method,
                    boundary_confidence=boundary_confidence,
                    source_candidate_ids=source_candidate_ids,
                    semantic_group=semantic_group,
                )
            )
        return shots

    async def extract_boundary_evidence(
        self,
        proxy_path: Path,
        candidates: list[SceneBoundaryCandidate],
        segmentation_dir: Path,
        analysis_id: UUID,
        duration_seconds: float,
    ) -> list[SceneBoundaryCandidate]:
        enriched: list[SceneBoundaryCandidate] = []
        for candidate in candidates:
            far_before, near_before, near_after, far_after = boundary_evidence_timestamps(
                candidate.timestamp_seconds,
                duration_seconds,
            )
            filename = f"{candidate.id}.jpg"
            output_path = segmentation_dir / filename
            await _run_command(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{far_before:.3f}",
                    "-i",
                    str(proxy_path),
                    "-ss",
                    f"{near_before:.3f}",
                    "-i",
                    str(proxy_path),
                    "-ss",
                    f"{near_after:.3f}",
                    "-i",
                    str(proxy_path),
                    "-ss",
                    f"{far_after:.3f}",
                    "-i",
                    str(proxy_path),
                    "-filter_complex",
                    (
                        "[0:v]scale=240:300:force_original_aspect_ratio=decrease,"
                        "pad=240:300:(ow-iw)/2:(oh-ih)/2:color=black[far_before];"
                        "[1:v]scale=240:300:force_original_aspect_ratio=decrease,"
                        "pad=240:300:(ow-iw)/2:(oh-ih)/2:color=black[near_before];"
                        "[2:v]scale=240:300:force_original_aspect_ratio=decrease,"
                        "pad=240:300:(ow-iw)/2:(oh-ih)/2:color=black[near_after];"
                        "[3:v]scale=240:300:force_original_aspect_ratio=decrease,"
                        "pad=240:300:(ow-iw)/2:(oh-ih)/2:color=black[far_after];"
                        "[far_before][near_before][near_after][far_after]"
                        "hstack=inputs=4,"
                        "drawbox=x=479:y=0:w=2:h=ih:color=white:t=fill[comparison]"
                    ),
                    "-map",
                    "[comparison]",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(output_path),
                ],
                timeout_seconds=60,
            )
            url = artifact_url(analysis_id, f"segmentation/{filename}")
            enriched.append(
                candidate.model_copy(
                    update={
                        "comparison_image_url": url,
                        "evidence_frame_urls": [url],
                        "evidence_timestamps": [
                            far_before,
                            near_before,
                            near_after,
                            far_after,
                        ],
                    }
                )
            )
        return enriched

    async def create_segmentation_context(
        self,
        proxy_path: Path,
        segmentation_dir: Path,
        analysis_id: UUID,
        duration_seconds: float,
    ) -> tuple[str, list[float]]:
        count = min(MAX_CONTEXT_FRAMES, max(2, math.ceil(duration_seconds / 1.5)))
        timestamps = [round(duration_seconds * (index + 0.5) / count, 3) for index in range(count)]
        for index, timestamp in enumerate(timestamps, 1):
            output_path = segmentation_dir / f"context_{index:03d}.jpg"
            await _run_command(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(proxy_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=w='min(480,iw)':h=-2",
                    "-q:v",
                    "3",
                    str(output_path),
                ],
                timeout_seconds=60,
            )

        columns = min(4, count)
        rows = max(1, math.ceil(count / columns))
        context_path = segmentation_dir / "context-sheet.jpg"
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-framerate",
                "1",
                "-start_number",
                "1",
                "-i",
                str(segmentation_dir / "context_%03d.jpg"),
                "-vf",
                (
                    "scale=240:240:force_original_aspect_ratio=decrease,"
                    "pad=240:240:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"tile={columns}x{rows}:nb_frames={count}:padding=8:margin=8:color=white"
                ),
                "-frames:v",
                "1",
                str(context_path),
            ],
            timeout_seconds=120,
        )
        return artifact_url(analysis_id, "segmentation/context-sheet.jpg"), timestamps

    async def create_contact_sheet(self, shots_dir: Path, output_path: Path, count: int) -> None:
        tile_count = min(count, 20)
        columns = min(4, tile_count)
        rows = max(1, math.ceil(tile_count / columns))
        filter_graph = (
            "scale=320:180:force_original_aspect_ratio=decrease,"
            "pad=320:180:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"tile={columns}x{rows}:nb_frames={tile_count}:padding=8:margin=8:color=white"
        )
        await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-framerate",
                "1",
                "-start_number",
                "1",
                "-i",
                str(shots_dir / "shot_%03d.jpg"),
                "-vf",
                filter_graph,
                "-frames:v",
                "1",
                str(output_path),
            ],
            timeout_seconds=120,
        )

    async def apply_segmentation(
        self,
        evidence: MediaEvidence,
        analysis_id: UUID,
        segmentation: SegmentationMetadata,
        *,
        record_id: UUID | None = None,
    ) -> MediaEvidence:
        artifact_root = get_analysis_artifact_root(analysis_id, record_id)
        proxy_path = artifact_root / "proxy.mp4"
        shots_dir = artifact_root / "shots"
        await asyncio.to_thread(shots_dir.mkdir, parents=True, exist_ok=True)
        shots = await self.extract_keyframes(
            proxy_path,
            segmentation.final_boundaries,
            shots_dir,
            analysis_id,
            boundary_candidates=segmentation.candidates,
        )
        contact_sheet_path = artifact_root / "contact-sheet.jpg"
        await self.create_contact_sheet(shots_dir, contact_sheet_path, len(shots))
        updated = evidence.model_copy(
            update={
                "shots": shots,
                "segmentation": segmentation,
            }
        )
        manifest_path = artifact_root / "manifest.json"
        await asyncio.to_thread(
            manifest_path.write_text,
            updated.model_dump_json(indent=2),
            "utf-8",
        )
        return updated

    async def process(
        self,
        source_path: Path,
        analysis_id: UUID,
        *,
        granularity: str,
        include_audio: bool,
        progress: ProgressCallback,
        record_id: UUID | None = None,
    ) -> MediaEvidence:
        artifact_root = get_analysis_artifact_root(analysis_id, record_id)
        shots_dir = artifact_root / "shots"
        await asyncio.to_thread(shots_dir.mkdir, parents=True, exist_ok=True)

        await progress(AnalysisStage.INGESTING, 8, "正在计算文件哈希并读取媒体流")
        metadata = await self.probe(source_path)

        proxy_path = artifact_root / "proxy.mp4"
        await progress(AnalysisStage.PREPROCESSING, 22, "正在生成 H.264/AAC 分析代理")
        await self.create_proxy(source_path, proxy_path)

        audio_url: str | None = None
        if include_audio and metadata.has_audio:
            await progress(AnalysisStage.PREPROCESSING, 34, "正在提取 16 kHz 单声道音频")
            audio_path = artifact_root / "audio.wav"
            await self.extract_audio(proxy_path, audio_path)
            audio_url = artifact_url(analysis_id, "audio.wav")

        subtitle_url: str | None = None
        subtitle_message: str | None = None
        subtitle_stream = next(
            (stream for stream in metadata.subtitle_streams if stream.extractable),
            None,
        )
        if subtitle_stream is not None:
            subtitle_path = artifact_root / "subtitles.srt"
            try:
                await self.extract_subtitle(source_path, subtitle_path, subtitle_stream.index)
            except MediaProcessingError:
                subtitle_message = "检测到文本字幕轨，但 FFmpeg 无法将其转换为 SRT"
            else:
                subtitle_url = artifact_url(analysis_id, "subtitles.srt")
                subtitle_message = f"已提取 {subtitle_stream.codec_name} 内嵌字幕轨"
        elif metadata.subtitle_streams:
            subtitle_message = "检测到图像型或暂不支持的字幕轨，首期仅转换文本字幕轨"

        await progress(AnalysisStage.SEGMENTING, 48, "正在生成多层镜头边界候选")
        candidates = await self.detect_scene_candidates(
            proxy_path,
            metadata.duration_seconds,
            granularity=granularity,
        )
        segmentation_dir = artifact_root / "segmentation"
        await asyncio.to_thread(segmentation_dir.mkdir, parents=True, exist_ok=True)
        candidates = await self.extract_boundary_evidence(
            proxy_path,
            candidates,
            segmentation_dir,
            analysis_id,
            metadata.duration_seconds,
        )
        context_sheet_url, context_timestamps = await self.create_segmentation_context(
            proxy_path,
            segmentation_dir,
            analysis_id,
            metadata.duration_seconds,
        )
        boundaries = boundaries_from_candidates(candidates, metadata.duration_seconds)
        segmentation = SegmentationMetadata(
            detector_version=SEGMENTATION_DETECTOR_VERSION,
            candidate_count=len(candidates),
            candidates=candidates,
            context_sheet_url=context_sheet_url,
            context_timestamps=context_timestamps,
            program_boundaries=boundaries,
            selected_candidate_ids=[
                candidate.id for candidate in candidates if candidate.hard_boundary
            ],
            final_boundaries=boundaries,
            final_shot_count=max(0, len(boundaries) - 1),
            fallback_reason="等待 VLM 语义确认，当前采用硬切边界",
        )
        await progress(AnalysisStage.SEGMENTING, 66, "正在提取逐镜头代表关键帧")
        shots = await self.extract_keyframes(
            proxy_path,
            boundaries,
            shots_dir,
            analysis_id,
            boundary_candidates=candidates,
        )

        contact_sheet_path = artifact_root / "contact-sheet.jpg"
        await self.create_contact_sheet(shots_dir, contact_sheet_path, len(shots))
        evidence = MediaEvidence(
            processor_version=PROCESSOR_VERSION,
            metadata=metadata,
            proxy_url=artifact_url(analysis_id, "proxy.mp4"),
            audio_url=audio_url,
            subtitle_url=subtitle_url,
            subtitle_extraction_message=subtitle_message,
            contact_sheet_url=artifact_url(analysis_id, "contact-sheet.jpg"),
            manifest_url=artifact_url(analysis_id, "manifest.json"),
            shots=shots,
            segmentation=segmentation,
        )
        manifest_path = artifact_root / "manifest.json"
        await asyncio.to_thread(
            manifest_path.write_text,
            evidence.model_dump_json(indent=2),
            "utf-8",
        )
        return evidence
