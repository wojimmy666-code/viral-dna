from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from fractions import Fraction
from itertools import pairwise
from math import gcd
from pathlib import Path
from uuid import UUID

from .models import AnalysisStage, MediaEvidence, MediaMetadata, ShotEvidence

PROCESSOR_VERSION = "ffmpeg-media-v1"
MAX_VIDEO_SECONDS = 5 * 60
MAX_SHOTS = 120
MIN_SHOT_SECONDS = 0.45

ProgressCallback = Callable[[AnalysisStage, int, str], Awaitable[None]]


class MediaProcessingError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def get_storage_root() -> Path:
    return Path(os.getenv("VIRAL_DNA_STORAGE_ROOT", "storage")).resolve()


def get_analysis_artifact_root(analysis_id: UUID) -> Path:
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

    async def extract_keyframes(
        self,
        proxy_path: Path,
        boundaries: list[float],
        shots_dir: Path,
        analysis_id: UUID,
    ) -> list[ShotEvidence]:
        shots: list[ShotEvidence] = []
        for index, (start, end) in enumerate(pairwise(boundaries), 1):
            representative = round(start + (end - start) / 2, 3)
            filename = f"shot_{index:03d}.jpg"
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
                    f"{representative:.3f}",
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
            shots.append(
                ShotEvidence(
                    shot_id=f"shot_{index:03d}",
                    index=index,
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                    duration_seconds=round(end - start, 3),
                    representative_timestamp=representative,
                    keyframe_url=artifact_url(analysis_id, f"shots/{filename}"),
                    detection_method="ffmpeg_scene_score",
                )
            )
        return shots

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

    async def process(
        self,
        source_path: Path,
        analysis_id: UUID,
        *,
        granularity: str,
        include_audio: bool,
        progress: ProgressCallback,
    ) -> MediaEvidence:
        artifact_root = get_analysis_artifact_root(analysis_id)
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

        await progress(AnalysisStage.SEGMENTING, 48, "正在检测真实镜头边界")
        boundaries = await self.detect_scene_boundaries(
            proxy_path,
            metadata.duration_seconds,
            granularity=granularity,
        )
        await progress(AnalysisStage.SEGMENTING, 66, "正在提取逐镜头代表关键帧")
        shots = await self.extract_keyframes(proxy_path, boundaries, shots_dir, analysis_id)

        contact_sheet_path = artifact_root / "contact-sheet.jpg"
        await self.create_contact_sheet(shots_dir, contact_sheet_path, len(shots))
        evidence = MediaEvidence(
            processor_version=PROCESSOR_VERSION,
            metadata=metadata,
            proxy_url=artifact_url(analysis_id, "proxy.mp4"),
            audio_url=audio_url,
            contact_sheet_url=artifact_url(analysis_id, "contact-sheet.jpg"),
            manifest_url=artifact_url(analysis_id, "manifest.json"),
            shots=shots,
        )
        manifest_path = artifact_root / "manifest.json"
        await asyncio.to_thread(
            manifest_path.write_text,
            evidence.model_dump_json(indent=2),
            "utf-8",
        )
        return evidence
