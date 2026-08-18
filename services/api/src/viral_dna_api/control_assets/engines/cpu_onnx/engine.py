from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import math
import os
import re
import sys
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path

from ...jobs.domain import (
    DepthControlJobStage,
    DepthControlPreset,
    DepthExecutionDevice,
)
from ...jobs.progress import DepthProgressEvent
from ..contracts import DepthEngineCapability, DepthEngineOutput, DepthGenerationProfile
from ..process_runner import AsyncProcessRunner
from ..video_depth_anything import _probe, _quality_metrics, _resolve_command

ProgressCallback = Callable[[DepthProgressEvent], Awaitable[None]]

ENGINE_ID = "depth_anything_v2_onnx"
ENGINE_VERSION = "onnx-stream-v1"
MODEL_VARIANT = "vits"
MODEL_NAME = "depth_anything_v2_vits.onnx"
MODEL_URL = (
    "https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/"
    "v2.0.0/depth_anything_v2_vits.onnx"
)
MODEL_SHA256 = "d2b11a11c1d4a12b47608fa65a17ee9a4c605b55ee1730c8e3b526304f2562be"
REPOSITORY_URL = "https://github.com/fabio-sim/Depth-Anything-ONNX"
LICENSE = "Apache-2.0"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[7]


def _default_model_path() -> Path:
    configured = os.getenv("VIRAL_DNA_DEPTH_ONNX_MODEL", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        _repository_root()
        / "tools"
        / "depth-anything-onnx"
        / "models"
        / MODEL_NAME
    ).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _FrameProgressParser:
    pattern = re.compile(
        r"frames=(?P<current>\d+)/(?P<total>\d+).*?eta=(?P<eta>[0-9.]+)s"
    )

    def __init__(self, callback: ProgressCallback) -> None:
        self.callback = callback
        self.buffer = ""
        self.last_current = -1

    async def feed(self, chunk: str) -> None:
        self.buffer += chunk
        lines = self.buffer.splitlines(keepends=True)
        self.buffer = "" if lines and lines[-1].endswith(("\n", "\r")) else lines.pop()
        for line in lines:
            match = self.pattern.search(line)
            if not match:
                continue
            current = int(match.group("current"))
            total = max(1, int(match.group("total")))
            if current <= self.last_current:
                continue
            self.last_current = current
            eta = max(0, round(float(match.group("eta"))))
            await self.callback(
                DepthProgressEvent(
                    stage=DepthControlJobStage.INFERRING_DEPTH,
                    ratio=min(1.0, current / total),
                    message=f"正在逐帧生成空间深度 · {current}/{total} 帧 · 预计剩余 {eta} 秒",
                    processed_frames=current,
                    total_frames=total,
                )
            )


class DepthAnythingOnnxCpuEngine:
    engine_id = ENGINE_ID

    def __init__(self, runner: AsyncProcessRunner | None = None) -> None:
        self.model_path = _default_model_path()
        self.python = sys.executable
        self.ffmpeg = _resolve_command(os.getenv("VIRAL_DNA_FFMPEG_PATH", "ffmpeg"))
        self.ffprobe = _resolve_command(os.getenv("VIRAL_DNA_FFPROBE_PATH", "ffprobe"))
        self.runner = runner or AsyncProcessRunner()

    def capability(self) -> DepthEngineCapability:
        missing: list[str] = []
        if importlib.util.find_spec("onnxruntime") is None:
            missing.append("ONNX Runtime")
        if importlib.util.find_spec("numpy") is None:
            missing.append("NumPy")
        if importlib.util.find_spec("PIL") is None:
            missing.append("Pillow")
        if not self.model_path.is_file():
            missing.append("Depth Anything V2 Small ONNX 模型")
        if self.ffmpeg is None or self.ffprobe is None:
            missing.append("FFmpeg/FFprobe")
        available = not missing
        return DepthEngineCapability(
            engine=ENGINE_ID,
            version=ENGINE_VERSION,
            model_variant=MODEL_VARIANT,
            available=available,
            availability_note=("" if available else "缺少：" + "、".join(missing)),
            repository_url=REPOSITORY_URL,
            checkpoint_path=self.model_path if self.model_path.is_file() else None,
            runtime_path=Path(self.python),
            license=LICENSE,
        )

    def install(self, progress) -> DepthEngineCapability:
        if importlib.util.find_spec("onnxruntime") is None:
            raise RuntimeError("缺少 ONNX Runtime，请先安装 API local-ai 依赖")
        if self.ffmpeg is None or self.ffprobe is None:
            raise RuntimeError("未找到 FFmpeg/FFprobe")
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.model_path.with_suffix(".downloading")
        temporary.unlink(missing_ok=True)
        try:
            progress(5, "正在准备 Depth Anything V2 Small ONNX 模型")
            request = urllib.request.Request(
                MODEL_URL,
                headers={"User-Agent": "ViralDNA/1.0 depth-cpu-installer"},
            )
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open(
                "wb"
            ) as output:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        progress(
                            10 + round(min(1.0, downloaded / total) * 80),
                            "正在下载 CPU 深度模型",
                        )
            progress(92, "正在校验 CPU 深度模型")
            if _sha256(temporary) != MODEL_SHA256:
                raise RuntimeError("CPU 深度模型 SHA-256 校验失败")
            os.replace(temporary, self.model_path)
            progress(100, "CPU 深度引擎已安装")
            capability = self.capability()
            if not capability.available:
                raise RuntimeError(capability.availability_note)
            return capability
        finally:
            temporary.unlink(missing_ok=True)

    async def profile(self, requested: DepthControlPreset) -> DepthGenerationProfile:
        del requested
        try:
            import onnxruntime as ort

            runtime_version = ort.__version__
        except Exception:
            runtime_version = None
        return DepthGenerationProfile(
            preset=DepthControlPreset.CPU_FAST,
            device=DepthExecutionDevice.CPU,
            device_name="CPU · ONNX Runtime",
            target_fps=30,
            input_size=518,
            max_resolution=1280,
            timeout_seconds=7200,
            runtime_version=runtime_version,
        )

    async def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        working_root: Path,
        start_seconds: float,
        end_seconds: float,
        profile: DepthGenerationProfile,
        cancellation: asyncio.Event,
        progress: ProgressCallback,
    ) -> DepthEngineOutput:
        capability = self.capability()
        if not capability.available:
            raise RuntimeError(capability.availability_note)
        assert self.ffmpeg is not None
        assert self.ffprobe is not None

        await asyncio.to_thread(working_root.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination_path.parent.mkdir, parents=True, exist_ok=True)
        source_width, source_height, source_fps, _, _ = await asyncio.to_thread(
            _probe, self.ffprobe, source_path
        )
        duration = end_seconds - start_seconds
        target_fps = min(float(profile.target_fps), source_fps)
        scale = min(1.0, profile.max_resolution / max(source_width, source_height))
        width = max(2, round(source_width * scale / 2) * 2)
        height = max(2, round(source_height * scale / 2) * 2)
        total_frames = max(1, math.ceil(duration * target_fps))

        await progress(
            DepthProgressEvent(
                stage=DepthControlJobStage.LOADING_MODEL,
                ratio=0,
                message="正在加载 Depth Anything V2 Small ONNX 模型",
                total_frames=total_frames,
            )
        )
        parser = _FrameProgressParser(progress)
        await self.runner.run(
            [
                self.python,
                "-m",
                "viral_dna_api.control_assets.engines.cpu_onnx.worker",
                "--source",
                str(source_path),
                "--output",
                str(destination_path),
                "--thumbnail",
                str(thumbnail_path),
                "--model",
                str(self.model_path),
                "--ffmpeg",
                self.ffmpeg,
                "--start",
                f"{start_seconds:.6f}",
                "--duration",
                f"{duration:.6f}",
                "--width",
                str(width),
                "--height",
                str(height),
                "--fps",
                f"{target_fps:.8f}",
                "--frames",
                str(total_frames),
            ],
            cwd=_repository_root(),
            timeout_seconds=profile.timeout_seconds,
            cancellation=cancellation,
            on_stdout=parser.feed,
            on_stderr=parser.feed,
            on_started=lambda process_id: progress(
                DepthProgressEvent(
                    stage=DepthControlJobStage.LOADING_MODEL,
                    ratio=0.4,
                    message="CPU 深度推理进程已启动",
                    total_frames=total_frames,
                    process_id=process_id,
                )
            ),
        )

        await progress(
            DepthProgressEvent(
                stage=DepthControlJobStage.VALIDATING_OUTPUT,
                ratio=0.2,
                message="正在校验 CPU 深度视频",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        out_width, out_height, fps, out_duration, frame_count = await asyncio.to_thread(
            _probe, self.ffprobe, destination_path
        )
        metrics = await asyncio.to_thread(
            _quality_metrics, self.python, destination_path
        )
        metrics.update(
            {
                "engine": ENGINE_ID,
                "provider": "CPUExecutionProvider",
                "requested_frames": total_frames,
            }
        )
        return DepthEngineOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            width=out_width,
            height=out_height,
            fps=fps,
            duration_seconds=out_duration,
            frame_count=frame_count,
            validation_message="CPU ONNX 深度视频已通过文件、时长、画幅和灰度动态范围检查。",
            validation_metrics=metrics,
        )
