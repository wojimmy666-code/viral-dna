from __future__ import annotations

import asyncio
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .media import MediaProcessingError, MediaProcessor
from .models import MediaMetadata

VIDEO_QUALITY_SCHEMA = "viral-dna-video-quality/v2"
VIDEO_COVER_MAX_SIZE = 640
VIDEO_DURATION_TOLERANCE_SECONDS = 0.35
VIDEO_ASPECT_RATIO_TOLERANCE = 0.03
VIDEO_PLAYBACK_RATE_MIN = 0.8
VIDEO_PLAYBACK_RATE_MAX = 1.25


def _file_has_content(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


class TimedTextLike(Protocol):
    id: str
    start_seconds: float
    end_seconds: float
    text: str
    language: str | None


class ProductionVideoInspectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VideoInspectionResult:
    metadata: MediaMetadata
    cover_timestamp_seconds: float
    quality_status: str
    quality_report: dict[str, Any]


def clamp_video_timestamp(value: float, duration_seconds: float) -> float:
    upper = max(0.0, duration_seconds - 0.04)
    return round(min(max(0.0, value), upper), 3)


def map_timed_text(
    items: Iterable[TimedTextLike],
    *,
    source_start_seconds: float,
    source_end_seconds: float,
    kind: str,
) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for item in items:
        overlap_start = max(float(item.start_seconds), source_start_seconds)
        overlap_end = min(float(item.end_seconds), source_end_seconds)
        if overlap_end <= overlap_start:
            continue
        mapped.append(
            {
                "id": item.id,
                "kind": kind,
                "text": item.text,
                "language": item.language,
                "source_start_seconds": round(float(item.start_seconds), 3),
                "source_end_seconds": round(float(item.end_seconds), 3),
                "clip_start_seconds": round(overlap_start - source_start_seconds, 3),
                "clip_end_seconds": round(overlap_end - source_start_seconds, 3),
                "clipped": (
                    float(item.start_seconds) < source_start_seconds
                    or float(item.end_seconds) > source_end_seconds
                ),
            }
        )
    return mapped


def playback_alignment(
    prepared_duration_seconds: float,
    timeline_duration_seconds: float,
) -> tuple[float, str]:
    rate = prepared_duration_seconds / timeline_duration_seconds
    rounded = round(rate, 4)
    if abs(rate - 1.0) <= 0.02:
        return rounded, "exact"
    if VIDEO_PLAYBACK_RATE_MIN <= rate <= VIDEO_PLAYBACK_RATE_MAX:
        return rounded, "retime"
    return rounded, "outside_safe_range"


class ProductionVideoInspector:
    def __init__(self, media_processor: MediaProcessor | None = None) -> None:
        self.media_processor = (
            media_processor
            if media_processor is not None
            and hasattr(media_processor, "probe")
            and hasattr(media_processor, "ffmpeg")
            else MediaProcessor()
        )
        self.ffmpeg = self.media_processor.ffmpeg

    async def inspect(
        self,
        source_path: Path,
        cover_path: Path,
        *,
        cover_timestamp_seconds: float,
        expected_width: int | None,
        expected_height: int | None,
        expected_duration_seconds: float | None,
    ) -> VideoInspectionResult:
        try:
            metadata = await self.media_processor.probe(source_path)
        except MediaProcessingError as exc:
            raise ProductionVideoInspectionError(
                "video_probe_failed",
                f"视频候选技术检测失败：{exc}",
            ) from exc

        cover_timestamp = clamp_video_timestamp(
            cover_timestamp_seconds,
            metadata.duration_seconds,
        )
        try:
            await asyncio.to_thread(cover_path.parent.mkdir, parents=True, exist_ok=True)
            await self._extract_cover(source_path, cover_path, cover_timestamp)
        except (OSError, ProductionVideoInspectionError):
            raise

        checks: dict[str, dict[str, Any]] = {
            "file_integrity": {
                "status": "passed",
                "size_bytes": metadata.size_bytes,
                "format": metadata.format_name,
                "video_codec": metadata.video_codec,
            },
            "duration": {
                "status": "passed",
                "expected_seconds": expected_duration_seconds,
                "actual_seconds": metadata.duration_seconds,
                "delta_seconds": None,
            },
            "dimensions": {
                "status": "passed",
                "expected_width": expected_width,
                "expected_height": expected_height,
                "width": metadata.width,
                "height": metadata.height,
            },
            "frame_rate": {
                "status": "passed" if 12 <= metadata.fps <= 120 else "warning",
                "fps": metadata.fps,
            },
            "native_audio": {
                "status": "informational",
                "present": metadata.has_audio,
                "codec": metadata.audio_codec,
            },
        }
        warnings: list[str] = []
        if expected_duration_seconds is not None:
            delta = abs(metadata.duration_seconds - expected_duration_seconds)
            checks["duration"]["delta_seconds"] = round(delta, 3)
            tolerance = max(
                VIDEO_DURATION_TOLERANCE_SECONDS,
                expected_duration_seconds * 0.15,
            )
            if delta > tolerance:
                checks["duration"]["status"] = "warning"
                warnings.append("视频文件时长与生成结果记录存在明显偏差")

        if expected_width and expected_height:
            expected_ratio = expected_width / expected_height
            actual_ratio = metadata.width / metadata.height
            ratio_delta = abs(actual_ratio - expected_ratio) / expected_ratio
            checks["dimensions"]["aspect_ratio_delta"] = round(ratio_delta, 4)
            if ratio_delta > VIDEO_ASPECT_RATIO_TOLERANCE:
                checks["dimensions"]["status"] = "warning"
                warnings.append("视频画幅与生成请求不一致")

        signal_scan = await self._scan_visual_signals(source_path)
        checks["visual_signals"] = signal_scan
        if signal_scan["status"] == "warning":
            if signal_scan["black_segments"]:
                warnings.append("检测到持续黑屏片段，请人工复核")
            if signal_scan["freeze_segments"]:
                warnings.append("检测到持续静帧片段，请人工复核")
        if checks["frame_rate"]["status"] == "warning":
            warnings.append("视频帧率不在常用范围内")

        status = "warning" if warnings else "passed"
        report = {
            "schema_version": VIDEO_QUALITY_SCHEMA,
            "status": status,
            "summary": (
                "基础技术质检通过，但有项目需要人工复核。"
                if warnings
                else "文件、时长、画幅、帧率和基础画面信号检查通过。"
            ),
            "automated_checks": checks,
            "warnings": warnings,
            "manual_checks": [
                {"id": "motion", "label": "动作与运镜", "status": "required"},
                {"id": "identity", "label": "人物与产品稳定性", "status": "required"},
                {"id": "continuity", "label": "画面连续性", "status": "required"},
            ],
        }
        return VideoInspectionResult(
            metadata=metadata,
            cover_timestamp_seconds=cover_timestamp,
            quality_status=status,
            quality_report=report,
        )

    async def _extract_cover(
        self,
        source_path: Path,
        cover_path: Path,
        timestamp_seconds: float,
    ) -> None:
        _, stderr = await _run_command(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{timestamp_seconds:.3f}",
                "-i",
                str(source_path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                (
                    f"scale={VIDEO_COVER_MAX_SIZE}:{VIDEO_COVER_MAX_SIZE}:"
                    "force_original_aspect_ratio=decrease"
                ),
                "-c:v",
                "libwebp",
                "-quality",
                "84",
                str(cover_path),
            ],
            timeout_seconds=30,
            error_code="video_cover_failed",
            error_message="无法从视频候选提取封面帧",
        )
        if not await asyncio.to_thread(_file_has_content, cover_path):
            raise ProductionVideoInspectionError(
                "video_cover_failed",
                stderr.strip() or "无法从视频候选提取封面帧",
            )

    async def _scan_visual_signals(self, source_path: Path) -> dict[str, Any]:
        try:
            _, stderr = await _run_command(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-nostdin",
                    "-i",
                    str(source_path),
                    "-an",
                    "-vf",
                    "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=1.5",
                    "-f",
                    "null",
                    "-",
                ],
                timeout_seconds=60,
                error_code="video_signal_scan_failed",
                error_message="视频画面信号检测失败",
            )
        except ProductionVideoInspectionError as exc:
            return {
                "status": "skipped",
                "message": str(exc),
                "black_segments": [],
                "freeze_segments": [],
            }
        black_segments = [
            {
                "start_seconds": round(float(start), 3),
                "end_seconds": round(float(end), 3),
                "duration_seconds": round(float(duration), 3),
            }
            for start, end, duration in re.findall(
                r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)",
                stderr,
            )
        ]
        freeze_starts = [float(value) for value in re.findall(r"freeze_start:\s*([0-9.]+)", stderr)]
        freeze_ends = [float(value) for value in re.findall(r"freeze_end:\s*([0-9.]+)", stderr)]
        freeze_durations = [
            float(value) for value in re.findall(r"freeze_duration:\s*([0-9.]+)", stderr)
        ]
        freeze_segments = [
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(duration, 3),
            }
            for start, end, duration in zip(
                freeze_starts,
                freeze_ends,
                freeze_durations,
                strict=False,
            )
        ]
        return {
            "status": "warning" if black_segments or freeze_segments else "passed",
            "black_segments": black_segments,
            "freeze_segments": freeze_segments,
        }


async def _run_command(
    args: list[str],
    *,
    timeout_seconds: int,
    error_code: str,
    error_message: str,
) -> tuple[str, str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError) as exc:
        raise ProductionVideoInspectionError(error_code, error_message) from exc
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ProductionVideoInspectionError(error_code, f"{error_message}：处理超时") from exc
    decoded_stdout = stdout.decode("utf-8", errors="replace")
    decoded_stderr = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise ProductionVideoInspectionError(
            error_code,
            decoded_stderr.strip()[-1000:] or error_message,
        )
    return decoded_stdout, decoded_stderr
