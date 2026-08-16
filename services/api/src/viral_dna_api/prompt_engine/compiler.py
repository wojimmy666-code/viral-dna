from __future__ import annotations

from typing import Any

from .base_compiler import clean_text
from .contracts import (
    PromptMotionPhaseDraft,
    PromptShotDraft,
    PromptTransitionDraft,
    PromptVisualDraft,
)
from .language_policy import normalize_natural_text, normalize_prompt_draft
from .providers import compile_minimax_prompt, compile_seedance_prompt, compile_wan_prompt


def _target_family(target_model: str) -> str:
    normalized = clean_text(target_model).casefold()
    if "minimax" in normalized or "hailuo" in normalized or "海螺" in normalized:
        return "minimax"
    if "wan" in normalized or "万相" in normalized or "百炼" in normalized:
        return "wan"
    return "seedance"


def compile_prompt_draft(draft: PromptShotDraft, target_model: str) -> str:
    draft = normalize_prompt_draft(draft)
    family = _target_family(target_model)
    if family == "minimax":
        return compile_minimax_prompt(draft)
    if family == "wan":
        return compile_wan_prompt(draft)
    return compile_seedance_prompt(draft)


def _phase_from_fact(phase: Any) -> PromptMotionPhaseDraft:
    return PromptMotionPhaseDraft(
        id=f"phase_{int(getattr(phase, 'index', 1)):02d}",
        start_seconds=round(float(phase.start_seconds), 3),
        end_seconds=round(float(phase.end_seconds), 3),
        subject_motion=normalize_natural_text(getattr(phase, "subject_motion", "")),
        camera_motion=normalize_natural_text(getattr(phase, "camera_motion", "")),
        foreground_motion=normalize_natural_text(getattr(phase, "foreground_motion", "")),
        focus_change=normalize_natural_text(getattr(phase, "focus_change", "")),
    )


def _transition_from_fact(transition: Any) -> PromptTransitionDraft:
    instruction = normalize_natural_text(
        getattr(transition, "generation_prompt", "")
        or getattr(transition, "description", "")
    )
    return PromptTransitionDraft(
        kind=getattr(transition, "kind", "none"),
        start_seconds=getattr(transition, "start_seconds", None),
        end_seconds=getattr(transition, "end_seconds", None),
        instruction=instruction if instruction != "无出场转场" else "",
        mask_object=normalize_natural_text(getattr(transition, "mask_object", "")),
        direction=normalize_natural_text(getattr(transition, "direction", "")),
        terminal_frame=normalize_natural_text(getattr(transition, "terminal_frame", "")),
    )


def _fallback_phase(source: Any) -> PromptMotionPhaseDraft:
    start = float(
        getattr(source, "content_start_seconds", None)
        if getattr(source, "content_start_seconds", None) is not None
        else getattr(source, "start_seconds", 0)
    )
    end = float(
        getattr(source, "content_end_seconds", None)
        if getattr(source, "content_end_seconds", None) is not None
        else getattr(source, "end_seconds", max(0.1, start + 0.1))
    )
    return PromptMotionPhaseDraft(
        id="phase_01",
        start_seconds=round(start, 3),
        end_seconds=round(max(end, start + 0.01), 3),
        subject_motion=normalize_natural_text(getattr(source, "action", "")),
        camera_motion=normalize_natural_text(getattr(source, "camera", "")),
    )


def draft_from_shot(shot: Any, *, negative_constraints: list[str] | None = None) -> PromptShotDraft:
    phases = [_phase_from_fact(item) for item in getattr(shot, "motion_phases", [])]
    return PromptShotDraft(
        visual=PromptVisualDraft(
            subjects="、".join(
                normalize_natural_text(item)
                for item in getattr(shot, "subjects", [])
                if normalize_natural_text(item)
            ),
            scene=normalize_natural_text(getattr(shot, "scene", "")),
            composition=normalize_natural_text(getattr(shot, "composition", "")),
            lighting=normalize_natural_text(getattr(shot, "lighting", "")),
            color=normalize_natural_text(getattr(shot, "color", "")),
        ),
        phases=phases or [_fallback_phase(shot)],
        transition=_transition_from_fact(getattr(shot, "outgoing_transition", None)),
        negative_constraints=list(negative_constraints or []),
    )


def draft_from_visual_facts(facts: Any) -> PromptShotDraft:
    phases = [_phase_from_fact(item) for item in getattr(facts, "motion_phases", [])]
    if not phases:
        raise ValueError("视觉事实必须先补齐至少一个运镜阶段")
    return PromptShotDraft(
        visual=PromptVisualDraft(
            subjects="、".join(
                normalize_natural_text(item)
                for item in getattr(facts, "subjects", [])
                if normalize_natural_text(item)
            ),
            scene=normalize_natural_text(getattr(facts, "scene", "")),
            composition=normalize_natural_text(getattr(facts, "composition", "")),
            lighting=normalize_natural_text(getattr(facts, "lighting", "")),
            color=normalize_natural_text(getattr(facts, "color", "")),
        ),
        phases=phases,
        transition=_transition_from_fact(getattr(facts, "outgoing_transition", None)),
    )
