from __future__ import annotations

from viral_dna_api.models import Shot

from ..contracts import ViralStrategy
from .base import BaseConceptStrategyBuilder, ConceptGenerationContext, StrategyDecision


class ProofStrategyBuilder(BaseConceptStrategyBuilder):
    strategy = ViralStrategy.PROOF
    label = "证据说服"
    one_liner = "先抛结论，再用可拍摄、可比较的细节证据逐步完成信任与转化。"
    difficulty = "high"
    cost = "medium"

    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision:
        return StrategyDecision(
            why_it_can_work=(
                f"以“{context.primary_selling_point}”作为需要被验证的结论，借用原片"
                f"“{context.strongest_mechanism}”的注意力结构，逐镜加入细节、对比和"
                "使用结果，减少只靠气氛表达造成的不确定性。"
            ),
            retained_dna=[
                context.strongest_mechanism,
                "原片核心信息到达时机",
                "结尾明确兑现",
            ],
            improvements=[
                "首秒前置可验证结论",
                "中段加入材质、结构或使用过程特写",
                "结尾用同条件对比或清晰结果完成证据闭环",
            ],
            required_assets=[
                f"{context.primary_selling_point}细节特写",
                "同条件对比素材",
                "真实使用过程与结果画面",
            ],
            risks=[
                "证据必须真实可拍，不能使用无法支持的功效表述",
                "特写和对比镜头需要统一光线与拍摄条件",
                "信息标签过多会遮挡主体并降低观看节奏",
            ],
            thesis=f"用连续可视证据证明{context.primary_selling_point}，让结论先于解释出现。",
            hook=f"首秒直接展示最强结果或细节，并提出“为什么能做到{context.primary_selling_point}”。",
            narrative_structure="结论前置 → 细节拆解 → 同条件验证 → 结果与行动兑现",
            visual_memory=f"围绕{context.primary_selling_point}的极近景细节与同条件对比",
            payoff="证据链在结尾汇总为明确结果，并给出下一步行动理由。",
            category_fit_summary=(
                f"把{context.category_profile.category_name}卖点变成可观察事实，"
                "适合提升理解、信任与购买决策效率。"
            ),
            changed_elements=["信息顺序", "证据镜头", "景别体系", "结尾行动理由"],
        )

    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str:
        phase = {
            "开场钩子": "先给结果或最强细节，建立待验证结论",
            "信息铺垫": "明确判断标准和对比条件",
            "留存推进": "拆解材质、结构或使用过程",
            "证据展示": "在同条件下呈现直接证据",
            "结果兑现": "汇总证据并清楚兑现卖点",
            "互动承接": "给出基于证据的选择理由",
        }.get(role_label, "补充一条可观察的卖点证据")
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
            heading="证据说服静态画面：",
            role_label=role_label,
            directive=(
                f"围绕{context.primary_selling_point}选择可验证细节、特写或同条件对比；"
                "画面只保留一个主要证据，标签不得遮挡主体。"
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
            heading="证据说服动作表达：",
            role_label=role_label,
            directive=(
                "动作按结论、拆解、验证、结果推进；每镜只证明一个判断，"
                "对比条件、光线和主体位置保持一致。"
            ),
            base=base,
        )

    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]:
        return ["使用无法拍摄或无法验证的证据", "改变对比条件", "堆叠过多信息标签"]

    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]:
        return [context.strongest_mechanism, f"{role_key}信息时点", "证据—结论闭环"]
