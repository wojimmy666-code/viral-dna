from __future__ import annotations

from viral_dna_api.models import Shot

from ..contracts import ViralStrategy
from .base import (
    BaseConceptStrategyBuilder,
    ConceptGenerationContext,
    StrategyDecision,
    unique_strings,
)


class EnhancedStrategyBuilder(BaseConceptStrategyBuilder):
    strategy = ViralStrategy.ENHANCED
    label = "强化改进版"
    one_liner = "只锁定证据支持的核心机制，前置信号、压缩停留并强化结尾兑现。"
    difficulty = "high"
    cost = "high"

    def build_decision(self, context: ConceptGenerationContext) -> StrategyDecision:
        evidence_improvements = [item.title for item in context.insight.improvements]
        lead_improvement = (
            evidence_improvements[0] if evidence_improvements else "核心视觉信号前置"
        )
        retained = unique_strings(
            [
                *context.insight.dna.invariants[:1],
                *context.insight.dna.recommended_locks[:2],
                "核心因果链与跨镜头连续性",
            ]
        )
        return StrategyDecision(
            why_it_can_work=(
                f"锁定“{context.strongest_mechanism}”这一核心因果链，并执行"
                f"“{lead_improvement}”等优化，"
                "主动压缩低信息停留、强化首尾呼应和结果兑现。"
            ),
            retained_dna=retained,
            improvements=unique_strings(
                [
                    *evidence_improvements,
                    "压缩低信息停留并提高每秒画面变化密度",
                    "强化结果展示与分享、互动动机",
                ]
            ),
            required_assets=[
                *(context.replacement_labels or ["强化版主体参考图"]),
                "首屏核心视觉关键帧",
                "结尾兑现参考画面",
            ],
            risks=[
                "节奏前置和结构强化会提高图片生成、视频生成与剪辑成本",
                "信息密度提升过度可能造成理解负担或画面过载",
                "重写动作阶段和节奏后可能改变原片的情绪气质",
            ],
        )

    def shot_description(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
    ) -> str:
        role_action = {
            "开场钩子": "前置核心视觉信号并缩短理解等待",
            "结果兑现": "强化结果画面和首尾呼应",
        }.get(role_label, "压缩无信息停留并持续推进视觉变化")
        return f"第 {shot.index} 镜承担{role_label}，重点{role_action}。"

    def image_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        return self.compose_image_prompt(
            heading="强化改进静态画面：",
            directive="提高核心主体和结果信号的可见性，减少无效背景信息，强化视觉对比与记忆点。",
            base=base,
        )

    def video_prompt(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
        role_label: str,
        base: str,
    ) -> str:
        directive = (
            "核心视觉信号在首秒出现，快速进入关键动作并建立观看问题。"
            if role_label == "开场钩子"
            else "压缩无信息停留，强化动作变化；结尾明确完成结果兑现和首尾呼应。"
        )
        return self.compose_prompt(
            context,
            heading="强化改进动作阶段：",
            role_label=role_label,
            directive=directive,
            base=base,
        )

    def strategy_constraints(
        self,
        context: ConceptGenerationContext,
        shot: Shot,
    ) -> list[str]:
        return [
            "核心视觉信号出现过晚",
            "无信息停留",
            "结尾缺少明确兑现",
            "信息堆叠导致画面过载",
        ]

    def retained_mechanisms(
        self,
        context: ConceptGenerationContext,
        role_key: str,
    ) -> list[str]:
        improvements = [item.title for item in context.insight.improvements[:2]]
        return [context.strongest_mechanism, *improvements]
