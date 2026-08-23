from __future__ import annotations

from viral_dna_api.models import Shot

from ..contracts import ViralStrategy
from .base import BaseConceptStrategyBuilder, ConceptGenerationContext, StrategyDecision


class ScenarioStrategyBuilder(BaseConceptStrategyBuilder):
    strategy = ViralStrategy.SCENARIO
    label = "场景叙事"
    one_liner = "从目标人群的真实场景切入，用问题、选择和结果建立新的品类记忆。"
    difficulty = "medium"
    cost = "medium"

    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision:
        return StrategyDecision(
            why_it_can_work=(
                f"原片的“{context.strongest_mechanism}”被转译为{context.primary_audience}"
                f"在{context.primary_scene}中的具体问题与选择，让{context.primary_selling_point}"
                "成为情节转折，而非悬空口号。"
            ),
            retained_dna=[
                context.strongest_mechanism,
                "关键节奏点与信息到达时机",
                "首尾问题—结果闭环",
            ],
            improvements=[
                f"用{context.primary_scene}替代原片表层场景",
                f"让{context.primary_audience}的真实阻力成为开场问题",
                "通过使用前后状态变化建立视觉记忆",
            ],
            required_assets=[
                f"{context.primary_scene}场景素材",
                f"符合{context.primary_audience}的人物参考",
                f"可展示{context.primary_selling_point}的产品状态",
            ],
            risks=[
                "场景信息过多会拖慢首秒理解",
                "问题设置必须能由产品真实解决",
                "人物、道具与环境需要保持跨镜头连续",
            ],
            thesis=(
                f"在{context.primary_scene}中，把{context.primary_audience}的一个高频困扰"
                f"转化为可见变化，证明{context.primary_selling_point}。"
            ),
            hook=f"首秒展示{context.primary_scene}中的典型困扰，让用户立即代入。",
            narrative_structure="场景困扰 → 尝试与选择 → 使用转折 → 身份与结果兑现",
            visual_memory=f"同一场景内的使用前后状态对照，突出{context.primary_selling_point}",
            payoff="人物在真实场景中获得可感知结果，并回扣开场困扰。",
            category_fit_summary=(
                f"用{context.category_profile.category_name}的真实使用情境解释价值，"
                "更适合建立共鸣、收藏和评论讨论。"
            ),
            changed_elements=["人物动机", "场景关系", "叙事因果", "视觉记忆点"],
        )

    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str:
        phase = {
            "开场钩子": f"暴露{context.primary_scene}中的具体困扰",
            "信息铺垫": "交代人物需要与使用条件",
            "留存推进": f"让{context.primary_selling_point}进入行动",
            "证据展示": "展示使用中的可见变化",
            "结果兑现": "形成使用前后对照并回扣问题",
            "互动承接": "邀请观众代入自己的场景",
        }.get(role_label, "推进场景中的问题—解决关系")
        return f"第 {shot.index} 镜承担{role_label}，重点{phase}。"

    def image_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        return self.compose_prompt(
            context,
            heading="场景叙事静态画面：",
            role_label=role_label,
            directive=(
                f"重构为{context.primary_scene}，人物行为必须来自真实需要；"
                f"以环境和状态变化承载{context.primary_selling_point}，不复制原画面。"
            ),
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
            heading="场景叙事动作表达：",
            role_label=role_label,
            directive=(
                "动作按问题出现、做出选择、产生变化的因果推进；保留关键节奏，"
                "但重写人物目的、空间关系与表演。"
            ),
            base=base,
        )

    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]:
        return ["只有产品展示而没有人物动机", "场景与目标人群无关", "结果未回扣开场问题"]

    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]:
        return [context.strongest_mechanism, f"{role_key}节奏点", "问题—结果闭环"]
