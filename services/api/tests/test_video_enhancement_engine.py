from __future__ import annotations

import asyncio
import hashlib
import zipfile
from pathlib import Path

import pytest

from viral_dna_api.video_enhancement import engine as engine_module
from viral_dna_api.video_enhancement.domain import VideoEnhancementJobStage
from viral_dna_api.video_enhancement.engine import (
    RealEsrganNcnnEngine,
    _NcnnProgressParser,
)


def _write_package(path: Path, *, include_binary_model: bool = True) -> str:
    root = "realesrgan-ncnn-vulkan-20220424-windows"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(f"{root}/realesrgan-ncnn-vulkan.exe", b"engine")
        package.writestr(f"{root}/vcomp140.dll", b"runtime")
        package.writestr(f"{root}/models/realesrgan-x4plus.param", b"model graph")
        if include_binary_model:
            package.writestr(f"{root}/models/realesrgan-x4plus.bin", b"model weights")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configured_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package: Path,
    package_sha256: str,
) -> tuple[RealEsrganNcnnEngine, Path]:
    destination = tmp_path / "tools" / "realesrgan-ncnn-vulkan" / "0.2.0"
    monkeypatch.setattr(engine_module, "WINDOWS_PACKAGE_URL", package.as_uri())
    monkeypatch.setattr(engine_module, "WINDOWS_PACKAGE_SHA256", package_sha256)
    monkeypatch.setattr(engine_module, "_automatic_install_supported", lambda: True)
    engine = RealEsrganNcnnEngine()
    engine.executable = destination / "realesrgan-ncnn-vulkan.exe"
    engine.ffmpeg = "ffmpeg"
    engine.ffprobe = "ffprobe"
    return engine, destination


def test_installer_replaces_a_partial_install_with_the_complete_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "complete.zip"
    package_sha256 = _write_package(package)
    engine, destination = _configured_engine(
        tmp_path,
        monkeypatch,
        package,
        package_sha256,
    )
    destination.mkdir(parents=True)
    (destination / "realesrgan-ncnn-vulkan.exe").write_bytes(b"old engine")
    (destination / "partial-install.txt").write_text("stale", encoding="utf-8")
    updates: list[tuple[int, str]] = []

    capability = engine.install(lambda percent, message: updates.append((percent, message)))

    assert capability.available is True
    assert capability.installation_path == destination
    assert (destination / "models" / "realesrgan-x4plus.param").is_file()
    assert (destination / "models" / "realesrgan-x4plus.bin").is_file()
    assert not (destination / "partial-install.txt").exists()
    assert updates[-1] == (100, "Real-ESRGAN 快速引擎已安装")
    assert not list(destination.parent.glob("*.backup"))
    assert not list(destination.parent.glob("*.prepared"))


def test_installer_keeps_the_existing_install_when_the_package_lacks_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "missing-model.zip"
    package_sha256 = _write_package(package, include_binary_model=False)
    engine, destination = _configured_engine(
        tmp_path,
        monkeypatch,
        package,
        package_sha256,
    )
    destination.mkdir(parents=True)
    marker = destination / "partial-install.txt"
    marker.write_text("keep until replacement is validated", encoding="utf-8")

    with pytest.raises(RuntimeError, match="realesrgan-x4plus.bin"):
        engine.install(lambda _percent, _message: None)

    assert marker.read_text("utf-8") == "keep until replacement is validated"


def test_ncnn_progress_counts_completed_frames_across_split_output() -> None:
    async def scenario() -> None:
        updates = []

        async def capture(event) -> None:
            updates.append(event)

        parser = _NcnnProgressParser(capture, total_frames=4)
        await parser.feed_stderr("93.33%\ninput/frame_00000001.png -> output/frame_")
        assert updates == []
        await parser.feed_stderr("00000001.png done\n0.00%\n")
        await parser.feed_stdout("input/frame_00000002.png -> output/frame_00000002.png done\n")
        await parser.feed_stderr("input/frame_00000001.png -> output/frame_00000001.png done\n")

        assert len(updates) == 2
        assert updates[0].stage == VideoEnhancementJobStage.UPSCALING
        assert updates[0].processed_frames == 1
        assert updates[0].message == "正在增强画面细节 · 1/4 帧"
        assert updates[-1].processed_frames == 2
        assert updates[-1].percent == 50

    asyncio.run(scenario())
