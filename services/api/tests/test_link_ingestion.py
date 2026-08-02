from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from viral_dna_api.link_ingestion import (
    LinkCollector,
    LinkIngestionError,
    identify_platform,
)
from viral_dna_api.models import SourceType, Video


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://v.douyin.com/abc123/", SourceType.DOUYIN),
        ("https://www.douyin.com/video/123", SourceType.DOUYIN),
        ("https://xhslink.com/m/abc123", SourceType.XIAOHONGSHU),
        ("https://www.xiaohongshu.com/explore/abc123", SourceType.XIAOHONGSHU),
        ("https://www.rednote.com/explore/abc123", SourceType.XIAOHONGSHU),
    ],
)
def test_identify_platform(url: str, expected: SourceType) -> None:
    assert identify_platform(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video.mp4",
        "https://xiaohongshu.com.evil.example/video",
        "https://127.0.0.1/video",
        "https://user:password@www.douyin.com/video/123",
        "https://www.douyin.com:8080/video/123",
    ],
)
def test_identify_platform_rejects_unsafe_url(url: str) -> None:
    with pytest.raises(LinkIngestionError):
        identify_platform(url)


def test_collect_persists_sanitized_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path / "storage"))
    collector = LinkCollector()
    video = Video(
        source_type=SourceType.XIAOHONGSHU,
        source_url="https://www.xiaohongshu.com/explore/note-1?xsec_token=test#fragment",
        title="小红书链接视频",
    )

    def fake_download(
        source_url: str,
        target_dir: Path,
        _logger: object,
    ) -> dict[str, object]:
        assert source_url.endswith("xsec_token=test")
        output_path = target_dir / "source.mp4"
        output_path.write_bytes(b"fake-public-video")
        return {
            "id": "note-1",
            "title": "测试公开视频",
            "uploader": "测试作者",
            "duration": 12.5,
            "webpage_url": source_url,
            "_filename": str(output_path),
        }

    monkeypatch.setattr(collector, "_download_sync", fake_download)
    result = asyncio.run(collector.collect(video))

    assert result.platform == SourceType.XIAOHONGSHU
    assert result.path.read_bytes() == b"fake-public-video"
    assert result.source_video_id == "note-1"
    assert result.title == "测试公开视频"
    assert result.author == "测试作者"
    assert result.duration_seconds == 12.5
    assert "#fragment" not in result.resolved_url

    manifest = json.loads((result.path.parent / "ingestion.json").read_text(encoding="utf-8"))
    assert manifest["collector_version"] == "yt-dlp-link-v1"
    assert manifest["platform"] == "xiaohongshu"
    assert manifest["source_video_id"] == "note-1"
    assert manifest["file_size_bytes"] == len(b"fake-public-video")


def test_collect_translates_platform_auth_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(tmp_path / "storage"))
    collector = LinkCollector()
    video = Video(
        source_type=SourceType.DOUYIN,
        source_url="https://v.douyin.com/test/",
        title="抖音链接视频",
    )

    def fail_download(*_args: object) -> dict[str, object]:
        raise DownloadError("Fresh cookies are needed")

    monkeypatch.setattr(collector, "_download_sync", fail_download)
    with pytest.raises(LinkIngestionError) as caught:
        asyncio.run(collector.collect(video))

    assert caught.value.code == "link_auth_required"
    assert caught.value.retryable is True
    assert "Cookie" in str(caught.value)
