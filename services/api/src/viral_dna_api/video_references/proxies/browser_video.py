from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from uuid import uuid4


class BrowserVideoEncodingError(RuntimeError):
    """Raised when a privacy proxy cannot be delivered as browser-safe MP4."""


class FfmpegBrowserVideoEncoder:
    """Encode proxy video as H.264/yuv420p MP4 without exposing long paths to ffmpeg."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable
        self._lock = threading.Lock()

    def _resolve_executable(self) -> str:
        configured = (
            self.executable
            or os.getenv("VIRAL_DNA_FFMPEG_PATH", "").strip()
            or "ffmpeg"
        )
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise BrowserVideoEncodingError(
            "未找到 FFmpeg，无法生成浏览器可播放的 H.264 视频白模"
        )

    def encode(self, source_path: Path, destination_path: Path) -> Path:
        """Encode atomically, using a short temporary path for Windows compatibility."""

        executable = self._resolve_executable()
        with self._lock, tempfile.TemporaryDirectory(prefix="viraldna-white-model-") as root:
            temp_root = Path(root)
            input_suffix = source_path.suffix.lower() or ".avi"
            staged_source = temp_root / f"source{input_suffix}"
            staged_output = temp_root / "browser.mp4"
            shutil.copyfile(source_path, staged_source)
            command = [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(staged_source),
                "-map_metadata",
                "-1",
                "-an",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2:in_range=full:out_range=tv,"
                "format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-movflags",
                "+faststart",
                str(staged_output),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BrowserVideoEncodingError(
                    "FFmpeg 启动失败或处理超时，无法生成视频白模"
                ) from exc
            if result.returncode != 0 or not staged_output.is_file():
                detail = result.stderr.decode("utf-8", errors="replace").strip()[-800:]
                raise BrowserVideoEncodingError(
                    f"FFmpeg 无法编码视频白模：{detail or '未知编码错误'}"
                )

            destination_path.parent.mkdir(parents=True, exist_ok=True)
            pending = destination_path.with_name(
                f".{destination_path.stem}.{uuid4().hex}.tmp.mp4"
            )
            try:
                shutil.copyfile(staged_output, pending)
                os.replace(pending, destination_path)
            finally:
                pending.unlink(missing_ok=True)
        return destination_path

    def ensure_cached_preview(self, source_path: Path, preview_path: Path) -> Path:
        """Create a derived H.264 preview for legacy mp4v proxy assets."""

        try:
            if (
                preview_path.is_file()
                and preview_path.stat().st_size > 0
                and preview_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns
            ):
                return preview_path
        except OSError:
            pass
        return self.encode(source_path, preview_path)
