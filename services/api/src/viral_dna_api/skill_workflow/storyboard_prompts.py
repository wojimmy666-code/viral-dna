"""Editable shot bodies and frozen, non-editable project prompt context.

No model call, translation of user prose, or regeneration of a creative spec is
performed here. The bodies are authoritative; specs remain directing metadata.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .contracts import ShotManifestRevision, StyleBibleRevision

DISPLAY_TERMS = {
    "preserve subject identity and material detail": "保持主体身份与材质细节一致",
    "keep one coherent visual language": "全片保持统一的视觉语言",
    "one dominant subject per shot": "每个镜头只有一个视觉主体",
    "reserve safe area for deterministic typography": "为后期准确叠加文字预留安全区域",
    "controlled motivated lighting": "光线受控且具有合理光源",
    "no invented certifications or claims": "不得编造认证或宣传声明",
    "no generated logo or unreadable packaging text": "不得生成标志或不可辨认的包装文字",
    "no unexplained identity changes": "不得无故改变主体身份",
    "warm_side_backlight": "暖色侧逆光",
    "extremely_light": "极轻薄雾",
    "soft_not_clipped": "柔和高光且不过曝",
    "locked": "固定机位",
    "slow_linear_push": "缓慢直线推进",
    "slow_lateral_slider": "缓慢横向滑动",
    "restrained_arc": "克制的小幅环绕",
    "controlled_focus_pull": "有控制的焦点转移",
    "slow_push": "缓慢推进",
    "slow_pan": "缓慢摇镜",
    "macro": "微距",
    "handheld_shake": "手持抖动",
    "random_handheld": "无目的手持晃动",
    "unmotivated_whip_pan": "无动机的快速甩镜",
    "drone": "无人机航拍",
    "fast_zoom": "快速变焦",
    "whip_pan": "快速甩镜",
    "speed_ramp": "速度渐变",
    "hard_cut": "直接切换",
    "cut": "直接切换",
    "match_cut": "匹配剪辑",
    "dissolve": "叠化",
    "crossfade": "交叉淡化",
    "fade": "淡入淡出",
    "brand_then_reference": "以品牌资料为主，参考素材为辅",
    "project_asset": "以项目素材为准",
    "deterministic_overlay": "后期准确叠加",
    "forbidden": "禁止",
    "charcoal": "炭黑",
    "warm_amber": "暖琥珀",
    "grey_olive": "灰橄榄",
    "cream": "奶油白",
    "low": "低",
    "medium": "中等",
    "high": "高",
    "hook": "开场引入",
    "reveal": "主体揭示",
    "proof": "价值证明",
    "resolution": "结尾收束",
    "slow_orbit": "缓慢环绕",
    "macro_slide": "微距横移",
    "gentle_follow": "轻缓跟拍",
    "detail_insert": "细节特写",
    "tracking": "跟拍",
    "low_angle_follow": "低机位跟拍",
    "controlled_whip": "有控制的甩镜",
    "near_field": "近场拟音",
    "restrained": "克制",
    "physically_matched": "与动作物理特征一致",
    "continuous_sound_bed": "连续环境声底",
    "minimal_low_frequency_industrial": "极简低频工业音乐",
    "no_dialogue": "不生成对白",
    "no_narration": "不生成旁白",
}


def chinese_term(value: str) -> str:
    """Translate only platform-owned labels, never arbitrary/manual prose."""
    return DISPLAY_TERMS.get(value, DISPLAY_TERMS.get(value.lower(), value))


_STYLE_LABELS = {
    "principles": "原则",
    "colors": "色彩",
    "base_colors": "基底色",
    "source": "依据",
    "saturation": "饱和度",
    "brand_accent": "品牌色",
    "temperature_kelvin": "色温 K",
    "direction": "方向",
    "contrast": "光比",
    "haze": "薄雾",
    "highlight": "高光",
    "camera_character": "摄影质感",
    "fps": "帧率",
    "shutter_angle": "快门角度",
    "allowed_motion": "镜头运动",
    "avoid_motion": "避免的镜头运动",
    "render_mode": "文字处理",
    "generated_text": "生成文字",
    "max_lines": "最大行数",
    "grain": "颗粒",
    "description": "说明",
    "style": "风格",
    "font_family": "字体",
    "font_weight": "字重",
    "placement": "位置",
    "music_cue": "音乐要求",
    "ambience": "环境音",
    "forbidden": "禁止",
    "base": "基底色",
    "detail_ratio": "细节镜头占比",
    "environment_ratio": "环境镜头占比",
    "dialogue": "对白",
    "narration": "旁白",
    "shot_music": "镜头内配乐",
    "synchronous_foley": "同步拟音",
    "required": "是否需要",
    "qualities": "质感",
    "strategy": "策略",
    "level": "音量",
    "bpm": "BPM",
    "bpm_tolerance": "节拍容差",
}


def style_text(value: Any) -> str:
    if isinstance(value, str):
        return chinese_term(value)
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (float, int)):
        return str(value)
    if isinstance(value, list):
        return "、".join(filter(None, (style_text(item) for item in value)))
    if isinstance(value, dict):
        return "；".join(
            f"{_STYLE_LABELS[key]}：{style_text(item)}"
            if key in _STYLE_LABELS
            else style_text(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    return ""


def common_style_prompt(bible: StyleBibleRevision, *, video: bool) -> str:
    # Sound, motion and typography instructions never enter static image context.
    sections = [
        ("全片风格", bible.positive_lock),
        ("全片色彩", bible.palette),
        ("全片构图", bible.composition),
        ("全片光线", bible.lighting),
        ("全片材质", bible.texture),
        ("主体一致性", [*bible.product_identity_lock, *bible.character_identity_lock]),
    ]
    if video:
        sound = {key: value for key, value in bible.sound.items() if key != "editing_music"}
        sections += [
            ("全片镜头规范", bible.camera),
            ("全片运动规范", bible.motion),
            ("全片声音", sound),
        ]
    sections += [("全片禁用内容", bible.negative_lock)]
    return "\n".join(f"【{name}】{style_text(value)}" for name, value in sections if value)


def prompt_sections(prompt: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"【([^】]+)】", prompt))
    if not matches:
        return [("", prompt)] if prompt else []
    sections = [("", prompt[: matches[0].start()].strip())] if matches[0].start() else []
    sections += [
        (
            match.group(1),
            prompt[
                match.start() : matches[index + 1].start()
                if index + 1 < len(matches)
                else len(prompt)
            ].strip(),
        )
        for index, match in enumerate(matches)
    ]
    return sections


def editable_prompt_body(shot: Any, part: str) -> str:
    value = getattr(shot, f"{part}_prompt_body", None)
    return value if value is not None else getattr(shot, f"{part}_prompt")


def local_body_from_prompt(prompt: str, common: str, *, video: bool) -> str:
    shared = set(prompt_sections(common))
    return "\n\n".join(
        text
        for name, text in prompt_sections(prompt)
        if (name, text) not in shared and not (video and name == "首帧约束")
    )


def factor_prompt_context(
    manifest: ShotManifestRevision, bible: StyleBibleRevision
) -> ShotManifestRevision:
    """Factor genuinely repeated sections only; never discard shot-specific text."""
    if not manifest.shots or all(
        shot.image_prompt_body is not None and shot.video_prompt_body is not None
        for shot in manifest.shots
    ):
        return manifest
    updates: dict[str, Any] = {}
    shots = list(manifest.shots)
    for part in ("image", "video"):
        candidates = {
            "参考约束",
            "连续性锁定",
            "确定性图形",
            "统一视觉锁定",
            "光线与色彩",
            "严格约束",
        }
        parsed = [prompt_sections(getattr(shot, f"{part}_prompt")) for shot in shots]
        common = set(parsed[0]) if parsed else set()
        for sections in parsed[1:]:
            common.intersection_update(sections)
        common = {
            (name, text)
            for name, text in common
            if name in candidates and (len(shots) > 1 or name not in {"严格约束", "光线与色彩"})
        }
        shared = [common_style_prompt(bible, video=part == "video")]
        shared += [text for name, text in parsed[0] if (name, text) in common] if parsed else []
        updates[f"common_{part}_prompt"] = "\n\n".join(filter(None, shared))
        for index, shot in enumerate(shots):
            # Bind the first frame to current timing, never a stale shot number.
            local = "\n\n".join(
                text
                for name, text in parsed[index]
                if (name, text) not in common and not (part == "video" and name == "首帧约束")
            )
            shots[index] = shot.model_copy(update={f"{part}_prompt_body": local})
    return manifest.model_copy(update={**updates, "shots": shots})


def effective_prompt(
    body: str, common: str, *, video: bool, duration: int, aspect_ratio: str, fps: int
) -> str:
    if not body.strip():
        return ""
    first_frame = (
        (
            "【首帧约束】以当前分镜已采用的图片为唯一首帧、主体、场景、构图与明暗关系依据，"
            f"生成{duration}秒、{aspect_ratio}、{fps}fps的单一连续镜头。"
            "一镜到底，不得擅自改变主体身份、几何结构或自动切镜。"
        )
        if video
        else ""
    )
    return "\n\n".join(filter(None, [first_frame, common, body]))


def allocate_frames(weights: Sequence[int], total: int) -> list[int]:
    """Largest-remainder allocation, with >=1 frame per active shot and exact total."""
    if not weights:
        return []
    # Never reject or drop shots to fit a duration target: retain at least one frame each.
    total = max(total, len(weights))
    if sum(weights) == total and all(weight > 0 for weight in weights):
        return list(weights)
    positive = [max(1, value) for value in weights]
    remaining = total - len(positive)
    denominator = sum(positive)
    allocations = [1 + remaining * weight // denominator for weight in positive]
    residual = total - sum(allocations)
    order = sorted(
        range(len(positive)),
        key=lambda index: (-(remaining * positive[index] % denominator), index),
    )
    for index in order[:residual]:
        allocations[index] += 1
    return allocations


def creative_approach(manifest: ShotManifestRevision, outline: Any, objective: str = "") -> str:
    if manifest.creative_approach:
        return manifest.creative_approach
    beats = getattr(outline, "beats", [])
    ideas = [str(beat.message or beat.purpose).strip().rstrip("。；") for beat in beats]
    summary = "；".join(dict.fromkeys(filter(None, ideas))) or objective
    if len(summary) > 150:
        summary = summary[:149].rstrip("，；、") + "。"
    elif summary and not summary.endswith("。"):
        summary += "。"
    return summary


def draft_issues(manifest: ShotManifestRevision) -> list[str]:
    if not manifest.shots:
        return ["请至少添加一个分镜"]
    return [
        f"分镜 {shot.order} 的{'图片' if part == 'image' else '视频'}提示词尚未填写"
        for shot in manifest.shots
        for part in ("image", "video")
        if not editable_prompt_body(shot, part).strip()
    ]
