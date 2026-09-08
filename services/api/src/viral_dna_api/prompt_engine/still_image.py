"""Image-only projection of shared directing instructions; never changes video text.

Keep static photography and reference fidelity. Remove named video sections and
recognizable temporal directives, not generic words such as '镜头' or '一致'.
"""

from __future__ import annotations

import re
from typing import Any

from .punctuation import normalize_prompt_punctuation

VIDEO_SECTIONS = {
    "连续性锁定",
    "主体一致性",
    "统一视觉锁定",
    "首帧约束",
    "连续性引用",
    "全片镜头规范",
    "全片运动规范",
    "全片声音",
    "时序运镜",
    "时间轴",
    "镜头运动",
    "全片运镜",
    "运镜",
    "运镜约束",
    "主体动作",
    "动作阶段",
    "焦点变化",
    "同步音效",
    "音效",
    "出场转场",
    "转场指令",
    "剪辑落点",
}
VIDEO_STYLE_KEYS = {
    "allowed_motion",
    "avoid_motion",
    "camera_motion",
    "motion",
    "motion_extent",
    "fps",
    "shutter_angle",
    "action_phases",
    "continuity_locks",
    "sound",
    "editing",
}
_VIDEO_DIRECTIVE = re.compile(
    r"运镜|镜头运动|摄影机运动|摄像机运动|一镜到底|自动切镜|切换镜头|突然换景|"
    r"跨(?:帧|镜头)|前后镜头|相邻镜头|上一(?:镜|帧)|下一(?:镜|帧)|连续镜头|单一连续|"
    r"逐帧|帧间|首尾帧|时间轴|时间过程|时间序列|动作阶段|全过程|时序|"
    r"(?:(?:镜头|摄影机|摄像机|机位).{0,12}(?:推进|推近|拉远|横移|环绕|跟随|跟拍|移动|晃动|抖动))|"
    r"(?:缓慢|慢速|快速|极慢|轻缓)(?:直线)?(?:推进|推近|横移|摇镜|变焦|跟拍|环绕)|"
    r"(?:甩镜|摇镜|推轨|拉镜|滑轨运动|手持抖动|手持晃动|快速变焦|速度渐变|变速转场)|"
    r"(?:焦点|焦平面).{0,10}(?:转移|移动|变化)|拉焦|"
    r"(?:禁止|不得|避免|不允许).{0,8}(?:切镜|转场|跳帧|频闪)|"
    r"(?:画面|人物|主体|构图).{0,10}(?:漂移|跳变|闪烁)|"
    r"无人机(?:穿越|运动|环绕)|\d+(?:\.\d+)?\s*[–—-]\s*\d+(?:\.\d+)?\s*(?:秒|s\b)|"
    r"\b(?:handheld_shake|random_handheld|unmotivated_whip_pan|fast_zoom|whip_pan|"
    r"speed_ramp|slow_(?:pan|push|orbit|linear_push|lateral_slider)|controlled_focus_pull|"
    r"hard_cut|match_cut|crossfade|dissolve|camera\s+(?:movement|motion|pan|tracking)|"
    r"single\s+(?:continuous\s+)?shot|across\s+(?:frames|shots)|temporal\s+consistency)\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'“[^”]*”|「[^」]*」|"[^"\n]*"')
_NEGATION = re.compile(r"^(?:禁止|不得|不要|避免|不允许)")


def contains_video_directives(value: str) -> bool:
    # Words printed on packaging or named in quoted content are not directions.
    return bool(_VIDEO_DIRECTIVE.search(_QUOTED.sub("", value)))


def _static_clause(value: str) -> str:
    if not contains_video_directives(value):
        return value
    # A motion list such as '运镜缓慢、稳定、克制' is one instruction.
    if re.match(r"^(?:全片)?(?:运镜|镜头运动|摄影机运动|摄像机运动)\s*[：:]?", value):
        return ""
    parts = re.split(r"[，,、]", value)
    kept = [part.strip() for part in parts if part.strip() and not contains_video_directives(part)]
    result = "，".join(kept)
    negation = _NEGATION.match(value)
    if result and negation and not _NEGATION.match(result):
        result = negation.group() + result
    return result


def static_image_text(value: str | None) -> str:
    """Remove only video-specific sections/clauses from current image instructions."""
    text = str(value or "").strip()
    blocks = []
    for block in re.split(r"(?=【[^】]+】)", text):
        header = re.match(r"【([^】]+)】", block)
        if header and header.group(1) in VIDEO_SECTIONS:
            continue
        label = header.group() if header else ""
        body = block[len(label) :].strip()
        if contains_video_directives(body):
            clauses = re.split(r"([。；;\n])", body)
            fragments = []
            for index in range(0, len(clauses), 2):
                clean = _static_clause(clauses[index].strip())
                if clean:
                    fragments.append(
                        clean + (clauses[index + 1] if index + 1 < len(clauses) else "")
                    )
            body = "".join(fragments).strip("，、；; \n")
        if body:
            blocks.append(label + body)
    return normalize_prompt_punctuation("\n".join(blocks).strip())


def static_image_constraints(values: list[str]) -> list[str]:
    return list(dict.fromkeys(clean for value in values if (clean := static_image_text(value))))


def static_image_style(value: Any) -> Any:
    """Project shared style fields before turning their values into prose."""
    if isinstance(value, str):
        return static_image_text(value)
    if isinstance(value, list):
        return [clean for item in value if (clean := static_image_style(item)) not in ("", [], {})]
    if isinstance(value, dict):
        return {
            key: clean
            for key, item in value.items()
            if key not in VIDEO_STYLE_KEYS
            and (clean := static_image_style(item)) not in ("", [], {})
        }
    return value
