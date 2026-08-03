from __future__ import annotations

import asyncio
import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import UUID

from .media import artifact_url, get_analysis_artifact_root
from .models import (
    EvidenceProviderRun,
    EvidenceProviderStatus,
    EvidenceTimeline,
    MediaEvidence,
    OCRObservation,
    ShotEvidence,
    ShotTimelineEvidence,
    SubtitleCue,
    TranscriptSegment,
)

TIMELINE_VERSION = "phase1-evidence-timeline-v2"
TIMESTAMP_TOLERANCE_SECONDS = 0.25
OCR_DEDUP_WINDOW_SECONDS = 1.5


class EvidenceProviderUnavailable(RuntimeError):
    """Raised when a configured provider has no usable runtime adapter."""


@dataclass(frozen=True, slots=True)
class ASRProviderResult:
    language: str | None
    segments: list[TranscriptSegment]


@dataclass(frozen=True, slots=True)
class OCRFrame:
    shot_id: str
    timestamp_seconds: float
    path: Path
    url: str


class ASRProvider(Protocol):
    provider_id: str
    model_id: str | None
    enabled: bool

    async def transcribe(self, audio_path: Path) -> ASRProviderResult: ...


class OCRProvider(Protocol):
    provider_id: str
    model_id: str | None
    enabled: bool

    async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]: ...


class DisabledASRProvider:
    provider_id = "disabled"
    model_id: str | None = None
    enabled = False

    async def transcribe(self, audio_path: Path) -> ASRProviderResult:
        del audio_path
        return ASRProviderResult(language=None, segments=[])


class DisabledOCRProvider:
    provider_id = "disabled"
    model_id: str | None = None
    enabled = False

    async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]:
        del frames
        return []


class UnavailableASRProvider:
    enabled = True

    def __init__(self, provider_id: str, model_id: str | None) -> None:
        self.provider_id = provider_id
        self.model_id = model_id

    async def transcribe(self, audio_path: Path) -> ASRProviderResult:
        del audio_path
        raise EvidenceProviderUnavailable(f"尚未安装 ASR Provider 适配器：{self.provider_id}")


class UnavailableOCRProvider:
    enabled = True

    def __init__(self, provider_id: str, model_id: str | None) -> None:
        self.provider_id = provider_id
        self.model_id = model_id

    async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]:
        del frames
        raise EvidenceProviderUnavailable(f"尚未安装 OCR Provider 适配器：{self.provider_id}")


class EmbeddedSubtitleProvider:
    provider_id = "ffmpeg-subtitle"
    enabled = True

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id


def _configured_provider(kind: str) -> tuple[str, str | None]:
    raw_provider = os.getenv(f"VIRAL_DNA_{kind}_PROVIDER", "disabled")
    provider = re.sub(r"[^a-z0-9_.-]+", "-", raw_provider.strip().lower())[:80]
    model = os.getenv(f"VIRAL_DNA_{kind}_MODEL", "").strip()[:120] or None
    return provider or "disabled", model


def asr_provider_from_environment() -> ASRProvider:
    provider, model = _configured_provider("ASR")
    if provider in {"disabled", "none", "off"}:
        return DisabledASRProvider()
    if provider in {"faster-whisper", "faster_whisper", "whisper"}:
        from .local_providers import FasterWhisperASRProvider

        return FasterWhisperASRProvider(model)
    return UnavailableASRProvider(provider, model)


def ocr_provider_from_environment() -> OCRProvider:
    provider, model = _configured_provider("OCR")
    if provider in {"disabled", "none", "off"}:
        return DisabledOCRProvider()
    if provider in {"rapidocr", "rapid-ocr", "rapid_ocr"}:
        from .local_providers import RapidOCRProvider

        return RapidOCRProvider(model)
    return UnavailableOCRProvider(provider, model)


def _safe_error_message(error: Exception) -> str:
    message = " ".join(str(error).replace("\x00", "").split())
    message = re.sub(
        r"(?i)(api[_ -]?key|token|authorization|cookie)(\s*[:=]\s*)\S+",
        r"\1\2[REDACTED]",
        message,
    )
    return message[:500] or type(error).__name__


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _join_unique_text(values: list[str]) -> str | None:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return " ".join(result) or None


def _srt_timestamp(value: str) -> float | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", value.strip())
    if match is None:
        return None
    hours, minutes, seconds, milliseconds = (int(part) for part in match.groups())
    millisecond_scale = 10 ** (3 - len(match.group(4)))
    return hours * 3600 + minutes * 60 + seconds + milliseconds * millisecond_scale / 1000


def _parse_srt(
    payload: str,
    *,
    language: str | None,
    stream_index: int | None,
) -> list[SubtitleCue]:
    normalized = payload.replace("\r\n", "\n").replace("\r", "\n").strip()
    cues: list[SubtitleCue] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.splitlines()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = re.match(
            r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
            r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})",
            lines[timing_index],
        )
        if timing is None:
            continue
        start = _srt_timestamp(timing.group("start"))
        end = _srt_timestamp(timing.group("end"))
        raw_text = " ".join(lines[timing_index + 1 :])
        cleaned = re.sub(r"\{\\[^}]+}", "", raw_text)
        cleaned = html.unescape(re.sub(r"<[^>]+>", "", cleaned))
        cleaned = _clean_text(cleaned)[:4000]
        if start is None or end is None or end <= start or not cleaned:
            continue
        cues.append(
            SubtitleCue(
                id=f"subtitle_{len(cues) + 1:04d}",
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                text=cleaned,
                language=language,
                stream_index=stream_index,
            )
        )
    return cues


def _provider_run(
    *,
    kind: str,
    provider: ASRProvider | OCRProvider | EmbeddedSubtitleProvider,
    status: EvidenceProviderStatus,
    started_at: float,
    item_count: int = 0,
    message: str | None = None,
) -> EvidenceProviderRun:
    return EvidenceProviderRun(
        kind=kind,
        provider=provider.provider_id,
        model=provider.model_id,
        status=status,
        item_count=item_count,
        duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
        message=message,
    )


class EvidenceTimelineBuilder:
    def __init__(
        self,
        *,
        asr_provider: ASRProvider | None = None,
        ocr_provider: OCRProvider | None = None,
    ) -> None:
        self.asr_provider = asr_provider or asr_provider_from_environment()
        self.ocr_provider = ocr_provider or ocr_provider_from_environment()

    @classmethod
    def from_environment(cls) -> EvidenceTimelineBuilder:
        return cls(
            asr_provider=asr_provider_from_environment(),
            ocr_provider=ocr_provider_from_environment(),
        )

    async def build(
        self,
        *,
        analysis_id: UUID,
        evidence: MediaEvidence,
        include_audio: bool,
        include_ocr: bool,
        record_id: UUID | None = None,
    ) -> EvidenceTimeline:
        artifact_root = get_analysis_artifact_root(analysis_id, record_id)
        await asyncio.to_thread(artifact_root.mkdir, parents=True, exist_ok=True)

        asr_result, asr_run = await self._run_asr(
            artifact_root=artifact_root,
            evidence=evidence,
            include_audio=include_audio,
        )
        frames = self._ocr_frames(artifact_root, evidence)
        ocr_observations, ocr_run = await self._run_ocr(
            frames=frames,
            include_ocr=include_ocr,
        )
        subtitle_cues, subtitle_run = await self._run_subtitles(
            artifact_root=artifact_root,
            evidence=evidence,
        )

        warnings: list[str] = []
        segments = self._valid_segments(
            asr_result.segments,
            evidence.metadata.duration_seconds,
            warnings,
        )
        observations = self._valid_ocr_observations(
            ocr_observations,
            evidence,
            warnings,
        )
        cues = self._valid_subtitle_cues(
            subtitle_cues,
            evidence.metadata.duration_seconds,
            warnings,
        )
        asr_run.item_count = len(segments)
        ocr_run.item_count = len(observations)
        subtitle_run.item_count = len(cues)
        shot_timeline = self._align_shots(evidence.shots, segments, cues, observations)

        language = asr_result.language or next(
            (segment.language for segment in segments if segment.language),
            next((cue.language for cue in cues if cue.language), None),
        )
        timeline = EvidenceTimeline(
            timeline_version=TIMELINE_VERSION,
            duration_seconds=evidence.metadata.duration_seconds,
            language=language,
            provider_runs=[asr_run, ocr_run, subtitle_run],
            transcript_segments=segments,
            subtitle_cues=cues,
            ocr_observations=observations,
            shots=shot_timeline,
            warnings=warnings,
            artifact_url=artifact_url(analysis_id, "timeline.json"),
        )
        timeline_path = artifact_root / "timeline.json"
        await asyncio.to_thread(
            timeline_path.write_text,
            timeline.model_dump_json(indent=2),
            "utf-8",
        )
        return timeline

    async def _run_asr(
        self,
        *,
        artifact_root: Path,
        evidence: MediaEvidence,
        include_audio: bool,
    ) -> tuple[ASRProviderResult, EvidenceProviderRun]:
        started_at = perf_counter()
        empty = ASRProviderResult(language=None, segments=[])
        if not include_audio:
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="用户关闭音频分析",
            )
        if not evidence.audio_url:
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="视频没有可用音轨",
            )
        if not self.asr_provider.enabled:
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="未配置 ASR Provider",
            )

        audio_path = artifact_root / "audio.wav"
        if not await asyncio.to_thread(audio_path.is_file):
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.FAILED,
                started_at=started_at,
                message="音频证据文件不存在",
            )
        try:
            result = await self.asr_provider.transcribe(audio_path)
        except EvidenceProviderUnavailable as error:
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.UNAVAILABLE,
                started_at=started_at,
                message=_safe_error_message(error),
            )
        except Exception as error:  # pragma: no cover - provider safety boundary
            return empty, _provider_run(
                kind="asr",
                provider=self.asr_provider,
                status=EvidenceProviderStatus.FAILED,
                started_at=started_at,
                message=_safe_error_message(error),
            )
        return result, _provider_run(
            kind="asr",
            provider=self.asr_provider,
            status=EvidenceProviderStatus.COMPLETED,
            started_at=started_at,
            item_count=len(result.segments),
        )

    async def _run_ocr(
        self,
        *,
        frames: list[OCRFrame],
        include_ocr: bool,
    ) -> tuple[list[OCRObservation], EvidenceProviderRun]:
        started_at = perf_counter()
        if not include_ocr:
            return [], _provider_run(
                kind="ocr",
                provider=self.ocr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="用户关闭 OCR 分析",
            )
        if not frames:
            return [], _provider_run(
                kind="ocr",
                provider=self.ocr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="没有可用于 OCR 的关键帧",
            )
        if not self.ocr_provider.enabled:
            return [], _provider_run(
                kind="ocr",
                provider=self.ocr_provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="未配置 OCR Provider",
            )
        try:
            observations = await self.ocr_provider.recognize(frames)
        except EvidenceProviderUnavailable as error:
            return [], _provider_run(
                kind="ocr",
                provider=self.ocr_provider,
                status=EvidenceProviderStatus.UNAVAILABLE,
                started_at=started_at,
                message=_safe_error_message(error),
            )
        except Exception as error:  # pragma: no cover - provider safety boundary
            return [], _provider_run(
                kind="ocr",
                provider=self.ocr_provider,
                status=EvidenceProviderStatus.FAILED,
                started_at=started_at,
                message=_safe_error_message(error),
            )
        return observations, _provider_run(
            kind="ocr",
            provider=self.ocr_provider,
            status=EvidenceProviderStatus.COMPLETED,
            started_at=started_at,
            item_count=len(observations),
        )

    async def _run_subtitles(
        self,
        *,
        artifact_root: Path,
        evidence: MediaEvidence,
    ) -> tuple[list[SubtitleCue], EvidenceProviderRun]:
        started_at = perf_counter()
        first_stream = next(
            (stream for stream in evidence.metadata.subtitle_streams if stream.extractable),
            evidence.metadata.subtitle_streams[0]
            if evidence.metadata.subtitle_streams
            else None,
        )
        provider = EmbeddedSubtitleProvider(first_stream.codec_name if first_stream else None)
        if first_stream is None:
            return [], _provider_run(
                kind="subtitle",
                provider=provider,
                status=EvidenceProviderStatus.SKIPPED,
                started_at=started_at,
                message="视频没有独立字幕轨；画面烧录字幕由 OCR 识别",
            )
        if not evidence.subtitle_url:
            return [], _provider_run(
                kind="subtitle",
                provider=provider,
                status=EvidenceProviderStatus.UNAVAILABLE,
                started_at=started_at,
                message=evidence.subtitle_extraction_message or "独立字幕轨无法转换为文本",
            )

        subtitle_path = artifact_root / "subtitles.srt"
        if not await asyncio.to_thread(subtitle_path.is_file):
            return [], _provider_run(
                kind="subtitle",
                provider=provider,
                status=EvidenceProviderStatus.FAILED,
                started_at=started_at,
                message="字幕证据文件不存在",
            )
        payload = await asyncio.to_thread(subtitle_path.read_text, "utf-8", "replace")
        cues = _parse_srt(
            payload,
            language=first_stream.language,
            stream_index=first_stream.index,
        )
        return cues, _provider_run(
            kind="subtitle",
            provider=provider,
            status=EvidenceProviderStatus.COMPLETED,
            started_at=started_at,
            item_count=len(cues),
            message=evidence.subtitle_extraction_message,
        )

    @staticmethod
    def _ocr_frames(artifact_root: Path, evidence: MediaEvidence) -> list[OCRFrame]:
        return [
            OCRFrame(
                shot_id=shot.shot_id,
                timestamp_seconds=shot.representative_timestamp,
                path=artifact_root / "shots" / f"shot_{shot.index:03d}.jpg",
                url=shot.keyframe_url,
            )
            for shot in evidence.shots
        ]

    @staticmethod
    def _valid_segments(
        values: list[TranscriptSegment],
        duration_seconds: float,
        warnings: list[str],
    ) -> list[TranscriptSegment]:
        result: list[TranscriptSegment] = []
        seen_ids: set[str] = set()
        for segment in sorted(values, key=lambda item: (item.start_seconds, item.end_seconds)):
            if segment.id in seen_ids:
                warnings.append(f"丢弃重复转写 ID：{segment.id}")
                continue
            if (
                segment.start_seconds >= duration_seconds
                or segment.end_seconds > duration_seconds + TIMESTAMP_TOLERANCE_SECONDS
            ):
                warnings.append(f"丢弃越界转写片段：{segment.id}")
                continue
            cleaned = _clean_text(segment.text)
            if not cleaned:
                warnings.append(f"丢弃空转写片段：{segment.id}")
                continue
            seen_ids.add(segment.id)
            result.append(segment.model_copy(update={"text": cleaned}))
        return result

    @classmethod
    def _valid_ocr_observations(
        cls,
        values: list[OCRObservation],
        evidence: MediaEvidence,
        warnings: list[str],
    ) -> list[OCRObservation]:
        result: list[OCRObservation] = []
        seen_ids: set[str] = set()
        for observation in sorted(values, key=lambda item: item.timestamp_seconds):
            if observation.id in seen_ids:
                warnings.append(f"丢弃重复 OCR ID：{observation.id}")
                continue
            if observation.timestamp_seconds > (
                evidence.metadata.duration_seconds + TIMESTAMP_TOLERANCE_SECONDS
            ):
                warnings.append(f"丢弃越界 OCR 观察：{observation.id}")
                continue
            cleaned = _clean_text(observation.text)
            if not cleaned:
                warnings.append(f"丢弃空 OCR 观察：{observation.id}")
                continue
            shot = cls._shot_at(evidence.shots, observation.timestamp_seconds)
            if shot is None:
                warnings.append(f"OCR 观察未命中镜头：{observation.id}")
                continue
            if result:
                previous = result[-1]
                if (
                    previous.text.casefold() == cleaned.casefold()
                    and observation.timestamp_seconds - previous.timestamp_seconds
                    <= OCR_DEDUP_WINDOW_SECONDS
                ):
                    continue
            seen_ids.add(observation.id)
            result.append(
                observation.model_copy(
                    update={
                        "text": cleaned,
                        "shot_id": shot.shot_id,
                        "frame_url": observation.frame_url or shot.keyframe_url,
                    }
                )
            )
        return result

    @staticmethod
    def _valid_subtitle_cues(
        values: list[SubtitleCue],
        duration_seconds: float,
        warnings: list[str],
    ) -> list[SubtitleCue]:
        result: list[SubtitleCue] = []
        seen_ids: set[str] = set()
        for cue in sorted(values, key=lambda item: (item.start_seconds, item.end_seconds)):
            if cue.id in seen_ids:
                warnings.append(f"丢弃重复字幕 ID：{cue.id}")
                continue
            if cue.start_seconds >= duration_seconds:
                warnings.append(f"丢弃越界字幕：{cue.id}")
                continue
            cleaned = _clean_text(cue.text)
            if not cleaned:
                warnings.append(f"丢弃空字幕：{cue.id}")
                continue
            end_seconds = min(cue.end_seconds, duration_seconds)
            if end_seconds <= cue.start_seconds:
                continue
            seen_ids.add(cue.id)
            result.append(
                cue.model_copy(
                    update={
                        "end_seconds": round(end_seconds, 3),
                        "text": cleaned,
                    }
                )
            )
        return result

    @staticmethod
    def _shot_at(shots: list[ShotEvidence], timestamp: float) -> ShotEvidence | None:
        for index, shot in enumerate(shots):
            is_last = index == len(shots) - 1
            if shot.start_seconds <= timestamp < shot.end_seconds:
                return shot
            if is_last and shot.start_seconds <= timestamp <= shot.end_seconds:
                return shot
        return None

    @staticmethod
    def _align_shots(
        shots: list[ShotEvidence],
        segments: list[TranscriptSegment],
        cues: list[SubtitleCue],
        observations: list[OCRObservation],
    ) -> list[ShotTimelineEvidence]:
        timeline: list[ShotTimelineEvidence] = []
        for shot in shots:
            matched_segments = [
                segment
                for segment in segments
                if segment.start_seconds < shot.end_seconds
                and segment.end_seconds > shot.start_seconds
            ]
            matched_ocr = [
                observation for observation in observations if observation.shot_id == shot.shot_id
            ]
            matched_cues = [
                cue
                for cue in cues
                if cue.start_seconds < shot.end_seconds and cue.end_seconds > shot.start_seconds
            ]
            timeline.append(
                ShotTimelineEvidence(
                    shot_id=shot.shot_id,
                    start_seconds=shot.start_seconds,
                    end_seconds=shot.end_seconds,
                    transcript_segment_ids=[segment.id for segment in matched_segments],
                    transcript_text=_join_unique_text(
                        [segment.text for segment in matched_segments]
                    ),
                    subtitle_cue_ids=[cue.id for cue in matched_cues],
                    subtitle_text=_join_unique_text([cue.text for cue in matched_cues]),
                    ocr_observation_ids=[observation.id for observation in matched_ocr],
                    ocr_text=_join_unique_text([observation.text for observation in matched_ocr]),
                )
            )
        return timeline
