from __future__ import annotations

from collections.abc import Callable

from ..contracts import ViralConcept


class ConceptDiversityError(ValueError):
    def __init__(self, duplicate_fields: list[str]) -> None:
        self.duplicate_fields = duplicate_fields
        super().__init__("三套方案差异不足：" + "、".join(duplicate_fields))


def _normalized_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _normalized_list(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(_normalized_text(value) for value in values))


def validate_concept_diversity(concepts: list[ViralConcept]) -> None:
    if len(concepts) < 2:
        return

    checks: list[tuple[str, Callable[[ViralConcept], object]]] = [
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
