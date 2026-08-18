from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from viral_dna_api.control_assets.engines import DepthEngineCapability
from viral_dna_api.control_assets.engines.video_depth_anything import (
    CHECKPOINT_SHA256,
    DEPENDENCY_PROFILE,
    REPOSITORY_SSH_URL,
    RUNTIME_REQUIREMENTS,
)
from viral_dna_api.control_assets.service import (
    DepthControlService,
    _filesystem_path,
    _write_json,
    _write_text_atomic,
)
from viral_dna_api.workspace import WorkspaceManager


def _capability(*, available: bool) -> DepthEngineCapability:
    return DepthEngineCapability(
        engine="video_depth_anything",
        version="test",
        model_variant="vits",
        available=available,
        availability_note="" if available else "尚未安装",
        repository_url="https://github.com/DepthAnything/Video-Depth-Anything",
        checkpoint_path=Path("checkpoint.pth") if available else None,
        runtime_path=Path("runtime") if available else None,
        license="Apache-2.0",
    )


class FakeDepthEngine:
    def __init__(self, *, fail: bool = False) -> None:
        self.available = False
        self.fail = fail

    def capability(self) -> DepthEngineCapability:
        return _capability(available=self.available)

    def install(self, progress) -> DepthEngineCapability:
        progress(20, "准备依赖")
        time.sleep(0.03)
        progress(80, "下载模型")
        if self.fail:
            raise RuntimeError("模拟安装失败")
        self.available = True
        return self.capability()


class FakeNotificationPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, **payload):
        self.events.append(payload)
        return payload


async def _wait_for_terminal(service: DepthControlService, installation_id) -> object:
    for _ in range(100):
        installation = service.installation(installation_id)
        if installation.status in {"succeeded", "failed"}:
            return installation
        await asyncio.sleep(0.01)
    raise AssertionError("安装任务没有进入终态")


@pytest.mark.asyncio
async def test_depth_engine_installation_reports_progress_and_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    engine = FakeDepthEngine()
    notifications = FakeNotificationPublisher()
    service = DepthControlService(
        WorkspaceManager(),
        engine=engine,
        notification_publisher=notifications,
    )

    queued = await service.start_installation("video_depth_anything")
    duplicate = await service.start_installation("video_depth_anything")
    assert duplicate.id == queued.id

    completed = await _wait_for_terminal(service, queued.id)
    assert completed.status == "succeeded"
    assert completed.progress_percent == 100
    assert completed.capability is not None
    assert completed.capability.available is True
    assert notifications.events[-1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_depth_engine_installation_preserves_failure_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    service = DepthControlService(
        WorkspaceManager(),
        engine=FakeDepthEngine(fail=True),
    )

    queued = await service.start_installation("video_depth_anything")
    completed = await _wait_for_terminal(service, queued.id)
    assert completed.status == "failed"
    assert completed.error == "模拟安装失败"


def test_depth_engine_installer_uses_ssh_and_pinned_small_checkpoint() -> None:
    assert REPOSITORY_SSH_URL == (
        "git@github.com:DepthAnything/Video-Depth-Anything.git"
    )
    assert len(CHECKPOINT_SHA256) == 64
    assert CHECKPOINT_SHA256 == CHECKPOINT_SHA256.lower()
    assert DEPENDENCY_PROFILE == "viral-dna-inference-core/v1"
    assert "xformers==0.0.23" not in RUNTIME_REQUIREMENTS
    assert "OpenEXR==3.3.1" not in RUNTIME_REQUIREMENTS
    assert "torch==2.1.1" in RUNTIME_REQUIREMENTS


def test_depth_atomic_writes_support_windows_long_paths(tmp_path: Path) -> None:
    root = tmp_path
    while len(str(root / "manifest.json")) < 280:
        root /= "deep-depth-control-artifact-segment"
    manifest = root / "manifest.json"
    diagnostics = root / "stderr-tail.log"

    _write_json(manifest, {"status": "passed", "message": "深度资产已保存"})
    _write_text_atomic(diagnostics, "诊断信息")

    assert _filesystem_path(manifest).read_text(encoding="utf-8").startswith("{")
    assert "深度资产已保存" in _filesystem_path(manifest).read_text(encoding="utf-8")
    assert _filesystem_path(diagnostics).read_text(encoding="utf-8") == "诊断信息"
    assert not list(_filesystem_path(root).glob(".tmp-*"))
