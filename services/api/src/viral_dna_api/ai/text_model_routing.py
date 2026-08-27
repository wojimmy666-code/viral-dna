from __future__ import annotations

from collections.abc import Mapping

from ..models import ModelTask, TextGenerationPurpose

DEFAULT_TEXT_MODEL_ALIAS = "qwen37"

TEXT_MODEL_TASK_ROUTES: dict[TextGenerationPurpose, tuple[ModelTask, ...]] = {
    TextGenerationPurpose.REPLICATION_PLAN: (ModelTask.VIRAL_REASONING,),
    TextGenerationPurpose.SHOT_IMAGE_PROMPT: (
        ModelTask.SHOT_FACTS,
        ModelTask.PROMPT_GENERATION,
    ),
    TextGenerationPurpose.VIDEO_PROMPT: (ModelTask.VIDEO_INTENT,),
}


def preferred_text_model_aliases(
    default_alias: str = DEFAULT_TEXT_MODEL_ALIAS,
    overrides: Mapping[TextGenerationPurpose | str, str] | None = None,
) -> dict[ModelTask, str]:
    normalized_overrides = {
        TextGenerationPurpose(key): value
        for key, value in (overrides or {}).items()
        if value
    }
    aliases: dict[ModelTask, str] = {}
    for purpose, tasks in TEXT_MODEL_TASK_ROUTES.items():
        alias = normalized_overrides.get(purpose, default_alias)
        for task in tasks:
            aliases[task] = alias
    return aliases


def effective_text_model_alias(
    purpose: TextGenerationPurpose,
    default_alias: str = DEFAULT_TEXT_MODEL_ALIAS,
    overrides: Mapping[TextGenerationPurpose | str, str] | None = None,
) -> str:
    return preferred_text_model_aliases(default_alias, overrides)[
        TEXT_MODEL_TASK_ROUTES[purpose][0]
    ]
