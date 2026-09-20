from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from viral_dna_api.link_ingestion import (
    LinkCollector,
    LinkCredentialSession,
    LinkIngestionError,
    configured_timeout,
    normalize_platform_url,
)
from viral_dna_api.link_worker import download
from viral_dna_api.models import AnalysisJob, AnalysisMode, SourceType, Video
from viral_dna_api.real_pipeline import HybridAnalysisPipeline
from viral_dna_api.store import InMemoryStore


def test_favorite_link_uses_modal_video_not_private_profile():
    assert normalize_platform_url(
        "https://www.douyin.com/user/self?from_tab_name=main&modal_id=7686022704168443034"
        "&showSubTab=video&showTab=favorite_collection"
    ) == "https://www.douyin.com/video/7686022704168443034"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_timeout_never_disables_deadline(value, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_LINK_TIMEOUT_SECONDS", value)
    assert configured_timeout("VIRAL_DNA_LINK_TIMEOUT_SECONDS", 120) == 120


@pytest.mark.asyncio
async def test_link_deadline_includes_credential_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path))
    cancelled = asyncio.Event()

    class Resolver:
        @asynccontextmanager
        async def session_for(self, platform):
            try:
                await asyncio.Event().wait()
                yield
            finally:
                cancelled.set()

    collector = LinkCollector(Resolver())
    collector.timeout_seconds = 0.05
    with pytest.raises(LinkIngestionError) as caught:
        await collector.collect(Video(title="test", source_type=SourceType.DOUYIN,
                                      source_url="https://www.douyin.com/video/123"))
    assert cancelled.is_set()
    assert caught.value.code == "link_download_timeout"
    assert caught.value.retryable


@pytest.mark.asyncio
async def test_link_deadline_is_shared_by_anonymous_and_authenticated_attempts(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path))
    second_cancelled = asyncio.Event()
    session_closed = asyncio.Event()
    attempts = []

    class Resolver:
        @asynccontextmanager
        async def session_for(self, platform):
            try:
                yield LinkCredentialSession(True, "on_auth_required", "test")
            finally:
                session_closed.set()

        async def report_failure(self, *args):
            pass

    collector = LinkCollector(Resolver())
    collector.timeout_seconds = 0.15

    async def fake_download(url, directory, session):
        attempts.append(session)
        if session is None:
            await asyncio.sleep(0.03)
            raise LinkIngestionError("link_auth_required", "login", retryable=True)
        try:
            await asyncio.Event().wait()
        finally:
            second_cancelled.set()

    monkeypatch.setattr(collector, "_download_process", fake_download)
    with pytest.raises(LinkIngestionError, match="已停止"):
        await collector.collect(Video(title="test", source_type=SourceType.DOUYIN,
                                      source_url="https://www.douyin.com/video/123"))
    assert len(attempts) == 2
    assert second_cancelled.is_set() and session_closed.is_set()


@pytest.mark.asyncio
async def test_download_process_is_reaped_on_cancellation(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path))
    real_spawn = asyncio.create_subprocess_exec
    children = []
    started = asyncio.Event()

    async def fake_spawn(*args, **kwargs):
        if "viral_dna_api.link_worker" in args:
            assert "cookie-secret" not in " ".join(args)
            process = await real_spawn(
                sys.executable, "-c", "import time; time.sleep(60)", **kwargs,
            )
            children.append(process)
            started.set()
            return process
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    collector = LinkCollector()
    task = asyncio.create_task(collector._download_process(
        "https://www.douyin.com/video/123", tmp_path,
        LinkCredentialSession(True, "always", "test", tmp_path / "cookie-secret"),
    ))
    try:
        async with asyncio.timeout(5):
            await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert children[0].returncode is not None
    finally:
        for process in children:
            if process.returncode is None:
                process.kill()
                await process.wait()


def test_worker_translates_auth_errors_without_leaking_secrets(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise DownloadError("Login required secret-cookie-value")

    monkeypatch.setattr(LinkCollector, "_download_sync", fail)
    response = download({
        "source_url": "https://www.douyin.com/video/123", "target_dir": str(tmp_path),
        "max_download_bytes": 1024, "socket_timeout": 1, "retries": 0,
        "use_legacy_cookie": False,
    })
    assert response["error"]["code"] == "link_auth_required"
    assert "secret-cookie-value" not in json.dumps(response)


def test_worker_protocol_without_network(tmp_path):
    env = dict(os.environ)
    env["VIRAL_DNA_WORKSPACE_ROOT"] = str(tmp_path)
    env["VIRAL_DNA_STORAGE_ROOT"] = str(tmp_path)
    env["VIRAL_DNA_AUTH_MODE"] = "password"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "viral_dna_api.link_worker"],
        input=json.dumps({
            "source_url": "https://www.douyin.com/video/123", "target_dir": str(tmp_path),
            "max_download_bytes": 1024, "socket_timeout": 1, "retries": 0,
            "use_legacy_cookie": False, "cookie_file": str(tmp_path / "missing-cookie.txt"),
        }).encode(),
        capture_output=True, env=env, timeout=20,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout)["error"]["code"] == "link_cookie_file_missing"


@pytest.mark.asyncio
async def test_analysis_timeout_persists_failure_and_cancels_work(monkeypatch):
    repository = InMemoryStore()
    video = await repository.add_video(Video(title="test", source_type=SourceType.UPLOAD))
    analysis = await repository.add_analysis(AnalysisJob(
        video_id=video.id, analysis_mode=AnalysisMode.MEDIA_EVIDENCE, simulated=False,
    ))
    pipeline = HybridAnalysisPipeline(repository)
    pipeline.timeout_seconds = 0.05
    stopped = asyncio.Event()

    async def hanging_work(analysis, video, budget=None):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(pipeline, "_run_analysis", hanging_work)
    await pipeline.run(analysis.id)
    saved = await repository.get_analysis(analysis.id)
    assert stopped.is_set()
    assert saved.stage == "failed"
    assert saved.error.code == "analysis_timeout" and saved.error.retryable
    assert saved.completed_at is not None
    assert (await repository.get_video(video.id)).status == "failed"
    assert await repository.get_report(video.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["link_auth_required", "link_access_denied"])
async def test_pipeline_preserves_immediate_auth_failure(monkeypatch, code):
    repository = InMemoryStore()
    video = await repository.add_video(Video(
        title="test", source_type=SourceType.DOUYIN, source_url="https://www.douyin.com/video/123",
    ))
    analysis = await repository.add_analysis(AnalysisJob(
        video_id=video.id, analysis_mode=AnalysisMode.MEDIA_EVIDENCE, simulated=False,
    ))

    async def auth_required(*args):
        raise LinkIngestionError(code, "平台读取失败", retryable=True)

    monkeypatch.setattr(LinkCollector, "collect", auth_required)
    await HybridAnalysisPipeline(repository).run(analysis.id)
    assert analysis.stage == "failed"
    assert analysis.error.code == code
    assert analysis.progress == 3
    assert await repository.get_report(video.id) is None
