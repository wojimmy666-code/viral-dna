from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from .ai.shot_facts import ShotFactsOutcome, ShotFactsService
from .ai.shot_segmentation import SegmentationOutcome, ShotSegmentationService
from .evidence import EvidenceTimelineBuilder
from .link_ingestion import (
    LinkCollector,
    LinkCredentialResolver,
    LinkIngestionError,
    LinkIngestionResult,
)
from .media import MediaProcessingError, MediaProcessor
from .models import (
    AnalysisError,
    AnalysisJob,
    AnalysisMode,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
    EvidenceProviderStatus,
    EvidenceTimeline,
    MediaEvidence,
    ModelRun,
    PriceSnapshot,
    PromptPackage,
    PromptShot,
    Shot,
    ShotTransitionFact,
    ShotVisualFacts,
    SourceType,
    Video,
    VideoOverview,
    VideoStatus,
)
from .pipeline import SimulatedAnalysisPipeline
from .prompt_engine.compiler import compile_prompt_draft, draft_from_shot
from .records import (
    DEFAULT_LINK_RECORD_NAMES,
    normalize_record_name,
    resolve_record_name_from_video,
    resolve_video_path,
    write_source_metadata,
)
from .thumbnails import thumbnail_service
from .workspace import workspace_manager


def utc_now() -> datetime:
    return datetime.now(UTC)


class AnalysisRepository(Protocol):
    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...

    async def get_video(self, video_id: UUID) -> Video | None: ...

    async def save_video(self, video: Video) -> Video: ...

    async def get_record(self, record_id: UUID) -> AnalysisRecord | None: ...

    async def save_record(self, record: AnalysisRecord) -> AnalysisRecord: ...

    async def save_report(self, report: AnalysisReport) -> AnalysisReport: ...

    async def save_model_run(self, run: ModelRun) -> ModelRun: ...

    async def list_model_runs(self, analysis_id: UUID) -> list[ModelRun]: ...

    async def find_completed_model_run(self, request_fingerprint: str) -> ModelRun | None: ...

    async def save_price_snapshot(self, snapshot: PriceSnapshot) -> PriceSnapshot: ...


class HybridAnalysisPipeline:
    """Collects uploads and platform links before building real FFmpeg evidence."""

    def __init__(
        self,
        repository: AnalysisRepository,
        credential_resolver: LinkCredentialResolver | None = None,
    ) -> None:
        self.repository = repository
        self.credential_resolver = credential_resolver
        self.simulated = SimulatedAnalysisPipeline(repository)  # type: ignore[arg-type]
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self, analysis_id: UUID) -> None:
        task = asyncio.create_task(self.run(analysis_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self, analysis_id: UUID) -> None:
        analysis = await self.repository.get_analysis(analysis_id)
        if analysis is None:
            return
        video = await self.repository.get_video(analysis.video_id)
        if video is None:
            return

        if analysis.analysis_mode == AnalysisMode.SIMULATED:
            await self.simulated.run(analysis_id)
            return

        try:
            video.status = VideoStatus.ANALYZING
            await self.repository.save_video(video)

            async def progress(stage: AnalysisStage, value: int, message: str) -> None:
                analysis.stage = stage
                analysis.progress = value
                analysis.message = message
                analysis.updated_at = utc_now()
                await self.repository.save_analysis(analysis)

            is_link = video.source_type in {SourceType.DOUYIN, SourceType.XIAOHONGSHU}
            if is_link and not (video.stored_path or video.stored_relative_path):
                await progress(AnalysisStage.INGESTING, 3, "正在校验平台链接并读取视频信息")
                collected = await LinkCollector(self.credential_resolver).collect(video)
                self._apply_ingestion(video, collected)
                await self._sync_ingested_record_name(video)
                await self.repository.save_video(video)
                await write_source_metadata(video)
                await thumbnail_service.ensure(video)
                await progress(AnalysisStage.INGESTING, 24, "平台视频下载完成，正在准备媒体分析")

            if not (video.stored_path or video.stored_relative_path):
                raise MediaProcessingError(
                    "media_source_missing",
                    "视频没有可分析的本地媒体文件",
                )

            async def media_progress(
                stage: AnalysisStage,
                value: int,
                message: str,
            ) -> None:
                if is_link:
                    scaled_value = min(82, 24 + round(value * 0.72))
                    await progress(stage, scaled_value, message)
                else:
                    await progress(stage, value, message)

            processor = MediaProcessor()
            evidence = await processor.process(
                source_path=resolve_video_path(video),
                analysis_id=analysis.id,
                granularity=analysis.granularity,
                include_audio=analysis.include_audio,
                progress=media_progress,
                record_id=analysis.record_id,
            )
            self._apply_metadata(video, evidence)
            await self.repository.save_video(video)

            segmentation_outcome: SegmentationOutcome | None = None
            if analysis.model_plan is not None:
                await progress(
                    AnalysisStage.SEGMENTING,
                    76,
                    "正在使用 VLM 确认候选分镜边界",
                )
                segmentation_outcome = await ShotSegmentationService(self.repository).analyze(
                    analysis=analysis,
                    video=video,
                    evidence=evidence,
                )
                evidence = await processor.apply_segmentation(
                    evidence,
                    analysis.id,
                    segmentation_outcome.segmentation,
                    record_id=analysis.record_id,
                )

            await progress(AnalysisStage.TRANSCRIBING, 84, "正在运行 ASR/OCR 证据 Provider")
            timeline = await EvidenceTimelineBuilder.from_environment().build(
                analysis_id=analysis.id,
                evidence=evidence,
                include_audio=analysis.include_audio,
                include_ocr=analysis.include_ocr,
                record_id=analysis.record_id,
            )
            model_outcome: ShotFactsOutcome | None = None
            if analysis.model_plan is not None:
                await progress(AnalysisStage.UNDERSTANDING, 87, "正在启动逐镜头视觉理解")

                async def model_progress(current: int, total: int, message: str) -> None:
                    value = min(95, 87 + round(current / max(total, 1) * 8))
                    await progress(AnalysisStage.UNDERSTANDING, value, message)

                model_outcome = await ShotFactsService(self.repository).analyze(
                    analysis=analysis,
                    video=video,
                    evidence=evidence,
                    timeline=timeline,
                    progress=model_progress,
                )
            else:
                await progress(
                    AnalysisStage.UNDERSTANDING,
                    91,
                    "正在将语音和画面文字对齐到镜头；VLM 未启用",
                )
            await progress(AnalysisStage.VALIDATING, 96, "正在校验证据、模型结果与成本账本")
            self._apply_metadata(video, evidence)
            report = build_media_evidence_report(
                video,
                analysis,
                evidence,
                timeline,
                model_outcome=model_outcome,
                segmentation_outcome=segmentation_outcome,
            )
            if analysis.record_id is not None:
                await thumbnail_service.promote_from_report(analysis.record_id, report)
            await self.repository.save_report(report)

            analysis.stage = AnalysisStage.COMPLETED
            analysis.progress = 100
            analysis.message = _completion_message(
                is_link=is_link,
                timeline=timeline,
                model_outcome=model_outcome,
                segmentation_outcome=segmentation_outcome,
                vlm_configured=analysis.model_plan is not None,
            )
            analysis.updated_at = utc_now()
            analysis.completed_at = utc_now()
            await self.repository.save_analysis(analysis)

            video.status = VideoStatus.COMPLETED
            await self.repository.save_video(video)
        except LinkIngestionError as exc:
            await self._fail(
                analysis,
                video,
                exc.code,
                str(exc),
                exc.retryable,
                context="链接采集",
            )
        except MediaProcessingError as exc:
            await self._fail(analysis, video, exc.code, str(exc), exc.retryable)
        except Exception as exc:  # pragma: no cover - orchestration safety boundary
            await self._fail(analysis, video, "analysis_failed", str(exc), True, context="分析")

    async def _fail(
        self,
        analysis: AnalysisJob,
        video: Video,
        code: str,
        message: str,
        retryable: bool,
        context: str = "媒体处理",
    ) -> None:
        analysis.stage = AnalysisStage.FAILED
        analysis.progress = 100
        analysis.message = f"{context}失败：{message}"
        analysis.error = AnalysisError(code=code, message=message, retryable=retryable)
        analysis.updated_at = utc_now()
        analysis.completed_at = utc_now()
        await self.repository.save_analysis(analysis)
        video.status = VideoStatus.FAILED
        await self.repository.save_video(video)

    async def _sync_ingested_record_name(self, video: Video) -> None:
        if video.record_id is None:
            return
        record = await self.repository.get_record(video.record_id)
        if record is None:
            return
        resolved_name = resolve_record_name_from_video(record.name, video.title)
        video.title = resolved_name
        if resolved_name != record.name:
            record.name = resolved_name
            record.updated_at = utc_now()
            await self.repository.save_record(record)

    @staticmethod
    def _apply_ingestion(video: Video, result: LinkIngestionResult) -> None:
        video.stored_path = str(result.path)
        if video.record_id is not None:
            video.stored_relative_path = workspace_manager.relative(result.path)
        video.original_filename = result.path.name
        video.resolved_source_url = result.resolved_url
        video.source_video_id = result.source_video_id
        video.source_author = result.author
        video.ingested_at = utc_now()
        if result.duration_seconds is not None:
            video.duration_seconds = result.duration_seconds
        if result.title and normalize_record_name(video.title) in DEFAULT_LINK_RECORD_NAMES:
            video.title = normalize_record_name(result.title, fallback=video.title)

    @staticmethod
    def _apply_metadata(video: Video, evidence: MediaEvidence) -> None:
        metadata = evidence.metadata
        video.duration_seconds = metadata.duration_seconds
        video.width = metadata.width
        video.height = metadata.height
        video.fps = metadata.fps
        video.sha256 = metadata.sha256
        video.has_audio = metadata.has_audio
        video.video_codec = metadata.video_codec
        video.audio_codec = metadata.audio_codec


def build_media_evidence_report(
    video: Video,
    analysis: AnalysisJob,
    evidence: MediaEvidence,
    timeline: EvidenceTimeline,
    *,
    model_outcome: ShotFactsOutcome | None = None,
    segmentation_outcome: SegmentationOutcome | None = None,
) -> AnalysisReport:
    timeline_by_shot = {shot.shot_id: shot for shot in timeline.shots}
    visual_facts = model_outcome.facts if model_outcome else {}
    shots: list[Shot] = []
    for shot in evidence.shots:
        facts: ShotVisualFacts | None = visual_facts.get(shot.shot_id)
        shots.append(
            Shot(
                id=shot.shot_id,
                index=shot.index,
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
                content_start_seconds=shot.content_start_seconds,
                content_end_seconds=shot.content_end_seconds,
                title=facts.title if facts else f"镜头 {shot.index:02d}",
                subjects=facts.subjects if facts else [],
                action=facts.action if facts else "待多模态模型识别",
                scene=facts.scene if facts else "待多模态模型识别",
                camera=(
                    facts.camera if facts else f"真实镜头边界，持续 {shot.duration_seconds:.1f} 秒"
                ),
                composition=(facts.composition if facts else "已提取多时点关键帧，构图语义待分析"),
                lighting=facts.lighting if facts else "待多模态模型识别",
                color=facts.color if facts else "待多模态模型识别",
                dialogue=timeline_by_shot[shot.shot_id].transcript_text,
                subtitle_text=timeline_by_shot[shot.shot_id].subtitle_text,
                ocr_text=timeline_by_shot[shot.shot_id].ocr_text,
                audio=_shot_audio_description(timeline, shot.shot_id, evidence),
                transition=(
                    facts.transition
                    if facts
                    else "视频开始"
                    if shot.index == 1
                    else "VLM 已确认候选边界代表新的语义镜头"
                    if shot.boundary_method == "hybrid_vlm_verified"
                    else "FFmpeg 硬切分数达到锁定阈值"
                    if shot.boundary_method == "hard_scene_score"
                    else "程序检测到画面切换"
                ),
                narrative_role=facts.narrative_role if facts else "待 VLM 分析",
                prompt=(
                    facts.replication_prompt
                    if facts
                    else "当前仅完成真实媒体证据提取；启用 VLM 后生成复刻提示词。"
                ),
                confidence=facts.confidence if facts else 0.82,
                keyframe_url=shot.keyframe_url,
                evidence_frame_urls=shot.evidence_frame_urls or [shot.keyframe_url],
                evidence_kind="model" if facts else "measured",
                boundary_method=shot.boundary_method or shot.detection_method,
                boundary_confidence=shot.boundary_confidence,
                source_candidate_ids=shot.source_candidate_ids,
                semantic_group=shot.semantic_group,
                visual_beats=facts.visual_beats if facts else [],
                motion_phases=facts.motion_phases if facts else [],
                continuous_take=facts.continuous_take if facts else None,
                motion_confidence=facts.motion_confidence if facts else 0,
                outgoing_transition=(
                    facts.outgoing_transition if facts else ShotTransitionFact()
                ),
            )
        )

    model_count = len(visual_facts)
    prompt_shots: list[PromptShot] = []
    for shot in shots:
        draft = draft_from_shot(shot)
        prompt_shots.append(
            PromptShot(
                shot_id=shot.id,
                duration_seconds=round(shot.end_seconds - shot.start_seconds, 3),
                prompt=compile_prompt_draft(draft, video.target_model),
                negative_constraints=[],
                draft=draft,
                source_draft=draft.model_copy(deep=True),
            )
        )
    prompt_package = PromptPackage(
        target_model=video.target_model,
        aspect_ratio=evidence.metadata.aspect_ratio,
        global_prompt=(
            "逐镜头视觉事实和复刻提示词已生成；全局实体连续性将在下一阶段归并。"
            if model_count
            else "尚未生成：真实关键帧已就绪，等待 VLM 语义分析。"
        ),
        continuity_locks=[],
        entities={},
        shots=prompt_shots,
        negative_constraints=[],
    )
    metadata = evidence.metadata
    return AnalysisReport(
        video_id=video.id,
        analysis_id=analysis.id,
        analysis_mode=analysis.analysis_mode,
        overview=VideoOverview(
            summary=(
                f"已完成真实媒体处理：{metadata.duration_seconds:.1f} 秒、"
                f"{metadata.width}×{metadata.height}、{len(shots)} 个镜头；"
                f"{len(timeline.subtitle_cues)} 条内嵌字幕；"
                f"VLM 已完成 {model_count}/{len(shots)} 个镜头。"
            ),
            content_type="真实多模态镜头分析" if model_count else "真实媒体证据 · 语义待分析",
            narrative_structure=(
                "逐镜头视觉事实已生成；全局叙事与爆点待下一阶段推理"
                if model_count
                else "真实分镜时间线已生成；叙事结构待 VLM 分析"
            ),
            audience_inference="待爆点推理阶段分析",
            visual_style=(
                f"{metadata.video_codec.upper()} · {metadata.fps:.2f} FPS · {metadata.aspect_ratio}"
            ),
            duration_seconds=metadata.duration_seconds,
            aspect_ratio=metadata.aspect_ratio,
            viral_potential_score=0,
            confidence=1.0,
        ),
        shots=shots,
        entities=[],
        viral_findings=[],
        prompt_package=prompt_package,
        media_evidence=evidence,
        evidence_timeline=timeline,
        model_warnings=list(
            dict.fromkeys(
                [
                    *(segmentation_outcome.warnings if segmentation_outcome else []),
                    *(model_outcome.warnings if model_outcome else []),
                ]
            )
        ),
        model_cost_summary=(
            model_outcome.cost_summary
            if model_outcome
            else segmentation_outcome.cost_summary
            if segmentation_outcome
            else None
        ),
    )


def _provider_run(timeline: EvidenceTimeline, kind: str):
    return next((run for run in timeline.provider_runs if run.kind == kind), None)


def _shot_audio_description(
    timeline: EvidenceTimeline,
    shot_id: str,
    evidence: MediaEvidence,
) -> str:
    shot = next(item for item in timeline.shots if item.shot_id == shot_id)
    if shot.transcript_text:
        return "ASR 已生成带时间戳的镜头转写"
    run = _provider_run(timeline, "asr")
    if run and run.status == EvidenceProviderStatus.COMPLETED:
        return "ASR 已完成，本镜头没有识别到语音"
    if run and run.message:
        return run.message
    return "已提取 16 kHz 音频" if evidence.audio_url else "原视频无音轨或未提取音频"


def _completion_message(
    *,
    is_link: bool,
    timeline: EvidenceTimeline,
    model_outcome: ShotFactsOutcome | None,
    segmentation_outcome: SegmentationOutcome | None,
    vlm_configured: bool,
) -> str:
    prefix = "链接采集、媒体证据和时间线生成完成" if is_link else "媒体证据和时间线生成完成"
    completed = [
        run.kind.upper()
        for run in timeline.provider_runs
        if run.status == EvidenceProviderStatus.COMPLETED
    ]
    evidence_message = f"{'/'.join(completed)} 已执行" if completed else "ASR/OCR 未执行"
    segmentation_message = ""
    if segmentation_outcome:
        segmentation = segmentation_outcome.segmentation
        segmentation_message = (
            f"；混合分镜确认完成，共 {segmentation.final_shot_count} 个镜头"
            if segmentation.verified_by_model
            else "；分镜语义确认已降级为程序硬切边界"
        )
    if model_outcome and model_outcome.facts:
        cost = model_outcome.cost_summary.measured_cost_micros / 1_000_000
        return (
            f"{prefix}；{evidence_message}{segmentation_message}；VLM 已完成 "
            f"{len(model_outcome.facts)} 个镜头，模型成本约 ¥{cost:.4f}"
        )
    if model_outcome and model_outcome.warnings:
        return f"{prefix}；{evidence_message}；VLM 已降级：{model_outcome.warnings[0]}"
    if vlm_configured:
        return f"{prefix}；{evidence_message}；VLM 未返回有效镜头事实"
    if completed:
        return f"{prefix}；{evidence_message}；VLM 未启用"
    return f"{prefix}；ASR/OCR Provider 待配置，内嵌字幕已检查，VLM 未启用"
