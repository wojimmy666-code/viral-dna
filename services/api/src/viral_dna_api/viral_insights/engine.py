from __future__ import annotations

import hashlib
import json

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
            "analysis_id": str(report.analysis_id),
            "generated_at": report.generated_at.isoformat(),
            "overview": report.overview.model_dump(mode="json"),
            "shots": [shot.model_dump(mode="json") for shot in report.shots],
            "entities": [entity.model_dump(mode="json") for entity in report.entities],
            "findings": [item.model_dump(mode="json") for item in report.viral_findings],
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
    matches = [
        shot
        for shot in report.shots
        if shot.end_seconds > start and shot.start_seconds < max(start + 0.01, end)
    ]
    return matches or sorted(report.shots, key=lambda item: item.index)[:1]


def _derived_mechanisms(report: AnalysisReport) -> list[ViralMechanism]:
    shots = sorted(report.shots, key=lambda item: item.index)
    if not shots:
        return []
    selected: list[tuple[str, Shot, str, str, list[str]]] = [
        (
            "hook",
            shots[0],
            "首屏快速建立视觉问题",
            "首个镜头直接呈现主体、动作或视觉反差，降低理解门槛。",
            ["click", "retention"],
        )
    ]
    if len(shots) > 2:
        middle = shots[len(shots) // 2]
        selected.append(
            (
                "retention",
                middle,
                "过程信息持续推进",
                "中段通过动作、景别或信息变化维持未完成感，延后用户退出。",
                ["retention", "like"],
            )
        )
    if len(shots) > 1:
        selected.append(
            (
                "payoff",
                shots[-1],
                "结尾提供视觉兑现",
                "最后镜头完成前文动作或情绪的兑现，形成完整观看闭环。",
                ["retention", "share"],
            )
        )
    score = report.overview.viral_potential_score
    return [
        ViralMechanism(
            id=f"derived-{kind}-{shot.id}",
            type=kind,
            title=title,
            claim_kind=ViralClaimKind.INFERRED,
            observation=_text(
                f"{shot.title}：{shot.action}；运镜为 {shot.camera}。",
                shot.prompt,
            ),
            mechanism=mechanism,
            expected_effect="这是基于内容结构的流量作用推断，需结合平台数据验证。",
            impact_dimensions=dimensions,
            score=max(45, min(92, score - index * 4)),
            confidence=max(0.35, min(0.88, shot.confidence * 0.85)),
            recommendation=("复刻时保留该镜头的出现时点、动作方向和信息功能，可替换人物与场景。"),
            evidence=_shot_evidence(shot),
        )
        for index, (kind, shot, title, mechanism, dimensions) in enumerate(selected)
    ]


def _finding_mechanisms(report: AnalysisReport) -> list[ViralMechanism]:
    type_map = {
        "hook": "hook",
        "retention": "retention",
        "payoff": "payoff",
        "emotion": "emotion",
        "visual": "visual_memory",
        "interaction": "interaction",
        "share": "share",
    }
    mechanisms = []
    for finding in report.viral_findings:
        kind = next(
            (mapped for token, mapped in type_map.items() if token in finding.type.lower()),
            "platform_fit",
        )
        evidence = [
            item
            for shot in _overlapping_shots(report, finding.start_seconds, finding.end_seconds)
            for item in _shot_evidence(shot)
        ]
        mechanisms.append(
            ViralMechanism(
                id=finding.id,
                type=kind,
                title=_text(finding.title, "内容机制"),
                claim_kind=ViralClaimKind.INFERRED,
                observation=_text(finding.observation, "当前视频存在可复用的结构特征。"),
                mechanism=_text(finding.mechanism, "通过降低理解成本并制造未完成感提升留存。"),
                expected_effect=_text(
                    finding.expected_effect,
                    "可能影响点击、留存或互动，需要平台数据验证。",
                ),
                impact_dimensions=["retention", "share"]
                if kind == "payoff"
                else ["click", "retention"],
                score=finding.score,
                confidence=finding.confidence,
                recommendation=_text(finding.recommendation, "保留该机制，替换表层元素。"),
                evidence=evidence[:20],
            )
        )
    return mechanisms


def _shot_role(index: int, count: int, shot: Shot) -> str:
    role_text = _text(shot.narrative_role).lower()
    if any(token in role_text for token in ("钩子", "开场", "hook")) or index == 0:
        return "hook"
    if (
        any(token in role_text for token in ("结果", "兑现", "结尾", "payoff"))
        or index == count - 1
    ):
        return "payoff"
    if any(token in role_text for token in ("证明", "展示", "proof")):
        return "proof"
    return "retention" if index >= max(1, count // 3) else "setup"


def _shot_roles(report: AnalysisReport, mechanisms: list[ViralMechanism]) -> list[ViralShotRole]:
    shots = sorted(report.shots, key=lambda item: item.index)
    roles = []
    for offset, shot in enumerate(shots):
        role = _shot_role(offset, len(shots), shot)
        related = [
            mechanism
            for mechanism in mechanisms
            if any(item.shot_id == shot.id for item in mechanism.evidence)
        ]
        must_keep = [
            _text(shot.camera, "关键运镜"),
            _text(shot.action, "主体动作"),
        ]
        replaceable = [
            entity.name for entity in report.entities if shot.id in entity.occurrence_shot_ids
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
                    else f"承担{ROLE_LABELS[role]}，通过{_text(shot.action, '画面变化')}推进观看。"
                ),
                contribution_score=(
                    max(item.score for item in related)
                    if related
                    else max(45, report.overview.viral_potential_score - offset * 3)
                ),
                must_keep=list(dict.fromkeys(item for item in must_keep if item))[:4],
                replaceable=list(dict.fromkeys(replaceable))[:8],
                improvements=[
                    "压缩无信息变化的停留时间"
                    if role in {"setup", "retention"}
                    else "强化首尾视觉信号"
                ],
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


def _improvements(report: AnalysisReport, roles: list[ViralShotRole]) -> list[ViralImprovement]:
    if not roles:
        return []
    first = roles[0]
    last = roles[-1]
    items = [
        ViralImprovement(
            id="improve-hook-density",
            title="把核心视觉信号前置到首秒",
            rationale="首镜头承担点击后的承接；更早出现主体动作或结果预告，可减少进入后的理解等待。",
            priority="high",
            expected_gain="优先改善首屏理解效率与早期留存。",
            affected_shot_ids=[first.shot_id],
        ),
        ViralImprovement(
            id="improve-payoff",
            title="强化结尾兑现与首尾呼应",
            rationale="结尾若能明确回应开场提出的视觉问题，更容易形成完整记忆和二次观看动机。",
            priority="high",
            expected_gain="优先改善完播、分享与复看动机。",
            affected_shot_ids=[last.shot_id],
        ),
    ]
    if not any(shot.subtitle_text or shot.ocr_text for shot in report.shots):
        items.append(
            ViralImprovement(
                id="improve-text-anchor",
                title="补充一句可静音理解的文字锚点",
                rationale="当前证据未发现稳定字幕或画面文字，静音浏览时可能增加理解成本。",
                priority="medium",
                expected_gain="提升无声播放场景下的信息到达率。",
                affected_shot_ids=[first.shot_id],
            )
        )
    return items


def build_viral_insight(report: AnalysisReport) -> ViralInsightReport:
    mechanisms = _finding_mechanisms(report) or _derived_mechanisms(report)
    roles = _shot_roles(report, mechanisms)
    replacements = _replacement_opportunities(report)
    improvements = _improvements(report, roles)
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
            f"这条视频的内容流量潜力主要来自“{strongest.title}”与首尾信息闭环。"
            if strongest
            else "当前视频已完成结构拆解，但缺少足够证据形成流量机制判断。"
        ),
        content_value=_text(report.overview.summary, "通过短时视觉叙事完成信息传达。"),
        audience=_text(report.overview.audience_inference, "偏好快速、直观内容的短视频用户"),
        data_basis="content_inference",
        evidence_coverage=(evidence_count / len(mechanisms) if mechanisms else 0),
        confidence=(
            sum(item.confidence for item in mechanisms) / len(mechanisms) if mechanisms else 0
        ),
        strongest_hook=(
            f"{strongest.observation} {strongest.mechanism}"
            if strongest
            else "尚未识别出明确开场钩子。"
        ),
        replication_difficulty=(
            "high" if len(report.shots) >= 8 else "medium" if len(report.shots) >= 4 else "low"
        ),
        mechanisms=mechanisms,
        shot_roles=roles,
        dna=ViralDNA(
            invariants=invariant_titles,
            recommended_locks=locks or ["分镜时长", "主体动作", "机位与运镜"],
            variables=[item.label for item in replacements],
            risks=["内容推断不等于真实平台表现", "替换人物或产品时需保持跨镜头一致性"],
        ),
        replacement_opportunities=replacements,
        improvements=improvements,
    )


def build_concept_set(
    report: AnalysisReport,
    insight: ViralInsightReport,
    strategies: list[ViralStrategy],
    selections: list[ViralReplacementSelection],
) -> ViralConceptSet:
    context = build_strategy_context(report, insight, selections)
    concepts = [get_strategy_builder(strategy).build(context) for strategy in strategies]
    validate_concept_diversity(concepts)
    fingerprint = _fingerprint(
        {
            "generator_id": CONCEPT_GENERATOR_ID,
            "strategy_contract_version": STRATEGY_CONTRACT_VERSION,
            "insight": insight.input_fingerprint,
            "strategies": [item.value for item in strategies],
            "replacements": [item.model_dump(mode="json") for item in selections],
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
        concepts=concepts,
    )
