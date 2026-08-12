from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from viral_dna_api.models import (
    GenerationCandidate,
    GenerationRun,
    ReferenceBinding,
    ReferenceRole,
    ShotLock,
    ShotPlan,
)

from .contracts import (
    ContinuityBoundaryResult,
    ContinuityBoundaryStatus,
    ContinuityDimension,
    ContinuityFinding,
    ContinuityFindingSeverity,
    ContinuityFindingState,
    ContinuityReport,
    ContinuityReportStatus,
    ContinuitySnapshot,
    ContinuityVerificationState,
)

_REFERENCE_DIMENSIONS = {
    ReferenceRole.IDENTITY.value: ContinuityDimension.IDENTITY,
    ReferenceRole.WARDROBE.value: ContinuityDimension.WARDROBE,
    ReferenceRole.PRODUCT.value: ContinuityDimension.PRODUCT,
    ReferenceRole.SCENE.value: ContinuityDimension.SCENE,
    ReferenceRole.STYLE.value: ContinuityDimension.COLOR,
    ReferenceRole.LAYOUT.value: ContinuityDimension.SCREEN_POSITION,
}

_BLOCKING_REFERENCE_DIMENSIONS = {
    ContinuityDimension.IDENTITY,
    ContinuityDimension.PRODUCT,
}

_DIRECT_FACTS = {
    "identity": (ContinuityDimension.IDENTITY, None),
    "wardrobe": (ContinuityDimension.WARDROBE, None),
    "product": (ContinuityDimension.PRODUCT, None),
    "scene": (ContinuityDimension.SCENE, None),
    "camera_axis": (ContinuityDimension.CAMERA_AXIS, ShotLock.CAMERA.value),
    "lighting": (ContinuityDimension.LIGHTING, ShotLock.LIGHTING.value),
    "color": (ContinuityDimension.COLOR, ShotLock.LIGHTING.value),
}

_ENDPOINT_FACTS = {
    ContinuityDimension.ACTION: ("action_end", "action_start", ShotLock.ACTION.value),
    ContinuityDimension.SCREEN_POSITION: (
        "screen_position_end",
        "screen_position_start",
        ShotLock.COMPOSITION.value,
    ),
    ContinuityDimension.MOTION_DIRECTION: (
        "motion_direction_end",
        "motion_direction_start",
        ShotLock.ACTION.value,
    ),
}

_FACT_ALIASES = {
    "subject_identity": "identity",
    "character_identity": "identity",
    "person_identity": "identity",
    "costume": "wardrobe",
    "clothing": "wardrobe",
    "location": "scene",
    "camera_side": "camera_axis",
    "screen_direction_start": "motion_direction_start",
    "screen_direction_end": "motion_direction_end",
}


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalized_fact(value: Any) -> str:
    if isinstance(value, str):
        rendered = value
    elif isinstance(value, (list, tuple, set)):
        rendered = " | ".join(str(item) for item in value)
    elif isinstance(value, Mapping):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        rendered = str(value)
    return " ".join(unicodedata.normalize("NFKC", rendered).strip().split())[:1000]


def _candidate_facts(
    candidate: GenerationCandidate | None,
) -> tuple[dict[str, str], str]:
    if candidate is None:
        return {}, "rule_only"
    raw = candidate.quality_report.get("continuity_facts")
    if not isinstance(raw, Mapping):
        return {}, "rule_only"
    source_value = str(raw.get("evidence_source") or raw.get("source") or "").casefold()
    source = "vlm" if source_value == "vlm" else "candidate_metadata"
    facts: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = _FACT_ALIASES.get(str(key).strip().casefold(), str(key).strip().casefold())
        if normalized_key in {"source", "evidence_source", "verification"} or value is None:
            continue
        normalized_value = _normalized_fact(value)
        if normalized_value:
            facts[normalized_key] = normalized_value
    return facts, source if facts else "rule_only"


def _snapshot_verification_state(snapshot: ContinuitySnapshot) -> ContinuityVerificationState:
    if snapshot.evidence_source == "vlm":
        return ContinuityVerificationState.VERIFIED
    if snapshot.evidence_source == "candidate_metadata":
        return ContinuityVerificationState.PARTIAL
    return ContinuityVerificationState.RULE_ONLY


def _combined_verification_state(
    snapshots: Iterable[ContinuitySnapshot],
) -> ContinuityVerificationState:
    values = [_snapshot_verification_state(item) for item in snapshots]
    if values and all(item == ContinuityVerificationState.VERIFIED for item in values):
        return ContinuityVerificationState.VERIFIED
    if any(item != ContinuityVerificationState.RULE_ONLY for item in values):
        return ContinuityVerificationState.PARTIAL
    return ContinuityVerificationState.RULE_ONLY


def build_continuity_snapshot(
    plan: ShotPlan,
    bindings: Iterable[ReferenceBinding],
    candidate: GenerationCandidate | None,
    run: GenerationRun | None = None,
) -> ContinuitySnapshot:
    references: dict[str, list[UUID]] = {}
    for binding in bindings:
        references.setdefault(binding.role.value, []).append(binding.reference_asset_id)
    references = {
        role: sorted(set(asset_ids), key=str) for role, asset_ids in sorted(references.items())
    }
    facts, evidence_source = _candidate_facts(candidate)
    prompt_fingerprint = _canonical_sha256(
        {
            "video_prompt": plan.video_prompt,
            "video_negative_constraints": plan.video_negative_constraints,
        }
    )
    payload = {
        "shot_plan_id": str(plan.id),
        "shot_index": plan.index,
        "candidate_id": str(candidate.id) if candidate is not None else None,
        "candidate_sha256": candidate.sha256 if candidate is not None else None,
        "generation_run_id": str(run.id) if run is not None else None,
        "generation_provider": run.provider if run is not None else None,
        "generation_model": run.model if run is not None else None,
        "generation_model_snapshot": run.model_snapshot if run is not None else None,
        "references": {
            role: [str(asset_id) for asset_id in asset_ids]
            for role, asset_ids in references.items()
        },
        "locks": sorted(item.value for item in plan.locks),
        "prompt_fingerprint": prompt_fingerprint,
        "facts": facts,
        "evidence_source": evidence_source,
    }
    return ContinuitySnapshot(
        shot_plan_id=plan.id,
        shot_index=plan.index,
        approved_video_candidate_id=candidate.id if candidate is not None else None,
        generation_run_id=run.id if run is not None else None,
        generation_provider=run.provider if run is not None else None,
        generation_model=run.model if run is not None else None,
        generation_model_snapshot=run.model_snapshot if run is not None else None,
        candidate_sha256=candidate.sha256 if candidate is not None else None,
        reference_asset_ids=references,
        locks=payload["locks"],
        prompt_fingerprint=prompt_fingerprint,
        observed_facts=facts,
        evidence_source=evidence_source,
        fingerprint=_canonical_sha256(payload),
    )


def boundary_key(left: ContinuitySnapshot, right: ContinuitySnapshot) -> str:
    return f"{left.shot_index}:{left.shot_plan_id}->{right.shot_index}:{right.shot_plan_id}"


def impacted_boundary_keys(
    snapshots: Iterable[ContinuitySnapshot],
    shot_plan_id: UUID,
) -> list[str]:
    ordered = sorted(snapshots, key=lambda item: item.shot_index)
    impacted: list[str] = []
    for left, right in zip(ordered, ordered[1:], strict=False):
        if shot_plan_id in {left.shot_plan_id, right.shot_plan_id}:
            impacted.append(boundary_key(left, right))
    return impacted


def _finding_key(
    project_id: UUID,
    pair_key: str,
    code: str,
    dimension: ContinuityDimension,
    expected: Any,
    actual: Any,
) -> str:
    return _canonical_sha256(
        {
            "project_id": str(project_id),
            "boundary_key": pair_key,
            "code": code,
            "dimension": dimension.value,
            "expected": expected,
            "actual": actual,
        }
    )


def _new_finding(
    *,
    project_id: UUID,
    pair_key: str,
    left: ContinuitySnapshot,
    right: ContinuitySnapshot,
    code: str,
    dimension: ContinuityDimension,
    severity: ContinuityFindingSeverity,
    message: str,
    suggestion: str,
    expected: Any,
    actual: Any,
    previous_findings: Mapping[str, ContinuityFinding],
    confidence: float = 1,
) -> ContinuityFinding:
    key = _finding_key(project_id, pair_key, code, dimension, expected, actual)
    previous = previous_findings.get(key)
    return ContinuityFinding(
        key=key,
        code=code,
        dimension=dimension,
        severity=severity,
        state=previous.state if previous is not None else ContinuityFindingState.OPEN,
        boundary_key=pair_key,
        left_shot_plan_id=left.shot_plan_id,
        right_shot_plan_id=right.shot_plan_id,
        message=message,
        suggestion=suggestion,
        expected=expected,
        actual=actual,
        confidence=confidence,
        decision_reason=previous.decision_reason if previous is not None else None,
        decided_at=previous.decided_at if previous is not None else None,
    )


def _boundary_status(
    findings: Iterable[ContinuityFinding],
    verification_state: ContinuityVerificationState,
) -> ContinuityBoundaryStatus:
    open_findings = [item for item in findings if item.state == ContinuityFindingState.OPEN]
    if any(item.severity == ContinuityFindingSeverity.BLOCKER for item in open_findings):
        return ContinuityBoundaryStatus.BLOCKED
    if any(item.severity == ContinuityFindingSeverity.WARNING for item in open_findings):
        return ContinuityBoundaryStatus.WARNING
    if verification_state != ContinuityVerificationState.VERIFIED:
        return ContinuityBoundaryStatus.UNVERIFIED
    return ContinuityBoundaryStatus.PASSED


def _compare_reference_bindings(
    *,
    project_id: UUID,
    pair_key: str,
    left: ContinuitySnapshot,
    right: ContinuitySnapshot,
    previous_findings: Mapping[str, ContinuityFinding],
) -> list[ContinuityFinding]:
    findings: list[ContinuityFinding] = []
    roles = set(left.reference_asset_ids) | set(right.reference_asset_ids)
    for role in sorted(roles):
        dimension = _REFERENCE_DIMENSIONS.get(role)
        if dimension is None:
            continue
        left_ids = [str(item) for item in left.reference_asset_ids.get(role, [])]
        right_ids = [str(item) for item in right.reference_asset_ids.get(role, [])]
        if left_ids == right_ids:
            continue
        severity = (
            ContinuityFindingSeverity.BLOCKER
            if dimension in _BLOCKING_REFERENCE_DIMENSIONS
            else ContinuityFindingSeverity.WARNING
        )
        missing = not left_ids or not right_ids
        role_label = {
            ContinuityDimension.IDENTITY: "人物身份",
            ContinuityDimension.WARDROBE: "服装",
            ContinuityDimension.PRODUCT: "产品",
            ContinuityDimension.SCENE: "场景",
            ContinuityDimension.COLOR: "视觉风格",
            ContinuityDimension.SCREEN_POSITION: "构图布局",
        }.get(dimension, dimension.value)
        findings.append(
            _new_finding(
                project_id=project_id,
                pair_key=pair_key,
                left=left,
                right=right,
                code=("reference_binding_missing" if missing else "reference_binding_changed"),
                dimension=dimension,
                severity=severity,
                message=(
                    f"相邻分镜的{role_label}参考资产在一侧缺失"
                    if missing
                    else f"相邻分镜使用了不同的{role_label}参考资产"
                ),
                suggestion=("绑定同一参考资产后重新生成，或在确认属于有意变化时进行豁免。"),
                expected=left_ids or "未绑定",
                actual=right_ids or "未绑定",
                previous_findings=previous_findings,
            )
        )
    return findings


def _compare_observed_facts(
    *,
    project_id: UUID,
    pair_key: str,
    left: ContinuitySnapshot,
    right: ContinuitySnapshot,
    previous_findings: Mapping[str, ContinuityFinding],
) -> list[ContinuityFinding]:
    findings: list[ContinuityFinding] = []
    common_locks = set(left.locks) & set(right.locks)
    for fact_name, (dimension, required_lock) in _DIRECT_FACTS.items():
        if required_lock is not None and required_lock not in common_locks:
            continue
        expected = left.observed_facts.get(fact_name)
        actual = right.observed_facts.get(fact_name)
        if not expected or not actual or expected.casefold() == actual.casefold():
            continue
        severity = (
            ContinuityFindingSeverity.BLOCKER
            if dimension in _BLOCKING_REFERENCE_DIMENSIONS
            else ContinuityFindingSeverity.WARNING
        )
        findings.append(
            _new_finding(
                project_id=project_id,
                pair_key=pair_key,
                left=left,
                right=right,
                code="observed_fact_changed",
                dimension=dimension,
                severity=severity,
                message=f"相邻分镜的 {dimension.value} 视觉事实不一致",
                suggestion="检查提示词与参考图；若这是剧情要求的变化，可记录原因后豁免。",
                expected=expected,
                actual=actual,
                previous_findings=previous_findings,
                confidence=0.9,
            )
        )
    for dimension, (left_name, right_name, required_lock) in _ENDPOINT_FACTS.items():
        if required_lock not in common_locks:
            continue
        expected = left.observed_facts.get(left_name)
        actual = right.observed_facts.get(right_name)
        if not expected or not actual or expected.casefold() == actual.casefold():
            continue
        findings.append(
            _new_finding(
                project_id=project_id,
                pair_key=pair_key,
                left=left,
                right=right,
                code="boundary_endpoint_mismatch",
                dimension=dimension,
                severity=ContinuityFindingSeverity.WARNING,
                message=f"前一分镜结尾与后一分镜开头的 {dimension.value} 不连续",
                suggestion="调整后一分镜起始提示词或采用能承接前一镜头结尾的候选。",
                expected=expected,
                actual=actual,
                previous_findings=previous_findings,
                confidence=0.9,
            )
        )
    return findings


def recalculate_continuity_report(
    report: ContinuityReport,
    *,
    boundaries: list[ContinuityBoundaryResult] | None = None,
) -> ContinuityReport:
    next_boundaries = boundaries if boundaries is not None else report.boundaries
    active_findings = [
        finding
        for boundary in next_boundaries
        for finding in boundary.findings
        if finding.state == ContinuityFindingState.OPEN
    ]
    blocker_count = sum(
        item.severity == ContinuityFindingSeverity.BLOCKER for item in active_findings
    )
    warning_count = sum(
        item.severity == ContinuityFindingSeverity.WARNING for item in active_findings
    )
    stale_keys = [
        boundary.key
        for boundary in next_boundaries
        if boundary.status == ContinuityBoundaryStatus.STALE
    ]
    status = ContinuityReportStatus.STALE if stale_keys else ContinuityReportStatus.COMPLETED
    return report.model_copy(
        update={
            "status": status,
            "boundaries": next_boundaries,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "open_finding_count": len(active_findings),
            "score": max(0, 100 - blocker_count * 25 - warning_count * 8),
            "stale_boundary_keys": stale_keys,
            "updated_at": datetime.now(UTC),
        }
    )


def evaluate_continuity(
    *,
    project_id: UUID,
    revision_id: UUID,
    snapshots: list[ContinuitySnapshot],
    previous_report: ContinuityReport | None = None,
) -> ContinuityReport:
    ordered = sorted(snapshots, key=lambda item: item.shot_index)
    previous_findings = {
        finding.key: finding
        for boundary in (previous_report.boundaries if previous_report else [])
        for finding in boundary.findings
    }
    boundaries: list[ContinuityBoundaryResult] = []
    for left, right in zip(ordered, ordered[1:], strict=False):
        pair_key = boundary_key(left, right)
        pair_snapshots = [left, right]
        verification_state = _combined_verification_state(pair_snapshots)
        findings = _compare_reference_bindings(
            project_id=project_id,
            pair_key=pair_key,
            left=left,
            right=right,
            previous_findings=previous_findings,
        )
        findings.extend(
            _compare_observed_facts(
                project_id=project_id,
                pair_key=pair_key,
                left=left,
                right=right,
                previous_findings=previous_findings,
            )
        )
        boundaries.append(
            ContinuityBoundaryResult(
                key=pair_key,
                left_shot_plan_id=left.shot_plan_id,
                right_shot_plan_id=right.shot_plan_id,
                left_shot_index=left.shot_index,
                right_shot_index=right.shot_index,
                status=_boundary_status(findings, verification_state),
                verification_state=verification_state,
                findings=findings,
            )
        )
    report = ContinuityReport(
        project_id=project_id,
        revision_id=revision_id,
        verification_state=_combined_verification_state(ordered),
        input_fingerprint=_canonical_sha256(
            {
                "project_id": str(project_id),
                "revision_id": str(revision_id),
                "snapshots": [item.fingerprint for item in ordered],
                "rule_version": "continuity-rules-v1",
            }
        ),
        snapshots=ordered,
        boundaries=boundaries,
    )
    return recalculate_continuity_report(report)


def stale_continuity_report(
    report: ContinuityReport,
    *,
    shot_plan_id: UUID,
    invalidated_by_revision_id: UUID,
) -> ContinuityReport:
    impacted = set(impacted_boundary_keys(report.snapshots, shot_plan_id))
    if not impacted:
        return report
    boundaries = [
        boundary.model_copy(update={"status": ContinuityBoundaryStatus.STALE})
        if boundary.key in impacted
        else boundary
        for boundary in report.boundaries
    ]
    recalculated = recalculate_continuity_report(report, boundaries=boundaries)
    return recalculated.model_copy(
        update={
            "invalidated_by_revision_id": invalidated_by_revision_id,
            "updated_at": datetime.now(UTC),
        }
    )


def update_finding_decision(
    report: ContinuityReport,
    *,
    finding_key: str,
    state: ContinuityFindingState,
    reason: str | None,
) -> ContinuityReport:
    found = False
    boundaries: list[ContinuityBoundaryResult] = []
    for boundary in report.boundaries:
        findings: list[ContinuityFinding] = []
        for finding in boundary.findings:
            if finding.key != finding_key:
                findings.append(finding)
                continue
            found = True
            findings.append(
                finding.model_copy(
                    update={
                        "state": state,
                        "decision_reason": reason,
                        "decided_at": (
                            datetime.now(UTC) if state != ContinuityFindingState.OPEN else None
                        ),
                    }
                )
            )
        status = (
            ContinuityBoundaryStatus.STALE
            if boundary.status == ContinuityBoundaryStatus.STALE
            else _boundary_status(findings, boundary.verification_state)
        )
        boundaries.append(boundary.model_copy(update={"findings": findings, "status": status}))
    if not found:
        raise KeyError(finding_key)
    return recalculate_continuity_report(report, boundaries=boundaries)
