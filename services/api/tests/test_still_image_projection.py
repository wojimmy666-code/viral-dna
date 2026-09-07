from dataclasses import replace
from uuid import uuid4

import pytest
from test_generation_jobs import _project, _shot

from viral_dna_api.image_generation.contracts import ImageGenerationRequest
from viral_dna_api.image_generation.gateway import _compiled_prompt, _negative_prompt
from viral_dna_api.production import _shot_for_visual_beat, _still_image_prompt_view
from viral_dna_api.prompt_engine.compiler import sanitize_still_image_prompt
from viral_dna_api.prompt_engine.still_image import (
    contains_video_directives,
    static_image_constraints,
    static_image_style,
    static_image_text,
)

LEGACY_IMAGE = (
    "【主体与场景】滤芯位于工厂工作台，35mm 镜头，低机位，浅景深。\n"
    "【连续性锁定】上一镜头的产品始终一致。\n"
    "【光线与色彩】暖色侧逆光，低饱和度。\n"
    "【主体一致性】保持跨镜头主体一致。\n"
    "【全片禁用内容】禁止甩镜、水印、产品结构变形；不得自动切镜；不得编造认证。\n"
    "【严格约束】镜头缓慢推进，保留准确的产品几何结构。"
)


def test_static_projection_removes_video_sections_and_preserves_static_facts():
    clean = static_image_text(LEGACY_IMAGE)
    for value in ("连续性锁定", "主体一致性", "上一镜头", "甩镜", "自动切镜", "缓慢推进"):
        assert value not in clean
    for value in (
        "35mm",
        "低机位",
        "浅景深",
        "暖色侧逆光",
        "低饱和度",
        "禁止水印",
        "产品结构变形",
        "不得编造认证",
        "保留准确的产品几何结构",
    ):
        assert value in clean
    assert static_image_text(clean) == clean
    assert sanitize_still_image_prompt(LEGACY_IMAGE) == clean


@pytest.mark.parametrize(
    "text",
    [
        "85mm 镜头，固定机位，浅景深，暖色侧逆光。",
        "人物手持产品，机位俯视，画面右侧预留文字区域。",
        "无人机航拍视角，静态建筑全景，产品外观与参考图一致。",
        "包装印有“缓慢推进”和“0–2秒”，保留准确文字。",
    ],
)
def test_static_photography_pose_reference_and_quoted_copy_are_not_removed(text):
    assert static_image_text(text) == text


def test_shared_style_projection_removes_motion_fields_before_flattening():
    style = {
        "principles": ["真实工业纪录广告", "运镜缓慢、稳定、克制"],
        "allowed_motion": ["slow_linear_push", "slow_pan"],
        "avoid_motion": ["handheld_shake"],
        "fps": 30,
        "colors": ["charcoal", "warm_amber"],
        "description": "35mm 镜头，低机位，浅景深",
    }
    assert static_image_style(style) == {
        "principles": ["真实工业纪录广告"],
        "colors": ["charcoal", "warm_amber"],
        "description": "35mm 镜头，低机位，浅景深",
    }
    assert style["fps"] == 30
    assert static_image_constraints(
        ["禁止切镜", "不要水印", "运镜缓慢、稳定、克制", "不要水印"]
    ) == ["不要水印"]


@pytest.mark.parametrize("execution_mode", ["local_tool", "remote_api"])
def test_legacy_production_views_and_actual_gateway_requests_are_static(execution_mode):
    project = _project()
    shot = _shot(project)
    beat = shot.visual_beats[0].model_copy(
        update={
            "image_prompt": LEGACY_IMAGE,
            "image_negative_constraints": ["禁止切镜", "不要水印"],
        }
    )
    legacy = shot.model_copy(update={"image_prompt": LEGACY_IMAGE, "visual_beats": [beat]})
    snapshot = legacy.model_dump(mode="json")
    view = _still_image_prompt_view(legacy)
    gateway_shot = _shot_for_visual_beat(legacy, beat)
    assert view.image_prompt == gateway_shot.image_prompt == static_image_text(LEGACY_IMAGE)
    assert view.visual_beats[0].image_negative_constraints == ["不要水印"]
    assert gateway_shot.image_negative_constraints == ["不要水印"]
    request = ImageGenerationRequest(
        project=project,
        shot=legacy,
        revision_id=uuid4(),
        input_mode="text_to_image",
        source_path=None,
        source_sha256=None,
        references=[],
        candidate_count=1,
        execution_mode=execution_mode,
    )
    for input_mode in ("text_to_image", "keyframe_edit"):
        prompt = _compiled_prompt(replace(request, input_mode=input_mode))
        assert not contains_video_directives(prompt)
        assert "【连续性锁定】" not in prompt
        assert "【主体一致性】" not in prompt
        assert "35mm" in prompt and "低饱和度" in prompt
        assert not contains_video_directives(_negative_prompt(request))
    assert legacy.model_dump(mode="json") == snapshot
    assert view.video_prompt == legacy.video_prompt
