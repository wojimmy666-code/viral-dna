from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from viral_dna_api.evidence import (
    OCRFrame,
    asr_provider_from_environment,
    ocr_provider_from_environment,
)
from viral_dna_api.local_providers import FasterWhisperASRProvider, RapidOCRProvider


@pytest.mark.asyncio
async def test_faster_whisper_maps_segments_and_words(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    class FakeModel:
        def transcribe(self, path: str, **kwargs):
            assert path == str(audio_path)
            assert kwargs["word_timestamps"] is True
            assert kwargs["vad_filter"] is True
            return (
                iter(
                    [
                        SimpleNamespace(
                            start=0.2,
                            end=1.5,
                            text="  你好 世界  ",
                            avg_logprob=-0.1,
                            words=[
                                SimpleNamespace(
                                    start=0.2,
                                    end=0.7,
                                    word="你好",
                                    probability=0.96,
                                ),
                                SimpleNamespace(
                                    start=0.7,
                                    end=1.5,
                                    word="世界",
                                    probability=0.91,
                                ),
                            ],
                        )
                    ]
                ),
                SimpleNamespace(language="zh"),
            )

    monkeypatch.setattr(
        "viral_dna_api.local_providers._load_whisper_model",
        lambda *args: FakeModel(),
    )
    result = await FasterWhisperASRProvider("fixture").transcribe(audio_path)

    assert result.language == "zh"
    assert len(result.segments) == 1
    assert result.segments[0].text == "你好 世界"
    assert result.segments[0].start_seconds == 0.2
    assert [word.text for word in result.segments[0].words] == ["你好", "世界"]
    assert result.segments[0].words[0].confidence == pytest.approx(0.96)


@pytest.mark.asyncio
async def test_rapidocr_maps_text_score_and_normalized_box(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame_path = tmp_path / "shot.jpg"
    frame_path.write_bytes(b"jpg")
    captured: dict[str, float] = {}

    class FakeEngine:
        def __call__(self, path: Path, *, text_score: float):
            assert path == frame_path
            captured["threshold"] = text_score
            return SimpleNamespace(
                txts=("画面字幕", "低置信度"),
                scores=(0.98, 0.2),
                boxes=(
                    ((10, 20), (90, 20), (90, 40), (10, 40)),
                    ((0, 0), (10, 0), (10, 10), (0, 10)),
                ),
                img=SimpleNamespace(shape=(100, 200, 3)),
            )

    monkeypatch.setenv("VIRAL_DNA_OCR_MIN_CONFIDENCE", "0.55")
    monkeypatch.setattr(
        "viral_dna_api.local_providers._load_rapidocr_engine",
        lambda: FakeEngine(),
    )
    provider = RapidOCRProvider()
    result = await provider.recognize(
        [
            OCRFrame(
                shot_id="shot_001",
                timestamp_seconds=1.25,
                path=frame_path,
                url="/frame.jpg",
            )
        ]
    )

    assert captured["threshold"] == 0.55
    assert len(result) == 1
    assert result[0].text == "画面字幕"
    assert result[0].confidence == pytest.approx(0.98)
    assert result[0].bounding_box == [0.05, 0.2, 0.45, 0.4]
    assert result[0].shot_id == "shot_001"


def test_environment_factories_select_local_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("VIRAL_DNA_ASR_MODEL", "base")
    monkeypatch.setenv("VIRAL_DNA_OCR_PROVIDER", "rapidocr")

    asr = asr_provider_from_environment()
    ocr = ocr_provider_from_environment()

    assert isinstance(asr, FasterWhisperASRProvider)
    assert asr.model_id == "base"
    assert isinstance(ocr, RapidOCRProvider)
