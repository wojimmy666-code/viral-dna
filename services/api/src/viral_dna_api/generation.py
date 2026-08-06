from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageDraw, ImageOps

from .models import (
    GenerationCandidate,
    GenerationKind,
    GenerationRun,
    ImageGenerationInputMode,
    ProductionProject,
    ProductionRunStatus,
    ReferenceAsset,
    ReferenceBinding,
    ShotPlan,
)
from .workspace import WorkspaceManager

SIMULATED_PROVIDER = "simulated"
SIMULATED_MODEL = "source-keyframe-copy"
SIMULATED_MODEL_SNAPSHOT = "batch4.1-simulated-image-v1"
SIMULATED_PROMPT_VERSION = "shot-image-v1"
SIMULATED_SCHEMA_VERSION = "generation-request-v1"
SIMULATED_PRICING_VERSION = "zero-cost-v1"


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    extended_prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(extended_prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{extended_prefix}UNC{separator}{raw[2:]}")
    return Path(f"{extended_prefix}{raw}")


def _write_atomic(destination: Path, payload: bytes) -> None:
    filesystem_destination = _filesystem_path(destination)
    filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = filesystem_destination.parent / f".tmp-{uuid4().hex[:8]}"
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, filesystem_destination)
    finally:
        temporary.unlink(missing_ok=True)


def _fit_fallback_dimensions(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1440 / max(width, height))
    return max(256, round(width * scale)), max(256, round(height * scale))


def _candidate_image(
    source_path: Path | None,
    project: ProductionProject,
    ordinal: int,
) -> Image.Image:
    image: Image.Image
    if source_path is not None and source_path.is_file():
        try:
            with Image.open(source_path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except OSError:
            source_path = None
    if source_path is None:
        width, height = _fit_fallback_dimensions(
            project.output_width,
            project.output_height,
        )
        image = Image.new("RGB", (width, height), (237, 234, 255))
        draw = ImageDraw.Draw(image)
        step = max(36, min(width, height) // 12)
        for offset in range(-height, width, step * 2):
            draw.line(
                (offset, height, offset + height, 0),
                fill=(217, 210, 255),
                width=max(8, step // 3),
            )

    draw = ImageDraw.Draw(image, "RGBA")
    label = f"SIMULATED  {ordinal}"
    box_width = min(image.width - 32, max(180, len(label) * 13 + 32))
    box_height = 48
    left = 16
    top = max(16, image.height - box_height - 16)
    draw.rounded_rectangle(
        (left, top, left + box_width, top + box_height),
        radius=12,
        fill=(34, 27, 67, 196),
    )
    draw.text((left + 16, top + 16), label, fill=(255, 255, 255, 255))
    return image


def build_generation_input(
    project: ProductionProject,
    plan: ShotPlan,
    revision_id: UUID,
    bindings: list[ReferenceBinding],
    assets: list[ReferenceAsset],
    input_mode: ImageGenerationInputMode = ImageGenerationInputMode.KEYFRAME_EDIT,
) -> dict[str, object]:
    assets_by_id = {asset.id: asset for asset in assets}
    return {
        "schema_version": SIMULATED_SCHEMA_VERSION,
        "project_id": str(project.id),
        "shot_plan_id": str(plan.id),
        "revision_id": str(revision_id),
        "input_mode": input_mode.value,
        "output": {
            "aspect_ratio": project.output_aspect_ratio,
            "width": project.output_width,
            "height": project.output_height,
        },
        "source_keyframe_url": (
            plan.source_keyframe_url
            if input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
            else None
        ),
        "image_prompt": plan.image_prompt,
        "image_prompt_mentions": [
            {
                "asset_id": str(item.reference_asset_id),
                "label": item.label,
            }
            for item in plan.image_prompt_mentions
        ],
        "image_negative_constraints": plan.image_negative_constraints,
        "locks": [item.value for item in plan.locks],
        "references": [
            {
                "asset_id": str(binding.reference_asset_id),
                "name": assets_by_id[binding.reference_asset_id].name,
                "role": binding.role.value,
                "weight": binding.weight,
                "crop_hint": binding.crop_hint,
                "notes": binding.notes,
                "sha256": assets_by_id[binding.reference_asset_id].sha256,
            }
            for binding in (
                bindings
                if input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
                else []
            )
            if binding.reference_asset_id in assets_by_id
        ],
    }


def generate_simulated_images(
    workspace: WorkspaceManager,
    project: ProductionProject,
    plan: ShotPlan,
    revision_id: UUID,
    bindings: list[ReferenceBinding],
    assets: list[ReferenceAsset],
    *,
    candidate_count: int,
    source_path: Path | None,
    input_mode: ImageGenerationInputMode = ImageGenerationInputMode.KEYFRAME_EDIT,
    run_id: UUID | None = None,
) -> tuple[GenerationRun, list[GenerationCandidate]]:
    started = time.perf_counter()
    input_payload = build_generation_input(
        project,
        plan,
        revision_id,
        bindings,
        assets,
        input_mode,
    )
    fingerprint = hashlib.sha256(_canonical_json(input_payload)).hexdigest()
    run_id = run_id or uuid4()
    run_root = (
        workspace.production_shot_root(project.record_id, project.id, plan.id)
        / "images"
        / str(run_id)
    )
    input_path = run_root / "input.json"
    _write_atomic(input_path, _canonical_json(input_payload) + bytes([10]))

    candidates: list[GenerationCandidate] = []
    for ordinal in range(1, candidate_count + 1):
        image = _candidate_image(source_path, project, ordinal)
        image_output = BytesIO()
        image.save(image_output, format="JPEG", quality=92, optimize=True)
        image_payload = image_output.getvalue()

        thumbnail = image.copy()
        thumbnail.thumbnail((640, 640), Image.Resampling.LANCZOS)
        thumbnail_output = BytesIO()
        thumbnail.save(thumbnail_output, format="WEBP", quality=84, method=4)

        candidate_path = run_root / f"candidate_{ordinal:03d}.jpg"
        thumbnail_path = run_root / f"candidate_{ordinal:03d}.webp"
        metadata_path = run_root / f"candidate_{ordinal:03d}.json"
        sha256 = hashlib.sha256(image_payload).hexdigest()
        metadata = {
            "simulated": True,
            "ordinal": ordinal,
            "source_keyframe_url": plan.source_keyframe_url,
            "request_fingerprint": fingerprint,
            "sha256": sha256,
        }
        _write_atomic(candidate_path, image_payload)
        _write_atomic(thumbnail_path, thumbnail_output.getvalue())
        _write_atomic(metadata_path, _canonical_json(metadata) + bytes([10]))
        candidates.append(
            GenerationCandidate(
                generation_run_id=run_id,
                ordinal=ordinal,
                kind=GenerationKind.IMAGE,
                relative_path=workspace.relative(candidate_path),
                thumbnail_relative_path=workspace.relative(thumbnail_path),
                width=image.width,
                height=image.height,
                sha256=sha256,
                metadata_relative_path=workspace.relative(metadata_path),
            )
        )

    completed_at = datetime.now(UTC)
    run = GenerationRun(
        id=run_id,
        project_id=project.id,
        shot_plan_id=plan.id,
        revision_id=revision_id,
        kind=GenerationKind.IMAGE,
        input_mode=input_mode,
        provider=SIMULATED_PROVIDER,
        model=SIMULATED_MODEL,
        model_snapshot=SIMULATED_MODEL_SNAPSHOT,
        prompt_version=SIMULATED_PROMPT_VERSION,
        schema_version=SIMULATED_SCHEMA_VERSION,
        pricing_version=SIMULATED_PRICING_VERSION,
        request_fingerprint=fingerprint,
        input_snapshot_relative_path=workspace.relative(input_path),
        status=ProductionRunStatus.COMPLETED,
        estimated_cost_micros=0,
        actual_cost_micros=0,
        latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
        completed_at=completed_at,
    )
    return run, candidates
