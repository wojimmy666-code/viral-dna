from uuid import uuid4

import pytest

from viral_dna_api.project_prompts import (
    ProjectPromptRevision,
    ProjectPromptService,
    compose_prompt,
    local_prompt,
)
from viral_dna_api.prompt_engine.punctuation import normalize_prompt_punctuation
from viral_dna_api.store import InMemoryStore


def test_only_repeated_chinese_full_stops_are_cleaned():
    text = "主体。。场景。。。\n2.5 秒……镜头...\n@目录/产品。。png https://example.com/a。。png\n光线。。"
    expected = (
        "主体。场景。\n2.5 秒……镜头...\n@目录/产品。。png https://example.com/a。。png\n光线。"
    )
    assert normalize_prompt_punctuation(text) == expected
    assert normalize_prompt_punctuation(expected) == expected
    assert (
        normalize_prompt_punctuation("参考 @素材/产品 45度。。png，黑色背景。。")
        == "参考 @素材/产品 45度。。png，黑色背景。"
    )
    for part in ("image", "video"):
        assert "主体。。" not in compose_prompt("【主体】主体。。", "【全片色彩】低饱和。。", part)


@pytest.mark.asyncio
async def test_current_projection_cleans_both_parts_without_rewriting_stored_revision():
    store = InMemoryStore()
    scope = uuid4()
    service = ProjectPromptService(store)
    initial = await service.current(scope)
    original = ProjectPromptRevision(
        project_id=scope,
        revision_number=1,
        common_image_prompt="【全片色彩】冷色。。",
        common_video_prompt="【全片运动】慢速。。",
    )
    await store.save_project_prompt_revision(original, initial.id)
    current = await service.current(scope)
    assert current.id == original.id
    assert current.common_image_prompt == "【全片色彩】冷色。"
    assert current.common_video_prompt == "【全片运动】慢速。"
    assert (await store.list_project_prompt_revisions(scope))[
        0
    ].model_dump() == original.model_dump()
    assert (
        local_prompt("【全片运动】慢速。。\n【本镜头】左移。。", current, "video")
        == "【本镜头】左移。"
    )
