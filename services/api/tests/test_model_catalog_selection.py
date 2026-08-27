from __future__ import annotations

import pytest

from viral_dna_api.ai.catalog import load_model_plan
from viral_dna_api.ai.text_model_routing import preferred_text_model_aliases
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


def test_account_text_model_only_overrides_text_generation_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.delenv("VIRAL_DNA_VLM_MODEL_ALIAS", raising=False)

    plan = load_model_plan(
        AnalysisProfile.ECONOMY,
        preferred_aliases=preferred_text_model_aliases(
            "qwen37",
            {"video_prompt": "qwen36flash"},
        ),
        fallback_enabled=False,
    )

    assert plan is not None
    assert [item.alias for item in plan.targets_for(ModelTask.SHOT_FACTS)] == ["qwen37"]
    assert [item.alias for item in plan.targets_for(ModelTask.PROMPT_GENERATION)] == [
        "qwen37"
    ]
    assert [item.alias for item in plan.targets_for(ModelTask.VIRAL_REASONING)] == [
        "qwen37"
    ]
    assert [item.alias for item in plan.targets_for(ModelTask.VIDEO_INTENT)] == [
        "qwen36flash"
    ]
    assert [item.alias for item in plan.targets_for(ModelTask.SHOT_SEGMENTATION)] == [
        "qwen36flash",
        "qwen37",
    ]


def test_account_text_model_keeps_profile_fallbacks_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    monkeypatch.delenv("VIRAL_DNA_VLM_MODEL_ALIAS", raising=False)

    plan = load_model_plan(
        AnalysisProfile.ECONOMY,
        preferred_aliases=preferred_text_model_aliases("qwen37"),
        fallback_enabled=True,
    )

    assert plan is not None
    assert [item.alias for item in plan.targets_for(ModelTask.VIDEO_INTENT)] == [
        "qwen37",
        "qwen36flash",
    ]
