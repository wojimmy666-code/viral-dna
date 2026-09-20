from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from viral_dna_api.browser_assist import BrowserAssistService, local_request
from viral_dna_api.browser_budget import HumanPauseBudget
from viral_dna_api.douyin_browser_worker import (
    find_detail,
    imported_cookies,
    media_urls,
    seed_cookies,
)
from viral_dna_api.link_ingestion import (
    LinkCollector,
    LinkCredentialError,
    LinkCredentialSession,
    LinkIngestionError,
)
from viral_dna_api.models import AnalysisJob, AnalysisMode, SourceType, Video
from viral_dna_api.real_pipeline import HybridAnalysisPipeline
from viral_dna_api.store import InMemoryStore


def request(client="127.0.0.1", host="127.0.0.1:8000", **headers):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "client": (client, 1234),
            "headers": [
                (name.encode(), value.encode()) for name, value in {"host": host, **headers}.items()
            ],
        }
    )


@pytest.mark.parametrize(
    "client,host,headers,allowed",
    [
        ("127.0.0.1", "localhost:8000", {}, True),
        ("::1", "[::1]:8000", {}, True),
        ("10.0.0.2", "localhost:8000", {}, False),
        ("127.0.0.1", "www.viraldnastudio.com", {}, False),
        ("127.0.0.1", "localhost:8000", {"x-forwarded-for": "127.0.0.1"}, False),
        ("127.0.0.1", "localhost:8000", {"forwarded": "for=127.0.0.1"}, False),
        ("127.0.0.1", "localhost:8000", {"origin": "https://outside.example"}, False),
        ("127.0.0.1", "localhost:8000", {"origin": "http://127.0.0.1:4174"}, True),
    ],
)
def test_local_only_boundary(client, host, headers, allowed):
    assert local_request(request(client, host, **headers)) is allowed


@pytest.mark.asyncio
async def test_paused_budget_excludes_human_time_but_still_expires_after_resume():
    with pytest.raises(TimeoutError):
        async with HumanPauseBudget(0.12) as budget:
            budget.waiting(True)
            budget.waiting(True)  # Duplicate events must not reset remaining time.
            await asyncio.sleep(0.2)
            budget.waiting(False)
            budget.waiting(False)
            await asyncio.sleep(0.3)


def test_exact_target_only_and_no_untrusted_media_urls():
    wanted = {
        "aweme_id": "123",
        "video": {
            "play_addr": {
                "url_list": [
                    "https://v3.douyinvod.com/target.mp4",
                    "http://127.0.0.1/private",
                    "https://evil.example/media",
                    "https://douyinvod.com.evil.example/a",
                    "https://user:secret@douyinvod.com/a",
                    "https://douyinvod.com:8080/a",
                ]
            }
        },
    }
    payload = {"list": [{"aweme_id": "999", "video": {}}, wanted]}
    assert find_detail(payload, "123") is wanted
    assert find_detail(payload, "456") is None
    assert media_urls(wanted) == ["https://v3.douyinvod.com/target.mp4"]


def test_cookie_import_only_douyin_nonexpired(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tTRUE\t0\tsession\tprivate-value\n"
        ".example.com\tTRUE\t/\tTRUE\t0\tother\tother-value\n"
        ".douyin.com\tTRUE\t/\tTRUE\t1\told\texpired-value\n",
        encoding="utf-8",
    )
    result = imported_cookies(path)
    assert len(result) == 1 and result[0]["name"] == "session"


@pytest.mark.asyncio
async def test_incompatible_cookie_does_not_block_the_browser():
    accepted = []

    class Context:
        async def add_cookies(self, cookies):
            if any(item["name"] == "incompatible" for item in cookies):
                raise ValueError("invalid Cookie fields")
            accepted.extend(cookies)

    rejected = await seed_cookies(Context(), [{"name": "valid"}, {"name": "incompatible"}])
    assert rejected == 1 and accepted == [{"name": "valid"}]


@pytest.mark.asyncio
async def test_403_fallback_pauses_collect_deadline_only_for_human(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path))
    observed = []
    session_id = str(uuid4())

    class Assist:
        def available(self):
            return True

        async def download(self, url, target, credentials, seconds, maximum, progress):
            await progress({"id": session_id, "state": "waiting_user", "message": "验证"})
            await asyncio.sleep(0.25)
            await progress({"id": session_id, "state": "downloading", "message": "下载"})
            path = target / "original.mp4"
            path.write_bytes(b"verified-by-browser-worker")
            return {"id": "123", "filepath": str(path), "webpage_url": url, "duration": 3}

    async def denied(*args):
        raise LinkIngestionError("link_access_denied", "403")

    async def progress(event):
        observed.append(event["state"])

    collector = LinkCollector(browser_assist=Assist(), browser_progress=progress)
    collector.timeout_seconds = 0.2
    monkeypatch.setattr(collector, "_attempt_download", denied)
    result = await collector.collect(
        Video(
            title="target",
            source_type=SourceType.DOUYIN,
            source_url="https://www.douyin.com/video/123",
        )
    )
    assert result.path.is_file()
    assert observed == ["waiting_user", "downloading"]


@pytest.mark.asyncio
async def test_non_access_errors_do_not_open_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path))
    assist = SimpleNamespace(available=lambda: True)

    async def oversized(*args):
        raise LinkIngestionError("link_size_exceeded", "too large")

    collector = LinkCollector(browser_assist=assist)
    monkeypatch.setattr(collector, "_attempt_download", oversized)
    with pytest.raises(LinkIngestionError) as error:
        await collector.collect(
            Video(
                title="target",
                source_type=SourceType.DOUYIN,
                source_url="https://www.douyin.com/video/123",
            )
        )
    assert error.value.code == "link_size_exceeded"


@pytest.mark.asyncio
async def test_isolated_owner_and_duplicate_session(monkeypatch, tmp_path):
    service = BrowserAssistService(None, None)
    owner = (str(uuid4()), str(uuid4()), str(uuid4()))

    async def current():
        return owner

    monkeypatch.setattr(service, "owner", current)
    monkeypatch.setattr(service, "available", lambda: True)
    monkeypatch.setattr(service, "root", lambda: tmp_path)
    first = await service._new("download")
    with pytest.raises(LinkIngestionError) as error:
        await service._new("download")
    assert error.value.code == "link_browser_busy"
    first.state = "cancelled"
    first.process = SimpleNamespace(returncode=None)
    with pytest.raises(LinkIngestionError) as error:
        await service._new("download")
    assert error.value.code == "link_browser_busy"  # Still releasing the profile.
    owner = (owner[0], str(uuid4()), owner[2])
    with pytest.raises(HTTPException) as error:
        await service.control(first.id, "focus")
    assert error.value.status_code == 404
    assert (await service.status())["session"] is None
    assert (await service._new("download")).owner != first.owner


@pytest.mark.asyncio
async def test_connect_can_recover_from_unreadable_imported_cookie(monkeypatch):
    @asynccontextmanager
    async def broken_cookie(platform):
        raise LinkCredentialError("link_cookie_expired", "export expired")
        yield  # pragma: no cover

    service = BrowserAssistService(None, SimpleNamespace(session_for=broken_cookie))

    async def current():
        return ("test-account", "test-user", "test-device")

    async def run(session, payload, credentials, progress):
        assert credentials is None
        assert payload["source_url"] == "https://www.douyin.com/"
        session.state = "completed"

    monkeypatch.setattr(service, "owner", current)
    monkeypatch.setattr(service, "available", lambda: True)
    monkeypatch.setattr(service, "_run", run)
    result = await service.connect()
    session = service.sessions[result["id"]]
    await session.task
    assert session.state == "completed"


@pytest.mark.asyncio
async def test_probe_falls_back_without_downloading(monkeypatch):
    observed = []

    class Assist:
        def available(self):
            return True

        async def probe(self, url, credentials, seconds, progress):
            assert 0 < seconds <= 45
            observed.append(url)
            return {"id": "123", "title": "target"}

    async def denied(*args, **kwargs):
        assert kwargs["metadata_only"] is True
        raise LinkIngestionError("link_access_denied", "403")

    collector = LinkCollector(browser_assist=Assist())
    monkeypatch.setattr(collector, "_download_process", denied)
    info = await collector.probe_url(
        "https://www.douyin.com/user/self?modal_id=123",
        LinkCredentialSession(configured=False, strategy="disabled", source_label="test"),
    )
    assert info["id"] == "123"
    assert observed == ["https://www.douyin.com/video/123"]


@pytest.mark.asyncio
async def test_cancel_stops_owned_worker_even_during_download(monkeypatch, tmp_path):
    service = BrowserAssistService(None, None)
    owner = (str(uuid4()), str(uuid4()), str(uuid4()))

    async def current():
        return owner

    monkeypatch.setattr(service, "owner", current)
    monkeypatch.setattr(service, "available", lambda: True)
    monkeypatch.setattr(service, "root", lambda: tmp_path)
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        if "viral_dna_api.douyin_browser_worker" in args:
            return await real_spawn(
                sys.executable,
                "-u",
                "-c",
                "import sys,json,time; json.loads(sys.stdin.readline()); "
                "print(json.dumps({'state':'downloading','message':'test'}),flush=True); "
                "time.sleep(60)",
                **kwargs,
            )
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    started = asyncio.Event()

    async def progress(event):
        if event["state"] == "downloading":
            started.set()

    job = asyncio.create_task(
        service.download(
            "https://www.douyin.com/video/123",
            tmp_path,
            None,
            120,
            1000,
            progress,
        )
    )
    await asyncio.wait_for(started.wait(), 10)
    session = next(iter(service.sessions.values()))
    await service.control(session.id, "cancel")
    with pytest.raises(LinkIngestionError) as error:
        await job
    assert error.value.code == "link_browser_cancelled"
    assert session.process.returncode is not None


@pytest.mark.asyncio
async def test_pipeline_wait_is_same_analysis_and_does_not_consume_analysis_budget(monkeypatch):
    repository = InMemoryStore()
    video = await repository.add_video(
        Video(
            title="target",
            source_type=SourceType.DOUYIN,
            source_url="https://www.douyin.com/video/123",
        )
    )
    analysis = await repository.add_analysis(
        AnalysisJob(
            video_id=video.id,
            analysis_mode=AnalysisMode.MEDIA_EVIDENCE,
            simulated=False,
        )
    )
    session_id = str(uuid4())

    async def collect(self, video):
        await self.browser_progress({"id": session_id, "state": "waiting_user", "message": "验证"})
        current = await repository.get_analysis(analysis.id)
        assert current.stage == "waiting_user"
        await asyncio.sleep(0.2)
        await self.browser_progress({"id": session_id, "state": "failed", "message": "超时"})
        raise LinkIngestionError("link_verification_timeout", "等待人工验证超时", retryable=True)

    monkeypatch.setattr(LinkCollector, "collect", collect)
    pipeline = HybridAnalysisPipeline(repository)
    pipeline.timeout_seconds = 0.12
    await pipeline.run(analysis.id)
    final = await repository.get_analysis(analysis.id)
    assert final.error.code == "link_verification_timeout"
    assert str(final.browser_session_id) == session_id
    assert final.id == analysis.id and final.stage == "failed"
