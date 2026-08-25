from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from viral_dna_api.video_enhancement import engine as engine_module
from viral_dna_api.video_enhancement.engine import RealEsrganNcnnEngine


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
