from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from typing import Any

from viral_dna_api.models import AnalysisReport, Shot

from .contracts import (
    GoldenAnalysisExpectation,
    GoldenRegressionFinding,
    GoldenRegressionResult,
    QualityFindingSeverity,
)


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _shot_quality_payload(shot: Shot) -> dict[str, Any]:
    return {
        "index": shot.index,
        "start_seconds": shot.start_seconds,
        "end_seconds": shot.end_seconds,
        "content_start_seconds": shot.content_start_seconds,
        "content_end_seconds": shot.content_end_seconds,
        "subjects": shot.subjects,
        "action": shot.action,
        "scene": shot.scene,
        "camera": shot.camera,
        "composition": shot.composition,
        "lighting": shot.lighting,
        "color": shot.color,
        "transition": shot.transition,
        "prompt": shot.prompt,
        "visual_beats": [
            {
                "index": item.index,
                "title": item.title,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "source_timestamp_seconds": item.source_timestamp_seconds,
                "image_prompt": item.image_prompt,
            }
            for item in shot.visual_beats
        ],
        "motion_phases": [
            {
                "index": item.index,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "description": item.description,
                "camera_motion": item.camera_motion,
                "subject_motion": item.subject_motion,
                "foreground_motion": item.foreground_motion,
                "focus_change": item.focus_change,
                "foreground_occupancy_start_percent": (item.foreground_occupancy_start_percent),
                "foreground_occupancy_end_percent": item.foreground_occupancy_end_percent,
                "occlusion_start_percent": item.occlusion_start_percent,
                "occlusion_end_percent": item.occlusion_end_percent,
            }
            for item in shot.motion_phases
        ],
        "outgoing_transition": shot.outgoing_transition.model_dump(mode="json"),
    }


def report_quality_fingerprint(report: AnalysisReport) -> str:
    payload = {
        "overview": {
            "duration_seconds": report.overview.duration_seconds,
            "aspect_ratio": report.overview.aspect_ratio,
        },
        "shots": [
            _shot_quality_payload(shot)
            for shot in sorted(report.shots, key=lambda item: item.index)
        ],
    }
    return _canonical_sha256(payload)


def _motion_corpus(shot: Shot) -> str:
    values = [
        shot.prompt,
        shot.action,
        shot.camera,
        shot.transition,
        shot.outgoing_transition.description,
        shot.outgoing_transition.terminal_frame,
        shot.outgoing_transition.generation_prompt,
    ]
    for phase in shot.motion_phases:
        values.extend(
            [
                phase.description,
                phase.camera_motion,
                phase.subject_motion,
                phase.foreground_motion,
                phase.focus_change,
            ]
        )
    return _normalized_text("\n".join(value for value in values if value))


def _missing_terms(corpus: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _normalized_text(term) not in corpus]


def _present_terms(corpus: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _normalized_text(term) in corpus]


def evaluate_golden_report(
    report: AnalysisReport,
    expectation: GoldenAnalysisExpectation,
) -> GoldenRegressionResult:
    findings: list[GoldenRegressionFinding] = []

    def add_finding(
        code: str,
        message: str,
        *,
        severity: QualityFindingSeverity = QualityFindingSeverity.ERROR,
        shot_index: int | None = None,
        expected: str | int | float | None = None,
        actual: str | int | float | None = None,
    ) -> None:
        findings.append(
            GoldenRegressionFinding(
                code=code,
                severity=severity,
                scope="shot" if shot_index is not None else "analysis",
                shot_index=shot_index,
                message=message,
                expected=expected,
                actual=actual,
            )
        )

    if len(report.shots) != expectation.expected_shot_count:
        add_finding(
            "shot_count_drift",
            "分析报告的分镜数量与黄金样本不一致",
            expected=expectation.expected_shot_count,
            actual=len(report.shots),
        )

    if expectation.source_sha256 is not None:
        source_sha256 = (
            report.media_evidence.metadata.sha256 if report.media_evidence is not None else None
        )
        if source_sha256 != expectation.source_sha256:
            add_finding(
                "source_fingerprint_mismatch",
                "分析报告不属于当前黄金样本源视频",
                expected=expectation.source_sha256,
                actual=source_sha256 or "missing",
            )

    ordered_shots = sorted(report.shots, key=lambda item: item.index)
    shot_by_index = {shot.index: shot for shot in ordered_shots}
    if len(shot_by_index) != len(ordered_shots):
        add_finding(
            "duplicate_shot_index",
            "分析报告包含重复分镜序号",
            expected="unique",
            actual=len(ordered_shots) - len(shot_by_index),
        )

    for previous, current in zip(ordered_shots, ordered_shots[1:], strict=False):
        delta = current.start_seconds - previous.end_seconds
        if delta > expectation.max_boundary_gap_seconds:
            add_finding(
                "timeline_gap",
                "相邻分镜之间存在超过黄金基线的时间空洞",
                severity=QualityFindingSeverity.WARNING,
                shot_index=current.index,
                expected=expectation.max_boundary_gap_seconds,
                actual=round(delta, 4),
            )
        elif delta < -expectation.max_boundary_overlap_seconds:
            add_finding(
                "timeline_overlap",
                "后一个分镜从前一个分镜结束之前重新开始",
                shot_index=current.index,
                expected=expectation.max_boundary_overlap_seconds,
                actual=round(abs(delta), 4),
            )

    for expected_shot in expectation.shots:
        shot = shot_by_index.get(expected_shot.shot_index)
        if shot is None:
            add_finding(
                "expected_shot_missing",
                "黄金样本要求的分镜不存在",
                shot_index=expected_shot.shot_index,
                expected=expected_shot.shot_index,
                actual="missing",
            )
            continue

        tolerance = expected_shot.time_tolerance_seconds
        if (
            expected_shot.expected_start_seconds is not None
            and abs(shot.start_seconds - expected_shot.expected_start_seconds) > tolerance
        ):
            add_finding(
                "shot_start_drift",
                "分镜开始时间超出黄金样本容差",
                shot_index=shot.index,
                expected=expected_shot.expected_start_seconds,
                actual=shot.start_seconds,
            )
        if (
            expected_shot.expected_end_seconds is not None
            and abs(shot.end_seconds - expected_shot.expected_end_seconds) > tolerance
        ):
            add_finding(
                "shot_end_drift",
                "分镜结束时间超出黄金样本容差",
                shot_index=shot.index,
                expected=expected_shot.expected_end_seconds,
                actual=shot.end_seconds,
            )

        prompt_corpus = _normalized_text(shot.prompt)
        for term in _missing_terms(prompt_corpus, expected_shot.required_prompt_terms):
            add_finding(
                "required_prompt_term_missing",
                f"分镜提示词缺少关键语义：{term}",
                shot_index=shot.index,
                expected=term,
                actual="missing",
            )
        for term in _present_terms(prompt_corpus, expected_shot.forbidden_prompt_terms):
            add_finding(
                "forbidden_prompt_term_present",
                f"分镜提示词重新出现禁止语义：{term}",
                shot_index=shot.index,
                expected="absent",
                actual=term,
            )
        motion_corpus = _motion_corpus(shot)
        for term in _missing_terms(motion_corpus, expected_shot.required_motion_terms):
            add_finding(
                "required_motion_term_missing",
                f"分镜运镜事实缺少关键语义：{term}",
                shot_index=shot.index,
                expected=term,
                actual="missing",
            )

        beat_count = len(shot.visual_beats)
        if beat_count < expected_shot.min_visual_beat_count:
            add_finding(
                "visual_beat_count_below_minimum",
                "分镜画面数量低于黄金样本下限",
                shot_index=shot.index,
                expected=expected_shot.min_visual_beat_count,
                actual=beat_count,
            )
        if (
            expected_shot.max_visual_beat_count is not None
            and beat_count > expected_shot.max_visual_beat_count
        ):
            add_finding(
                "visual_beat_count_above_maximum",
                "分镜画面数量高于黄金样本上限",
                shot_index=shot.index,
                expected=expected_shot.max_visual_beat_count,
                actual=beat_count,
            )
        if len(shot.motion_phases) < expected_shot.min_motion_phase_count:
            add_finding(
                "motion_phase_count_below_minimum",
                "分镜运镜阶段数量低于黄金样本下限",
                shot_index=shot.index,
                expected=expected_shot.min_motion_phase_count,
                actual=len(shot.motion_phases),
            )
        if (
            expected_shot.expected_transition_kind is not None
            and shot.outgoing_transition.kind != expected_shot.expected_transition_kind
        ):
            add_finding(
                "transition_kind_drift",
                "分镜出场转场类型与黄金样本不一致",
                shot_index=shot.index,
                expected=expected_shot.expected_transition_kind,
                actual=shot.outgoing_transition.kind,
            )

        content_start = shot.content_start_seconds or shot.start_seconds
        content_end = shot.content_end_seconds or shot.end_seconds
        for phase in shot.motion_phases:
            if (
                phase.start_seconds < content_start - tolerance
                or phase.end_seconds > content_end + tolerance
            ):
                add_finding(
                    "motion_phase_outside_shot",
                    "运镜阶段使用了当前分镜有效范围之外的时间",
                    shot_index=shot.index,
                    expected=f"{content_start:.3f}-{content_end:.3f}",
                    actual=f"{phase.start_seconds:.3f}-{phase.end_seconds:.3f}",
                )
        for beat in shot.visual_beats:
            if (
                beat.start_seconds < content_start - tolerance
                or beat.end_seconds > content_end + tolerance
            ):
                add_finding(
                    "visual_beat_outside_shot",
                    "画面事实使用了当前分镜有效范围之外的时间",
                    shot_index=shot.index,
                    expected=f"{content_start:.3f}-{content_end:.3f}",
                    actual=f"{beat.start_seconds:.3f}-{beat.end_seconds:.3f}",
                )

    error_count = sum(finding.severity == QualityFindingSeverity.ERROR for finding in findings)
    warning_count = sum(finding.severity == QualityFindingSeverity.WARNING for finding in findings)
    score = max(0, 100 - error_count * 20 - warning_count * 5)
    expectation_fingerprint = _canonical_sha256(expectation.model_dump(mode="json"))
    passed = error_count == 0 and score >= expectation.minimum_score
    return GoldenRegressionResult(
        sample_id=expectation.sample_id,
        sample_name=expectation.name,
        passed=passed,
        score=score,
        finding_count=len(findings),
        error_count=error_count,
        warning_count=warning_count,
        expectation_fingerprint=expectation_fingerprint,
        report_fingerprint=report_quality_fingerprint(report),
        findings=findings,
    )
