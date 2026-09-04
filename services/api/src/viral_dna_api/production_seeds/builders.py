from __future__ import annotations

import hashlib
import math
import re
from typing import Any
from uuid import UUID

from ..models import AnalysisReport, Video
from .contracts import (
    ProductionSeed,
    ProductionSeedAudioIntent,
    ProductionSeedOrigin,
    ProductionSeedReference,
    ProductionSeedShot,
    ProductionSeedSubtitleIntent,
    canonical_digest,
    seconds_to_frame,
)


def _stable_key(namespace: str, value: str) -> str:
    digest = hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()[:20]
    return f"shot_{digest}"


def _normalized_ratio(value: str | None, width: int, height: int) -> str:
    if value and re.fullmatch(r"\d{1,5}:\d{1,5}", value):
        return value
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _seal(payload: dict[str, Any]) -> ProductionSeed:
    draft = ProductionSeed.model_construct(**payload, content_hash="sha256:" + "0" * 64)
    materialized = draft.model_dump(mode="python")
    materialized["content_hash"] = canonical_digest(draft)
    return ProductionSeed.model_validate(materialized)


class AnalysisProductionSeedBuilder:
    """Adapter that preserves the current analysis semantics behind a stable seed."""

    def build(
        self,
        *,
        owner_project_id: UUID,
        record_name: str,
        video: Video,
        report: AnalysisReport,
        output_aspect_ratio: str,
        output_width: int,
        output_height: int,
        fps: int = 30,
    ) -> ProductionSeed:
        prompt_shots = {item.shot_id: item for item in report.prompt_package.shots}
        shots: list[ProductionSeedShot] = []
        for order, shot in enumerate(sorted(report.shots, key=lambda item: item.index), start=1):
            prompt_shot = prompt_shots.get(shot.id)
            start_frame = max(0, seconds_to_frame(shot.start_seconds, fps))
            end_frame = max(start_frame + 1, seconds_to_frame(shot.end_seconds, fps))
            duration = max(0.01, shot.end_seconds - shot.start_seconds)
            image_prompt = prompt_shot.prompt if prompt_shot is not None else shot.prompt
            image_negative = (
                prompt_shot.negative_constraints
                if prompt_shot is not None
                else report.prompt_package.negative_constraints
            )
            shot_payload = {
                "stable_shot_key": _stable_key(str(owner_project_id), shot.id),
                "order": order,
                "narrative_role": "analysis",
                "start_frame": start_frame,
                "duration_frames": end_frame - start_frame,
                "source_start_frame": start_frame,
                "source_duration_frames": end_frame - start_frame,
                "description": shot.title,
                "image_prompt": image_prompt,
                "image_negative_constraints": list(image_negative),
                "video_prompt": (
                    f"{shot.prompt}；动作过程：{shot.action}；"
                    f"运镜：{shot.camera}；持续 {duration:.2f} 秒。"
                ),
                "video_negative_constraints": list(report.prompt_package.negative_constraints),
                "output_mode": "image_to_video",
                "source_keyframe_url": shot.keyframe_url,
            }
            shot_payload["input_hash"] = canonical_digest(shot_payload)
            shots.append(ProductionSeedShot.model_validate(shot_payload))
        payload: dict[str, Any] = {
            "owner_project_id": owner_project_id,
            "origin_type": ProductionSeedOrigin.ANALYSIS,
            "origin_id": report.analysis_id,
            "name": f"{record_name} 复刻方案",
            "output_aspect_ratio": _normalized_ratio(
                output_aspect_ratio,
                output_width,
                output_height,
            ),
            "output_width": output_width,
            "output_height": output_height,
            "fps": fps,
            "source_video_id": video.id,
            "source_analysis_id": report.analysis_id,
            "source_prompt_package_id": report.prompt_package.id,
            "style_bible_snapshot": {},
            "reference_assets": [],
            "shots": shots,
            "audio_intent": ProductionSeedAudioIntent(
                clip_audio_strategy="source",
            ),
            "subtitle_intent": ProductionSeedSubtitleIntent(
                enabled=False,
                source="none",
            ),
        }
        return _seal(payload)


class SkillProductionSeedBuilder:
    def build(
        self,
        *,
        owner_project_id: UUID,
        skill_run_id: UUID,
        name: str,
        output_aspect_ratio: str,
        output_width: int,
        output_height: int,
        fps: int,
        style_bible_revision_id: UUID,
        style_bible_snapshot: dict[str, Any],
        shots: list[ProductionSeedShot],
        reference_assets: list[ProductionSeedReference],
        audio_intent: ProductionSeedAudioIntent,
        subtitle_intent: ProductionSeedSubtitleIntent,
    ) -> ProductionSeed:
        payload: dict[str, Any] = {
            "owner_project_id": owner_project_id,
            "origin_type": ProductionSeedOrigin.SKILL_RUN,
            "origin_id": skill_run_id,
            "name": name,
            "output_aspect_ratio": output_aspect_ratio,
            "output_width": output_width,
            "output_height": output_height,
            "fps": fps,
            "style_bible_revision_id": style_bible_revision_id,
            "style_bible_snapshot": style_bible_snapshot,
            "reference_assets": reference_assets,
            "shots": shots,
            "audio_intent": audio_intent,
            "subtitle_intent": subtitle_intent,
        }
        return _seal(payload)
