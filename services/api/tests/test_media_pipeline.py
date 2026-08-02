from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viral_dna_api.link_ingestion import LinkIngestionResult
from viral_dna_api.main import app
from viral_dna_api.models import SourceType

FFMPEG = shutil.which("ffmpeg")


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

        report_response = client.get(f"/api/v1/videos/{video_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["analysis_mode"] == "media_evidence"
        assert report["viral_findings"] == []
        assert report["entities"] == []
        assert report["evidence_timeline"]["timeline_version"] == (
            "phase1-evidence-timeline-v1"
        )
        assert len(report["evidence_timeline"]["shots"]) == len(report["shots"])
        assert {
            run["kind"]: run["status"]
            for run in report["evidence_timeline"]["provider_runs"]
        } == {"asr": "skipped", "ocr": "skipped"}
        assert report["media_evidence"]["metadata"]["duration_seconds"] == pytest.approx(
            2.0, abs=0.1
        )
        assert len(report["shots"]) >= 2

        proxy_response = client.get(report["media_evidence"]["proxy_url"])
        keyframe_response = client.get(report["shots"][0]["keyframe_url"])
        manifest_response = client.get(report["media_evidence"]["manifest_url"])
        timeline_response = client.get(report["evidence_timeline"]["artifact_url"])
        assert proxy_response.status_code == 200
        assert len(proxy_response.content) > 100
        assert keyframe_response.status_code == 200
        assert keyframe_response.headers["content-type"].startswith("image/jpeg")
        assert manifest_response.status_code == 200
        assert manifest_response.json()["processor_version"] == "ffmpeg-media-v1"
        assert timeline_response.status_code == 200
        assert timeline_response.json()["timeline_version"] == "phase1-evidence-timeline-v1"


def test_real_link_analysis_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "linked-two-scenes.mp4"
    storage_root = tmp_path / "storage"
    create_two_scene_video(source_path)
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_ANALYZER_MODE", "hybrid")

    class FakeLinkCollector:
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
        video_id = video_response.json()["id"]

        analysis_response = client.post(
            f"/api/v1/videos/{video_id}/analyses",
            json={"granularity": "fine", "include_audio": True, "include_ocr": True},
        )
        assert analysis_response.status_code == 202
        analysis_payload = analysis_response.json()
        assert analysis_payload["analysis_mode"] == "media_evidence"
        assert analysis_payload["analysis_version"] == "phase1-link-evidence-timeline-v1"
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

        report_response = client.get(f"/api/v1/videos/{video_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["analysis_mode"] == "media_evidence"
        assert len(report["shots"]) >= 2
        assert len(report["evidence_timeline"]["shots"]) == len(report["shots"])
        assert report["evidence_timeline"]["artifact_url"].endswith("/timeline.json")
