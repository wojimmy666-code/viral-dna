from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viral_dna_api.main import app


def _isolate_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    for name in (
        "VIRAL_DNA_VLM_PROVIDER",
        "VIRAL_DNA_VLM_MODEL_ALIAS",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "VIRAL_DNA_MODEL_LAST_VALIDATED_AT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_model_settings_api_returns_catalog_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_runtime_config(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/v1/settings/model")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "dashscope"
    assert payload["model_alias"] == "auto"
    assert payload["api_key_configured"] is False
    assert payload["api_key_hint"] is None
    assert {item["alias"] for item in payload["models"]} == {"qwen37", "qwen36flash"}
    assert "api_key" not in payload


def test_model_settings_api_rejects_endpoint_that_could_exfiltrate_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_runtime_config(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/settings/model",
            json={
                "provider": "dashscope",
                "model_alias": "auto",
                "api_key": "must-not-leak",
                "base_url": "https://evil.example/compatible-mode/v1",
            },
        )

    assert response.status_code == 422
    assert "保护 API Key" in response.json()["detail"]
    assert "must-not-leak" not in response.text
