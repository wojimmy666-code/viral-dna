from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .domain import VideoEnhancementJobStage
from .process_runner import AsyncEnhancementProcessRunner, EnhancementProcessError

ENGINE_ID = "realesrgan-ncnn-vulkan"
ENGINE_VERSION = "0.2.0"
MODEL_NAME = "realesrgan-x4plus"
REPOSITORY_URL = "https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan"
LICENSE = "MIT"
WINDOWS_PACKAGE_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
)
WINDOWS_PACKAGE_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
WINDOWS_PACKAGE_SIZE_BYTES = 45_474_481
REQUIRED_MODEL_FILES = (
    f"{MODEL_NAME}.param",
    f"{MODEL_NAME}.bin",
)
DOWNLOAD_ATTEMPTS = 4


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _resolve_command(configured: str) -> str | None:
    candidate = configured.strip()
    if not candidate:
        return None
    expanded = Path(candidate).expanduser()
    if expanded.is_file():
        return str(expanded.resolve())
    return shutil.which(candidate)


def _default_executable() -> Path:
    configured = os.getenv("VIRAL_DNA_REALESRGAN_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    executable = "realesrgan-ncnn-vulkan.exe" if os.name == "nt" else "realesrgan-ncnn-vulkan"
    return (
        _repository_root() / "tools" / "realesrgan-ncnn-vulkan" / ENGINE_VERSION / executable
    ).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _automatic_install_supported() -> bool:
    return os.name == "nt"


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _missing_model_files(model_root: Path) -> list[str]:
    return [name for name in REQUIRED_MODEL_FILES if not _is_nonempty_file(model_root / name)]


def _probe(ffprobe: str, path: Path) -> tuple[int, int, float, float, int]:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "FFprobe 无法读取视频")
    payload = json.loads(completed.stdout)
    stream = (payload.get("streams") or [{}])[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rate = str(stream.get("avg_frame_rate") or "0/1")
    numerator, denominator = (float(item) for item in rate.split("/", 1))
    fps = numerator / denominator if denominator else 0
    duration = float((payload.get("format") or {}).get("duration") or 0)
    frame_count = int(stream.get("nb_frames") or 0)
    if frame_count <= 0 and duration > 0 and fps > 0:
        frame_count = max(1, round(duration * fps))
    if width <= 0 or height <= 0 or fps <= 0 or duration <= 0 or frame_count <= 0:
        raise RuntimeError("视频尺寸、帧率或时长信息不完整")
    return width, height, fps, duration, frame_count


@dataclass(frozen=True, slots=True)
class VideoEnhancementCapability:
    engine: str
    version: str
    model: str
    available: bool
    availability_note: str
    repository_url: str
    installation_path: Path
    executable_path: Path | None
    execution_device: str
    license: str
    installable: bool


@dataclass(frozen=True, slots=True)
class VideoMediaInfo:
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int


@dataclass(frozen=True, slots=True)
class VideoEnhancementProgress:
    stage: VideoEnhancementJobStage
    percent: int
    message: str
    processed_frames: int | None = None
    total_frames: int | None = None
    process_id: int | None = None


@dataclass(frozen=True, slots=True)
class VideoEnhancementOutput:
    path: Path
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int
    sha256: str
    size_bytes: int


ProgressCallback = Callable[[VideoEnhancementProgress], Awaitable[None]]


class _FfmpegFrameParser:
    pattern = re.compile(r"frame=\s*(?P<frame>\d+)")

    def __init__(
        self,
        callback: ProgressCallback,
        *,
        stage: VideoEnhancementJobStage,
        start_percent: int,
        end_percent: int,
        total_frames: int,
        verb: str,
    ) -> None:
        self.callback = callback
        self.stage = stage
        self.start_percent = start_percent
        self.end_percent = end_percent
        self.total_frames = max(1, total_frames)
        self.verb = verb
        self.last_frame = -1

    async def feed(self, chunk: str) -> None:
        matches = list(self.pattern.finditer(chunk))
        if not matches:
            return
        frame = min(self.total_frames, int(matches[-1].group("frame")))
        if frame <= self.last_frame:
            return
        self.last_frame = frame
        ratio = frame / self.total_frames
        percent = self.start_percent + round((self.end_percent - self.start_percent) * ratio)
        await self.callback(
            VideoEnhancementProgress(
                stage=self.stage,
                percent=percent,
                message=f"{self.verb} · {frame}/{self.total_frames} 帧",
                processed_frames=frame,
                total_frames=self.total_frames,
            )
        )


class _NcnnProgressParser:
    completed_pattern = re.compile(
        r"\s->\s(?P<output>.+?)\s+done\s*$",
        flags=re.IGNORECASE,
    )

    def __init__(self, callback: ProgressCallback, total_frames: int) -> None:
        self.callback = callback
        self.total_frames = max(1, total_frames)
        self.completed_outputs: set[str] = set()
        self.buffers: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def feed(self, chunk: str) -> None:
        await self._feed("combined", chunk)

    async def feed_stdout(self, chunk: str) -> None:
        await self._feed("stdout", chunk)

    async def feed_stderr(self, chunk: str) -> None:
        await self._feed("stderr", chunk)

    async def _feed(self, channel: str, chunk: str) -> None:
        async with self.lock:
            buffered = self.buffers.get(channel, "") + chunk
            lines = buffered.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                self.buffers[channel] = lines.pop()
            else:
                self.buffers[channel] = ""

            previous_count = len(self.completed_outputs)
            for line in lines:
                match = self.completed_pattern.search(line.strip())
                if match:
                    self.completed_outputs.add(match.group("output").strip())
            completed = min(self.total_frames, len(self.completed_outputs))
            if completed <= previous_count:
                return

            overall = 16 + round(69 * completed / self.total_frames)
            await self.callback(
                VideoEnhancementProgress(
                    stage=VideoEnhancementJobStage.UPSCALING,
                    percent=overall,
                    message=f"正在增强画面细节 · {completed}/{self.total_frames} 帧",
                    processed_frames=completed,
                    total_frames=self.total_frames,
                )
            )


class RealEsrganNcnnEngine:
    engine_id = ENGINE_ID

    def __init__(self, runner: AsyncEnhancementProcessRunner | None = None) -> None:
        self.executable = _default_executable()
        self.ffmpeg = _resolve_command(os.getenv("VIRAL_DNA_FFMPEG_PATH", "ffmpeg"))
        self.ffprobe = _resolve_command(os.getenv("VIRAL_DNA_FFPROBE_PATH", "ffprobe"))
        self.runner = runner or AsyncEnhancementProcessRunner()

    def capability(self) -> VideoEnhancementCapability:
        missing: list[str] = []
        model_root = self.executable.parent / "models"
        if not _is_nonempty_file(self.executable):
            missing.append("Real-ESRGAN 快速引擎")
        missing_models = _missing_model_files(model_root)
        if missing_models:
            missing.append("Real-ESRGAN 模型（" + "、".join(missing_models) + "）")
        if self.ffmpeg is None or self.ffprobe is None:
            missing.append("FFmpeg/FFprobe")
        available = not missing
        installable = (
            _automatic_install_supported() and self.ffmpeg is not None and self.ffprobe is not None
        )
        return VideoEnhancementCapability(
            engine=ENGINE_ID,
            version=ENGINE_VERSION,
            model=MODEL_NAME,
            available=available,
            availability_note=("已就绪" if available else "缺少：" + "、".join(missing)),
            repository_url=REPOSITORY_URL,
            installation_path=self.executable.parent,
            executable_path=self.executable if _is_nonempty_file(self.executable) else None,
            execution_device="自动选择 Vulkan 设备",
            license=LICENSE,
            installable=installable,
        )

    def probe_source(self, source_path: Path) -> VideoMediaInfo:
        if self.ffprobe is None:
            raise RuntimeError("未找到 FFprobe，无法读取原视频信息")
        width, height, fps, duration, frame_count = _probe(self.ffprobe, source_path)
        return VideoMediaInfo(
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration,
            frame_count=frame_count,
        )

    @staticmethod
    def _download_package(
        archive: Path,
        progress: Callable[[int, str], None],
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            downloaded = archive.stat().st_size if archive.is_file() else 0
            headers = {"User-Agent": "ViralDNA/1.0 video-enhancement-installer"}
            if downloaded:
                headers["Range"] = f"bytes={downloaded}-"
            request = urllib.request.Request(WINDOWS_PACKAGE_URL, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    status = getattr(response, "status", None)
                    append = downloaded > 0 and status == 206
                    if not append:
                        downloaded = 0
                    content_range = str(response.headers.get("Content-Range") or "")
                    range_match = re.search(r"/(\d+)$", content_range)
                    content_length = int(response.headers.get("Content-Length") or 0)
                    total = (
                        int(range_match.group(1))
                        if range_match
                        else downloaded + content_length
                        if content_length
                        else WINDOWS_PACKAGE_SIZE_BYTES
                    )
                    mode = "ab" if append else "wb"
                    with archive.open(mode) as out:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                progress(
                                    8 + round(min(1.0, downloaded / total) * 70),
                                    "正在下载 Real-ESRGAN 官方完整包（含模型）",
                                )
                if total and archive.stat().st_size < total:
                    raise OSError(f"下载内容不完整：{archive.stat().st_size}/{total} 字节")
                return
            except Exception as exc:
                last_error = exc
                if attempt < DOWNLOAD_ATTEMPTS:
                    retained = archive.stat().st_size if archive.is_file() else 0
                    progress(
                        8 + round(min(1.0, retained / WINDOWS_PACKAGE_SIZE_BYTES) * 70),
                        f"下载中断，正在续传（{attempt}/{DOWNLOAD_ATTEMPTS}）",
                    )
        detail = str(last_error).strip() if last_error is not None else "未知网络错误"
        raise RuntimeError(f"Real-ESRGAN 官方完整包下载失败：{detail}") from last_error

    @staticmethod
    def _replace_installation(unpacked_root: Path, destination: Path) -> None:
        parent = destination.parent
        prepared = parent / f".re-{uuid4().hex[:12]}.prepared"
        backup = parent / f".re-{uuid4().hex[:12]}.backup"
        unpacked_root.replace(prepared)
        try:
            had_existing = destination.exists()
            if had_existing:
                destination.replace(backup)
            try:
                prepared.replace(destination)
            except Exception:
                if had_existing and backup.exists() and not destination.exists():
                    backup.replace(destination)
                raise
            else:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
        finally:
            if prepared.exists():
                shutil.rmtree(prepared, ignore_errors=True)

    def install(self, progress: Callable[[int, str], None]) -> VideoEnhancementCapability:
        capability = self.capability()
        if capability.available:
            progress(100, "Real-ESRGAN 快速引擎已就绪")
            return capability
        if not _automatic_install_supported():
            raise RuntimeError("当前自动安装仅支持 Windows；可通过环境变量配置本地可执行文件")
        if self.ffmpeg is None or self.ffprobe is None:
            raise RuntimeError("未找到 FFmpeg/FFprobe，无法安装视频清晰化引擎")

        destination = self.executable.parent
        tools_root = destination.parent
        tools_root.mkdir(parents=True, exist_ok=True)
        archive = tools_root / f".re-{uuid4().hex[:12]}.zip"
        extraction = tools_root / f".re-{uuid4().hex[:12]}.installing"
        try:
            progress(5, "正在准备 Real-ESRGAN 官方完整包")
            self._download_package(archive, progress)
            progress(82, "正在校验官方发布包")
            if _sha256(archive) != WINDOWS_PACKAGE_SHA256:
                raise RuntimeError("Real-ESRGAN 发布包 SHA-256 校验失败")
            extraction.mkdir(parents=True, exist_ok=False)
            with zipfile.ZipFile(archive) as package:
                extraction_root = extraction.resolve()
                for member in package.infolist():
                    target = (extraction / member.filename).resolve()
                    try:
                        target.relative_to(extraction_root)
                    except ValueError as exc:
                        raise RuntimeError("Real-ESRGAN 发布包包含无效路径") from exc
                package.extractall(extraction)
            progress(92, "正在配置本地快速引擎")
            unpacked_executable = next(
                extraction.rglob("realesrgan-ncnn-vulkan.exe"),
                None,
            )
            if unpacked_executable is None:
                raise RuntimeError("官方发布包中缺少 Real-ESRGAN 可执行文件")
            unpacked_root = unpacked_executable.parent
            missing_models = _missing_model_files(unpacked_root / "models")
            if missing_models:
                raise RuntimeError("官方完整包缺少模型文件：" + "、".join(missing_models))
            progress(95, "正在修复并配置本地快速引擎")
            self._replace_installation(unpacked_root, destination)
            progress(98, "正在检查引擎文件")
            capability = self.capability()
            if not capability.available:
                raise RuntimeError(capability.availability_note)
            progress(100, "Real-ESRGAN 快速引擎已安装")
            return capability
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(extraction, ignore_errors=True)

    @staticmethod
    def upscale_factor(
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> int:
        required = max(target_width / source_width, target_height / source_height)
        return next((scale for scale in (2, 3, 4) if scale >= required), 4)

    async def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        working_root: Path,
        target_width: int,
        target_height: int,
        timeout_seconds: int,
        cancellation: asyncio.Event,
        progress: ProgressCallback,
    ) -> VideoEnhancementOutput:
        capability = self.capability()
        if not capability.available:
            raise RuntimeError(capability.availability_note)
        assert self.ffmpeg is not None
        assert self.ffprobe is not None

        await progress(
            VideoEnhancementProgress(
                stage=VideoEnhancementJobStage.PROBING,
                percent=1,
                message="正在读取原始视频信息",
            )
        )
        source_width, source_height, fps, duration, total_frames = await asyncio.to_thread(
            _probe,
            self.ffprobe,
            source_path,
        )
        upscale_factor = self.upscale_factor(
            source_width,
            source_height,
            target_width,
            target_height,
        )
        input_frames = working_root / "input-frames"
        output_frames = working_root / "enhanced-frames"
        await asyncio.to_thread(input_frames.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output_frames.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination_path.parent.mkdir, parents=True, exist_ok=True)

        extract_parser = _FfmpegFrameParser(
            progress,
            stage=VideoEnhancementJobStage.EXTRACTING,
            start_percent=3,
            end_percent=15,
            total_frames=total_frames,
            verb="正在拆分视频帧",
        )
        await self.runner.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-map",
                "0:v:0",
                "-vsync",
                "0",
                str(input_frames / "frame_%08d.png"),
            ],
            timeout_seconds=min(timeout_seconds, 3600),
            cancellation=cancellation,
            on_stderr=extract_parser.feed,
            on_started=lambda process_id: progress(
                VideoEnhancementProgress(
                    stage=VideoEnhancementJobStage.EXTRACTING,
                    percent=3,
                    message="正在拆分视频帧",
                    total_frames=total_frames,
                    process_id=process_id,
                )
            ),
        )

        await progress(
            VideoEnhancementProgress(
                stage=VideoEnhancementJobStage.UPSCALING,
                percent=15,
                message="正在使用 Real-ESRGAN 增强画面细节",
                processed_frames=0,
                total_frames=total_frames,
            )
        )
        ncnn_parser = _NcnnProgressParser(progress, total_frames)
        ncnn_result = await self.runner.run(
            [
                str(self.executable),
                "-i",
                str(input_frames),
                "-o",
                str(output_frames),
                "-m",
                str(self.executable.parent / "models"),
                "-n",
                MODEL_NAME,
                "-s",
                str(upscale_factor),
                "-j",
                "1:2:2",
                "-f",
                "png",
                "-v",
            ],
            cwd=self.executable.parent,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
            on_stdout=ncnn_parser.feed_stdout,
            on_stderr=ncnn_parser.feed_stderr,
            on_started=lambda process_id: progress(
                VideoEnhancementProgress(
                    stage=VideoEnhancementJobStage.UPSCALING,
                    percent=16,
                    message="Real-ESRGAN 已开始处理视频帧",
                    total_frames=total_frames,
                    process_id=process_id,
                )
            ),
        )

        output_count = await asyncio.to_thread(
            lambda: sum(1 for _ in output_frames.glob("frame_*.png"))
        )
        if output_count < max(1, math.floor(total_frames * 0.98)):
            engine_detail = (ncnn_result.stderr or ncnn_result.stdout).strip()
            frame_detail = f"增强帧数量不完整：预期约 {total_frames} 帧，实际 {output_count} 帧"
            raise EnhancementProcessError(
                "Real-ESRGAN 未生成完整的增强帧",
                returncode=ncnn_result.returncode,
                output_tail=(f"{frame_detail}\n{engine_detail}" if engine_detail else frame_detail),
            )

        await progress(
            VideoEnhancementProgress(
                stage=VideoEnhancementJobStage.UPSCALING,
                percent=85,
                message=f"画面细节增强完成 · {output_count}/{total_frames} 帧",
                processed_frames=output_count,
                total_frames=total_frames,
            )
        )

        encode_parser = _FfmpegFrameParser(
            progress,
            stage=VideoEnhancementJobStage.ENCODING,
            start_percent=86,
            end_percent=97,
            total_frames=total_frames,
            verb="正在合成高清视频",
        )
        await self.runner.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostdin",
                "-y",
                "-framerate",
                f"{fps:.8f}",
                "-i",
                str(output_frames / "frame_%08d.png"),
                "-i",
                str(source_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0?",
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(destination_path),
            ],
            timeout_seconds=min(timeout_seconds, 7200),
            cancellation=cancellation,
            on_stderr=encode_parser.feed,
            on_started=lambda process_id: progress(
                VideoEnhancementProgress(
                    stage=VideoEnhancementJobStage.ENCODING,
                    percent=86,
                    message="正在合成高清视频并保留音频",
                    total_frames=total_frames,
                    process_id=process_id,
                )
            ),
        )

        await progress(
            VideoEnhancementProgress(
                stage=VideoEnhancementJobStage.VALIDATING,
                percent=98,
                message="正在检查清晰化结果",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        width, height, output_fps, output_duration, frame_count = await asyncio.to_thread(
            _probe,
            self.ffprobe,
            destination_path,
        )
        if (width, height) != (target_width, target_height):
            raise RuntimeError(
                f"清晰化结果尺寸异常：预期 {target_width}×{target_height}，实际 {width}×{height}"
            )
        if abs(output_duration - duration) > max(0.2, 2 / fps):
            raise RuntimeError("清晰化结果时长与原视频不一致")
        result_sha256 = await asyncio.to_thread(_sha256, destination_path)
        size_bytes = (await asyncio.to_thread(destination_path.stat)).st_size
        return VideoEnhancementOutput(
            path=destination_path,
            width=width,
            height=height,
            fps=output_fps,
            duration_seconds=output_duration,
            frame_count=frame_count,
            sha256=result_sha256,
            size_bytes=size_bytes,
        )
