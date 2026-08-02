from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from .media import MediaProcessingError, MediaProcessor
from .models import (
    AnalysisError,
    AnalysisJob,
    AnalysisMode,
    AnalysisReport,
    AnalysisStage,
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
    """Routes uploads through real FFmpeg evidence and links through the demo analyzer."""

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

        if video.source_type != SourceType.UPLOAD or not video.stored_path:
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

            processor = MediaProcessor()
            evidence = await processor.process(
                source_path=Path(video.stored_path),
                analysis_id=analysis.id,
                granularity=analysis.granularity,
                include_audio=analysis.include_audio,
                progress=progress,
            )

            await progress(AnalysisStage.VALIDATING, 90, "正在校验媒体证据与分镜时间线")
            self._apply_metadata(video, evidence)
            report = build_media_evidence_report(video, analysis, evidence)
            await self.repository.save_report(report)

            analysis.stage = AnalysisStage.COMPLETED
            analysis.progress = 100
            analysis.message = "真实媒体证据提取完成；ASR/OCR/VLM 待下一批接入"
            analysis.updated_at = utc_now()
            analysis.completed_at = utc_now()
            await self.repository.save_analysis(analysis)

            video.status = VideoStatus.COMPLETED
            await self.repository.save_video(video)
        except MediaProcessingError as exc:
            await self._fail(analysis, video, exc.code, str(exc), exc.retryable)
        except Exception as exc:  # pragma: no cover - orchestration safety boundary
            await self._fail(analysis, video, "analysis_failed", str(exc), True)

    async def _fail(
        self,
        analysis: AnalysisJob,
        video: Video,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        analysis.stage = AnalysisStage.FAILED
        analysis.progress = 100
        analysis.message = f"媒体处理失败：{message}"
        analysis.error = AnalysisError(code=code, message=message, retryable=retryable)
        analysis.updated_at = utc_now()
        await self.repository.save_analysis(analysis)
        video.status = VideoStatus.FAILED
        await self.repository.save_video(video)

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
) -> AnalysisReport:
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
            dialogue=None,
            ocr_text=None,
            audio=(
                "已提取 16 kHz 音频，ASR 待接入"
                if evidence.audio_url
                else "原视频无音轨或未提取音频"
            ),
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
    )
