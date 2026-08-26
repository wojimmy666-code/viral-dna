from __future__ import annotations

import hashlib
import json

from viral_dna_api.category_profiles.contracts import CategoryProfileSnapshot
from viral_dna_api.chinese import to_simplified
from viral_dna_api.models import AnalysisReport, Entity, Shot

from .concept_strategies import (
    CONCEPT_GENERATOR_ID,
    CONCEPT_SCHEMA_VERSION,
    STRATEGY_CONTRACT_VERSION,
    build_strategy_context,
    get_strategy_builder,
    validate_concept_diversity,
)
from .contracts import (
    ViralClaimKind,
    ViralConceptSet,
    ViralDNA,
    ViralEvidenceRef,
    ViralImprovement,
    ViralInsightReport,
    ViralMechanism,
    ViralReplacementOpportunity,
    ViralReplacementSelection,
    ViralShotRole,
    ViralStrategy,
)

ROLE_LABELS = {
    "hook": "开场钩子",
    "setup": "信息铺垫",
    "retention": "留存推进",
    "proof": "证据展示",
    "payoff": "结果兑现",
    "cta": "互动承接",
}

INSIGHT_GENERATOR_VERSION = "evidence-validator-v2"
MODEL_INSIGHT_GENERATOR_VERSION = "model-evidence-validator-v2"

def _text(value: str | None, fallback: str = "") -> str:
    cleaned = " ".join((to_simplified(value or "") or "").split()).strip()
    return cleaned or fallback


def _fingerprint(payload: object) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def report_fingerprint(report: AnalysisReport) -> str:
    return _fingerprint(
        {
            "insight_generator_version": INSIGHT_GENERATOR_VERSION,
            "analysis_id": str(report.analysis_id),
            "generated_at": report.generated_at.isoformat(),
            "overview": report.overview.model_dump(mode="json"),
            "shots": [shot.model_dump(mode="json") for shot in report.shots],
            "entities": [entity.model_dump(mode="json") for entity in report.entities],
            "findings": [item.model_dump(mode="json") for item in report.viral_findings],
            "viral_reasoning": (
                report.viral_reasoning.model_dump(mode="json")
                if report.viral_reasoning is not None
                else None
            ),
            "prompt_package": report.prompt_package.model_dump(mode="json"),
        }
    )


def _shot_evidence(shot: Shot) -> list[ViralEvidenceRef]:
    evidence = [
        ViralEvidenceRef(
            id=f"{shot.id}:frame",
            kind="frame",
            shot_id=shot.id,
            start_seconds=shot.start_seconds,
            end_seconds=shot.end_seconds,
            frame_url=shot.keyframe_url,
            text=_text(shot.action, shot.title),
            source_label=f"分镜 {shot.index} 关键帧",
        )
    ]
    for kind, value, label in (
        ("subtitle", shot.subtitle_text, "字幕"),
        ("dialogue", shot.dialogue, "对白"),
        ("ocr", shot.ocr_text, "画面文字"),
    ):
        if value and value.strip():
            evidence.append(
                ViralEvidenceRef(
                    id=f"{shot.id}:{kind}",
                    kind=kind,
                    shot_id=shot.id,
                    start_seconds=shot.start_seconds,
                    end_seconds=shot.end_seconds,
                    text=_text(value),
                    source_label=f"分镜 {shot.index} {label}",
                )
            )
    return evidence


def _overlapping_shots(report: AnalysisReport, start: float, end: float) -> list[Shot]:
    return [
        shot
        for shot in report.shots
        if shot.end_seconds > start and shot.start_seconds < max(start + 0.01, end)
    ]


def _finding_mechanisms(report: AnalysisReport) -> list[ViralMechanism]:
    type_map = {
        "hook": "hook",
        "钩子": "hook",
        "retention": "retention",
        "留存": "retention",
        "payoff": "payoff",
        "兑现": "payoff",
        "proof": "platform_fit",
        "证据": "platform_fit",
        "emotion": "emotion",
        "情绪": "emotion",
        "visual": "visual_memory",
        "视觉": "visual_memory",
        "contrast": "visual_memory",
        "反差": "visual_memory",
        "interaction": "interaction",
        "互动": "interaction",
        "share": "share",
        "分享": "share",
    }
    impact_by_kind = {
        "hook": ["click", "retention"],
        "retention": ["retention"],
        "payoff": ["retention", "share"],
        "emotion": ["like", "comment", "share"],
        "visual_memory": ["retention", "share"],
        "interaction": ["comment"],
        "share": ["share"],
        "platform_fit": ["retention", "conversion"],
    }
    mechanisms = []
    for finding in report.viral_findings:
        overlapping = _overlapping_shots(report, finding.start_seconds, finding.end_seconds)
        if not overlapping:
            continue
        kind = next(
            (mapped for token, mapped in type_map.items() if token in finding.type.lower()),
            "platform_fit",
        )
        evidence = [
            item
            for shot in overlapping
            for item in _shot_evidence(shot)
        ]
        mechanisms.append(
            ViralMechanism(
                id=finding.id,
                type=kind,
                title=_text(finding.title),
                claim_kind=ViralClaimKind.INFERRED,
                observation=_text(finding.observation),
                mechanism=_text(finding.mechanism),
                expected_effect=_text(finding.expected_effect),
                impact_dimensions=impact_by_kind[kind],
                score=finding.score,
                confidence=finding.confidence,
                recommendation=_text(finding.recommendation),
                evidence=evidence[:20],
            )
        )
    return mechanisms


def _shot_role(shot: Shot, related: list[ViralMechanism]) -> str:
    role_text = _text(shot.narrative_role).lower()
    if any(token in role_text for token in ("钩子", "hook")):
        return "hook"
    if any(token in role_text for token in ("结果", "兑现", "payoff")):
        return "payoff"
    if any(token in role_text for token in ("证明", "展示", "proof")):
        return "proof"
    if any(token in role_text for token in ("互动", "行动", "cta")):
        return "cta"
    if any(token in role_text for token in ("铺垫", "背景", "setup")):
        return "setup"
    if any(token in role_text for token in ("留存", "推进", "retention")):
        return "retention"
    if related:
        strongest = max(related, key=lambda item: item.score)
        return {
            "hook": "hook",
            "retention": "retention",
            "payoff": "payoff",
            "interaction": "cta",
            "platform_fit": "proof",
        }.get(strongest.type, "retention")
    return "setup"


def _shot_roles(report: AnalysisReport, mechanisms: list[ViralMechanism]) -> list[ViralShotRole]:
    shots = sorted(report.shots, key=lambda item: item.index)
    roles = []
    reasoning_improvements = report.viral_reasoning.improvements if report.viral_reasoning else []
    for shot in shots:
        related = [
            mechanism
            for mechanism in mechanisms
            if any(item.shot_id == shot.id for item in mechanism.evidence)
        ]
        role = _shot_role(shot, related)
        must_keep = [value for value in (_text(shot.camera), _text(shot.action)) if value]
        replaceable = [
            entity.name for entity in report.entities if shot.id in entity.occurrence_shot_ids
        ]
        shot_improvements = [
            _text(item.title)
            for item in reasoning_improvements
            if shot.id in item.affected_shot_ids
        ]
        roles.append(
            ViralShotRole(
                shot_id=shot.id,
                shot_index=shot.index,
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
                title=_text(shot.title, f"分镜 {shot.index}"),
                role=role,
                contribution=(
                    related[0].mechanism
                    if related
                    else f"当前证据仅确认该镜头为{ROLE_LABELS[role]}，尚未形成独立流量机制判断。"
                ),
                contribution_score=(
                    max(item.score for item in related)
                    if related
                    else max(20, min(60, round(shot.confidence * 60)))
                ),
                must_keep=list(dict.fromkeys(item for item in must_keep if item))[:4],
                replaceable=list(dict.fromkeys(replaceable))[:8],
                improvements=shot_improvements[:12],
                keyframe_url=shot.keyframe_url,
                evidence=_shot_evidence(shot),
            )
        )
    return roles


def _alternatives(entity: Entity) -> list[str]:
    return {
        "person": ["同姿态的目标受众代表人物", "更具辨识度的职业人物"],
        "wardrobe": ["保持轮廓与色彩关系的品牌服装", "更强对比色但同材质的服装"],
        "scene": ["保持空间层次的本地化场景", "更有品牌辨识度的同构场景"],
        "product": ["同品类核心产品", "功能相近但外形更醒目的产品"],
        "prop": ["承担相同动作功能的道具", "颜色更醒目的同尺寸道具"],
        "style": ["同节奏的品牌视觉风格", "对比更强的社媒视觉风格"],
    }.get(entity.type, ["同功能替代元素"])


def _replacement_opportunities(report: AnalysisReport) -> list[ViralReplacementOpportunity]:
    items = []
    for entity in report.entities:
        high_risk = entity.type in {"person", "product"} and len(entity.occurrence_shot_ids) > 1
        items.append(
            ViralReplacementOpportunity(
                entity_id=entity.id,
                entity_type=entity.type,
                label=_text(entity.name, entity.type),
                current_description=_text(entity.description, entity.name),
                must_preserve=["出现时点", "画面占比", "动作功能"],
                suggested_alternatives=_alternatives(entity),
                affected_shot_ids=entity.occurrence_shot_ids,
                risk="high" if high_risk else "medium" if entity.type == "scene" else "low",
            )
        )
    return items


def _improvements(report: AnalysisReport) -> list[ViralImprovement]:
    reasoning = report.viral_reasoning
    if reasoning is None or reasoning.insufficient_evidence:
        return []
    return [
        ViralImprovement(
            id=f"model-improvement-{index:02d}",
            title=_text(item.title),
            rationale=_text(item.rationale),
            priority=item.priority,
            expected_gain=_text(item.expected_gain),
            affected_shot_ids=item.affected_shot_ids,
        )
        for index, item in enumerate(reasoning.improvements, start=1)
    ]


def _replication_difficulty(report: AnalysisReport) -> str:
    shots = report.shots
    if not shots:
        return "low"
    score = 0
    if len(shots) >= 7:
        score += 2
    elif len(shots) >= 4:
        score += 1

    scenes = {
        _text(shot.scene).casefold()
        for shot in shots
        if _text(shot.scene) and "无法确认" not in _text(shot.scene)
    }
    if len(scenes) >= 3:
        score += 1

    if len(report.entities) >= 4:
        score += 1

    camera_text = " ".join(
        [
            *(_text(shot.camera) for shot in shots),
            *(
                _text(phase.camera_motion)
                for shot in shots
                for phase in shot.motion_phases
            ),
        ]
    )
    dynamic_camera_tokens = (
        "跟拍",
        "环绕",
        "甩镜",
        "推进",
        "拉远",
        "变焦",
        "升降",
        "手持",
        "摇镜",
    )
    dynamic_count = sum(token in camera_text for token in dynamic_camera_tokens)
    score += 2 if dynamic_count >= 2 else 1 if dynamic_count == 1 else 0

    if any(
        shot.outgoing_transition.kind not in {"none", "hard_cut", "uncertain"}
        for shot in shots
    ):
        score += 1
    if sum(len(shot.visual_beats) for shot in shots) > len(shots):
        score += 1

    return "high" if score >= 5 else "medium" if score >= 2 else "low"


def build_viral_insight(report: AnalysisReport) -> ViralInsightReport:
    reasoning = report.viral_reasoning
    mechanisms = _finding_mechanisms(report)
    roles = _shot_roles(report, mechanisms)
    replacements = _replacement_opportunities(report)
    improvements = _improvements(report)
    evidence_count = sum(bool(item.evidence) for item in mechanisms)
    strongest = max(mechanisms, key=lambda item: item.score, default=None)
    locks = list(dict.fromkeys(report.prompt_package.continuity_locks))[:12]
    invariant_titles = [
        item.title for item in sorted(mechanisms, key=lambda item: item.score, reverse=True)[:3]
    ]
    return ViralInsightReport(
        analysis_id=report.analysis_id,
        video_id=report.video_id,
        source_analysis_generated_at=report.generated_at,
        input_fingerprint=report_fingerprint(report),
        headline=(
            _text(reasoning.headline)
            if reasoning is not None
            else f"{strongest.title}：{strongest.observation}"
            if strongest is not None
            else "当前分析尚未形成经过模型综合与证据校验的内容机制结论。"
        ),
        content_value=(
            _text(reasoning.content_value)
            if reasoning is not None
            else _text(report.overview.summary, "当前只完成逐镜头事实整理。")
        ),
        audience=(
            _text(reasoning.audience)
            if reasoning is not None
            else _text(report.overview.audience_inference, "现有证据不足以推断目标受众。")
        ),
        data_basis="content_inference",
        evidence_coverage=(evidence_count / len(mechanisms) if mechanisms else 0),
        confidence=(
            reasoning.confidence
            if reasoning is not None
            else sum(item.confidence for item in mechanisms) / len(mechanisms)
            if mechanisms
            else 0
        ),
        strongest_hook=(
            _text(reasoning.strongest_hook)
            if reasoning is not None
            else f"{strongest.observation} {strongest.mechanism}"
            if strongest is not None
            else "现有证据不足以确认明确的流量抓手。"
        ),
        replication_difficulty=_replication_difficulty(report),
        mechanisms=mechanisms,
        shot_roles=roles,
        dna=ViralDNA(
            invariants=invariant_titles,
            recommended_locks=locks,
            variables=[item.label for item in replacements],
            risks=list(
                dict.fromkeys(
                    [
                        "内容推断不等于真实平台表现",
                        *(
                            [reasoning.insufficient_evidence_reason]
                            if reasoning is not None
                            and reasoning.insufficient_evidence_reason
                            else []
                        ),
                    ]
                )
            ),
        ),
        replacement_opportunities=replacements,
        improvements=improvements,
        generator_id=(
            MODEL_INSIGHT_GENERATOR_VERSION
            if reasoning is not None
            else INSIGHT_GENERATOR_VERSION
        ),
    )


def build_concept_set(
    report: AnalysisReport,
    insight: ViralInsightReport,
    strategies: list[ViralStrategy],
    selections: list[ViralReplacementSelection],
    category_profile: CategoryProfileSnapshot,
) -> ViralConceptSet:
    context = build_strategy_context(report, insight, selections, category_profile)
    concepts = [get_strategy_builder(strategy).build(context) for strategy in strategies]
    validate_concept_diversity(concepts, category_profile)
    fingerprint = _fingerprint(
        {
            "generator_id": CONCEPT_GENERATOR_ID,
            "strategy_contract_version": STRATEGY_CONTRACT_VERSION,
            "insight": insight.input_fingerprint,
            "strategies": [item.value for item in strategies],
            "replacements": [item.model_dump(mode="json") for item in selections],
            "category_profile_fingerprint": category_profile.fingerprint,
        }
    )
    return ViralConceptSet(
        schema_version=CONCEPT_SCHEMA_VERSION,
        analysis_id=report.analysis_id,
        video_id=report.video_id,
        insight_report_id=insight.id,
        input_fingerprint=fingerprint,
        source_insight_fingerprint=insight.input_fingerprint,
        strategy_contract_version=STRATEGY_CONTRACT_VERSION,
        generator_id=CONCEPT_GENERATOR_ID,
        category_profile=category_profile,
        concepts=concepts,
    )
