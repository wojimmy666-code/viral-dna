from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from viral_dna_api.chinese import to_simplified
from viral_dna_api.main import app


def test_workspace_records_folders_reopen_and_exports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "ViralDNA 工作区"
    env_file = tmp_path / ".env.local"
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_file))
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "before-switch"))
    monkeypatch.setenv("VIRAL_DNA_ANALYZER_MODE", "simulated")

    with TestClient(app) as client:
        validation = client.post(
            "/api/v1/workspace/validate",
            json={"path": str(workspace)},
        )
        assert validation.status_code == 200
        assert validation.json()["valid"] is True

        switched = client.put(
            "/api/v1/workspace",
            json={"path": str(workspace)},
        )
        assert switched.status_code == 200
        assert Path(switched.json()["root_path"]) == workspace.resolve()
        assert (workspace / ".viraldna" / "workspace.json").is_file()
        assert "VIRAL_DNA_WORKSPACE_ROOT=" in env_file.read_text("utf-8")

        uploaded = client.post(
            "/api/v1/videos/upload",
            files={"file": ("demo.mp4", b"workspace-video", "video/mp4")},
            data={"title": "工作區影片", "rights_confirmed": "true"},
        )
        assert uploaded.status_code == 201
        video = uploaded.json()
        record_id = video["record_id"]
        source_root = workspace / "records" / record_id / "source"
        assert (source_root / "original.mp4").read_bytes() == b"workspace-video"
        assert (source_root / "metadata.json").is_file()

        folder = client.post("/api/v1/folders", json={"name": "參考影片"})
        assert folder.status_code == 201
        assert folder.json()["name"] == "参考影片"
        folder_id = folder.json()["id"]

        renamed_folder = client.patch(
            f"/api/v1/folders/{folder_id}",
            json={"name": "重點案例"},
        )
        assert renamed_folder.status_code == 200
        assert renamed_folder.json()["name"] == "重点案例"

        moved = client.patch(
            f"/api/v1/records/{record_id}",
            json={"name": "產品示範影片", "folder_id": folder_id},
        )
        assert moved.status_code == 200
        assert moved.json()["name"] == "产品示范影片"

        records = client.get(
            "/api/v1/records",
            params={"q": "示范", "folder_id": folder_id},
        )
        assert records.status_code == 200
        assert records.json()["total"] == 1

        analysis = client.post(
            f"/api/v1/records/{record_id}/analyses",
            json={"granularity": "fine", "include_audio": True, "include_ocr": True},
        )
        assert analysis.status_code == 202
        analysis_id = analysis.json()["id"]
        deadline = time.monotonic() + 3
        stage = "queued"
        while time.monotonic() < deadline and stage != "completed":
            stage = client.get(f"/api/v1/analyses/{analysis_id}").json()["stage"]
            time.sleep(0.02)
        assert stage == "completed"

        reopened = client.get(f"/api/v1/records/{record_id}")
        assert reopened.status_code == 200
        detail = reopened.json()
        assert detail["record"]["latest_analysis_id"] == analysis_id
        assert detail["latest_report"]["analysis_id"] == analysis_id
        assert len(detail["analyses"]) == 1
        report_path = (
            workspace / "records" / record_id / "analyses" / analysis_id / "report.json"
        )
        assert report_path.is_file()

        exported = client.post(
            f"/api/v1/records/{record_id}/exports",
            json={"kinds": ["report_json", "report_markdown", "prompt_package"]},
        )
        assert exported.status_code == 201
        artifacts = exported.json()
        assert {item["kind"] for item in artifacts} == {
            "report_json",
            "report_markdown",
            "prompt_package",
        }
        export_root = workspace / "records" / record_id / "exports" / analysis_id
        assert (export_root / "report.json").is_file()
        assert (export_root / "report.md").is_file()
        assert (export_root / "prompt-package.json").is_file()
        downloaded = client.get(f"/api/v1/exports/{artifacts[0]['id']}/download")
        assert downloaded.status_code == 200

        entity_id = detail["latest_report"]["entities"][0]["id"]
        replacement = client.post(
            f"/api/v1/videos/{video['id']}/replacement-versions",
            json={
                "replacements": [
                    {"entity_id": entity_id, "description": "白色西装人物"}
                ]
            },
        )
        assert replacement.status_code == 201
        replacement_payload = replacement.json()
        replacement_export = client.post(
            f"/api/v1/records/{record_id}/exports",
            json={
                "analysis_id": analysis_id,
                "replacement_version_id": replacement_payload["id"],
                "kinds": ["prompt_package"],
            },
        )
        assert replacement_export.status_code == 201
        replacement_artifact = replacement_export.json()[0]
        assert replacement_artifact["filename"].startswith(
            "prompt-package-replacement-"
        )
        replacement_file = export_root / replacement_artifact["filename"]
        assert replacement_file.is_file()
        assert json.loads(replacement_file.read_text("utf-8"))["id"] == (
            replacement_payload["prompt_package"]["id"]
        )

        metadata = json.loads((source_root / "metadata.json").read_text("utf-8"))
        assert metadata["record_id"] == record_id
        updated_at_before_restart = client.get(
            f"/api/v1/records/{record_id}"
        ).json()["record"]["updated_at"]

    with TestClient(app) as restarted_client:
        restarted = restarted_client.get(f"/api/v1/records/{record_id}")
        assert restarted.json()["record"]["updated_at"] == updated_at_before_restart


def test_traditional_chinese_is_normalized() -> None:
    assert to_simplified("影片後臺與鏡頭對話、場景資訊") == "影片后台与镜头对话、场景资讯"
