from __future__ import annotations

import asyncio
import hashlib
import json
import math
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
    ShotMotionPhaseFact,
    ShotTimelineEvidence,
    ShotTransitionFact,
    ShotVisualBeatFact,
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
SHOT_FACTS_PROMPT_PATH = Path(__file__).with_name("prompts") / "shot_facts_v2.md"
DEFAULT_OUTPUT_TOKEN_ESTIMATE = 3600
MIN_NATIVE_VIDEO_SECONDS = 2.0
MAX_INLINE_VIDEO_BYTES = 7_000_000


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


def _motion_frame_paths(
    analysis_id: UUID,
    shot: ShotEvidence,
    record_id: UUID | None = None,
) -> tuple[Path, ...]:
    urls = shot.motion_frame_urls or shot.evidence_frame_urls or [shot.keyframe_url]
    return tuple(
        dict.fromkeys(
            path
            for url in urls
            if (path := _artifact_path(analysis_id, url, record_id)) is not None
        )
    )


def _analysis_clip_path(
    analysis_id: UUID,
    shot: ShotEvidence,
    record_id: UUID | None = None,
) -> Path | None:
    if not shot.analysis_clip_url:
        return None
    path = _artifact_path(analysis_id, shot.analysis_clip_url, record_id)
    if path is None or path.suffix.lower() != ".mp4":
        return None
    duration = _analysis_clip_duration(shot)
    if duration < MIN_NATIVE_VIDEO_SECONDS or path.stat().st_size > MAX_INLINE_VIDEO_BYTES:
        return None
    return path


def _analysis_clip_duration(shot: ShotEvidence) -> float:
    start = (
        shot.analysis_clip_start_seconds
        if shot.analysis_clip_start_seconds is not None
        else shot.content_start_seconds
        if shot.content_start_seconds is not None
        else shot.start_seconds
    )
    end = (
        shot.analysis_clip_end_seconds
        if shot.analysis_clip_end_seconds is not None
        else shot.content_end_seconds
        if shot.content_end_seconds is not None
        else shot.end_seconds
    )
    return max(0.0, float(end) - float(start))


def _analysis_video_fps(duration_seconds: float) -> float:
    if duration_seconds <= 6:
        return 6.0
    if duration_seconds <= 15:
        return 4.0
    return 2.0


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
    video_path: Path | None,
    video_fps: float,
    target,
    system_prompt: str,
    user_prompt: str,
) -> str:
    image_hashes = await asyncio.gather(
        *(asyncio.to_thread(_file_sha256, path) for path in image_paths)
    )
    video_hash = await asyncio.to_thread(_file_sha256, video_path) if video_path else None
    payload = {
        "video_sha256": video.sha256,
        "shot_id": shot.shot_id,
        "start_seconds": shot.start_seconds,
        "end_seconds": shot.end_seconds,
        "transcript": timeline.transcript_text,
        "subtitle": timeline.subtitle_text,
        "ocr": timeline.ocr_text,
        "image_hashes": image_hashes,
        "video_hash": video_hash,
        "video_fps": video_fps if video_path else None,
        "input_mode": "video" if video_path else "dense_frames",
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
    *,
    uses_native_video: bool,
) -> str:
    schema = json.dumps(ShotVisualFacts.model_json_schema(), ensure_ascii=False)
    content_start = (
        shot.content_start_seconds
        if shot.content_start_seconds is not None
        else shot.start_seconds
    )
    content_end = (
        shot.content_end_seconds
        if shot.content_end_seconds is not None
        else shot.end_seconds
    )
    evidence_timestamps = ", ".join(
        f"{value:.3f}s" for value in (shot.motion_timestamps or shot.evidence_timestamps)
    ) or "未记录"
    analysis_start = (
        shot.analysis_clip_start_seconds
        if shot.analysis_clip_start_seconds is not None
        else content_start
    )
    analysis_end = (
        shot.analysis_clip_end_seconds
        if shot.analysis_clip_end_seconds is not None
        else content_end
    )
    if (
        shot.outgoing_transition_start_seconds is not None
        and shot.outgoing_transition_end_seconds is not None
    ):
        transition_window = (
            f"{shot.outgoing_transition_start_seconds:.3f}s - "
            f"{shot.outgoing_transition_end_seconds:.3f}s"
        )
    else:
        transition_window = "无独立出场转场窗口"
    input_kind = "连续视频片段" if uses_native_video else "带绝对时间标签的密集序列帧"
    return (
        "请分析当前镜头的有效内容、连续运动和出场转场。"
        "主体、场景和 visual_beats 只能来自有效内容范围；"
        "outgoing_transition 允许描述出场转场窗口内如何接入下一镜头，"
        "但不得把下一镜头写成当前镜头的额外画面。\n"
        f"镜头编号：{shot.shot_id}\n"
        f"剪辑时间范围：{shot.start_seconds:.3f}s - {shot.end_seconds:.3f}s\n"
        f"有效内容范围：{content_start:.3f}s - {content_end:.3f}s\n"
        f"出场转场范围：{transition_window}\n"
        f"分析片段绝对范围：{analysis_start:.3f}s - {analysis_end:.3f}s\n"
        f"输入形式：{input_kind}\n"
        f"序列帧绝对时间（仅降级模式使用）：{evidence_timestamps}\n"
        f"镜头持续：{shot.duration_seconds:.3f}s\n"
        f"ASR 对白：{_clip(timeline.transcript_text, 4000)}\n"
        f"独立字幕：{_clip(timeline.subtitle_text, 4000)}\n"
        f"画面 OCR：{_clip(timeline.ocr_text, 6000)}\n"
        "请严格输出符合以下 JSON Schema 的 JSON 对象，不要输出其他内容：\n"
        f"{schema}"
    )


def _normalize_visual_beats(
    shot: ShotEvidence,
    facts: ShotVisualFacts,
) -> ShotVisualFacts:
    """Keep structured visual facts inside the clean content interval."""

    content_start = float(
        shot.content_start_seconds
        if shot.content_start_seconds is not None
        else shot.start_seconds
    )
    content_end = float(
        shot.content_end_seconds
        if shot.content_end_seconds is not None
        else shot.end_seconds
    )
    uses_relative_timing = _ranges_are_clip_relative(
        [(float(beat.start_seconds), float(beat.end_seconds)) for beat in facts.visual_beats],
        content_start=content_start,
        content_end=content_end,
    )
    normalized: list[ShotVisualBeatFact] = []
    for beat in sorted(facts.visual_beats, key=lambda item: (item.start_seconds, item.index)):
        offset = content_start if uses_relative_timing else 0.0
        start = max(content_start, float(beat.start_seconds) + offset)
        end = min(content_end, float(beat.end_seconds) + offset)
        if end - start < 0.01:
            continue
        source_timestamp = min(
            end,
            max(start, float(beat.source_timestamp_seconds) + offset),
        )
        normalized.append(
            beat.model_copy(
                update={
                    "index": len(normalized) + 1,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "source_timestamp_seconds": round(source_timestamp, 3),
                }
            )
        )
    if not normalized:
        source_timestamp = min(
            content_end,
            max(content_start, float(shot.representative_timestamp)),
        )
        normalized = [
            ShotVisualBeatFact(
                index=1,
                title="画面 1",
                start_seconds=round(content_start, 3),
                end_seconds=round(content_end, 3),
                source_timestamp_seconds=round(source_timestamp, 3),
                image_prompt=facts.replication_prompt,
            )
        ]
    return facts.model_copy(
        update={
            "visual_beats": normalized,
            "contains_multiple_scenes": len(normalized) > 1,
            "multiple_scenes_reason": (
                facts.multiple_scenes_reason if len(normalized) > 1 else None
            ),
        }
    )


def _ranges_are_clip_relative(
    ranges: list[tuple[float, float]],
    *,
    content_start: float,
    content_end: float,
) -> bool:
    """Detect a provider returning clip-local seconds despite the absolute-time contract."""

    if not ranges or content_start <= 0.05:
        return False
    duration = max(0.0, content_end - content_start)
    tolerance = max(0.25, duration * 0.05)
    return (
        any(start < content_start - tolerance for start, _ in ranges)
        and all(start >= -0.05 for start, _ in ranges)
        and all(end <= duration + tolerance for _, end in ranges)
    )


def _fallback_transition_text(kind: str) -> tuple[str, str]:
    descriptions = {
        "hard_cut": "当前镜头结束后直接切入下一镜头",
        "crossfade": "当前镜头逐渐淡出并与下一镜头叠化",
        "foreground_occlusion": "前景物逐渐靠近并遮满镜头，作为进入下一镜头的遮罩",
        "wipe": "画面中的移动边缘横向扫过镜头并完成转场",
        "whip_pan": "镜头快速甩动形成运动模糊并进入下一镜头",
        "match_cut": "利用主体位置、形状或动作连续性匹配切入下一镜头",
        "other": "当前镜头通过可见的连续画面变化进入下一镜头",
        "uncertain": "检测到出场转场窗口，但具体转场方式暂不能可靠判定",
    }
    description = descriptions.get(kind, descriptions["uncertain"])
    return description, description


def _normalize_motion_facts(
    shot: ShotEvidence,
    facts: ShotVisualFacts,
) -> ShotVisualFacts:
    content_start = float(
        shot.content_start_seconds
        if shot.content_start_seconds is not None
        else shot.start_seconds
    )
    content_end = float(
        shot.content_end_seconds
        if shot.content_end_seconds is not None
        else shot.end_seconds
    )
    uses_relative_timing = _ranges_are_clip_relative(
        [(float(phase.start_seconds), float(phase.end_seconds)) for phase in facts.motion_phases],
        content_start=content_start,
        content_end=content_end,
    )
    phases: list[ShotMotionPhaseFact] = []
    for phase in sorted(facts.motion_phases, key=lambda item: (item.start_seconds, item.index)):
        offset = content_start if uses_relative_timing else 0.0
        start = max(content_start, float(phase.start_seconds) + offset)
        end = min(content_end, float(phase.end_seconds) + offset)
        if end - start < 0.01:
            continue
        phases.append(
            phase.model_copy(
                update={
                    "index": len(phases) + 1,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                }
            )
        )
    if not phases:
        phases = [
            ShotMotionPhaseFact(
                index=1,
                start_seconds=round(content_start, 3),
                end_seconds=round(content_end, 3),
                description=facts.camera,
                camera_motion=facts.camera,
                subject_motion=facts.action,
                confidence=max(0.2, facts.motion_confidence or facts.confidence * 0.6),
            )
        ]

    transition = facts.outgoing_transition
    transition_start = shot.outgoing_transition_start_seconds
    transition_end = shot.outgoing_transition_end_seconds
    if transition_start is None or transition_end is None:
        transition = ShotTransitionFact(confidence=max(0.5, transition.confidence))
    elif transition.kind == "none":
        description, generation_prompt = _fallback_transition_text("uncertain")
        transition = transition.model_copy(
            update={
                "kind": "uncertain",
                "start_seconds": round(float(transition_start), 3),
                "end_seconds": round(float(transition_end), 3),
                "description": description,
                "generation_prompt": generation_prompt,
                "confidence": min(0.35, transition.confidence),
            }
        )
    else:
        description = transition.description
        generation_prompt = transition.generation_prompt
        if not description or description == "无出场转场":
            description, fallback_prompt = _fallback_transition_text(transition.kind)
            generation_prompt = generation_prompt or fallback_prompt
        transition = transition.model_copy(
            update={
                "start_seconds": round(float(transition_start), 3),
                "end_seconds": round(float(transition_end), 3),
                "description": description,
                "generation_prompt": generation_prompt,
            }
        )

    prompt = facts.replication_prompt.split("。时序运镜：", 1)[0]
    if facts.continuous_take:
        prompt = prompt.replace("随后画面切换为", "随后镜头连续推进至")
        prompt = prompt.replace("硬切", "连续过渡")
    phase_prompt = "；".join(
        f"{phase.start_seconds:g}-{phase.end_seconds:g}秒：{phase.description.rstrip('。；')}"
        for phase in phases
    )
    transition_prompt = transition.generation_prompt or transition.description
    compiled = f"{prompt.rstrip('。；')}。时序运镜：{phase_prompt}。"
    if transition.kind != "none" and transition_prompt:
        compiled += f"出场转场：{transition_prompt.rstrip('。；')}。"
    compiled = compiled[:4000]
    transition_summary = transition.description if transition.kind != "none" else facts.transition
    return facts.model_copy(
        update={
            "motion_phases": phases,
            "outgoing_transition": transition,
            "replication_prompt": compiled,
            "transition": transition_summary,
        }
    )


def _normalize_shot_facts(shot: ShotEvidence, facts: ShotVisualFacts) -> ShotVisualFacts:
    return _normalize_motion_facts(shot, _normalize_visual_beats(shot, facts))


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
        budget_exhausted = False

        for position, shot in enumerate(evidence.shots, 1):
            if budget_exhausted:
                break
            if progress:
                await progress(
                    position, len(evidence.shots), f"正在理解镜头 {position}/{len(evidence.shots)}"
                )
            shot_timeline = timeline_by_shot[shot.shot_id]
            image_paths = _motion_frame_paths(analysis.id, shot, analysis.record_id)
            video_path = _analysis_clip_path(analysis.id, shot, analysis.record_id)
            video_duration = _analysis_clip_duration(shot) if video_path else 0.0
            video_fps = _analysis_video_fps(video_duration) if video_path else 0.0
            if not image_paths and video_path is None:
                warnings.append(f"{shot.shot_id} 没有可供 VLM 分析的视频或关键帧")
                continue
            estimated_frame_width = min(640, evidence.metadata.width)
            estimated_frame_height = round(
                evidence.metadata.height * estimated_frame_width / evidence.metadata.width
            )
            user_prompt = _user_prompt(
                shot,
                shot_timeline,
                uses_native_video=video_path is not None,
            )
            image_labels = tuple(
                f"绝对时间 {timestamp:.3f}s"
                for timestamp in (shot.motion_timestamps or shot.evidence_timestamps)
            )
            if len(image_labels) != len(image_paths):
                image_labels = ()
            visual_frame_count = (
                max(4, math.ceil(video_duration * video_fps))
                if video_path is not None
                else len(image_paths)
            )

            shot_result: ShotVisualFacts | None = None
            previous_run_id: UUID | None = None
            attempt_number = 0
            for target in targets:
                fingerprint = await _request_fingerprint(
                    video=video,
                    shot=shot,
                    timeline=shot_timeline,
                    image_paths=image_paths,
                    video_path=video_path,
                    video_fps=video_fps,
                    target=target,
                    system_prompt=self.system_prompt,
                    user_prompt=user_prompt,
                )
                cached = await self.repository.find_completed_model_run(fingerprint)
                if cached and cached.result_payload:
                    try:
                        shot_result = _normalize_shot_facts(
                            shot,
                            ShotVisualFacts.model_validate(cached.result_payload),
                        )
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
                            usage=ModelUsage(
                                image_count=0 if video_path is not None else len(image_paths),
                                video_seconds=video_duration,
                            ),
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
                                image_count=visual_frame_count,
                                width=estimated_frame_width,
                                height=estimated_frame_height,
                            )
                        ),
                        output_tokens=DEFAULT_OUTPUT_TOKEN_ESTIMATE,
                        image_count=0 if video_path is not None else len(image_paths),
                        video_seconds=video_duration,
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
                                image_labels=image_labels,
                                video_path=video_path,
                                video_fps=video_fps or 4.0,
                                video_duration_seconds=video_duration,
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
                        normalized_data = _normalize_shot_facts(shot, result.data)
                        artifact_ref = await self._save_result_artifact(
                            analysis.id,
                            run.id,
                            normalized_data,
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
                        run.result_payload = normalized_data.model_dump(mode="json")
                        run.completed_at = _utc_now()
                        await self.repository.save_model_run(run)
                        analysis.measured_cost_micros += measured_cost
                        await self.repository.save_analysis(analysis)
                        shot_result = normalized_data
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
