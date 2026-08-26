from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from ..models import (
    AnalysisJob,
    AnalysisReport,
    ModelRun,
    ModelRunStatus,
    ModelTask,
    ModelUsage,
    PriceSnapshot,
    Shot,
    ViralFinding,
    ViralReasoningImprovement,
    ViralReasoningSynthesis,
)
from .billing import (
    PriceCatalog,
    PriceCatalogError,
    calculate_cost_micros,
    estimate_text_tokens,
    summarize_model_runs,
)
from .contracts import ModelProviderError, ModelProviderUnavailable, ModelRequest
from .router import ModelRouter

VIRAL_REASONING_PROMPT_PATH = Path(__file__).with_name("prompts") / "viral_reasoning_v1.md"
DEFAULT_OUTPUT_TOKEN_ESTIMATE = 3200
_GENERIC_HEADLINE_FRAGMENTS = (
    "首屏快速建立视觉问题",
    "首尾信息闭环",
    "核心视觉信号前置",
    "强化结尾兑现",
)
_GENERIC_IMPROVEMENT_FRAGMENTS = (
    "核心视觉信号前置",
    "强化结尾兑现",
    "首尾呼应",
    "文字锚点",
)
_PLACEHOLDER_FRAGMENTS = (
    "待多模态模型识别",
    "待 VLM 分析",
    "无法确认",
    "尚未识别",
    "等待分析",
    "真实镜头边界",
    "已提取多时点关键帧",
)
_SPACE_RE = re.compile(r"\s+")


class ViralReasoningRepository(Protocol):
    async def save_model_run(self, run: ModelRun) -> ModelRun: ...

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]: ...

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None: ...

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_error_message(error: Exception) -> str:
    message = " ".join(str(error).replace("\x00", "").split())
    return message[:500] or type(error).__name__


def _compact(value: str | None, limit: int = 600) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()[:limit]


def _evidence_payload(report: AnalysisReport) -> dict:
    return {
        "video_duration_seconds": report.overview.duration_seconds,
        "aspect_ratio": report.overview.aspect_ratio,
        "shots": [
            {
                "shot_id": shot.id,
                "index": shot.index,
                "start_seconds": shot.start_seconds,
                "end_seconds": shot.end_seconds,
                "title": _compact(shot.title, 240),
                "subjects": [_compact(item, 240) for item in shot.subjects[:12]],
                "action": _compact(shot.action),
                "scene": _compact(shot.scene),
                "camera": _compact(shot.camera),
                "composition": _compact(shot.composition),
                "lighting": _compact(shot.lighting, 300),
                "color": _compact(shot.color, 300),
                "dialogue": _compact(shot.dialogue),
                "subtitle": _compact(shot.subtitle_text),
                "ocr": _compact(shot.ocr_text),
                "audio": _compact(shot.audio, 300),
                "transition": _compact(shot.transition, 300),
                "narrative_role": _compact(shot.narrative_role, 300),
                "confidence": shot.confidence,
            }
            for shot in sorted(report.shots, key=lambda item: item.index)[:120]
        ],
    }


def _user_prompt(report: AnalysisReport) -> str:
    evidence = json.dumps(_evidence_payload(report), ensure_ascii=False, separators=(",", ":"))
    schema = json.dumps(ViralReasoningSynthesis.model_json_schema(), ensure_ascii=False)
    return (
        "以下 JSON 是当前视频经过 FFprobe、分镜检测、ASR/OCR 和逐镜头 VLM 后形成的证据。\n"
        f"证据：{evidence}\n"
        "请输出当前视频专属的内容机制综合判断。严格遵守以下 JSON Schema：\n"
        f"{schema}"
    )


def _request_fingerprint(
    report: AnalysisReport,
    *,
    target,
    system_prompt: str,
    user_prompt: str,
) -> str:
    payload = {
        "analysis_id": str(report.analysis_id),
        "generated_at": report.generated_at.isoformat(),
        "evidence": _evidence_payload(report),
        "provider": target.provider,
        "model": target.model,
        "prompt_version": target.prompt_version,
        "schema_version": target.schema_version,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _overlapping_shots(report: AnalysisReport, start: float, end: float) -> list[Shot]:
    return [
        shot
        for shot in report.shots
        if shot.end_seconds > start and shot.start_seconds < max(start + 0.01, end)
    ]


def _has_grounded_evidence(shot: Shot) -> bool:
    values = [
        shot.title,
        *shot.subjects,
        shot.action,
        shot.scene,
        shot.camera,
        shot.composition,
        shot.dialogue,
        shot.subtitle_text,
        shot.ocr_text,
    ]
    for value in values:
        text = _compact(value)
        if re.fullmatch(r"镜头\s*\d+", text):
            continue
        if len(text) >= 3 and not any(fragment in text for fragment in _PLACEHOLDER_FRAGMENTS):
            return True
    return False


def validate_viral_reasoning(
    report: AnalysisReport,
    synthesis: ViralReasoningSynthesis,
) -> ViralReasoningSynthesis:
    """Keep only claims that can be attached to real shot and time evidence."""

    duration = max(0.01, float(report.overview.duration_seconds))
    findings: list[ViralFinding] = []
    for item in synthesis.findings:
        start = max(0.0, min(duration, float(item.start_seconds)))
        end = max(start, min(duration, float(item.end_seconds)))
        overlapping = _overlapping_shots(report, start, end)
        if (
            end - start < 0.01
            or not overlapping
            or not any(_has_grounded_evidence(shot) for shot in overlapping)
        ):
            continue
        if item.confidence < 0.4 or len(_compact(item.observation)) < 6:
            continue
        findings.append(
            item.model_copy(
                update={
                    "id": f"viral-reasoning-{len(findings) + 1:02d}",
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                }
            )
        )
        if len(findings) == 4:
            break

    known_shot_ids = {shot.id for shot in report.shots}
    improvements: list[ViralReasoningImprovement] = []
    for item in synthesis.improvements:
        if any(fragment in item.title for fragment in _GENERIC_IMPROVEMENT_FRAGMENTS):
            continue
        affected = list(
            dict.fromkeys(
                shot_id
                for shot_id in item.affected_shot_ids
                if shot_id in known_shot_ids
            )
        )
        if not affected:
            continue
        improvements.append(item.model_copy(update={"affected_shot_ids": affected}))
        if len(improvements) == 4:
            break

    insufficient = synthesis.insufficient_evidence or not findings
    headline = _compact(synthesis.headline, 300)
    if not headline or any(fragment in headline for fragment in _GENERIC_HEADLINE_FRAGMENTS):
        headline = (
            f"{findings[0].title}：{_compact(findings[0].observation, 180)}"
            if findings
            else "现有证据不足以确认独特的内容流量机制"
        )
    if insufficient:
        improvements = []
    reason = synthesis.insufficient_evidence_reason
    if insufficient and not reason:
        reason = "逐镜头证据不足以支持可核验的独特机制判断。"
    strongest_hook = _compact(synthesis.strongest_hook, 1000)
    if insufficient or not strongest_hook:
        strongest_hook = "现有证据不足以确认明确的流量抓手。"
    return synthesis.model_copy(
        update={
            "headline": headline,
            "strongest_hook": strongest_hook,
            "findings": findings,
            "improvements": improvements,
            "confidence": min(synthesis.confidence, 0.45) if insufficient else synthesis.confidence,
            "insufficient_evidence": insufficient,
            "insufficient_evidence_reason": reason,
        }
    )


def apply_viral_reasoning(
    report: AnalysisReport,
    synthesis: ViralReasoningSynthesis,
) -> AnalysisReport:
    scores = [item.score for item in synthesis.findings]
    overview = report.overview.model_copy(
        update={
            "summary": synthesis.content_value,
            "narrative_structure": synthesis.narrative_structure,
            "audience_inference": synthesis.audience,
            "viral_potential_score": round(sum(scores) / len(scores)) if scores else 0,
            "confidence": synthesis.confidence,
        }
    )
    return report.model_copy(
        update={
            "overview": overview,
            "viral_findings": synthesis.findings,
            "viral_reasoning": synthesis,
        }
    )


class ViralReasoningService:
    def __init__(
        self,
        repository: ViralReasoningRepository,
        *,
        router: ModelRouter | None = None,
        price_catalog: PriceCatalog | None = None,
    ) -> None:
        self.repository = repository
        self.router = router or ModelRouter()
        self.price_catalog = price_catalog or PriceCatalog()
        self.system_prompt = VIRAL_REASONING_PROMPT_PATH.read_text("utf-8").strip()

    async def enrich(
        self,
        analysis: AnalysisJob,
        report: AnalysisReport,
    ) -> AnalysisReport:
        if report.viral_reasoning is not None or analysis.model_plan is None:
            return report
        targets = analysis.model_plan.targets_for(ModelTask.VIRAL_REASONING)
        if not targets:
            return await self._finish(report, analysis, ["模型计划没有 viral_reasoning 路由"])
        if analysis.model_plan.pricing_version != self.price_catalog.catalog_version:
            return await self._finish(report, analysis, ["模型计划价格版本不匹配，内容综合已停止"])

        user_prompt = _user_prompt(report)
        warnings: list[str] = []
        previous_run_id: UUID | None = None
        attempt = 0
        for target in targets:
            fingerprint = _request_fingerprint(
                report,
                target=target,
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
            )
            cached = await self.repository.find_completed_model_run(fingerprint)
            if cached and cached.result_payload:
                try:
                    synthesis = validate_viral_reasoning(
                        report,
                        ViralReasoningSynthesis.model_validate(cached.result_payload),
                    )
                except (ValidationError, ValueError):
                    pass
                else:
                    cached_run = ModelRun(
                        analysis_id=analysis.id,
                        video_id=report.video_id,
                        task=ModelTask.VIRAL_REASONING,
                        provider=target.provider,
                        requested_model=target.model,
                        resolved_model=cached.resolved_model,
                        prompt_version=target.prompt_version,
                        schema_version=target.schema_version,
                        request_fingerprint=fingerprint,
                        cache_source_run_id=cached.id,
                        status=ModelRunStatus.CACHED,
                        result_payload=synthesis.model_dump(mode="json"),
                        completed_at=_utc_now(),
                    )
                    await self.repository.save_model_run(cached_run)
                    return await self._finish(
                        apply_viral_reasoning(report, synthesis), analysis, warnings
                    )

            attempt += 1
            estimated_usage = ModelUsage(
                input_tokens=estimate_text_tokens(self.system_prompt + user_prompt),
                output_tokens=DEFAULT_OUTPUT_TOKEN_ESTIMATE,
            )
            estimated_usage.total_tokens = (
                estimated_usage.input_tokens + estimated_usage.output_tokens
            )
            try:
                estimated_price = self.price_catalog.snapshot_for(
                    target.provider,
                    target.model,
                    estimated_usage.input_tokens,
                )
            except PriceCatalogError as exc:
                warnings.append(str(exc))
                continue
            estimated_cost = calculate_cost_micros(estimated_usage, estimated_price)
            if (
                analysis.max_cost_micros is not None
                and analysis.estimated_cost_micros + estimated_cost > analysis.max_cost_micros
            ):
                blocked = ModelRun(
                    analysis_id=analysis.id,
                    video_id=report.video_id,
                    task=ModelTask.VIRAL_REASONING,
                    attempt=attempt,
                    retry_of_run_id=previous_run_id,
                    provider=target.provider,
                    requested_model=target.model,
                    prompt_version=target.prompt_version,
                    schema_version=target.schema_version,
                    request_fingerprint=fingerprint,
                    status=ModelRunStatus.BLOCKED,
                    price_snapshot_id=estimated_price.id,
                    estimated_cost_micros=estimated_cost,
                    error_code="budget_exceeded",
                    error_message="内容机制综合将超过任务成本上限",
                    completed_at=_utc_now(),
                )
                await self.repository.save_price_snapshot(estimated_price)
                await self.repository.save_model_run(blocked)
                warnings.append("内容机制综合已被成本上限阻止")
                break

            run = ModelRun(
                analysis_id=analysis.id,
                video_id=report.video_id,
                task=ModelTask.VIRAL_REASONING,
                attempt=attempt,
                retry_of_run_id=previous_run_id,
                provider=target.provider,
                requested_model=target.model,
                prompt_version=target.prompt_version,
                schema_version=target.schema_version,
                request_fingerprint=fingerprint,
                status=ModelRunStatus.RUNNING,
                price_snapshot_id=estimated_price.id,
                estimated_cost_micros=estimated_cost,
            )
            await self.repository.save_price_snapshot(estimated_price)
            await self.repository.save_model_run(run)
            analysis.estimated_cost_micros += estimated_cost
            await self.repository.save_analysis(analysis)
            try:
                provider = self.router.provider_for(target)
                result = await provider.generate(
                    ModelRequest(
                        task=ModelTask.VIRAL_REASONING,
                        target=target,
                        system_prompt=self.system_prompt,
                        user_prompt=user_prompt,
                    ),
                    ViralReasoningSynthesis,
                )
                synthesis = validate_viral_reasoning(report, result.data)
                measured_price = self._measured_price(
                    target.provider,
                    target.model,
                    result.resolved_model,
                    result.usage,
                )
                measured_cost = calculate_cost_micros(result.usage, measured_price)
                await self.repository.save_price_snapshot(measured_price)
                run.status = ModelRunStatus.COMPLETED
                run.resolved_model = result.resolved_model
                run.provider_request_id = result.provider_request_id
                run.usage = result.usage
                run.price_snapshot_id = measured_price.id
                run.measured_cost_micros = measured_cost
                run.latency_ms = result.latency_ms
                run.result_payload = synthesis.model_dump(mode="json")
                run.completed_at = _utc_now()
                await self.repository.save_model_run(run)
                analysis.measured_cost_micros += measured_cost
                await self.repository.save_analysis(analysis)
                return await self._finish(
                    apply_viral_reasoning(report, synthesis), analysis, warnings
                )
            except ModelProviderError as exc:
                run.status = ModelRunStatus.FAILED
                run.provider_request_id = exc.provider_request_id
                run.resolved_model = exc.resolved_model
                run.latency_ms = exc.latency_ms
                run.error_code = exc.code
                run.error_message = _safe_error_message(exc)
                run.completed_at = _utc_now()
                await self.repository.save_model_run(run)
                previous_run_id = run.id
                if isinstance(exc, ModelProviderUnavailable) or not exc.retryable:
                    warnings.append(f"内容机制综合不可用：{exc}")
                    break
            except Exception as exc:  # pragma: no cover - provider safety boundary
                run.status = ModelRunStatus.FAILED
                run.error_code = "viral_reasoning_failed"
                run.error_message = _safe_error_message(exc)
                run.completed_at = _utc_now()
                await self.repository.save_model_run(run)
                previous_run_id = run.id

        warnings.append("内容机制综合未返回可用结果")
        return await self._finish(report, analysis, warnings)

    def _measured_price(
        self,
        provider: str,
        requested_model: str,
        resolved_model: str,
        usage: ModelUsage,
    ) -> PriceSnapshot:
        try:
            return self.price_catalog.snapshot_for(provider, resolved_model, usage.input_tokens)
        except PriceCatalogError:
            return self.price_catalog.snapshot_for(provider, requested_model, usage.input_tokens)

    async def _finish(
        self,
        report: AnalysisReport,
        analysis: AnalysisJob,
        warnings: list[str],
    ) -> AnalysisReport:
        runs = await self.repository.list_model_runs(analysis.id)
        summary = summarize_model_runs(
            analysis.id,
            runs,
            estimated_cost_micros=analysis.estimated_cost_micros,
        )
        analysis.measured_cost_micros = summary.measured_cost_micros
        await self.repository.save_analysis(analysis)
        return report.model_copy(
            update={
                "model_warnings": list(dict.fromkeys([*report.model_warnings, *warnings])),
                "model_cost_summary": summary,
            }
        )
