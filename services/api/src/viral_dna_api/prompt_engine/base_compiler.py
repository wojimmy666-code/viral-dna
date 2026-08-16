from __future__ import annotations

import re
from collections.abc import Iterable

from .contracts import PromptShotDraft

_SPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = "。；;，,、 "
_PLACEHOLDER_VALUES = {
    "不确定",
    "未知",
    "无法判断",
    "无法确认",
    "无明显前景运动",
    "无明显变化",
}


def clean_text(value: str | None) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip().strip(_TRAILING_PUNCTUATION)


def unique_texts(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = re.sub(r"[\s。；;，,、：:]", "", text).casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _field_line(label: str, value: str | None) -> str:
    text = clean_text(value)
    if not text or text.casefold() in _PLACEHOLDER_VALUES:
        return ""
    return f"{label}：{text}"


def render_prompt(draft: PromptShotDraft, *, compact_timeline: bool = False) -> str:
    sections: list[str] = []
    visual_lines = unique_texts(
        [
            _field_line("主体", draft.visual.subjects),
            _field_line("场景", draft.visual.scene),
            _field_line("构图", draft.visual.composition),
            _field_line("光线", draft.visual.lighting),
            _field_line("色彩", draft.visual.color),
        ]
    )
    if visual_lines:
        sections.append("【基础画面】\n" + "\n".join(visual_lines))

    phase_lines: list[str] = []
    previous_values: dict[str, str] = {}
    for phase in sorted(draft.phases, key=lambda item: (item.start_seconds, item.end_seconds)):
        phase_values = {
            "主体": clean_text(phase.subject_motion),
            "镜头": clean_text(phase.camera_motion),
            "前景": clean_text(phase.foreground_motion),
            "焦点": clean_text(phase.focus_change),
        }
        details = unique_texts(
            [
                _field_line(label, value)
                if value.casefold() != previous_values.get(label, "").casefold()
                else ""
                for label, value in phase_values.items()
            ]
        )
        previous_values.update(
            {
                label: value
                for label, value in phase_values.items()
                if value and value.casefold() not in _PLACEHOLDER_VALUES
            }
        )
        if not details:
            continue
        time_label = f"{phase.start_seconds:.2f}–{phase.end_seconds:.2f}s"
        if compact_timeline:
            phase_lines.append(f"{time_label}｜" + "；".join(details))
        else:
            phase_lines.append(f"{time_label}\n" + "\n".join(f"  {item}" for item in details))
    if phase_lines:
        sections.append("【时间轴】\n" + "\n".join(phase_lines))

    transition = draft.transition
    if transition.kind != "none" or clean_text(transition.instruction):
        time_label = ""
        if transition.start_seconds is not None and transition.end_seconds is not None:
            time_label = f"{transition.start_seconds:.2f}–{transition.end_seconds:.2f}s｜"
        transition_lines = unique_texts(
            [
                f"{time_label}{transition.instruction}" if transition.instruction else "",
                f"遮挡对象：{transition.mask_object}" if transition.mask_object else "",
                f"运动方向：{transition.direction}" if transition.direction else "",
                f"结束状态：{transition.terminal_frame}" if transition.terminal_frame else "",
            ]
        )
        if transition_lines:
            sections.append("【出场转场】\n" + "\n".join(transition_lines))

    constraints = unique_texts(draft.negative_constraints)
    if constraints:
        sections.append("【约束】\n" + "\n".join(f"- {item}" for item in constraints))
    if clean_text(draft.custom_notes):
        sections.append("【补充说明】\n" + clean_text(draft.custom_notes))
    return "\n\n".join(section for section in sections if section).strip()
