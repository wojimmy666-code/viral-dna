from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viral_dna_api.link_ingestion import LinkIngestionResult
from viral_dna_api.main import app
from viral_dna_api.media import MediaProcessor
from viral_dna_api.models import SourceType
from viral_dna_api.records import resolve_record_name_from_video

FFMPEG = shutil.which("ffmpeg")


def test_platform_title_replaces_only_generated_record_placeholder() -> None:
    source_title = "春天会抵达 所有未完成的约定 #转场 #歌曲"

    assert resolve_record_name_from_video("抖音链接视频", source_title) == source_title
    assert resolve_record_name_from_video("小红书链接视频", source_title) == source_title
    assert resolve_record_name_from_video("TikTok链接视频", source_title) == source_title
    assert resolve_record_name_from_video("Instagram链接视频", source_title) == source_title
    assert (
        resolve_record_name_from_video("人工命名的活动素材", source_title)
        == "人工命名的活动素材"
    )


def create_two_scene_video(output_path: Path) -> None:
    if FFMPEG is None:
        pytest.skip("FFmpeg is not available")
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
        check=True,
        timeout=30,
    )


def add_mov_text_subtitles(source_path: Path, output_path: Path, subtitle_path: Path) -> None:
    if FFMPEG is None:
        pytest.skip("FFmpeg is not available")
    subtitle_path.write_text(
        "1\n00:00:00,200 --> 00:00:01,200\n第一句字幕\n\n"
        "2\n00:00:01,200 --> 00:00:01,900\n第二句字幕\n",
        "utf-8",
    )
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source_path),
            "-i",
            str(subtitle_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            str(output_path),
        ],
        check=True,
        timeout=30,
    )


@pytest.mark.asyncio
async def test_media_processor_extracts_text_subtitle_stream(tmp_path: Path) -> None:
    source_path = tmp_path / "source.mp4"
    subtitled_path = tmp_path / "subtitled.mp4"
    subtitle_source = tmp_path / "source.srt"
    extracted_path = tmp_path / "extracted.srt"
    create_two_scene_video(source_path)
    add_mov_text_subtitles(source_path, subtitled_path, subtitle_source)

    processor = MediaProcessor()
    metadata = await processor.probe(subtitled_path)

    assert len(metadata.subtitle_streams) == 1
    stream = metadata.subtitle_streams[0]
    assert stream.codec_name == "mov_text"
    assert stream.extractable is True

    await processor.extract_subtitle(subtitled_path, extracted_path, stream.index)
    extracted = extracted_path.read_text("utf-8")
    assert "第一句字幕" in extracted
    assert "第二句字幕" in extracted


def test_real_upload_analysis_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "two-scenes.mp4"
    storage_root = tmp_path / "storage"
    create_two_scene_video(source_path)
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))

    with TestClient(app) as client, source_path.open("rb") as source:
        upload_response = client.post(
            "/api/v1/videos/upload",
            files={"file": (source_path.name, source, "video/mp4")},
            data={
                "title": "真实双场景测试",
                "target_model": "seedance",
                "rights_confirmed": "true",
            },
        )
        assert upload_response.status_code == 201
        video_id = upload_response.json()["id"]

        analysis_response = client.post(
            f"/api/v1/videos/{video_id}/analyses",
            json={"granularity": "fine", "include_audio": True, "include_ocr": True},
        )
        assert analysis_response.status_code == 202
        analysis_payload = analysis_response.json()
        assert analysis_payload["analysis_mode"] == "media_evidence"
        assert analysis_payload["simulated"] is False
        analysis_id = analysis_payload["id"]

        deadline = time.monotonic() + 30
        status_payload = analysis_payload
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/analyses/{analysis_id}")
            assert response.status_code == 200
            status_payload = response.json()
            if status_payload["stage"] in {"completed", "failed"}:
                break
            time.sleep(0.1)

        assert status_payload["stage"] == "completed", status_payload.get("error")

        video_response = client.get(f"/api/v1/videos/{video_id}")
        assert video_response.status_code == 200
        processed_video = video_response.json()
        assert processed_video["width"] == 320
        assert processed_video["height"] == 240
        assert processed_video["has_audio"] is True
        assert len(processed_video["sha256"]) == 64

        records_response = client.get("/api/v1/records")
        assert records_response.status_code == 200
        record_id = upload_response.json()["record_id"]
        record_summary = next(
            item for item in records_response.json()["items"] if item["id"] == record_id
        )
        assert record_summary["duration_seconds"] == pytest.approx(2.0, abs=0.1)
        assert record_summary["thumbnail_url"].startswith(
            f"/api/v1/records/{record_id}/thumbnail?v="
        )
        thumbnail_response = client.get(record_summary["thumbnail_url"])
        assert thumbnail_response.status_code == 200
        assert thumbnail_response.headers["content-type"].startswith("image/jpeg")
        assert thumbnail_response.headers["etag"]
        assert thumbnail_response.content.startswith(b"\xff\xd8")

        report_response = client.get(f"/api/v1/videos/{video_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["analysis_mode"] == "media_evidence"
        assert report["viral_findings"] == []
        assert report["entities"] == []
        assert report["evidence_timeline"]["timeline_version"] == ("phase1-evidence-timeline-v2")
        assert len(report["evidence_timeline"]["shots"]) == len(report["shots"])
        assert {
            run["kind"]: run["status"] for run in report["evidence_timeline"]["provider_runs"]
        } == {"asr": "skipped", "ocr": "skipped", "subtitle": "skipped"}
        assert report["media_evidence"]["metadata"]["duration_seconds"] == pytest.approx(
            2.0, abs=0.1
        )
        assert len(report["shots"]) >= 2
        segmentation = report["media_evidence"]["segmentation"]
        assert segmentation["detector_version"] == "ffmpeg-hybrid-candidates-v3"
        assert segmentation["candidate_count"] >= 1
        assert segmentation["verified_by_model"] is False
        assert segmentation["final_shot_count"] == len(report["shots"])
        assert len(segmentation["candidates"][0]["evidence_timestamps"]) == 4
        assert report["shots"][0]["boundary_method"] == "video_start"

        proxy_response = client.get(report["media_evidence"]["proxy_url"])
        keyframe_response = client.get(report["shots"][0]["keyframe_url"])
        manifest_response = client.get(report["media_evidence"]["manifest_url"])
        timeline_response = client.get(report["evidence_timeline"]["artifact_url"])
        context_response = client.get(segmentation["context_sheet_url"])
        comparison_response = client.get(segmentation["candidates"][0]["comparison_image_url"])
        assert proxy_response.status_code == 200
        assert len(proxy_response.content) > 100
        assert keyframe_response.status_code == 200
        assert keyframe_response.headers["content-type"].startswith("image/jpeg")
        assert manifest_response.status_code == 200
        assert (
            manifest_response.json()["processor_version"]
            == "ffmpeg-hybrid-candidates-v4-motion-clips"
        )
        assert context_response.status_code == 200
        assert comparison_response.status_code == 200
        assert timeline_response.status_code == 200
        assert timeline_response.json()["timeline_version"] == "phase1-evidence-timeline-v2"
        thumbnail_metadata = json.loads(
            (storage_root / "records" / record_id / "source" / "thumbnail.json").read_text("utf-8")
        )
        assert thumbnail_metadata["source_kind"] == "analysis_keyframe"
        assert thumbnail_metadata["analysis_id"] == analysis_id


def test_real_link_analysis_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "linked-two-scenes.mp4"
    storage_root = tmp_path / "storage"
    create_two_scene_video(source_path)
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_ANALYZER_MODE", "hybrid")

    class FakeLinkCollector:
        def __init__(self, _credential_resolver=None) -> None:
            pass

        async def collect(self, video) -> LinkIngestionResult:
            target_dir = storage_root / "links" / str(video.id)
            target_dir.mkdir(parents=True, exist_ok=True)
            downloaded_path = target_dir / "source.mp4"
            shutil.copy2(source_path, downloaded_path)
            return LinkIngestionResult(
                path=downloaded_path,
                platform=SourceType.XIAOHONGSHU,
                resolved_url=str(video.source_url),
                source_video_id="note-123",
                title="真实链接采集测试",
                author="测试作者",
                duration_seconds=2.0,
                file_size_bytes=downloaded_path.stat().st_size,
            )

    monkeypatch.setattr("viral_dna_api.real_pipeline.LinkCollector", FakeLinkCollector)

    with TestClient(app) as client:
        video_response = client.post(
            "/api/v1/videos/link",
            json={
                "url": "https://www.xiaohongshu.com/explore/note-123?xsec_token=test",
                "target_model": "seedance",
                "rights_confirmed": True,
            },
        )
        assert video_response.status_code == 201
        video_payload = video_response.json()
        video_id = video_payload["id"]
        record_id = video_payload["record_id"]

        analysis_response = client.post(
            f"/api/v1/videos/{video_id}/analyses",
            json={"granularity": "fine", "include_audio": True, "include_ocr": True},
        )
        assert analysis_response.status_code == 202
        analysis_payload = analysis_response.json()
        assert analysis_payload["analysis_mode"] == "media_evidence"
        assert analysis_payload["analysis_version"] == "phase1-link-evidence-timeline-v2"
        assert analysis_payload["simulated"] is False
        analysis_id = analysis_payload["id"]

        deadline = time.monotonic() + 30
        status_payload = analysis_payload
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/analyses/{analysis_id}")
            assert response.status_code == 200
            status_payload = response.json()
            if status_payload["stage"] in {"completed", "failed"}:
                break
            time.sleep(0.1)

        assert status_payload["stage"] == "completed", status_payload.get("error")
        processed_video = client.get(f"/api/v1/videos/{video_id}").json()
        assert processed_video["title"] == "真实链接采集测试"
        assert processed_video["resolved_source_url"].startswith("https://www.xiaohongshu.com/")
        assert processed_video["source_video_id"] == "note-123"
        assert processed_video["source_author"] == "测试作者"
        assert processed_video["ingested_at"] is not None
        assert processed_video["width"] == 320
        assert processed_video["height"] == 240
        record_detail = client.get(f"/api/v1/records/{record_id}")
        assert record_detail.status_code == 200
        assert record_detail.json()["record"]["name"] == "真实链接采集测试"

        report_response = client.get(f"/api/v1/videos/{video_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["analysis_mode"] == "media_evidence"
        assert len(report["shots"]) >= 2
        assert len(report["evidence_timeline"]["shots"]) == len(report["shots"])
        assert report["evidence_timeline"]["artifact_url"].endswith("/timeline.json")
