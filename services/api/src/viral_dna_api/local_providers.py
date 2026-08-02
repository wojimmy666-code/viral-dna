from __future__ import annotations

import asyncio
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .evidence import ASRProviderResult, EvidenceProviderUnavailable, OCRFrame
from .models import OCRObservation, TranscriptSegment, TranscriptWord

DEFAULT_ASR_MODEL = "small"
DEFAULT_OCR_MODEL = "pp-ocrv6-small"


def _bounded_confidence(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def _confidence_from_log_probability(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, math.exp(number)))


def _optional_environment(key: str) -> str | None:
    return os.getenv(key, "").strip() or None


@lru_cache(maxsize=4)
def _load_whisper_model(
    model_id: str,
    device: str,
    compute_type: str,
    download_root: str | None,
):
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:  # pragma: no cover - depends on optional installation
        raise EvidenceProviderUnavailable(
            "缺少 faster-whisper；请安装 API 的 local-ai 可选依赖"
        ) from error

    kwargs: dict[str, Any] = {
        "device": device,
        "compute_type": compute_type,
    }
    if download_root:
        Path(download_root).mkdir(parents=True, exist_ok=True)
        kwargs["download_root"] = download_root
    return WhisperModel(model_id, **kwargs)


class FasterWhisperASRProvider:
    provider_id = "faster-whisper"
    enabled = True

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or DEFAULT_ASR_MODEL
        self.device = os.getenv("VIRAL_DNA_ASR_DEVICE", "cpu").strip() or "cpu"
        self.compute_type = (
            os.getenv("VIRAL_DNA_ASR_COMPUTE_TYPE", "int8").strip() or "int8"
        )
        self.language = _optional_environment("VIRAL_DNA_ASR_LANGUAGE")
        self.model_dir = _optional_environment("VIRAL_DNA_ASR_MODEL_DIR")

    async def transcribe(self, audio_path: Path) -> ASRProviderResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> ASRProviderResult:
        model = _load_whisper_model(
            self.model_id,
            self.device,
            self.compute_type,
            self.model_dir,
        )
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=self.language,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        language = str(getattr(info, "language", "") or self.language or "").strip() or None
        segments: list[TranscriptSegment] = []
        for index, raw_segment in enumerate(raw_segments, 1):
            text = " ".join(str(getattr(raw_segment, "text", "")).split())[:4000]
            start = float(getattr(raw_segment, "start", 0.0) or 0.0)
            end = float(getattr(raw_segment, "end", 0.0) or 0.0)
            if not text or start < 0 or end <= start:
                continue

            words: list[TranscriptWord] = []
            for raw_word in getattr(raw_segment, "words", None) or []:
                word_text = str(getattr(raw_word, "word", "")).strip()[:200]
                word_start = getattr(raw_word, "start", None)
                word_end = getattr(raw_word, "end", None)
                if not word_text or word_start is None or word_end is None:
                    continue
                word_start_number = float(word_start)
                word_end_number = float(word_end)
                if word_start_number < 0 or word_end_number <= word_start_number:
                    continue
                words.append(
                    TranscriptWord(
                        start_seconds=round(word_start_number, 3),
                        end_seconds=round(word_end_number, 3),
                        text=word_text,
                        confidence=_bounded_confidence(getattr(raw_word, "probability", None)),
                    )
                )

            segments.append(
                TranscriptSegment(
                    id=f"asr_{index:04d}",
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                    text=text,
                    language=language,
                    confidence=_confidence_from_log_probability(
                        getattr(raw_segment, "avg_logprob", None)
                    ),
                    words=words,
                )
            )
        return ASRProviderResult(language=language, segments=segments)


@lru_cache(maxsize=1)
def _load_rapidocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as error:  # pragma: no cover - depends on optional installation
        raise EvidenceProviderUnavailable(
            "缺少 rapidocr/onnxruntime；请安装 API 的 local-ai 可选依赖"
        ) from error
    return RapidOCR()


class RapidOCRProvider:
    provider_id = "rapidocr"
    enabled = True

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or DEFAULT_OCR_MODEL
        raw_threshold = os.getenv("VIRAL_DNA_OCR_MIN_CONFIDENCE", "0.55")
        try:
            threshold = float(raw_threshold)
        except ValueError:
            threshold = 0.55
        self.min_confidence = max(0.0, min(1.0, threshold))

    async def recognize(self, frames: list[OCRFrame]) -> list[OCRObservation]:
        return await asyncio.to_thread(self._recognize_sync, frames)

    def _recognize_sync(self, frames: list[OCRFrame]) -> list[OCRObservation]:
        engine = _load_rapidocr_engine()
        observations: list[OCRObservation] = []
        for frame_index, frame in enumerate(frames, 1):
            if not frame.path.is_file():
                continue
            output = engine(frame.path, text_score=self.min_confidence)
            raw_texts = getattr(output, "txts", None)
            raw_scores = getattr(output, "scores", None)
            raw_boxes = getattr(output, "boxes", None)
            texts = list(raw_texts) if raw_texts is not None else []
            scores = list(raw_scores) if raw_scores is not None else []
            boxes = list(raw_boxes) if raw_boxes is not None else []
            image = getattr(output, "img", None)
            shape = getattr(image, "shape", None)
            height = float(shape[0]) if shape and len(shape) >= 2 else 0.0
            width = float(shape[1]) if shape and len(shape) >= 2 else 0.0

            for item_index, text_value in enumerate(texts, 1):
                text = " ".join(str(text_value).split())[:2000]
                score = scores[item_index - 1] if item_index <= len(scores) else None
                confidence = _bounded_confidence(score)
                if not text or (confidence is not None and confidence < self.min_confidence):
                    continue
                box = boxes[item_index - 1] if item_index <= len(boxes) else None
                observations.append(
                    OCRObservation(
                        id=f"ocr_{frame_index:03d}_{item_index:03d}",
                        timestamp_seconds=frame.timestamp_seconds,
                        text=text,
                        confidence=confidence,
                        bounding_box=_normalized_box(box, width=width, height=height),
                        shot_id=frame.shot_id,
                        frame_url=frame.url,
                    )
                )
        return observations


def _normalized_box(box: object, *, width: float, height: float) -> list[float] | None:
    if box is None or width <= 0 or height <= 0:
        return None
    try:
        points = list(box)  # type: ignore[arg-type]
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return [
        round(max(0.0, min(1.0, min(xs) / width)), 4),
        round(max(0.0, min(1.0, min(ys) / height)), 4),
        round(max(0.0, min(1.0, max(xs) / width)), 4),
        round(max(0.0, min(1.0, max(ys) / height)), 4),
    ]
