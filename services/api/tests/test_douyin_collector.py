from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError, ExtractorError

from viral_dna_api.douyin_extractor import DouyinPageIE, share_video_detail
from viral_dna_api.link_ingestion import (
    LinkCollector,
    LinkCredentialSession,
    LinkIngestionError,
    _ObservedYoutubeDL,
    _YtDlpLogger,
)


def share_page(video_id="123"):
    return "window._ROUTER_DATA = " + json.dumps({"loaderData": {"video_(id)/page": {
        "videoInfoRes": {"item_list": [{"aweme_id": video_id, "video": {"duration": 2000}}]},
    }}}) + ";alert('never execute')"


@pytest.mark.parametrize(("status", "message", "code"), [
    (403, "Fresh cookies needed", "link_access_denied"),
    (429, "Fresh cookies needed", "link_rate_limited"),
    (503, "Fresh cookies needed", "link_platform_unavailable"),
    (401, "Fresh cookies needed", "link_auth_required"),
    (None, "Fresh cookies needed", "link_metadata_unavailable"),
    (None, "timed out; Fresh cookies needed", "link_download_timeout"),
    (None, "certificate verify failed; Fresh cookies needed", "link_network_failed"),
    (None, "Login required", "link_auth_required"),
    (None, "captcha", "link_auth_required"),
])
def test_real_cause_is_not_replaced_with_cookie_expiry(status, message, code):
    logger = _YtDlpLogger()
    logger.http_status = status
    error = LinkCollector()._translate_download_error(DownloadError(message + " SECRET"), logger)
    assert error.code == code
    assert "SECRET" not in str(error)


def test_http_status_survives_extractors_generic_error(monkeypatch):
    response = Response(io.BytesIO(b""), "https://www.douyin.com/", {}, status=403)

    def fail(*args):
        raise HTTPError(response)

    monkeypatch.setattr(YoutubeDL, "urlopen", fail)
    logger = _YtDlpLogger()
    with _ObservedYoutubeDL({"logger": logger}, auto_init=False) as downloader:
        with pytest.raises(HTTPError):
            downloader.urlopen("https://www.douyin.com/")
    assert logger.http_status == 403


def test_share_json_only_accepts_requested_video():
    assert share_video_detail(share_page(), "123")["aweme_id"] == "123"
    assert share_video_detail(share_page("456"), "123") is None
    assert share_video_detail("window._ROUTER_DATA = alert(1)", "123") is None
    assert share_video_detail('window._ROUTER_DATA = {"loaderData":{}}', "123") is None


def test_public_share_fallback_is_automatic_and_discards_old_http_failure(monkeypatch):
    def api_failure(*args):
        raise ExtractorError("Fresh cookies are needed")

    monkeypatch.setattr(DouyinIE, "_real_extract", api_failure)
    extractor = DouyinPageIE()
    logger = _YtDlpLogger()
    logger.http_status = 403
    extractor._downloader = SimpleNamespace(params={"logger": logger})
    monkeypatch.setattr(extractor, "_download_webpage", lambda *args, **kwargs: share_page())
    monkeypatch.setattr(extractor, "_parse_aweme_video_app", lambda data: {
        "id": data["aweme_id"], "formats": [
            {"url": "https://v3.douyinvod.com/public.mp4"},
            {"url": "http://127.0.0.1/private.mp4"},
            {"url": "https://douyinvod.com.evil.example/video.mp4"},
        ],
    })
    info = extractor._real_extract("https://www.douyin.com/video/123")
    assert info["id"] == "123"
    assert len(info["formats"]) == 1
    assert info["webpage_url"] == "https://www.douyin.com/video/123"
    assert logger.http_status is None


def test_empty_share_page_does_not_fake_success_or_reset_primary_failure(monkeypatch):
    original = ExtractorError("Fresh cookies are needed")

    def api_failure(*args):
        raise original

    monkeypatch.setattr(DouyinIE, "_real_extract", api_failure)
    extractor = DouyinPageIE()
    monkeypatch.setattr(extractor, "_download_webpage", lambda *args, **kwargs: "app shell only")
    with pytest.raises(ExtractorError) as caught:
        extractor._real_extract("https://www.douyin.com/video/123")
    assert caught.value is original


@pytest.mark.asyncio
async def test_metadata_test_uses_same_worker_without_downloading(monkeypatch):
    collector = LinkCollector()
    session = LinkCredentialSession(True, "always", "test")
    calls = []

    async def worker(url, target, credentials, *, metadata_only=False):
        calls.append((url, credentials, metadata_only))
        return {"id": "123"}

    monkeypatch.setattr(collector, "_download_process", worker)
    await collector.probe_url("https://www.douyin.com/user/self?modal_id=123", session)
    assert calls == [("https://www.douyin.com/video/123", session, True)]


@pytest.mark.asyncio
async def test_metadata_test_cancels_worker_at_deadline(monkeypatch):
    collector = LinkCollector()
    collector.timeout_seconds = 0.02
    stopped = asyncio.Event()

    async def worker(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(collector, "_download_process", worker)
    with pytest.raises(LinkIngestionError) as caught:
        await collector.probe_url(
            "https://www.douyin.com/video/123", LinkCredentialSession(True, "always", "test"),
        )
    assert caught.value.code == "link_probe_timeout"
    assert stopped.is_set()
