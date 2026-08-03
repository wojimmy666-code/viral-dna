from __future__ import annotations

import pytest

from viral_dna_api.ai.catalog import load_model_plan
from viral_dna_api.models import AnalysisProfile, ModelTask


def test_gui_selected_model_becomes_primary_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.setenv("VIRAL_DNA_VLM_MODEL_ALIAS", "qwen36flash")

    plan = load_model_plan(AnalysisProfile.BALANCED)

    assert plan is not None
    for task in ModelTask:
        targets = plan.targets_for(task)
        assert targets
        assert targets[0].alias == "qwen36flash"
