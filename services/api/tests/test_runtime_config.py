from __future__ import annotations

from pathlib import Path

import pytest

from viral_dna_api.runtime_config import (
    RuntimeConfigError,
    get_config_value,
    persist_config_values,
    read_local_env,
)


def test_persist_config_values_preserves_unrelated_lines_and_updates_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "# 用户自己的配置\nKEEP_ME=yes\nDASHSCOPE_API_KEY=old-key\nDASHSCOPE_API_KEY=duplicate\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("VIRAL_DNA_VLM_MODEL_ALIAS", raising=False)

    saved_path = persist_config_values(
        {
            "DASHSCOPE_API_KEY": "new-secret-key",
            "VIRAL_DNA_VLM_MODEL_ALIAS": "qwen37",
        }
    )

    content = env_path.read_text(encoding="utf-8")
    assert saved_path == env_path
    assert "# 用户自己的配置" in content
    assert "KEEP_ME=yes" in content
    assert content.count("DASHSCOPE_API_KEY=") == 1
    assert "DASHSCOPE_API_KEY=new-secret-key" in content
    assert read_local_env()["VIRAL_DNA_VLM_MODEL_ALIAS"] == "qwen37"
    assert get_config_value("DASHSCOPE_API_KEY") == "new-secret-key"


def test_persist_config_values_rejects_line_injection(tmp_path: Path) -> None:
    with pytest.raises(RuntimeConfigError, match="不能包含换行"):
        persist_config_values(
            {"DASHSCOPE_API_KEY": "secret\nINJECTED=true"},
            path=tmp_path / ".env.local",
        )
    assert not (tmp_path / ".env.local").exists()
