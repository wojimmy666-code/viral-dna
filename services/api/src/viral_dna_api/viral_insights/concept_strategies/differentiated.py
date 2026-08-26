from __future__ import annotations

from viral_dna_api.models import Shot

from ..contracts import ViralStrategy
from .base import BaseConceptStrategyBuilder, ConceptGenerationContext, StrategyDecision


class DifferentiatedStrategyBuilder(BaseConceptStrategyBuilder):
    strategy = ViralStrategy.DIFFERENTIATED
    label = "差异化同构"
    one_liner = "保留流量机制与关键节奏，重写人物、场景和视觉记忆点，避免只做换皮。"
    difficulty = "medium"
    cost = "medium"

    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision:
        visual_target = (
            "、".join(context.replacement_labels)
            if context.replacement_labels
            else "人物、场景与道具组合"
        )
        retained = [
            *context.insight.dna.invariants[:2],
            "开场钩子—留存推进—结尾兑现的功能顺序",
            "关键节奏点与信息到达时机",
        ]
        return StrategyDecision(
            why_it_can_work=(
                f"保留“{context.strongest_mechanism}”的流量功能和关键节奏，但重写{visual_target}，"
                "让目标受众获得新的视觉记忆，而不是复现原画面。"
            ),
            retained_dna=retained,
            improvements=[
                f"围绕{visual_target}建立新的视觉记忆点",
                "把原片机制转译为目标受众更熟悉的场景与人物关系",
                "在不改变钩子和兑现时点的前提下调整构图与美术风格",
            ],
            required_assets=[
                *(context.replacement_labels or ["差异化人物、产品或场景参考图"]),
                "新的视觉风格参考图",
            ],
            risks=[
                f"表层改写过大可能削弱“{context.strongest_mechanism}”",
                "新人物或场景必须兼容原有动作逻辑与运镜空间",
                "只做人物换皮而不改视觉符号，会导致方案仍然同质化",
            ],
        )

    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str:
        return f"保留第 {shot.index} 镜的{role_label}功能，重写视觉表现和记忆点。"

    def image_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        return self.compose_image_prompt(
            heading="差异化同构静态画面：",
            directive="保留信息功能，重写人物、场景、构图或视觉符号，避免复制原画面细节。",
            base=base,
        )

    def video_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        return self.compose_prompt(
            context,
            heading="差异化同构动作表达：",
            role_label=role_label,
            directive="保持流量功能和节奏点，以新的动作表演、场景关系和视觉记忆点重新演绎。",
            base=base,
        )

    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]:
        return [
            "只更换人物而保留原画面全部细节",
            "新旧人物或场景风格混杂",
            "破坏当前镜头的流量功能",
        ]

    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]:
        return [*context.mechanism_titles[:2], f"{role_key}功能与节奏点"]
