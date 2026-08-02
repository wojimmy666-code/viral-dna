from __future__ import annotations

import os
import time
from pathlib import Path

os.environ["VIRAL_DNA_SIMULATION_DELAY"] = "0.01"

from fastapi.testclient import TestClient  # noqa: E402

from viral_dna_api.main import app  # noqa: E402


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_video() -> None:
    payload = b"phase-one-video-fixture"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/videos/upload",
            files={"file": ("breakfast.mp4", payload, "video/mp4")},
            data={"title": "上传测试", "target_model": "seedance", "rights_confirmed": "true"},
        )
    assert response.status_code == 201
    video = response.json()
    stored_path = Path("storage") / "uploads" / video["id"] / "breakfast.mp4"
    assert video["source_type"] == "upload"
    assert stored_path.read_bytes() == payload
    stored_path.unlink(missing_ok=True)
    stored_path.parent.rmdir()


def test_link_analysis_and_replacement_flow() -> None:
    with TestClient(app) as client:
        video_response = client.post(
            "/api/v1/videos/link",
            json={
                "url": "https://v.douyin.com/example/",
                "title": "测试视频",
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
        analysis_id = analysis_response.json()["id"]

        deadline = time.monotonic() + 2
        stage = "queued"
        while time.monotonic() < deadline and stage != "completed":
            status_response = client.get(f"/api/v1/analyses/{analysis_id}")
            assert status_response.status_code == 200
            stage = status_response.json()["stage"]
            time.sleep(0.02)

        assert stage == "completed"

        report_response = client.get(f"/api/v1/videos/{video_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["analysis_mode"] == "simulated"
        assert len(report["shots"]) == 5
        assert report["prompt_package"]["target_model"] == "seedance"

        replacement_response = client.post(
            f"/api/v1/videos/{video_id}/replacement-versions",
            json={
                "replacements": [
                    {
                        "entity_id": "person_01",
                        "description": "35 岁中国男厨师，短发，沉稳气质",
                    }
                ],
                "locks": ["timing", "camera", "composition", "action"],
            },
        )
        assert replacement_response.status_code == 201
        replacement = replacement_response.json()
        assert replacement["prompt_package"]["version"] == 2
        assert replacement["diffs"][0]["entity_id"] == "person_01"


def test_rejects_non_platform_link() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/videos/link",
            json={
                "url": "https://example.com/video.mp4",
                "rights_confirmed": True,
            },
        )
    assert response.status_code == 422


def test_requires_rights_confirmation() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/videos/link",
            json={
                "url": "https://www.xiaohongshu.com/explore/example",
                "rights_confirmed": False,
            },
        )
    assert response.status_code == 422
