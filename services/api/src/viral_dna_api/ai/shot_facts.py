from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from ..media import artifact_url, get_analysis_artifact_root
from ..models import (
    AnalysisCostSummary,
    AnalysisJob,
    EvidenceTimeline,
    MediaEvidence,
    ModelRun,
    ModelRunStatus,
    ModelTask,
    ModelUsage,
    PriceSnapshot,
    ShotEvidence,
    ShotTimelineEvidence,
    ShotVisualFacts,
    Video,
)
from .billing import (
    PriceCatalog,
    PriceCatalogError,
    calculate_cost_micros,
    estimate_text_tokens,
    estimate_visual_tokens,
    summarize_model_runs,
)
from .contracts import ModelProviderError, ModelProviderUnavailable, ModelRequest
from .router import ModelRouter

ProgressCallback = Callable[[int, int, str], Awaitable[None]]
SHOT_FACTS_PROMPT_PATH = Path(__file__).with_name("prompts") / "shot_facts_v1.md"
DEFAULT_OUTPUT_TOKEN_ESTIMATE = 2400


class ModelRunRepository(Protocol):
    async def save_model_run(self, run: ModelRun) -> ModelRun: ...

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]: ...

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None: ...

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...


@dataclass(frozen=True, slots=True)
class ShotFactsOutcome:
    facts: dict[str, ShotVisualFacts]
    warnings: list[str]
    cost_summary: AnalysisCostSummary


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_error_message(error: Exception) -> str:
    message = " ".join(str(error).replace("\x00", "").split())
    return message[:500] or type(error).__name__


def _clip(value: str | None, limit: int) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned[:limit] or "无"


def _artifact_path(
    analysis_id: UUID,
    url: str,
    record_id: UUID | None = None,
) -> Path | None:
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


def _frame_paths(
    analysis_id: UUID,
    shot: ShotEvidence,
    record_id: UUID | None = None,
) -> tuple[Path, ...]:
    urls = shot.evidence_frame_urls or [shot.keyframe_url]
    paths = [
        path for url in urls if (path := _artifact_path(analysis_id, url, record_id)) is not None
    ]
    if not paths:
        keyframe = _artifact_path(analysis_id, shot.keyframe_url, record_id)
        if keyframe is not None:
            paths.append(keyframe)
    return tuple(dict.fromkeys(paths))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _request_fingerprint(
    *,
    video: Video,
    shot: ShotEvidence,
    timeline: ShotTimelineEvidence,
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
        "shot_id": shot.shot_id,
        "start_seconds": shot.start_seconds,
        "end_seconds": shot.end_seconds,
        "transcript": timeline.transcript_text,
        "subtitle": timeline.subtitle_text,
        "ocr": timeline.ocr_text,
        "image_hashes": image_hashes,
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


def _user_prompt(
    shot: ShotEvidence,
    timeline: ShotTimelineEvidence,
    previous: ShotVisualFacts | None,
) -> str:
    schema = json.dumps(ShotVisualFacts.model_json_schema(), ensure_ascii=False)
    previous_text = (
        f"上一镜头：{previous.title}；场景：{previous.scene}；动作：{previous.action}"
        if previous
        else "这是第一个镜头，没有上一镜头。"
    )
    return (
        "请分析当前短视频镜头。输入图片按时间顺序排列，通常为开始帧、中间帧、结束帧。\n"
        f"镜头编号：{shot.shot_id}\n"
        f"时间范围：{shot.start_seconds:.3f}s - {shot.end_seconds:.3f}s\n"
        f"镜头持续：{shot.duration_seconds:.3f}s\n"
        f"ASR 对白：{_clip(timeline.transcript_text, 4000)}\n"
        f"独立字幕：{_clip(timeline.subtitle_text, 4000)}\n"
        f"画面 OCR：{_clip(timeline.ocr_text, 6000)}\n"
        f"{previous_text}\n"
        "请严格输出符合以下 JSON Schema 的 JSON 对象，不要输出其他内容：\n"
        f"{schema}"
    )


class ShotFactsService:
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
        self.system_prompt = SHOT_FACTS_PROMPT_PATH.read_text("utf-8").strip()

    async def analyze(
        self,
        *,
        analysis: AnalysisJob,
        video: Video,
        evidence: MediaEvidence,
        timeline: EvidenceTimeline,
        progress: ProgressCallback | None = None,
    ) -> ShotFactsOutcome:
        if analysis.model_plan is None:
            return await self._outcome(analysis, {}, [])
        targets = analysis.model_plan.targets_for(ModelTask.SHOT_FACTS)
        if not targets:
            return await self._outcome(analysis, {}, ["模型计划没有 shot_facts 路由"])
        if analysis.model_plan.pricing_version != self.price_catalog.catalog_version:
            return await self._outcome(
                analysis,
                {},
                ["模型计划冻结的价格版本与当前价格目录不一致，已在调用前停止"],
            )

        timeline_by_shot = {shot.shot_id: shot for shot in timeline.shots}
        facts: dict[str, ShotVisualFacts] = {}
        warnings: list[str] = []
        previous: ShotVisualFacts | None = None
        budget_exhausted = False

        for position, shot in enumerate(evidence.shots, 1):
            if budget_exhausted:
                break
            if progress:
                await progress(
                    position, len(evidence.shots), f"正在理解镜头 {position}/{len(evidence.shots)}"
                )
            shot_timeline = timeline_by_shot[shot.shot_id]
            image_paths = _frame_paths(analysis.id, shot, analysis.record_id)
            if not image_paths:
                warnings.append(f"{shot.shot_id} 没有可供 VLM 分析的关键帧")
                continue
            estimated_frame_width = min(640, evidence.metadata.width)
            estimated_frame_height = round(
                evidence.metadata.height * estimated_frame_width / evidence.metadata.width
            )
            user_prompt = _user_prompt(shot, shot_timeline, previous)

            shot_result: ShotVisualFacts | None = None
            previous_run_id: UUID | None = None
            attempt_number = 0
            for target in targets:
                fingerprint = await _request_fingerprint(
                    video=video,
                    shot=shot,
                    timeline=shot_timeline,
                    image_paths=image_paths,
                    target=target,
                    system_prompt=self.system_prompt,
                    user_prompt=user_prompt,
                )
                cached = await self.repository.find_completed_model_run(fingerprint)
                if cached and cached.result_payload:
                    try:
                        shot_result = ShotVisualFacts.model_validate(cached.result_payload)
                    except ValidationError:
                        shot_result = None
                    else:
                        cached_run = ModelRun(
                            analysis_id=analysis.id,
                            video_id=video.id,
                            task=ModelTask.SHOT_FACTS,
                            shot_id=shot.shot_id,
                            provider=target.provider,
                            requested_model=target.model,
                            resolved_model=cached.resolved_model,
                            prompt_version=target.prompt_version,
                            schema_version=target.schema_version,
                            request_fingerprint=fingerprint,
                            cache_source_run_id=cached.id,
                            status=ModelRunStatus.CACHED,
                            usage=ModelUsage(image_count=len(image_paths)),
                            result_payload=shot_result.model_dump(mode="json"),
                            completed_at=_utc_now(),
                        )
                        await self.repository.save_model_run(cached_run)
                        break

                for _ in range(self.max_attempts):
                    attempt_number += 1
                    estimated_usage = ModelUsage(
                        input_tokens=(
                            estimate_text_tokens(self.system_prompt + user_prompt)
                            + estimate_visual_tokens(
                                image_count=len(image_paths),
                                width=estimated_frame_width,
                                height=estimated_frame_height,
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
                        budget_exhausted = True
                        break
                    estimated_cost = calculate_cost_micros(estimated_usage, estimated_price)
                    if (
                        analysis.max_cost_micros is not None
                        and analysis.estimated_cost_micros + estimated_cost
                        > analysis.max_cost_micros
                    ):
                        blocked = ModelRun(
                            analysis_id=analysis.id,
                            video_id=video.id,
                            task=ModelTask.SHOT_FACTS,
                            shot_id=shot.shot_id,
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
                            error_message="下一次模型调用将超过任务成本上限",
                            completed_at=_utc_now(),
                        )
                        await self.repository.save_price_snapshot(estimated_price)
                        await self.repository.save_model_run(blocked)
                        warnings.append("模型分析已在发起调用前被成本上限阻止")
                        budget_exhausted = True
                        break

                    run = ModelRun(
                        analysis_id=analysis.id,
                        video_id=video.id,
                        task=ModelTask.SHOT_FACTS,
                        shot_id=shot.shot_id,
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
                    analysis.estimated_cost_micros += estimated_cost
                    await self.repository.save_analysis(analysis)

                    try:
                        provider = self.router.provider_for(target)
                        result = await provider.generate(
                            ModelRequest(
                                task=ModelTask.SHOT_FACTS,
                                target=target,
                                system_prompt=self.system_prompt,
                                user_prompt=user_prompt,
                                image_paths=image_paths,
                            ),
                            ShotVisualFacts,
                        )
                        try:
                            measured_price = self.price_catalog.snapshot_for(
                                target.provider,
                                result.resolved_model,
                                result.usage.input_tokens,
                            )
                        except PriceCatalogError:
                            measured_price = self.price_catalog.snapshot_for(
                                target.provider,
                                target.model,
                                result.usage.input_tokens,
                            )
                        measured_cost = calculate_cost_micros(result.usage, measured_price)
                        await self.repository.save_price_snapshot(measured_price)
                        artifact_ref = await self._save_result_artifact(
                            analysis.id,
                            run.id,
                            result.data,
                            result.usage,
                            target.provider,
                            result.resolved_model,
                            record_id=analysis.record_id,
                        )
                        run.resolved_model = result.resolved_model
                        run.provider_request_id = result.provider_request_id
                        run.status = ModelRunStatus.COMPLETED
                        run.usage = result.usage
                        run.price_snapshot_id = measured_price.id
                        run.measured_cost_micros = measured_cost
                        run.latency_ms = result.latency_ms
                        run.raw_response_ref = artifact_ref
                        run.result_payload = result.data.model_dump(mode="json")
                        run.completed_at = _utc_now()
                        await self.repository.save_model_run(run)
                        analysis.measured_cost_micros += measured_cost
                        await self.repository.save_analysis(analysis)
                        shot_result = result.data
                        break
                    except ModelProviderError as exc:
                        run.status = ModelRunStatus.FAILED
                        run.provider_request_id = exc.provider_request_id
                        run.resolved_model = exc.resolved_model
                        run.latency_ms = exc.latency_ms
                        run.error_code = exc.code
                        run.error_message = _safe_error_message(exc)
                        run.completed_at = _utc_now()
                        if exc.usage is not None:
                            run.usage = exc.usage
                            try:
                                failure_price = self.price_catalog.snapshot_for(
                                    target.provider,
                                    exc.resolved_model or target.model,
                                    exc.usage.input_tokens,
                                )
                            except PriceCatalogError:
                                try:
                                    failure_price = self.price_catalog.snapshot_for(
                                        target.provider,
                                        target.model,
                                        exc.usage.input_tokens,
                                    )
                                except PriceCatalogError as price_error:
                                    warnings.append(
                                        f"{shot.shot_id} 的失败调用无法计费：{price_error}"
                                    )
                                else:
                                    await self.repository.save_price_snapshot(failure_price)
                                    run.price_snapshot_id = failure_price.id
                                    run.measured_cost_micros = calculate_cost_micros(
                                        exc.usage, failure_price
                                    )
                            else:
                                await self.repository.save_price_snapshot(failure_price)
                                run.price_snapshot_id = failure_price.id
                                run.measured_cost_micros = calculate_cost_micros(
                                    exc.usage, failure_price
                                )
                        if exc.raw_content:
                            run.raw_response_ref = await self._save_failure_artifact(
                                analysis.id,
                                run.id,
                                record_id=analysis.record_id,
                                provider=target.provider,
                                model=exc.resolved_model or target.model,
                                usage=exc.usage,
                                error_code=exc.code,
                                error_message=run.error_message,
                                raw_content=exc.raw_content,
                            )
                        await self.repository.save_model_run(run)
                        if run.measured_cost_micros:
                            analysis.measured_cost_micros += run.measured_cost_micros
                            await self.repository.save_analysis(analysis)
                        previous_run_id = run.id
                        if isinstance(exc, ModelProviderUnavailable):
                            warnings.append(str(exc))
                            budget_exhausted = True
                            break
                        if not exc.retryable:
                            warnings.append(f"{shot.shot_id} 的模型调用不可重试：{exc}")
                            budget_exhausted = True
                            break
                    except Exception as exc:  # pragma: no cover - provider safety boundary
                        run.status = ModelRunStatus.FAILED
                        run.error_code = "model_call_failed"
                        run.error_message = _safe_error_message(exc)
                        run.completed_at = _utc_now()
                        await self.repository.save_model_run(run)
                        previous_run_id = run.id
                        break
                if shot_result is not None or budget_exhausted:
                    break

            if shot_result is None:
                if not budget_exhausted:
                    warnings.append(f"{shot.shot_id} 的 VLM 分析失败，已保留媒体证据结果")
                continue
            facts[shot.shot_id] = shot_result
            if shot_result.contains_multiple_scenes:
                reason = shot_result.multiple_scenes_reason or "关键帧存在跨场景迹象"
                warnings.append(f"{shot.shot_id} 仍可能包含多个语义场景：{reason}")
            previous = shot_result

        return await self._outcome(analysis, facts, list(dict.fromkeys(warnings)))

    async def _outcome(
        self,
        analysis: AnalysisJob,
        facts: dict[str, ShotVisualFacts],
        warnings: list[str],
    ) -> ShotFactsOutcome:
        runs = await self.repository.list_model_runs(analysis.id)
        summary = summarize_model_runs(
            analysis.id,
            runs,
            estimated_cost_micros=analysis.estimated_cost_micros,
        )
        analysis.measured_cost_micros = summary.measured_cost_micros
        await self.repository.save_analysis(analysis)
        return ShotFactsOutcome(facts=facts, warnings=warnings, cost_summary=summary)

    async def _save_result_artifact(
        self,
        analysis_id: UUID,
        run_id: UUID,
        facts: ShotVisualFacts,
        usage: ModelUsage,
        provider: str,
        model: str,
        *,
        record_id: UUID | None = None,
    ) -> str:
        relative = f"model-runs/{run_id}.json"
        output_path = get_analysis_artifact_root(analysis_id, record_id) / relative
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "model": model,
            "usage": usage.model_dump(mode="json"),
            "result": facts.model_dump(mode="json"),
        }
        await asyncio.to_thread(
            output_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        return artifact_url(analysis_id, relative)

    async def _save_failure_artifact(
        self,
        analysis_id: UUID,
        run_id: UUID,
        *,
        record_id: UUID | None = None,
        provider: str,
        model: str,
        usage: ModelUsage | None,
        error_code: str,
        error_message: str,
        raw_content: str,
    ) -> str:
        relative = f"model-runs/{run_id}.json"
        output_path = get_analysis_artifact_root(analysis_id, record_id) / relative
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "model": model,
            "status": "failed",
            "usage": usage.model_dump(mode="json") if usage else None,
            "error": {"code": error_code, "message": error_message},
            "raw_content": raw_content,
        }
        await asyncio.to_thread(
            output_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        return artifact_url(analysis_id, relative)
