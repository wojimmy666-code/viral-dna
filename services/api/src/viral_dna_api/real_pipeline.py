from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from .evidence import EvidenceTimelineBuilder
from .link_ingestion import LinkCollector, LinkIngestionError, LinkIngestionResult
from .media import MediaProcessingError, MediaProcessor
from .models import (
    AnalysisError,
    AnalysisJob,
    AnalysisMode,
    AnalysisReport,
    AnalysisStage,
    EvidenceProviderStatus,
    EvidenceTimeline,
    MediaEvidence,
    PromptPackage,
    PromptShot,
    Shot,
    SourceType,
    Video,
    VideoOverview,
    VideoStatus,
)
from .pipeline import SimulatedAnalysisPipeline


def utc_now() -> datetime:
    return datetime.now(UTC)


class AnalysisRepository(Protocol):
    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None: ...

    async def save_analysis(self, analysis: AnalysisJob) -> AnalysisJob: ...

    async def get_video(self, video_id: UUID) -> Video | None: ...

    async def save_video(self, video: Video) -> Video: ...

    async def save_report(self, report: AnalysisReport) -> AnalysisReport: ...


class HybridAnalysisPipeline:
    """Collects uploads and platform links before building real FFmpeg evidence."""

    def __init__(self, repository: AnalysisRepository) -> None:
        self.repository = repository
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
            if is_link and not video.stored_path:
                await progress(AnalysisStage.INGESTING, 3, "正在校验平台链接并读取视频信息")
                collected = await LinkCollector().collect(video)
                self._apply_ingestion(video, collected)
                await self.repository.save_video(video)
                await progress(AnalysisStage.INGESTING, 24, "平台视频下载完成，正在准备媒体分析")

            if not video.stored_path:
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
                source_path=Path(video.stored_path),
                analysis_id=analysis.id,
                granularity=analysis.granularity,
                include_audio=analysis.include_audio,
                progress=media_progress,
            )

            await progress(AnalysisStage.TRANSCRIBING, 84, "正在运行 ASR/OCR 证据 Provider")
            timeline = await EvidenceTimelineBuilder.from_environment().build(
                analysis_id=analysis.id,
                evidence=evidence,
                include_audio=analysis.include_audio,
                include_ocr=analysis.include_ocr,
            )
            await progress(AnalysisStage.UNDERSTANDING, 89, "正在将语音和画面文字对齐到镜头")
            await progress(AnalysisStage.VALIDATING, 94, "正在校验媒体证据与统一时间线")
            self._apply_metadata(video, evidence)
            report = build_media_evidence_report(video, analysis, evidence, timeline)
            await self.repository.save_report(report)

            analysis.stage = AnalysisStage.COMPLETED
            analysis.progress = 100
            analysis.message = _completion_message(is_link=is_link, timeline=timeline)
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

    @staticmethod
    def _apply_ingestion(video: Video, result: LinkIngestionResult) -> None:
        video.stored_path = str(result.path)
        video.original_filename = result.path.name
        video.resolved_source_url = result.resolved_url
        video.source_video_id = result.source_video_id
        video.source_author = result.author
        video.ingested_at = utc_now()
        if result.duration_seconds is not None:
            video.duration_seconds = result.duration_seconds
        if result.title and video.title in {"抖音链接视频", "小红书链接视频"}:
            video.title = result.title[:120]

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
) -> AnalysisReport:
    timeline_by_shot = {shot.shot_id: shot for shot in timeline.shots}
    shots = [
        Shot(
            id=shot.shot_id,
            index=shot.index,
            start_seconds=shot.start_seconds,
            end_seconds=shot.end_seconds,
            title=f"镜头 {shot.index:02d}",
            subjects=[],
            action="待多模态模型识别",
            scene="待多模态模型识别",
            camera=f"真实镜头边界，持续 {shot.duration_seconds:.1f} 秒",
            composition="已提取代表关键帧，构图语义待分析",
            lighting="待多模态模型识别",
            color="待多模态模型识别",
            dialogue=timeline_by_shot[shot.shot_id].transcript_text,
            ocr_text=timeline_by_shot[shot.shot_id].ocr_text,
            audio=_shot_audio_description(timeline, shot.shot_id, evidence),
            transition=("视频开始" if shot.index == 1 else "FFmpeg scene score 检测到画面切换"),
            narrative_role="待 ASR/OCR/VLM 分析",
            prompt="当前仅完成真实媒体证据提取；接入多模态模型后生成复刻提示词。",
            confidence=0.82,
            keyframe_url=shot.keyframe_url,
            evidence_frame_urls=[shot.keyframe_url],
            evidence_kind="measured",
        )
        for shot in evidence.shots
    ]
    prompt_package = PromptPackage(
        target_model=video.target_model,
        aspect_ratio=evidence.metadata.aspect_ratio,
        global_prompt="尚未生成：真实关键帧已就绪，等待 ASR/OCR/VLM 语义分析。",
        continuity_locks=[],
        entities={},
        shots=[
            PromptShot(
                shot_id=shot.id,
                duration_seconds=round(shot.end_seconds - shot.start_seconds, 3),
                prompt=shot.prompt,
                negative_constraints=[],
            )
            for shot in shots
        ],
        negative_constraints=[],
    )
    metadata = evidence.metadata
    return AnalysisReport(
        video_id=video.id,
        analysis_id=analysis.id,
        analysis_mode=AnalysisMode.MEDIA_EVIDENCE,
        overview=VideoOverview(
            summary=(
                f"已完成真实媒体处理：{metadata.duration_seconds:.1f} 秒、"
                f"{metadata.width}×{metadata.height}、{len(shots)} 个镜头。"
            ),
            content_type="真实媒体证据 · 语义待分析",
            narrative_structure="真实分镜时间线已生成；叙事结构待 ASR/OCR/VLM 分析",
            audience_inference="待语义模型分析",
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


def _completion_message(*, is_link: bool, timeline: EvidenceTimeline) -> str:
    prefix = "链接采集、媒体证据和时间线生成完成" if is_link else "媒体证据和时间线生成完成"
    completed = [
        run.kind.upper()
        for run in timeline.provider_runs
        if run.status == EvidenceProviderStatus.COMPLETED
    ]
    if completed:
        return f"{prefix}；{'/'.join(completed)} 已执行，VLM 待下一批接入"
    return f"{prefix}；ASR/OCR Provider 待配置，VLM 待下一批接入"
