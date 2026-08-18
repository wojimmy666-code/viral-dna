from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .contracts import DepthEngineCapability, DepthEngineOutput

REPOSITORY_URL = "https://github.com/DepthAnything/Video-Depth-Anything"
REPOSITORY_SSH_URL = "git@github.com:DepthAnything/Video-Depth-Anything.git"
ENGINE_VERSION = "official-cli-v1"
MODEL_VARIANT = "vits"
SMALL_MODEL_LICENSE = "Apache-2.0"
CHECKPOINT_NAME = "video_depth_anything_vits.pth"
CHECKPOINT_URL = (
    "https://huggingface.co/depth-anything/Video-Depth-Anything-Small/resolve/main/"
    + CHECKPOINT_NAME
)
CHECKPOINT_SHA256 = "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609"
INSTALL_MANIFEST_NAME = ".viral-dna-depth-engine.json"
DEPENDENCY_PROFILE = "viral-dna-inference-core/v1"

# The upstream requirements file also pins xformers and OpenEXR.  Neither is
# required by the grayscale inference path used by ViralDNA: xformers has an
# explicit PyTorch fallback and OpenEXR is imported only for --save_exr.
# Keeping the runtime list explicit makes the one-click installer reliable on
# Windows while preserving the upstream versions needed for inference.
RUNTIME_REQUIREMENTS = (
    "numpy==1.24.0",
    "torch==2.1.1",
    "torchvision==0.16.1",
    "opencv-python",
    "matplotlib",
    "pillow",
    "imageio==2.37.0",
    "imageio-ffmpeg==0.4.7",
    "decord",
    "einops==0.4.1",
    "easydict",
    "tqdm",
)
CUDA_REQUIREMENTS = ("torch==2.1.1", "torchvision==0.16.1")
CUDA_WHEEL_INDEX = "https://download.pytorch.org/whl/cu121"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _configured_home() -> Path:
    configured = os.getenv("VIRAL_DNA_VIDEO_DEPTH_ANYTHING_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (_repository_root() / "tools" / "video-depth-anything").resolve()


def _environment_python(home: Path) -> Path:
    if os.name == "nt":
        return home / ".venv" / "Scripts" / "python.exe"
    return home / ".venv" / "bin" / "python"


def _configured_python(home: Path) -> str:
    configured = os.getenv("VIRAL_DNA_VIDEO_DEPTH_PYTHON", "").strip()
    if configured:
        return configured
    isolated = _environment_python(home)
    return str(isolated) if isolated.is_file() else sys.executable


def _resolve_command(value: str) -> str | None:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return shutil.which(value)


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 1800) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"深度引擎执行失败：{exc}") from exc
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(details or "深度引擎返回了失败状态")
    return completed.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    destination: Path,
    progress: Callable[[int, str], None],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ViralDNA/1.0 Video-Depth-Anything installer"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, destination.open(
        "wb"
    ) as target:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                ratio = min(1.0, downloaded / total)
                progress(72 + round(ratio * 20), "正在下载 Small 深度模型权重")


def _probe(ffprobe: str, path: Path) -> tuple[int, int, float, float, int]:
    raw = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        timeout=60,
    )
    payload = json.loads(raw)
    stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    if not isinstance(stream, dict):
        raise RuntimeError("深度控制文件中没有视频流")
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    numerator, _, denominator = rate.partition("/")
    fps = float(numerator or 0) / max(float(denominator or 1), 1)
    duration = float(
        stream.get("duration")
        or (payload.get("format") or {}).get("duration")
        or 0
    )
    frame_count = int(stream.get("nb_frames") or round(duration * fps))
    if width <= 0 or height <= 0 or fps <= 0 or duration <= 0 or frame_count <= 0:
        raise RuntimeError("深度控制视频的尺寸、帧率或时长无效")
    return width, height, fps, duration, frame_count


def _quality_metrics(python: str, path: Path) -> dict[str, float | int | str | bool]:
    script = """
import cv2, json, numpy as np, sys
cap=cv2.VideoCapture(sys.argv[1]); samples=[]; previous=None; diffs=[]; count=0
while True:
    ok, frame=cap.read()
    if not ok: break
    count += 1
    if count == 1 or count % 5 == 0:
        gray=cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small=cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        samples.append(small)
        if previous is not None:
            diffs.append(float(np.mean(np.abs(small.astype(np.float32)-previous.astype(np.float32)))/255.0))
        previous=small
cap.release()
if not samples: raise SystemExit(3)
pixels=np.concatenate([item.reshape(-1) for item in samples]).astype(np.float32)/255.0
payload={
    "sampled_frames":len(samples),
    "luma_p01":float(np.quantile(pixels,.01)),
    "luma_p99":float(np.quantile(pixels,.99)),
    "dynamic_range":float(np.quantile(pixels,.99)-np.quantile(pixels,.01)),
    "temporal_change_mean":float(np.mean(diffs) if diffs else 0.0),
    "grayscale":True,
}
print(json.dumps(payload))
""".strip()
    raw = _run([python, "-c", script, str(path)], timeout=180)
    return json.loads(raw.strip().splitlines()[-1])


class VideoDepthAnythingEngine:
    """Adapter for the official Video Depth Anything Small command-line tool."""

    def __init__(self) -> None:
        self.home = _configured_home()
        self.python = _configured_python(self.home)
        self.ffmpeg = _resolve_command(os.getenv("VIRAL_DNA_FFMPEG_PATH", "ffmpeg"))
        self.ffprobe = _resolve_command(os.getenv("VIRAL_DNA_FFPROBE_PATH", "ffprobe"))

    @property
    def checkpoint(self) -> Path:
        return self.home / "checkpoints" / CHECKPOINT_NAME

    def capability(self) -> DepthEngineCapability:
        python = _resolve_command(self.python)
        missing: list[str] = []
        if python is None:
            missing.append("Python 运行环境")
        if not (self.home / "run.py").is_file():
            missing.append("Video Depth Anything run.py")
        if not self.checkpoint.is_file():
            missing.append("Small 模型权重")
        if self.ffmpeg is None or self.ffprobe is None:
            missing.append("FFmpeg/FFprobe")
        available = not missing
        return DepthEngineCapability(
            engine="video_depth_anything",
            version=ENGINE_VERSION,
            model_variant=MODEL_VARIANT,
            available=available,
            availability_note=(
                ""
                if available
                else "缺少：" + "、".join(missing) + "。请在模型与设置中配置真实深度引擎。"
            ),
            repository_url=REPOSITORY_URL,
            checkpoint_path=self.checkpoint if self.checkpoint.is_file() else None,
            runtime_path=self.home if (self.home / "run.py").is_file() else None,
            license=SMALL_MODEL_LICENSE,
        )

    def install(self, progress: Callable[[int, str], None]) -> DepthEngineCapability:
        """Install the official Apache-2.0 Small model in an isolated environment."""

        git = _resolve_command("git")
        if git is None:
            raise RuntimeError("未找到 Git，无法安装 Video Depth Anything")
        if self.ffmpeg is None or self.ffprobe is None:
            raise RuntimeError("未找到 FFmpeg/FFprobe，请先完成媒体工具安装")

        parent = self.home.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".installing-video-depth-anything-{uuid4().hex}"
        backup = parent / f".replacing-video-depth-anything-{uuid4().hex}"
        try:
            progress(3, "正在获取 Video Depth Anything 官方源码")
            _run(
                [git, "clone", "--depth", "1", REPOSITORY_SSH_URL, str(temporary)],
                timeout=900,
            )

            progress(18, "正在创建独立 Python 运行环境")
            _run([sys.executable, "-m", "venv", str(temporary / ".venv")], timeout=300)
            isolated_python = _environment_python(temporary)
            if not isolated_python.is_file():
                raise RuntimeError("深度引擎独立 Python 环境创建失败")

            progress(25, "正在准备深度引擎依赖")
            _run(
                [str(isolated_python), "-m", "pip", "install", "--upgrade", "pip", "wheel"],
                timeout=900,
            )
            progress(34, "正在安装深度推理核心依赖，首次安装可能需要较长时间")
            _run(
                [
                    str(isolated_python),
                    "-m",
                    "pip",
                    "install",
                    "--index-url",
                    CUDA_WHEEL_INDEX,
                    *CUDA_REQUIREMENTS,
                ],
                cwd=temporary,
                timeout=3600,
            )
            non_torch_requirements = tuple(
                requirement
                for requirement in RUNTIME_REQUIREMENTS
                if not requirement.startswith(("torch==", "torchvision=="))
            )
            _run(
                [
                    str(isolated_python),
                    "-m",
                    "pip",
                    "install",
                    *non_torch_requirements,
                ],
                cwd=temporary,
                timeout=3600,
            )

            progress(72, "正在下载 Small 深度模型权重")
            checkpoint = temporary / "checkpoints" / CHECKPOINT_NAME
            _download(CHECKPOINT_URL, checkpoint, progress)
            if _sha256(checkpoint) != CHECKPOINT_SHA256:
                raise RuntimeError("Small 深度模型权重校验失败，已取消安装")

            progress(94, "正在验证独立推理环境")
            _run(
                [
                    str(isolated_python),
                    "-c",
                    "import cv2, decord, numpy, torch, torchvision; "
                    "assert torch.cuda.is_available(), 'NVIDIA CUDA is unavailable'; "
                    "print(torch.__version__, torch.cuda.get_device_name(0))",
                ],
                cwd=temporary,
                timeout=180,
            )
            (temporary / INSTALL_MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": "viral-dna-depth-engine/v1",
                        "engine": "video_depth_anything",
                        "engine_version": ENGINE_VERSION,
                        "model_variant": MODEL_VARIANT,
                        "checkpoint_sha256": CHECKPOINT_SHA256,
                        "repository_remote": REPOSITORY_SSH_URL,
                        "dependency_profile": DEPENDENCY_PROFILE,
                        "runtime_requirements": list(RUNTIME_REQUIREMENTS),
                        "license": SMALL_MODEL_LICENSE,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            if self.home.exists():
                os.replace(self.home, backup)
            os.replace(temporary, self.home)
            self.python = str(_environment_python(self.home))
            capability = self.capability()
            if not capability.available:
                raise RuntimeError(capability.availability_note)
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            progress(100, "Video Depth Anything Small 已安装")
            return capability
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            if backup.exists():
                shutil.rmtree(self.home, ignore_errors=True)
                os.replace(backup, self.home)
            raise

    def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        working_root: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> DepthEngineOutput:
        capability = self.capability()
        if not capability.available:
            raise RuntimeError(capability.availability_note)
        assert self.ffmpeg is not None
        assert self.ffprobe is not None
        python = _resolve_command(self.python)
        assert python is not None
        working_root.mkdir(parents=True, exist_ok=True)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        clipped = working_root / "source-shot.mp4"
        raw_root = working_root / "raw"
        raw_root.mkdir(parents=True, exist_ok=True)
        _run(
            [
                self.ffmpeg,
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
            timeout=600,
        )
        _run(
            [
                python,
                str(self.home / "run.py"),
                "--input_video",
                str(clipped),
                "--output_dir",
                str(raw_root),
                "--encoder",
                MODEL_VARIANT,
                "--grayscale",
            ],
            cwd=self.home,
            timeout=1800,
        )
        raw_output = raw_root / f"{clipped.stem}_vis.mp4"
        if not raw_output.is_file():
            matches = sorted(raw_root.glob("*_vis.mp4"))
            if len(matches) != 1:
                raise RuntimeError("Video Depth Anything 未输出预期的深度视频")
            raw_output = matches[0]
        _run(
            [
                self.ffmpeg,
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
            timeout=600,
        )
        width, height, fps, duration, frame_count = _probe(
            self.ffprobe, destination_path
        )
        expected_duration = end_seconds - start_seconds
        duration_error = abs(duration - expected_duration)
        if duration_error > max(0.35, expected_duration * 0.08):
            raise RuntimeError("深度视频与原分镜时长不一致，已阻止提交")
        metrics = _quality_metrics(python, destination_path)
        dynamic_range = float(metrics.get("dynamic_range") or 0)
        if dynamic_range < 0.10:
            raise RuntimeError("深度视频灰度层次不足，无法可靠表达前后空间")
        midpoint = max(0.0, min(duration / 2, max(0.0, duration - 0.05)))
        _run(
            [
                self.ffmpeg,
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
            timeout=120,
        )
        metrics["duration_error_seconds"] = round(duration_error, 6)
        metrics["source_duration_seconds"] = round(expected_duration, 6)
        return DepthEngineOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration,
            frame_count=frame_count,
            validation_message="全场景深度、时长、帧率与灰度动态范围检查通过",
            validation_metrics=metrics,
        )
