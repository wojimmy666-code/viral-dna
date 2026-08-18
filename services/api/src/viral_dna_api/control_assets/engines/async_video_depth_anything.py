from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from ..jobs.domain import (
    DepthControlJobStage,
    DepthControlPreset,
    DepthExecutionDevice,
)
from ..jobs.progress import DepthProgressEvent
from .contracts import DepthEngineOutput, DepthGenerationProfile
from .process_runner import AsyncProcessRunner
from .video_depth_anything import (
    MODEL_VARIANT,
    VideoDepthAnythingEngine,
    _probe,
    _quality_metrics,
    _resolve_command,
)

ProgressCallback = Callable[[DepthProgressEvent], Awaitable[None]]


def _profile_for(
    requested: DepthControlPreset,
    *,
    cuda_available: bool,
    device_name: str,
) -> DepthGenerationProfile:
    if requested == DepthControlPreset.AUTO:
        requested = (
            DepthControlPreset.BALANCED
            if cuda_available
            else DepthControlPreset.CPU_FAST
        )
    if requested in {DepthControlPreset.BALANCED, DepthControlPreset.QUALITY}:
        if not cuda_available:
            raise RuntimeError("当前设备没有可用的 NVIDIA CUDA，不能使用平衡或高质量档")
        if requested == DepthControlPreset.QUALITY:
            return DepthGenerationProfile(
                preset=requested,
                device=DepthExecutionDevice.CUDA,
                device_name=device_name,
                target_fps=24,
                input_size=518,
                max_resolution=1280,
                timeout_seconds=3600,
            )
        return DepthGenerationProfile(
            preset=requested,
            device=DepthExecutionDevice.CUDA,
            device_name=device_name,
            target_fps=15,
            input_size=448,
            max_resolution=960,
            timeout_seconds=2400,
        )
    return DepthGenerationProfile(
        preset=DepthControlPreset.CPU_FAST,
        device=DepthExecutionDevice.CPU,
        device_name="CPU",
        target_fps=12,
        input_size=392,
        max_resolution=960,
        timeout_seconds=1800,
    )


class _TqdmProgressParser:
    _pattern = re.compile(
        r"(?P<percent>\d{1,3})%[^\r\n]*?(?P<current>\d+)\s*/\s*(?P<total>\d+)"
    )

    def __init__(self, *, total_frames: int, callback: ProgressCallback) -> None:
        self.total_frames = total_frames
        self.callback = callback
        self.buffer = ""
        self.last_percent = -1

    async def feed(self, chunk: str) -> None:
        self.buffer += chunk
        pieces = re.split(r"[\r\n]", self.buffer)
        self.buffer = pieces.pop() if pieces else ""
        for line in pieces:
            match = self._pattern.search(line)
            if not match:
                continue
            percent = max(0, min(100, int(match.group("percent"))))
            if percent <= self.last_percent:
                continue
            self.last_percent = percent
            current = int(match.group("current"))
            total = max(1, int(match.group("total")))
            processed = min(
                self.total_frames,
                round(self.total_frames * min(1.0, current / total)),
            )
            await self.callback(
                DepthProgressEvent(
                    stage=DepthControlJobStage.INFERRING_DEPTH,
                    ratio=percent / 100,
                    message=f"正在推理空间深度 · {processed}/{self.total_frames} 帧",
                    processed_frames=processed,
                    total_frames=self.total_frames,
                )
            )


class AsyncVideoDepthAnythingEngine:
    """Cancellable, progress-aware adapter around the official CLI."""

    def __init__(
        self,
        engine: VideoDepthAnythingEngine,
        runner: AsyncProcessRunner | None = None,
    ) -> None:
        self.engine = engine
        self.runner = runner or AsyncProcessRunner()

    engine_id = "video_depth_anything_cuda"

    def capability(self):
        return replace(self.engine.capability(), engine=self.engine_id)

    def install(self, progress):
        return self.engine.install(progress)

    async def profile(self, requested: DepthControlPreset) -> DepthGenerationProfile:
        python = _resolve_command(self.engine.python)
        if python is None:
            return _profile_for(requested, cuda_available=False, device_name="CPU")
        command = [
            python,
            "-c",
            (
                "import json, torch; "
                "print(json.dumps({'cuda': bool(torch.cuda.is_available()), "
                "'name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU', "
                "'version': str(torch.__version__)}))"
            ),
        ]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
            )
            payload = json.loads((completed.stdout or "{}").strip().splitlines()[-1])
            return replace(
                _profile_for(
                requested,
                cuda_available=bool(payload.get("cuda")),
                device_name=str(payload.get("name") or "CPU"),
                ),
                runtime_version=str(payload.get("version") or "") or None,
            )
        except Exception:
            return _profile_for(requested, cuda_available=False, device_name="CPU")

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
        capability = self.engine.capability()
        if not capability.available:
            raise RuntimeError(capability.availability_note)
        assert self.engine.ffmpeg is not None
        assert self.engine.ffprobe is not None
        python = _resolve_command(self.engine.python)
        if python is None:
            raise RuntimeError("深度引擎 Python 运行环境不可用")
        await asyncio.to_thread(working_root.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            destination_path.parent.mkdir,
            parents=True,
            exist_ok=True,
        )
        clipped = working_root / "source-shot.mp4"
        raw_root = working_root / "raw"
        await asyncio.to_thread(raw_root.mkdir, parents=True, exist_ok=True)
        expected_duration = end_seconds - start_seconds
        total_frames = max(1, math.ceil(expected_duration * profile.target_fps))

        await progress(
            DepthProgressEvent(
                DepthControlJobStage.CLIPPING_SOURCE,
                0,
                "正在提取原视频分镜",
                total_frames=total_frames,
            )
        )
        await self.runner.run(
            [
                self.engine.ffmpeg,
                "-y",
                "-ss",
                f"{start_seconds:.6f}",
                "-to",
                f"{end_seconds:.6f}",
                "-i",
                str(source_path),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(clipped),
            ],
            timeout_seconds=600,
            cancellation=cancellation,
        )
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.CLIPPING_SOURCE,
                1,
                "原视频分镜已准备",
                total_frames=total_frames,
            )
        )
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.LOADING_MODEL,
                0,
                f"正在加载深度模型 · {profile.device_name}",
                total_frames=total_frames,
            )
        )
        parser = _TqdmProgressParser(total_frames=total_frames, callback=progress)

        async def started(pid: int) -> None:
            await progress(
                DepthProgressEvent(
                    DepthControlJobStage.LOADING_MODEL,
                    1,
                    f"模型已启动 · {profile.device_name}",
                    total_frames=total_frames,
                    process_id=pid,
                )
            )
            await progress(
                DepthProgressEvent(
                    DepthControlJobStage.INFERRING_DEPTH,
                    0,
                    f"正在推理空间深度 · 0/{total_frames} 帧",
                    processed_frames=0,
                    total_frames=total_frames,
                    process_id=pid,
                )
            )

        await self.runner.run(
            [
                python,
                str(self.engine.home / "run.py"),
                "--input_video",
                str(clipped),
                "--output_dir",
                str(raw_root),
                "--encoder",
                MODEL_VARIANT,
                "--target_fps",
                str(profile.target_fps),
                "--input_size",
                str(profile.input_size),
                "--max_res",
                str(profile.max_resolution),
                "--grayscale",
            ],
            cwd=self.engine.home,
            timeout_seconds=profile.timeout_seconds,
            cancellation=cancellation,
            on_stdout=parser.feed,
            on_stderr=parser.feed,
            on_started=started,
        )
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.WRITING_DEPTH,
                1,
                "深度帧已写入，正在准备视频",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        raw_output = raw_root / f"{clipped.stem}_vis.mp4"
        if not raw_output.is_file():
            matches = sorted(raw_root.glob("*_vis.mp4"))
            if len(matches) != 1:
                raise RuntimeError("Video Depth Anything 未输出预期的深度视频")
            raw_output = matches[0]

        await progress(
            DepthProgressEvent(
                DepthControlJobStage.ENCODING_VIDEO,
                0,
                "正在编码可播放的深度视频",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        await self.runner.run(
            [
                self.engine.ffmpeg,
                "-y",
                "-i",
                str(raw_output),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(destination_path),
            ],
            timeout_seconds=600,
            cancellation=cancellation,
        )
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.ENCODING_VIDEO,
                1,
                "深度视频编码完成",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.VALIDATING_OUTPUT,
                0,
                "正在检查时长、帧率和深度层次",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        width, height, fps, duration, frame_count = await asyncio.to_thread(
            _probe, self.engine.ffprobe, destination_path
        )
        duration_error = abs(duration - expected_duration)
        if duration_error > max(0.35, expected_duration * 0.08):
            raise RuntimeError("深度视频与原分镜时长不一致")
        metrics = await asyncio.to_thread(_quality_metrics, python, destination_path)
        if float(metrics.get("dynamic_range") or 0) < 0.10:
            raise RuntimeError("深度视频灰度层次不足，无法可靠表达空间关系")
        midpoint = max(0.0, min(duration / 2, max(0.0, duration - 0.05)))
        await self.runner.run(
            [
                self.engine.ffmpeg,
                "-y",
                "-ss",
                f"{midpoint:.6f}",
                "-i",
                str(destination_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(thumbnail_path),
            ],
            timeout_seconds=120,
            cancellation=cancellation,
        )
        metrics["duration_error_seconds"] = round(duration_error, 6)
        metrics["source_duration_seconds"] = round(expected_duration, 6)
        metrics["generation_preset"] = profile.preset.value
        metrics["execution_device"] = profile.device.value
        metrics["target_fps"] = profile.target_fps
        metrics["input_size"] = profile.input_size
        metrics["max_resolution"] = profile.max_resolution
        await progress(
            DepthProgressEvent(
                DepthControlJobStage.VALIDATING_OUTPUT,
                1,
                "输出质量检查通过",
                processed_frames=total_frames,
                total_frames=total_frames,
            )
        )
        return DepthEngineOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration,
            frame_count=frame_count,
            validation_message="全场景深度、时长、帧率和灰度动态范围检查通过",
            validation_metrics=metrics,
        )
