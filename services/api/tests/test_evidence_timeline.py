from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.evidence import ASRProviderResult, EvidenceTimelineBuilder, OCRFrame
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisMode,
    MediaEvidence,
    MediaMetadata,
    OCRObservation,
    ShotEvidence,
    SourceType,
    SubtitleStream,
    TranscriptSegment,
    Video,
)
from viral_dna_api.real_pipeline import build_media_evidence_report


def build_evidence(analysis_id) -> MediaEvidence:
    return MediaEvidence(
        processor_version="ffmpeg-media-v1",
        metadata=MediaMetadata(
            duration_seconds=4.0,
            width=720,
            height=1280,
            fps=30,
            format_name="mp4",
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
            size_bytes=1024,
            sha256="a" * 64,
            aspect_ratio="9:16",
        ),
        proxy_url=f"/api/v1/analyses/{analysis_id}/artifacts/proxy.mp4",
        audio_url=f"/api/v1/analyses/{analysis_id}/artifacts/audio.wav",
        contact_sheet_url=None,
        manifest_url=f"/api/v1/analyses/{analysis_id}/artifacts/manifest.json",
        shots=[
            ShotEvidence(
                shot_id="shot_001",
                index=1,
                start_seconds=0,
                end_seconds=2,
                duration_seconds=2,
                representative_timestamp=1,
                keyframe_url=f"/api/v1/analyses/{analysis_id}/artifacts/shots/shot_001.jpg",
                detection_method="test",
            ),
            ShotEvidence(
                shot_id="shot_002",
                index=2,
                start_seconds=2,
                end_seconds=4,
                duration_seconds=2,
                representative_timestamp=3,
                keyframe_url=f"/api/v1/analyses/{analysis_id}/artifacts/shots/shot_002.jpg",
                detection_method="test",
            ),
        ],
    )


class FakeASRProvider:
    provider_id = "fake-asr"
    model_id = "fixture-v1"
    enabled = True

    async def transcribe(self, audio_path: Path) -> ASRProviderResult:
        assert audio_path.name == "audio.wav"
        return ASRProviderResult(
            language="zh",
            segments=[
                TranscriptSegment(
                    id="asr_001",
                    start_seconds=0.5,
                    end_seconds=2.5,
                    text="  跨镜头语句  ",
                    language="zh",
                    confidence=0.95,
                ),
                TranscriptSegment(
                    id="asr_002",
                    start_seconds=3.0,
                    end_seconds=3.8,
                    text="第二个镜头",
                    language="zh",
                    confidence=0.9,
                ),
                TranscriptSegment(
                    id="asr_outside",
                    start_seconds=4.2,
                    end_seconds=4.8,
                    text="越界内容",
                ),
            ],
        )


class FakeOCRProvider:
    provider_id = "fake-ocr"
    model_id = "fixture-v1"
    enabled = True

    async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]:
        assert [frame.shot_id for frame in frames] == ["shot_001", "shot_002"]
        return [
            OCRObservation(
                id="ocr_001",
                timestamp_seconds=1.0,
                text=" AI 工作台 ",
                confidence=0.93,
            ),
            OCRObservation(
                id="ocr_duplicate",
                timestamp_seconds=1.4,
                text="AI 工作台",
                confidence=0.89,
            ),
            OCRObservation(
                id="ocr_002",
                timestamp_seconds=3.0,
                text="去掉 AI 味",
                confidence=0.91,
            ),
            OCRObservation(
                id="ocr_outside",
                timestamp_seconds=4.5,
                text="越界文字",
            ),
        ]


@pytest.mark.asyncio
async def test_asr_and_ocr_start_in_parallel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_id = uuid4()
    storage_root = tmp_path / "storage"
    artifact_root = storage_root / "analyses" / str(analysis_id)
    shots_dir = artifact_root / "shots"
    shots_dir.mkdir(parents=True)
    (artifact_root / "audio.wav").write_bytes(b"wav")
    (shots_dir / "shot_001.jpg").write_bytes(b"jpg")
    (shots_dir / "shot_002.jpg").write_bytes(b"jpg")
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    both_started = asyncio.Event()
    started: set[str] = set()

    async def rendezvous(kind: str) -> None:
        started.add(kind)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)

    class ParallelASR(FakeASRProvider):
        async def transcribe(self, audio_path: Path) -> ASRProviderResult:
            await rendezvous("asr")
            return await super().transcribe(audio_path)

    class ParallelOCR(FakeOCRProvider):
        async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]:
            await rendezvous("ocr")
            return await super().recognize(frames)

    timeline = await EvidenceTimelineBuilder(
        asr_provider=ParallelASR(),
        ocr_provider=ParallelOCR(),
    ).build(
        analysis_id=analysis_id,
        evidence=build_evidence(analysis_id),
        include_audio=True,
        include_ocr=True,
    )

    assert started == {"asr", "ocr"}
    assert [run.status for run in timeline.provider_runs[:2]] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_timeline_aligns_fake_asr_and_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_id = uuid4()
    storage_root = tmp_path / "storage"
    artifact_root = storage_root / "analyses" / str(analysis_id)
    shots_dir = artifact_root / "shots"
    shots_dir.mkdir(parents=True)
    (artifact_root / "audio.wav").write_bytes(b"wav")
    (shots_dir / "shot_001.jpg").write_bytes(b"jpg")
    (shots_dir / "shot_002.jpg").write_bytes(b"jpg")
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))

    timeline = await EvidenceTimelineBuilder(
        asr_provider=FakeASRProvider(),
        ocr_provider=FakeOCRProvider(),
    ).build(
        analysis_id=analysis_id,
        evidence=build_evidence(analysis_id),
        include_audio=True,
        include_ocr=True,
    )

    assert timeline.language == "zh"
    assert [run.status for run in timeline.provider_runs] == [
        "completed",
        "completed",
        "skipped",
    ]
    assert [run.item_count for run in timeline.provider_runs] == [2, 2, 0]
    assert [segment.id for segment in timeline.transcript_segments] == ["asr_001", "asr_002"]
    assert [item.id for item in timeline.ocr_observations] == ["ocr_001", "ocr_002"]
    assert timeline.shots[0].transcript_segment_ids == ["asr_001"]
    assert timeline.shots[1].transcript_segment_ids == ["asr_001", "asr_002"]
    assert timeline.shots[0].transcript_text == "跨镜头语句"
    assert timeline.shots[0].ocr_text == "AI 工作台"
    assert timeline.shots[1].ocr_text == "去掉 AI 味"
    assert any("越界转写" in warning for warning in timeline.warnings)
    assert any("越界 OCR" in warning for warning in timeline.warnings)

    video = Video(source_type=SourceType.UPLOAD, title="时间线测试")
    analysis = AnalysisJob(video_id=video.id, analysis_mode=AnalysisMode.MEDIA_EVIDENCE)
    report = build_media_evidence_report(
        video,
        analysis,
        build_evidence(analysis_id),
        timeline,
    )
    assert report.shots[0].dialogue == "跨镜头语句"
    assert report.shots[0].ocr_text == "AI 工作台"
    assert report.shots[1].dialogue == "跨镜头语句 第二个镜头"
    assert report.evidence_timeline == timeline

    payload = json.loads((artifact_root / "timeline.json").read_text("utf-8"))
    assert payload["timeline_version"] == "phase1-evidence-timeline-v2"
    assert len(payload["shots"]) == 2


@pytest.mark.asyncio
async def test_configured_but_unavailable_provider_degrades_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_id = uuid4()
    storage_root = tmp_path / "storage"
    artifact_root = storage_root / "analyses" / str(analysis_id)
    shots_dir = artifact_root / "shots"
    shots_dir.mkdir(parents=True)
    (artifact_root / "audio.wav").write_bytes(b"wav")
    (shots_dir / "shot_001.jpg").write_bytes(b"jpg")
    (shots_dir / "shot_002.jpg").write_bytes(b"jpg")
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_ASR_PROVIDER", "future-cloud-asr")
    monkeypatch.setenv("VIRAL_DNA_OCR_PROVIDER", "disabled")

    timeline = await EvidenceTimelineBuilder.from_environment().build(
        analysis_id=analysis_id,
        evidence=build_evidence(analysis_id),
        include_audio=True,
        include_ocr=True,
    )

    assert timeline.transcript_segments == []
    assert timeline.ocr_observations == []
    assert timeline.provider_runs[0].status == "unavailable"
    assert timeline.provider_runs[0].provider == "future-cloud-asr"
    assert "尚未安装" in (timeline.provider_runs[0].message or "")
    assert timeline.provider_runs[1].status == "skipped"


@pytest.mark.asyncio
async def test_embedded_subtitles_are_parsed_and_aligned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_id = uuid4()
    storage_root = tmp_path / "storage"
    artifact_root = storage_root / "analyses" / str(analysis_id)
    artifact_root.mkdir(parents=True)
    (artifact_root / "subtitles.srt").write_text(
        "1\n00:00:00,500 --> 00:00:02,500\n<b>跨镜头字幕</b>\n\n"
        "2\n00:00:03,000 --> 00:00:03,800\n第二句字幕\n",
        "utf-8",
    )
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_ASR_PROVIDER", "disabled")
    monkeypatch.setenv("VIRAL_DNA_OCR_PROVIDER", "disabled")
    evidence = build_evidence(analysis_id)
    evidence.metadata.subtitle_streams = [
        SubtitleStream(
            index=2,
            codec_name="mov_text",
            language="zh",
            extractable=True,
        )
    ]
    evidence.subtitle_url = (
        f"/api/v1/analyses/{analysis_id}/artifacts/subtitles.srt"
    )
    evidence.subtitle_extraction_message = "已提取 mov_text 内嵌字幕轨"

    timeline = await EvidenceTimelineBuilder.from_environment().build(
        analysis_id=analysis_id,
        evidence=evidence,
        include_audio=False,
        include_ocr=False,
    )

    assert timeline.provider_runs[2].kind == "subtitle"
    assert timeline.provider_runs[2].status == "completed"
    assert timeline.provider_runs[2].item_count == 2
    assert timeline.subtitle_cues[0].text == "跨镜头字幕"
    assert timeline.subtitle_cues[0].language == "zh"
    assert timeline.shots[0].subtitle_text == "跨镜头字幕"
    assert timeline.shots[1].subtitle_text == "跨镜头字幕 第二句字幕"
