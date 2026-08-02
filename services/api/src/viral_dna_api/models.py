from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceType(StrEnum):
    UPLOAD = "upload"
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"


class VideoStatus(StrEnum):
    READY = "ready"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisMode(StrEnum):
    SIMULATED = "simulated"
    MEDIA_EVIDENCE = "media_evidence"
    MODEL = "model"


class AnalysisStage(StrEnum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    PREPROCESSING = "preprocessing"
    SEGMENTING = "segmenting"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    REASONING = "reasoning"
    COMPILING_PROMPTS = "compiling_prompts"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class LinkVideoCreate(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=120)
    target_model: str = Field(default="seedance", max_length=40)
    rights_confirmed: bool


class Video(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    source_url: str | None = None
    resolved_source_url: str | None = None
    source_video_id: str | None = None
    source_author: str | None = None
    ingested_at: datetime | None = None
    original_filename: str | None = None
    stored_path: str | None = Field(default=None, exclude=True)
    title: str
    target_model: str = "seedance"
    status: VideoStatus = VideoStatus.READY
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sha256: str | None = None
    has_audio: bool | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AnalysisCreate(BaseModel):
    granularity: Literal["standard", "fine"] = "fine"
    include_audio: bool = True
    include_ocr: bool = True


class AnalysisError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AnalysisJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    analysis_version: str = "phase1-simulated-v1"
    analysis_mode: AnalysisMode = AnalysisMode.SIMULATED
    granularity: Literal["standard", "fine"] = "fine"
    include_audio: bool = True
    include_ocr: bool = True
    stage: AnalysisStage = AnalysisStage.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    message: str = "等待分析"
    simulated: bool = True
    error: AnalysisError | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class Shot(BaseModel):
    id: str
    index: int
    start_seconds: float
    end_seconds: float
    title: str
    subjects: list[str]
    action: str
    scene: str
    camera: str
    composition: str
    lighting: str
    color: str
    dialogue: str | None = None
    subtitle_text: str | None = None
    ocr_text: str | None = None
    audio: str
    transition: str
    narrative_role: str
    prompt: str
    confidence: float = Field(ge=0, le=1)
    keyframe_url: str | None = None
    evidence_frame_urls: list[str] = Field(default_factory=list)
    evidence_kind: Literal["simulated", "measured", "model"] = "simulated"


class Entity(BaseModel):
    id: str
    type: Literal["person", "wardrobe", "scene", "product", "prop", "style"]
    name: str
    description: str
    occurrence_shot_ids: list[str]
    replaceable_fields: list[str]
    confidence: float = Field(ge=0, le=1)


class ViralFinding(BaseModel):
    id: str
    type: str
    title: str
    score: int = Field(ge=0, le=100)
    start_seconds: float
    end_seconds: float
    observation: str
    mechanism: str
    expected_effect: str
    recommendation: str
    confidence: float = Field(ge=0, le=1)


class PromptShot(BaseModel):
    shot_id: str
    duration_seconds: float
    prompt: str
    negative_constraints: list[str]


class PromptPackage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    version: int = 1
    target_model: str
    aspect_ratio: str = "9:16"
    global_prompt: str
    continuity_locks: list[str]
    entities: dict[str, str]
    shots: list[PromptShot]
    negative_constraints: list[str]
    created_at: datetime = Field(default_factory=utc_now)


class VideoOverview(BaseModel):
    summary: str
    content_type: str
    narrative_structure: str
    audience_inference: str
    visual_style: str
    duration_seconds: float
    aspect_ratio: str
    viral_potential_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)


class SubtitleStream(BaseModel):
    index: int = Field(ge=0)
    codec_name: str = Field(min_length=1, max_length=80)
    language: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=200)
    extractable: bool = False


class MediaMetadata(BaseModel):
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation: int = 0
    fps: float = Field(ge=0)
    format_name: str
    video_codec: str
    audio_codec: str | None = None
    has_audio: bool
    size_bytes: int = Field(gt=0)
    bit_rate: int | None = Field(default=None, ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    aspect_ratio: str
    subtitle_streams: list[SubtitleStream] = Field(default_factory=list)


class ShotEvidence(BaseModel):
    shot_id: str
    index: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    representative_timestamp: float = Field(ge=0)
    keyframe_url: str
    detection_method: str


class MediaEvidence(BaseModel):
    processor_version: str
    metadata: MediaMetadata
    proxy_url: str
    audio_url: str | None = None
    subtitle_url: str | None = None
    subtitle_extraction_message: str | None = Field(default=None, max_length=500)
    contact_sheet_url: str | None = None
    manifest_url: str
    shots: list[ShotEvidence]


class EvidenceProviderStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class EvidenceProviderRun(BaseModel):
    kind: Literal["asr", "ocr", "subtitle"]
    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    status: EvidenceProviderStatus
    item_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    message: str | None = Field(default=None, max_length=500)


class TranscriptWord(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def end_after_start(self) -> TranscriptWord:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("词级转写结束时间必须晚于开始时间")
        return self


class TranscriptSegment(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[TranscriptWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def end_after_start(self) -> TranscriptSegment:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("转写片段结束时间必须晚于开始时间")
        return self


class SubtitleCue(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=20)
    stream_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def end_after_start(self) -> SubtitleCue:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("字幕结束时间必须晚于开始时间")
        return self


class OCRObservation(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    timestamp_seconds: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: list[float] | None = Field(default=None, min_length=4, max_length=4)
    shot_id: str | None = Field(default=None, max_length=80)
    frame_url: str | None = None


class ShotTimelineEvidence(BaseModel):
    shot_id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    transcript_segment_ids: list[str] = Field(default_factory=list)
    transcript_text: str | None = None
    subtitle_cue_ids: list[str] = Field(default_factory=list)
    subtitle_text: str | None = None
    ocr_observation_ids: list[str] = Field(default_factory=list)
    ocr_text: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> ShotTimelineEvidence:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("镜头时间线结束时间必须晚于开始时间")
        return self


class EvidenceTimeline(BaseModel):
    timeline_version: str = "phase1-evidence-timeline-v2"
    duration_seconds: float = Field(gt=0)
    language: str | None = Field(default=None, max_length=20)
    provider_runs: list[EvidenceProviderRun]
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    subtitle_cues: list[SubtitleCue] = Field(default_factory=list)
    ocr_observations: list[OCRObservation] = Field(default_factory=list)
    shots: list[ShotTimelineEvidence]
    warnings: list[str] = Field(default_factory=list)
    artifact_url: str


class AnalysisReport(BaseModel):
    video_id: UUID
    analysis_id: UUID
    analysis_mode: AnalysisMode = AnalysisMode.SIMULATED
    overview: VideoOverview
    shots: list[Shot]
    entities: list[Entity]
    viral_findings: list[ViralFinding]
    prompt_package: PromptPackage
    media_evidence: MediaEvidence | None = None
    evidence_timeline: EvidenceTimeline | None = None
    generated_at: datetime = Field(default_factory=utc_now)


class ReplacementItem(BaseModel):
    entity_id: str
    description: str = Field(min_length=2, max_length=500)


class ReplacementCreate(BaseModel):
    replacements: list[ReplacementItem] = Field(min_length=1, max_length=10)
    locks: list[Literal["timing", "camera", "composition", "action", "lighting", "audio"]] = Field(
        default_factory=lambda: ["timing", "camera", "composition", "action"]
    )

    @model_validator(mode="after")
    def unique_entities(self) -> ReplacementCreate:
        ids = [item.entity_id for item in self.replacements]
        if len(ids) != len(set(ids)):
            raise ValueError("同一元素不能重复替换")
        return self


class ReplacementDiff(BaseModel):
    entity_id: str
    before: str
    after: str
    affected_shot_ids: list[str]


class ReplacementVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    source_prompt_package_id: UUID
    prompt_package: PromptPackage
    diffs: list[ReplacementDiff]
    locks: list[str]
    created_at: datetime = Field(default_factory=utc_now)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "viral-dna-api"
    version: str = "0.1.0"
    analyzer_mode: str


class ApiMessage(BaseModel):
    message: str
    details: dict[str, Any] | None = None
