from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from ..media import artifact_url, boundaries_from_candidates, get_analysis_artifact_root
from ..models import (
    AnalysisCostSummary,
    AnalysisJob,
    MediaEvidence,
    ModelRun,
    ModelRunStatus,
    ModelTask,
    ModelUsage,
    PriceSnapshot,
    SceneBoundaryCandidate,
    SegmentationMetadata,
    ShotSegmentationSelection,
    Video,
)
from .billing import (
    PriceCatalog,
    PriceCatalogError,
    calculate_cost_micros,
    committed_model_cost_micros,
    estimate_text_tokens,
    estimate_visual_tokens,
    summarize_model_runs,
)
from .contracts import ModelProviderError, ModelProviderUnavailable, ModelRequest
from .router import ModelRouter

SHOT_SEGMENTATION_PROMPT_PATH = Path(__file__).with_name("prompts") / "shot_segmentation_v5.md"
DEFAULT_OUTPUT_TOKEN_ESTIMATE = 2800


class ModelRunRepository(Protocol):
    async def save_model_run(self, run: ModelRun) -> ModelRun: ...

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]: ...

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None: ...

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...


@dataclass(frozen=True, slots=True)
class SegmentationOutcome:
    segmentation: SegmentationMetadata
    warnings: list[str]
    cost_summary: AnalysisCostSummary


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_error_message(error: Exception) -> str:
    message = " ".join(str(error).replace("\x00", "").split())
    return message[:500] or type(error).__name__


def _artifact_path(
    analysis_id: UUID,
    url: str | None,
    record_id: UUID | None,
) -> Path | None:
    if not url:
        return None
    prefix = f"/api/v1/analyses/{analysis_id}/artifacts/"
    if not url.startswith(prefix):
        return None
    root = get_analysis_artifact_root(analysis_id, record_id).resolve()
    candidate = (root / url.removeprefix(prefix)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _image_paths(
    analysis: AnalysisJob,
    segmentation: SegmentationMetadata,
) -> tuple[Path, ...]:
    urls = [
        segmentation.context_sheet_url,
        *(candidate.comparison_image_url for candidate in segmentation.candidates),
    ]
    paths = [
        path
        for url in urls
        if (path := _artifact_path(analysis.id, url, analysis.record_id)) is not None
    ]
    return tuple(dict.fromkeys(paths))


def _image_labels(segmentation: SegmentationMetadata) -> tuple[str, ...]:
    labels = ["全片上下文图：仅用于理解时间顺序，不可单独作为候选边界证据。"]
    labels.extend(
        (
            f"候选 {candidate.id}，时间 {candidate.timestamp_seconds:.3f}s。"
            "请只检查紧随本标签的四帧图：从左到右为远前、近前、近后、远后，"
            f"对应时间为 {', '.join(f'{value:.3f}s' for value in candidate.evidence_timestamps)}；"
            "中间白线是候选时刻。"
        )
        for candidate in segmentation.candidates
    )
    return tuple(labels)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _user_prompt(segmentation: SegmentationMetadata, duration_seconds: float) -> str:
    schema = json.dumps(ShotSegmentationSelection.model_json_schema(), ensure_ascii=False)
    context_times = ", ".join(f"{value:.3f}s" for value in segmentation.context_timestamps)
    candidate_lines = []
    for image_index, candidate in enumerate(segmentation.candidates, 2):
        methods = "/".join(candidate.methods)
        locked = "；硬切锁定，程序必保留" if candidate.hard_boundary else ""
        evidence_times = ", ".join(f"{value:.3f}s" for value in candidate.evidence_timestamps)
        candidate_lines.append(
            f"图片 {image_index}：{candidate.id}，时间 {candidate.timestamp_seconds:.3f}s，"
            f"检测方法 {methods}，分数 {candidate.score:.6f}，"
            f"四帧时间 {evidence_times or '未记录'}{locked}"
        )
    return (
        f"视频总时长：{duration_seconds:.3f}s\n"
        f"图片 1 是全片上下文图，宫格时间依次为：{context_times}\n"
        "候选边界四帧微时间线映射如下；每张图依次为远前、近前、近后、远后：\n"
        + "\n".join(candidate_lines)
        + "\n请在 candidate_reviews 中逐项审核每个软候选；硬切锁定点不要重复审核。"
        "\n请严格输出符合以下 JSON Schema 的 JSON 对象：\n" + schema
    )


async def _request_fingerprint(
    *,
    video: Video,
    segmentation: SegmentationMetadata,
    image_paths: tuple[Path, ...],
    target,
    system_prompt: str,
    user_prompt: str,
) -> str:
    image_hashes = await asyncio.gather(
        *(asyncio.to_thread(_file_sha256, path) for path in image_paths)
    )
    payload = {
        "video_sha256": video.sha256,
        "detector_version": segmentation.detector_version,
        "candidates": [
            {
                "id": item.id,
                "timestamp_seconds": item.timestamp_seconds,
                "score": item.score,
                "methods": item.methods,
                "hard_boundary": item.hard_boundary,
                "evidence_timestamps": item.evidence_timestamps,
            }
            for item in segmentation.candidates
        ],
        "context_timestamps": segmentation.context_timestamps,
        "image_hashes": image_hashes,
        "image_labels": _image_labels(segmentation),
        "provider": target.provider,
        "model": target.model,
        "thinking": target.thinking,
        "prompt_version": target.prompt_version,
        "schema_version": target.schema_version,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def apply_model_selection(
    segmentation: SegmentationMetadata,
    selection: ShotSegmentationSelection,
    duration_seconds: float,
) -> SegmentationMetadata:
    candidates_by_id = {candidate.id: candidate for candidate in segmentation.candidates}
    decision_ids = [decision.candidate_id for decision in selection.candidate_reviews]
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("模型返回了重复的候选边界 ID")
    unknown = sorted(set(decision_ids) - set(candidates_by_id))
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"模型返回了不存在的候选边界：{unknown_text}")

    soft_candidate_ids = {
        candidate.id for candidate in segmentation.candidates if not candidate.hard_boundary
    }
    unexpected = sorted(set(decision_ids) - soft_candidate_ids)
    if unexpected:
        raise ValueError(f"模型不应审核硬切锁定边界：{', '.join(unexpected)}")
    missing = sorted(soft_candidate_ids - set(decision_ids))
    if missing:
        raise ValueError(f"模型缺少候选边界审核结果：{', '.join(missing)}")

    decisions = {decision.candidate_id: decision for decision in selection.candidate_reviews}

    def is_consistent_keep(decision) -> bool:
        return (
            decision.decision == "keep"
            and not decision.progressive_motion
            and decision.semantic_group_before != decision.semantic_group_after
        )

    selected_ids = {
        candidate.id for candidate in segmentation.candidates if candidate.hard_boundary
    }
    selected_ids.update(
        decision.candidate_id
        for decision in selection.candidate_reviews
        if is_consistent_keep(decision)
    )
    enriched: list[SceneBoundaryCandidate] = []
    for candidate in segmentation.candidates:
        decision = decisions.get(candidate.id)
        accepted = decision is not None and is_consistent_keep(decision)
        adjusted = decision is not None and decision.decision == "keep" and not accepted
        reason = decision.reason if decision else None
        if adjusted and reason:
            reason = (
                reason.rstrip("。；; ")
                + "；一致性校验：前后仍属同一粗粒度叙事组或存在连续运镜，已合并。"
            )[:800]
        transition_start: float | None = None
        stable_new_scene: float | None = None
        if candidate.hard_boundary:
            transition_start = candidate.timestamp_seconds
            stable_new_scene = candidate.timestamp_seconds
        elif accepted:
            evidence_times = sorted(candidate.evidence_timestamps)
            fallback_transition_start = (
                evidence_times[1]
                if len(evidence_times) >= 4
                else candidate.timestamp_seconds
            )
            fallback_stable_new_scene = (
                evidence_times[-1]
                if evidence_times
                else candidate.timestamp_seconds
            )
            transition_start = (
                decision.transition_start_seconds
                if decision.transition_start_seconds is not None
                else fallback_transition_start
            )
            stable_new_scene = (
                decision.stable_new_scene_seconds
                if decision.stable_new_scene_seconds is not None
                else fallback_stable_new_scene
            )
            lower = evidence_times[0] if evidence_times else candidate.timestamp_seconds
            upper = evidence_times[-1] if evidence_times else candidate.timestamp_seconds
            transition_start = round(min(upper, max(lower, transition_start)), 3)
            stable_new_scene = round(min(upper, max(transition_start, stable_new_scene)), 3)
        enriched.append(
            candidate.model_copy(
                update={
                    "selected_by_model": accepted,
                    "model_confidence": decision.confidence if decision else None,
                    "model_before_description": (decision.before_description if decision else None),
                    "model_after_description": (decision.after_description if decision else None),
                    "model_reason": reason,
                    "model_decision": decision.decision if decision else None,
                    "model_progressive_motion": (decision.progressive_motion if decision else None),
                    "model_consistency_adjusted": adjusted,
                    "semantic_group_before": (decision.semantic_group_before if decision else None),
                    "semantic_group_after": (decision.semantic_group_after if decision else None),
                    "transition_start_seconds": transition_start,
                    "stable_new_scene_seconds": stable_new_scene,
                }
            )
        )
    boundaries = boundaries_from_candidates(
        enriched,
        duration_seconds,
        selected_candidate_ids=selected_ids,
    )
    adjusted_ids = [candidate.id for candidate in enriched if candidate.model_consistency_adjusted]
    model_summary = selection.summary
    if adjusted_ids:
        model_summary = (
            model_summary.rstrip("。；; ")
            + f"；一致性校验已合并模型误保留候选：{', '.join(adjusted_ids)}。"
        )[:1200]
    return segmentation.model_copy(
        update={
            "candidates": enriched,
            "selected_candidate_ids": [
                candidate.id for candidate in enriched if candidate.id in selected_ids
            ],
            "final_boundaries": boundaries,
            "final_shot_count": max(0, len(boundaries) - 1),
            "verified_by_model": True,
            "model_confidence": selection.confidence,
            "model_summary": model_summary,
            "fallback_reason": None,
        }
    )


class ShotSegmentationService:
    def __init__(
        self,
        repository: ModelRunRepository,
        *,
        router: ModelRouter | None = None,
        price_catalog: PriceCatalog | None = None,
        providers: Mapping | None = None,
    ) -> None:
        self.repository = repository
        self.router = router or ModelRouter(providers)
        self.price_catalog = price_catalog or PriceCatalog()
        self.max_attempts = max(1, int(os.getenv("VIRAL_DNA_MODEL_MAX_ATTEMPTS", "2")))
        self.system_prompt = SHOT_SEGMENTATION_PROMPT_PATH.read_text("utf-8").strip()

    async def analyze(
        self,
        *,
        analysis: AnalysisJob,
        video: Video,
        evidence: MediaEvidence,
    ) -> SegmentationOutcome:
        segmentation = evidence.segmentation
        if segmentation is None:
            raise ValueError("媒体证据缺少分镜候选元数据")
        if not segmentation.candidates:
            fallback = segmentation.model_copy(
                update={"fallback_reason": "程序没有检测到可审核的内部边界候选"}
            )
            return await self._outcome(analysis, fallback, [])
        if analysis.model_plan is None:
            return await self._outcome(analysis, segmentation, [])
        targets = analysis.model_plan.targets_for(ModelTask.SHOT_SEGMENTATION)
        if not targets:
            return await self._outcome(
                analysis,
                segmentation,
                ["模型计划没有 shot_segmentation 路由，已采用程序硬切边界"],
            )
        if analysis.model_plan.pricing_version != self.price_catalog.catalog_version:
            return await self._outcome(
                analysis,
                segmentation,
                ["模型计划价格版本不匹配，分镜语义确认已在调用前停止"],
            )

        image_paths = _image_paths(analysis, segmentation)
        expected_image_count = len(segmentation.candidates) + 1
        if len(image_paths) != expected_image_count:
            return await self._outcome(
                analysis,
                segmentation,
                ["分镜候选图片不完整，已采用程序硬切边界"],
            )
        user_prompt = _user_prompt(segmentation, evidence.metadata.duration_seconds)
        warnings: list[str] = []
        previous_run_id: UUID | None = None
        attempt_number = 0

        for target in targets:
            fingerprint = await _request_fingerprint(
                video=video,
                segmentation=segmentation,
                image_paths=image_paths,
                target=target,
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
            )
            cached = await self.repository.find_completed_model_run(fingerprint)
            if cached and cached.result_payload:
                try:
                    selection = ShotSegmentationSelection.model_validate(cached.result_payload)
                    verified = apply_model_selection(
                        segmentation,
                        selection,
                        evidence.metadata.duration_seconds,
                    )
                except (ValidationError, ValueError):
                    pass
                else:
                    cached_run = ModelRun(
                        analysis_id=analysis.id,
                        video_id=video.id,
                        task=ModelTask.SHOT_SEGMENTATION,
                        provider=target.provider,
                        requested_model=target.model,
                        resolved_model=cached.resolved_model,
                        prompt_version=target.prompt_version,
                        schema_version=target.schema_version,
                        request_fingerprint=fingerprint,
                        cache_source_run_id=cached.id,
                        status=ModelRunStatus.CACHED,
                        usage=ModelUsage(image_count=len(image_paths)),
                        result_payload=selection.model_dump(mode="json"),
                        completed_at=_utc_now(),
                    )
                    await self.repository.save_model_run(cached_run)
                    return await self._outcome(analysis, verified, warnings)

            for _ in range(self.max_attempts):
                attempt_number += 1
                estimated_usage = ModelUsage(
                    input_tokens=(
                        estimate_text_tokens(self.system_prompt + user_prompt)
                        + estimate_visual_tokens(
                            image_count=len(image_paths),
                            width=640,
                            height=360,
                        )
                    ),
                    output_tokens=DEFAULT_OUTPUT_TOKEN_ESTIMATE,
                    image_count=len(image_paths),
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
                    return await self._outcome(analysis, segmentation, warnings)
                estimated_cost = calculate_cost_micros(estimated_usage, estimated_price)
                existing_runs = await self.repository.list_model_runs(analysis.id)
                committed_cost = committed_model_cost_micros(existing_runs)
                if (
                    analysis.max_cost_micros is not None
                    and committed_cost + estimated_cost > analysis.max_cost_micros
                ):
                    blocked = ModelRun(
                        analysis_id=analysis.id,
                        video_id=video.id,
                        task=ModelTask.SHOT_SEGMENTATION,
                        attempt=attempt_number,
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
                        error_message="分镜语义确认将超过任务成本上限",
                        completed_at=_utc_now(),
                    )
                    await self.repository.save_price_snapshot(estimated_price)
                    await self.repository.save_model_run(blocked)
                    warnings.append("分镜语义确认已被成本上限阻止，保留程序硬切边界")
                    return await self._outcome(analysis, segmentation, warnings)

                run = ModelRun(
                    analysis_id=analysis.id,
                    video_id=video.id,
                    task=ModelTask.SHOT_SEGMENTATION,
                    attempt=attempt_number,
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
                analysis.estimated_cost_micros = committed_cost + estimated_cost
                await self.repository.save_analysis(analysis)

                try:
                    provider = self.router.provider_for(target)
                    result = await provider.generate(
                        ModelRequest(
                            task=ModelTask.SHOT_SEGMENTATION,
                            target=target,
                            system_prompt=self.system_prompt,
                            user_prompt=user_prompt,
                            image_paths=image_paths,
                            image_labels=_image_labels(segmentation),
                        ),
                        ShotSegmentationSelection,
                    )
                    measured_price = self._measured_price(
                        target.provider,
                        target.model,
                        result.resolved_model,
                        result.usage,
                    )
                    measured_cost = calculate_cost_micros(result.usage, measured_price)
                    await self.repository.save_price_snapshot(measured_price)
                    try:
                        verified = apply_model_selection(
                            segmentation,
                            result.data,
                            evidence.metadata.duration_seconds,
                        )
                    except ValueError as exc:
                        run.status = ModelRunStatus.FAILED
                        run.error_code = "segmentation_selection_invalid"
                        run.error_message = _safe_error_message(exc)
                        warnings.append(f"模型分镜结果无效：{exc}；已采用程序硬切边界")
                    else:
                        run.status = ModelRunStatus.COMPLETED
                        run.result_payload = result.data.model_dump(mode="json")
                    run.resolved_model = result.resolved_model
                    run.provider_request_id = result.provider_request_id
                    run.usage = result.usage
                    run.price_snapshot_id = measured_price.id
                    run.measured_cost_micros = measured_cost
                    run.latency_ms = result.latency_ms
                    run.raw_response_ref = await self._save_artifact(
                        analysis,
                        run.id,
                        provider=target.provider,
                        model=result.resolved_model,
                        usage=result.usage,
                        result_payload=result.data.model_dump(mode="json"),
                        raw_content=result.raw_content,
                        status=run.status.value,
                    )
                    run.completed_at = _utc_now()
                    await self.repository.save_model_run(run)
                    analysis.measured_cost_micros += measured_cost
                    await self.repository.save_analysis(analysis)
                    if run.status == ModelRunStatus.COMPLETED:
                        return await self._outcome(analysis, verified, warnings)
                    return await self._outcome(analysis, segmentation, warnings)
                except ModelProviderError as exc:
                    run.status = ModelRunStatus.FAILED
                    run.provider_request_id = exc.provider_request_id
                    run.resolved_model = exc.resolved_model
                    run.latency_ms = exc.latency_ms
                    run.error_code = exc.code
                    run.error_message = _safe_error_message(exc)
                    run.completed_at = _utc_now()
                    if exc.usage is not None:
                        try:
                            failure_price = self._measured_price(
                                target.provider,
                                target.model,
                                exc.resolved_model or target.model,
                                exc.usage,
                            )
                        except PriceCatalogError as price_error:
                            warnings.append(f"失败调用无法计费：{price_error}")
                        else:
                            await self.repository.save_price_snapshot(failure_price)
                            run.usage = exc.usage
                            run.price_snapshot_id = failure_price.id
                            run.measured_cost_micros = calculate_cost_micros(
                                exc.usage,
                                failure_price,
                            )
                    if exc.raw_content:
                        run.raw_response_ref = await self._save_artifact(
                            analysis,
                            run.id,
                            provider=target.provider,
                            model=exc.resolved_model or target.model,
                            usage=exc.usage,
                            result_payload=None,
                            raw_content=exc.raw_content,
                            status="failed",
                        )
                    await self.repository.save_model_run(run)
                    if run.measured_cost_micros:
                        analysis.measured_cost_micros += run.measured_cost_micros
                        await self.repository.save_analysis(analysis)
                    previous_run_id = run.id
                    if isinstance(exc, ModelProviderUnavailable) or not exc.retryable:
                        warnings.append(f"分镜语义确认不可用：{exc}；已采用程序硬切边界")
                        return await self._outcome(analysis, segmentation, warnings)
                except Exception as exc:  # pragma: no cover - provider safety boundary
                    run.status = ModelRunStatus.FAILED
                    run.error_code = "model_call_failed"
                    run.error_message = _safe_error_message(exc)
                    run.completed_at = _utc_now()
                    await self.repository.save_model_run(run)
                    previous_run_id = run.id

        warnings.append("分镜语义确认失败，已采用程序硬切边界")
        return await self._outcome(analysis, segmentation, list(dict.fromkeys(warnings)))

    def _measured_price(
        self,
        provider: str,
        requested_model: str,
        resolved_model: str,
        usage: ModelUsage,
    ) -> PriceSnapshot:
        try:
            return self.price_catalog.snapshot_for(
                provider,
                resolved_model,
                usage.input_tokens,
            )
        except PriceCatalogError:
            return self.price_catalog.snapshot_for(
                provider,
                requested_model,
                usage.input_tokens,
            )

    async def _outcome(
        self,
        analysis: AnalysisJob,
        segmentation: SegmentationMetadata,
        warnings: list[str],
    ) -> SegmentationOutcome:
        if warnings and not segmentation.verified_by_model:
            segmentation = segmentation.model_copy(update={"fallback_reason": warnings[0][:500]})
        runs = await self.repository.list_model_runs(analysis.id)
        analysis.estimated_cost_micros = committed_model_cost_micros(runs)
        summary = summarize_model_runs(
            analysis.id,
            runs,
            estimated_cost_micros=analysis.estimated_cost_micros,
        )
        analysis.measured_cost_micros = summary.measured_cost_micros
        await self.repository.save_analysis(analysis)
        return SegmentationOutcome(
            segmentation=segmentation,
            warnings=list(dict.fromkeys(warnings)),
            cost_summary=summary,
        )

    async def _save_artifact(
        self,
        analysis: AnalysisJob,
        run_id: UUID,
        *,
        provider: str,
        model: str,
        usage: ModelUsage | None,
        result_payload: dict | None,
        raw_content: str,
        status: str,
    ) -> str:
        relative = f"model-runs/{run_id}.json"
        output_path = get_analysis_artifact_root(analysis.id, analysis.record_id) / relative
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "model": model,
            "status": status,
            "usage": usage.model_dump(mode="json") if usage else None,
            "result": result_payload,
            "raw_content": raw_content,
        }
        await asyncio.to_thread(
            output_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        return artifact_url(analysis.id, relative)
