from __future__ import annotations

from viral_dna_api.models import Shot

from ..contracts import ViralStrategy
from .base import (
    BaseConceptStrategyBuilder,
    ConceptGenerationContext,
    StrategyDecision,
    unique_strings,
)


class FaithfulStrategyBuilder(BaseConceptStrategyBuilder):
    strategy = ViralStrategy.FAITHFUL
    label = "结构忠实复刻"
    one_liner = "锁定原片节奏、运镜与信息兑现顺序，只替换明确指定的可变元素。"
    difficulty = "low"
    cost = "low"

    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision:
        first_improvement = (
            context.insight.improvements[0].title
            if context.insight.improvements
            else "首屏视觉钩子"
        )
        retained = unique_strings(
            [*context.insight.dna.invariants, *context.insight.dna.recommended_locks],
            limit=10,
        )
        return StrategyDecision(
            why_it_can_work=(
                f"完整保留“{context.strongest_mechanism}”及原片的镜头顺序、动作方向和"
                "首尾兑现关系，只替换用户指定元素，以最大限度复现原有观看节奏。"
            ),
            retained_dna=retained,
            improvements=[
                f"校准“{first_improvement}”的执行细节，但不改变原镜头结构",
                "保持主体动作、运镜方向与转场落点",
                "只修复清晰度、闪烁和跨镜头一致性问题",
            ],
            required_assets=[
                "原视频关键帧",
                "原分镜时间线",
                *context.replacement_labels,
            ],
            risks=[
                "高相似度复刻可能同时继承原片的节奏弱点",
                "替换元素的体型、材质或比例可能不再匹配原动作与构图",
                "人物或产品替换后仍需逐镜头核对身份一致性",
            ],
        )

    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str:
        return f"按原片第 {shot.index} 镜的时长和构图执行，完整承担{role_label}。"

    def image_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        return self.compose_prompt(
            context,
            heading="忠实复刻静态画面：",
            role_label=role_label,
            directive="保持原构图、主体相对位置、色彩和光线，只应用指定元素替换。",
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
            heading="忠实复刻原动作阶段：",
            role_label=role_label,
            directive="保持原时长、动作方向、运镜轨迹与转场落点，不新增剧情或镜头。",
            base=base,
        )

    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]:
        return ["改变原镜头数量或顺序", "擅自改变动作方向", "转场时点漂移"]

    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]:
        return context.mechanism_titles[:3]
