from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from viral_dna_api.chinese import simplify_model, to_simplified

from .contracts import PromptShotDraft

_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_ALLOWED_VERBATIM_RE = re.compile(
    r"(?:英文)?(?:台词|对白|字幕|标识|画面文字|屏幕文字)\s*[：:]\s*"
    r"(?:“[^”\n]*”|\"[^\"\n]*\"|「[^」\n]*」|『[^』\n]*』)",
    re.IGNORECASE,
)
_EMPTY_TEXT_VALUES = {
    "none",
    "n/a",
    "na",
    "nil",
    "null",
    "not applicable",
    "not visible",
    "unknown",
}

LANGUAGE_POLICY_MESSAGE = (
    "除英文台词、英文字幕或画面内英文标识的原文外，提示词必须使用简体中文。"
    "保留英文原文时请写成：英文标识：“Customer Map”。"
)


@dataclass(frozen=True, slots=True)
class PromptLanguageIssue:
    field: str
    preview: str


def normalize_natural_text(value: str | None) -> str:
    text = (to_simplified(str(value or "")) or "").strip()
    if text.casefold() in _EMPTY_TEXT_VALUES:
        return ""
    return text


def contains_unlabeled_english(value: str | None) -> bool:
    text = normalize_natural_text(value)
    if not text:
        return False
    without_allowed_literals = _ALLOWED_VERBATIM_RE.sub("", text)
    return bool(_ENGLISH_WORD_RE.search(without_allowed_literals))


def _issue(field: str, value: str | None) -> PromptLanguageIssue | None:
    text = normalize_natural_text(value)
    if not contains_unlabeled_english(text):
        return None
    preview = " ".join(text.split())[:80]
    return PromptLanguageIssue(field=field, preview=preview)


def _issues(values: Iterable[tuple[str, str | None]]) -> list[PromptLanguageIssue]:
    return [issue for field, value in values if (issue := _issue(field, value)) is not None]


def normalize_prompt_draft(draft: PromptShotDraft) -> PromptShotDraft:
    normalized = simplify_model(draft)
    visual = normalized.visual.model_copy(
        update={
            field: normalize_natural_text(getattr(normalized.visual, field))
            for field in ("subjects", "scene", "composition", "lighting", "color")
        }
    )
    phases = [
        phase.model_copy(
            update={
                field: normalize_natural_text(getattr(phase, field))
                for field in (
                    "subject_motion",
                    "camera_motion",
                    "foreground_motion",
                    "focus_change",
                )
            }
        )
        for phase in normalized.phases
    ]
    transition = normalized.transition.model_copy(
        update={
            field: normalize_natural_text(getattr(normalized.transition, field))
            for field in ("instruction", "mask_object", "direction", "terminal_frame")
        }
    )
    return normalized.model_copy(
        update={
            "visual": visual,
            "phases": phases,
            "transition": transition,
            "negative_constraints": [
                text
                for value in normalized.negative_constraints
                if (text := normalize_natural_text(value))
            ],
            "custom_notes": normalize_natural_text(normalized.custom_notes),
        }
    )


def find_prompt_draft_language_issues(
    draft: PromptShotDraft,
) -> list[PromptLanguageIssue]:
    values: list[tuple[str, str | None]] = [
        ("基础画面·主体与服装", draft.visual.subjects),
        ("基础画面·场景", draft.visual.scene),
        ("基础画面·构图", draft.visual.composition),
        ("基础画面·光线", draft.visual.lighting),
        ("基础画面·色彩", draft.visual.color),
    ]
    for index, phase in enumerate(draft.phases, 1):
        values.extend(
            [
                (f"时间轴 {index}·主体动作", phase.subject_motion),
                (f"时间轴 {index}·镜头运动", phase.camera_motion),
                (f"时间轴 {index}·前景变化", phase.foreground_motion),
                (f"时间轴 {index}·焦点变化", phase.focus_change),
            ]
        )
    values.extend(
        [
            ("出场转场·指令", draft.transition.instruction),
            ("出场转场·遮挡对象", draft.transition.mask_object),
            ("出场转场·运动方向", draft.transition.direction),
            ("出场转场·结束状态", draft.transition.terminal_frame),
            *(
                (f"负面约束 {index}", value)
                for index, value in enumerate(draft.negative_constraints, 1)
            ),
            ("补充说明", draft.custom_notes),
        ]
    )
    return _issues(values)


def _shot_fact_texts(facts: Any) -> Iterator[tuple[str, str | None]]:
    for field, label in (
        ("title", "标题"),
        ("action", "主体动作"),
        ("scene", "场景"),
        ("camera", "镜头"),
        ("composition", "构图"),
        ("lighting", "光线"),
        ("color", "色彩"),
        ("transition", "转场摘要"),
        ("narrative_role", "叙事角色"),
        ("replication_prompt", "基础复刻提示词"),
        ("multiple_scenes_reason", "多场景原因"),
    ):
        yield label, getattr(facts, field, "")
    for index, subject in enumerate(getattr(facts, "subjects", []), 1):
        yield f"主体 {index}", subject
    for index, beat in enumerate(getattr(facts, "visual_beats", []), 1):
        yield f"画面 {index}·标题", getattr(beat, "title", "")
        yield f"画面 {index}·图片提示词", getattr(beat, "image_prompt", "")
    for index, phase in enumerate(getattr(facts, "motion_phases", []), 1):
        for field, label in (
            ("description", "阶段描述"),
            ("subject_motion", "主体动作"),
            ("camera_motion", "镜头运动"),
            ("foreground_motion", "前景变化"),
            ("focus_change", "焦点变化"),
        ):
            yield f"时间轴 {index}·{label}", getattr(phase, field, "")
    transition = getattr(facts, "outgoing_transition", None)
    if transition is not None:
        for field, label in (
            ("description", "描述"),
            ("mask_object", "遮挡对象"),
            ("direction", "运动方向"),
            ("terminal_frame", "结束状态"),
            ("continuity_anchor", "连续性锚点"),
            ("generation_prompt", "生成指令"),
        ):
            yield f"出场转场·{label}", getattr(transition, field, "")


def find_shot_facts_language_issues(facts: Any) -> list[PromptLanguageIssue]:
    return _issues(_shot_fact_texts(facts))


def summarize_language_issues(issues: list[PromptLanguageIssue], *, limit: int = 4) -> str:
    labels = "、".join(issue.field for issue in issues[:limit])
    suffix = "等字段" if len(issues) > limit else ""
    return f"{LANGUAGE_POLICY_MESSAGE} 请检查：{labels}{suffix}"
