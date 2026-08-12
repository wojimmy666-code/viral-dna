from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from viral_dna_api.chinese import to_simplified
from viral_dna_api.models import AnalysisReport, Entity, PromptShot, Shot

from ..contracts import (
    ViralConcept,
    ViralConceptShot,
    ViralInsightReport,
    ViralReplacementSelection,
    ViralShotRole,
    ViralStrategy,
)

CONCEPT_SCHEMA_VERSION = "viral-dna-concepts-v2"
CONCEPT_GENERATOR_ID = "replication-rules-v2"
STRATEGY_CONTRACT_VERSION = "strategy-contract-v2"

ROLE_LABELS = {
    "hook": "开场钩子",
    "setup": "信息铺垫",
    "retention": "留存推进",
    "proof": "证据展示",
    "payoff": "结果兑现",
    "cta": "互动承接",
}


def clean_text(value: str | None, fallback: str = "") -> str:
    cleaned = " ".join((to_simplified(value or "") or "").split()).strip()
    return cleaned or fallback


def unique_strings(values: list[str], *, limit: int = 20) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))[:limit]


def replace_entities(text: str, entities: list[Entity], replacements: dict[str, str]) -> str:
    result = text
    for entity in entities:
        replacement = replacements.get(entity.id)
        if not replacement:
            continue
        for token in (entity.name, entity.description):
            if token:
                result = result.replace(token, replacement)
    return result


@dataclass(frozen=True)
class StrategyDecision:
    why_it_can_work: str
    retained_dna: list[str]
    improvements: list[str]
    required_assets: list[str]
    risks: list[str]


@dataclass(frozen=True)
class ConceptGenerationContext:
    report: AnalysisReport
    insight: ViralInsightReport
    replacements: dict[str, str]
    replacement_labels: list[str]
    replacement_clause: str
    prompt_shots: dict[str, PromptShot]
    roles: dict[str, ViralShotRole]

    @property
    def mechanism_titles(self) -> list[str]:
        return [item.title for item in self.insight.mechanisms]

    @property
    def strongest_mechanism(self) -> str:
        return self.mechanism_titles[0] if self.mechanism_titles else "原片核心流量机制"


def build_strategy_context(
    report: AnalysisReport,
    insight: ViralInsightReport,
    selections: list[ViralReplacementSelection],
) -> ConceptGenerationContext:
    replacements = {item.entity_id: clean_text(item.replacement) for item in selections}
    replacement_pairs = [
        f"{entity.name}改为{replacements[entity.id]}"
        for entity in report.entities
        if entity.id in replacements
    ]
    replacement_labels = [
        opportunity.label
        for opportunity in insight.replacement_opportunities
        if opportunity.entity_id in replacements
    ]
    return ConceptGenerationContext(
        report=report,
        insight=insight,
        replacements=replacements,
        replacement_labels=replacement_labels,
        replacement_clause=("；元素替换：" + "、".join(replacement_pairs))
        if replacement_pairs
        else "",
        prompt_shots={item.shot_id: item for item in report.prompt_package.shots},
        roles={item.shot_id: item for item in insight.shot_roles},
    )


class BaseConceptStrategyBuilder(ABC):
    strategy: ViralStrategy
    label: str
    one_liner: str
    difficulty: str
    cost: str

    def build(self, context: ConceptGenerationContext) -> ViralConcept:
        decision = self.build_decision(context)
        shots = [
            self.build_shot(context, shot)
            for shot in sorted(context.report.shots, key=lambda item: item.index)
        ]
        return ViralConcept(
            strategy=self.strategy,
            name=f"{self.label}方案",
            one_liner=self.one_liner,
            target_audience=context.insight.audience,
            why_it_can_work=decision.why_it_can_work,
            difficulty=self.difficulty,
            estimated_cost_level=self.cost,
            retained_dna=unique_strings(decision.retained_dna),
            improvements=unique_strings(decision.improvements),
            required_assets=unique_strings(decision.required_assets, limit=30),
            risks=unique_strings(decision.risks),
            shots=shots,
        )

    def build_shot(self, context: ConceptGenerationContext, shot: Shot) -> ViralConceptShot:
        source_prompt = context.prompt_shots.get(shot.id)
        role = context.roles.get(shot.id)
        role_key = role.role if role else "retention"
        role_label = ROLE_LABELS.get(role_key, "留存推进")
        base_image = replace_entities(
            source_prompt.prompt if source_prompt else shot.prompt,
            context.report.entities,
            context.replacements,
        ) + context.replacement_clause
        base_video = replace_entities(
            f"{shot.prompt}；动作过程：{shot.action}；运镜：{shot.camera}。",
            context.report.entities,
            context.replacements,
        ) + context.replacement_clause
        base_constraints = (
            source_prompt.negative_constraints
            if source_prompt
            else context.report.prompt_package.negative_constraints
        )
        return ViralConceptShot(
            source_shot_id=shot.id,
            index=shot.index,
            duration_seconds=max(0.01, shot.end_seconds - shot.start_seconds),
            title=clean_text(shot.title, f"分镜 {shot.index}"),
            traffic_role=role_label,
            description=self.shot_description(context, shot, role_label),
            image_prompt=self.image_prompt(context, shot, role_label, base_image),
            video_prompt=self.video_prompt(context, shot, role_label, base_video),
            negative_constraints=unique_strings(
                [*base_constraints, *self.strategy_constraints(context, shot)],
                limit=40,
            ),
            retained_mechanisms=unique_strings(self.retained_mechanisms(context, role_key)),
        )

    def compose_prompt(
        self,
        context: ConceptGenerationContext,
        *,
        heading: str,
        role_label: str,
        directive: str,
        base: str,
    ) -> str:
        locks = context.insight.dna.recommended_locks[:4]
        lock_text = "、".join(locks) if locks else "时长、动作、运镜"
        return f"{heading} 本镜头承担{role_label}；锁定{lock_text}。{directive} {base}"

    @abstractmethod
    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision: ...

    @abstractmethod
    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str: ...

    @abstractmethod
    def image_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str: ...

    @abstractmethod
    def video_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str: ...

    @abstractmethod
    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]: ...

    @abstractmethod
    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]: ...
