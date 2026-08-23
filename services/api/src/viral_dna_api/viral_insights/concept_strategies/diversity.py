from __future__ import annotations

from collections.abc import Callable

from viral_dna_api.category_profiles.contracts import CategoryProfileSnapshot

from ..contracts import ViralConcept


class ConceptDiversityError(ValueError):
    def __init__(self, duplicate_fields: list[str]) -> None:
        self.duplicate_fields = duplicate_fields
        super().__init__("三套方案差异不足：" + "、".join(duplicate_fields))


def _normalized_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _normalized_list(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(_normalized_text(value) for value in values))


def validate_concept_diversity(
    concepts: list[ViralConcept],
    category_profile: CategoryProfileSnapshot | None = None,
) -> None:
    if len(concepts) < 2:
        return

    checks: list[tuple[str, Callable[[ViralConcept], object]]] = [
        ("创意主张", lambda item: _normalized_text(item.thesis)),
        ("开场钩子", lambda item: _normalized_text(item.hook)),
        ("叙事结构", lambda item: _normalized_text(item.narrative_structure)),
        ("视觉记忆点", lambda item: _normalized_text(item.visual_memory)),
        ("结尾兑现", lambda item: _normalized_text(item.payoff)),
        ("品类适配说明", lambda item: _normalized_text(item.category_fit_summary)),
        ("核心改动", lambda item: _normalized_list(item.changed_elements)),
        ("有效性说明", lambda item: _normalized_text(item.why_it_can_work)),
        ("重点改进", lambda item: _normalized_list(item.improvements)),
        ("制作风险", lambda item: _normalized_list(item.risks)),
        ("DNA 保留策略", lambda item: _normalized_list(item.retained_dna)),
        (
            "逐镜头图片提示词",
            lambda item: tuple(_normalized_text(shot.image_prompt) for shot in item.shots),
        ),
        (
            "逐镜头视频提示词",
            lambda item: tuple(_normalized_text(shot.video_prompt) for shot in item.shots),
        ),
    ]
    duplicate_fields = [
        label
        for label, extractor in checks
        if len({extractor(concept) for concept in concepts}) != len(concepts)
    ]
    if duplicate_fields:
        raise ConceptDiversityError(duplicate_fields)
    if category_profile is None:
        return
    category_token = _normalized_text(category_profile.category_name)
    selling_tokens = [
        _normalized_text(value) for value in category_profile.selling_points if value
    ]
    ungrounded = []
    for concept in concepts:
        corpus = _normalized_text(
            " ".join(
                [
                    concept.thesis,
                    concept.hook,
                    concept.category_fit_summary,
                    *[
                        f"{shot.description} {shot.image_prompt} {shot.video_prompt}"
                        for shot in concept.shots
                    ],
                ]
            )
        )
        if category_token not in corpus or not any(token in corpus for token in selling_tokens):
            ungrounded.append(concept.name)
    if ungrounded:
        raise ConceptDiversityError(["品类与核心卖点约束"])
