from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from viral_dna_api.models import (
    ProductionOriginType,
    ProductionProject,
    ReferenceAsset,
    ReferenceAssetType,
)
from viral_dna_api.production import ProductionService
from viral_dna_api.production_seeds import (
    ProductionSeed,
    ProductionSeedAudioIntent,
    ProductionSeedReference,
    ProductionSeedShot,
    ProductionSeedSubtitleIntent,
    SkillProductionSeedBuilder,
    canonical_digest,
    seconds_to_frame,
)
from viral_dna_api.production_seeds.contracts import ExactOverlayInstruction


def test_integer_frame_projection_and_skill_seed_integrity() -> None:
    assert seconds_to_frame(2.667, 30) == 80
    assert seconds_to_frame(0.5, 25) == 13

    project_id = uuid4()
    run_id = uuid4()
    style_id = uuid4()
    shot_payload = {
        "stable_shot_key": "shot_12345678",
        "order": 1,
        "start_frame": 0,
        "duration_frames": 80,
        "description": "hero",
        "image_prompt": "static product hero",
        "video_prompt": "slow push in",
    }
    shot_payload["input_hash"] = canonical_digest(shot_payload)
    seed = SkillProductionSeedBuilder().build(
        owner_project_id=project_id,
        skill_run_id=run_id,
        name="Seed",
        output_aspect_ratio="9:16",
        output_width=1080,
        output_height=1920,
        fps=30,
        style_bible_revision_id=style_id,
        style_bible_snapshot={"palette": "brand"},
        shots=[ProductionSeedShot.model_validate(shot_payload)],
        reference_assets=[],
        audio_intent=ProductionSeedAudioIntent(clip_audio_strategy="candidate"),
        subtitle_intent=ProductionSeedSubtitleIntent(enabled=True, source="final_speech"),
    )

    assert seed.origin_type == "skill_run"
    assert seed.source_video_id is None
    assert seed.shots[0].duration_frames == 80
    assert canonical_digest(seed) == seed.content_hash

    tampered = seed.model_dump(mode="python")
    tampered["name"] = "tampered"
    with pytest.raises(ValidationError):
        ProductionSeed.model_validate(tampered)


def test_skill_seed_maps_reference_assets_and_exact_overlays_into_shot_plans() -> None:
    owner_project_id = uuid4()
    run_id = uuid4()
    style_id = uuid4()
    product_usage_id = uuid4()
    logo_usage_id = uuid4()
    shot_payload = {
        "stable_shot_key": "shot_seedrefs01",
        "order": 1,
        "start_frame": 0,
        "duration_frames": 90,
        "description": "product hero",
        "image_prompt": "static product hero with clean logo-safe area",
        "video_prompt": "slow push in from the accepted product image",
        "image_asset_usage_ids": [product_usage_id],
        "exact_overlays": [
            ExactOverlayInstruction(
                asset_usage_id=logo_usage_id,
                placement="bottom_right",
                start_frame=0,
                end_frame=90,
            )
        ],
    }
    shot_payload["input_hash"] = canonical_digest(shot_payload)
    seed = SkillProductionSeedBuilder().build(
        owner_project_id=owner_project_id,
        skill_run_id=run_id,
        name="Seed references",
        output_aspect_ratio="9:16",
        output_width=1080,
        output_height=1920,
        fps=30,
        style_bible_revision_id=style_id,
        style_bible_snapshot={"palette": "brand"},
        shots=[ProductionSeedShot.model_validate(shot_payload)],
        reference_assets=[
            ProductionSeedReference(
                id=product_usage_id,
                asset_id=uuid4(),
                role="product_hero",
                name="Product",
                sha256="a" * 64,
                fidelity="identity_lock",
                rights_status="confirmed",
            ),
            ProductionSeedReference(
                id=logo_usage_id,
                asset_id=uuid4(),
                role="logo",
                name="Logo",
                sha256="b" * 64,
                fidelity="exact",
                rights_status="confirmed",
            ),
        ],
        audio_intent=ProductionSeedAudioIntent(clip_audio_strategy="candidate"),
        subtitle_intent=ProductionSeedSubtitleIntent(enabled=True, source="final_speech"),
    )
    project = ProductionProject(
        record_id=owner_project_id,
        owner_project_id=owner_project_id,
        origin_type=ProductionOriginType.SKILL_RUN,
        origin_id=run_id,
        production_seed_id=seed.id,
        style_bible_revision_id=style_id,
        name=seed.name,
        output_aspect_ratio=seed.output_aspect_ratio,
        output_width=seed.output_width,
        output_height=seed.output_height,
    )
    product_reference = ReferenceAsset(
        id=seed.reference_assets[0].asset_id,
        project_id=project.id,
        type=ReferenceAssetType.PRODUCT,
        name="Product",
        relative_path="objects/product.png",
        mime_type="image/png",
        width=800,
        height=800,
        sha256="a" * 64,
        rights_confirmed=True,
    )
    logo_reference = ReferenceAsset(
        id=seed.reference_assets[1].asset_id,
        project_id=project.id,
        type=ReferenceAssetType.PROP,
        name="Logo",
        relative_path="objects/logo.png",
        mime_type="image/png",
        width=400,
        height=200,
        sha256="b" * 64,
        rights_confirmed=True,
    )

    plans = ProductionService._shot_plans_from_seed(
        project,
        seed,
        uuid4(),
        {
            product_usage_id: product_reference,
            logo_usage_id: logo_reference,
        },
    )

    assert len(plans) == 1
    assert plans[0].stable_shot_key == "shot_seedrefs01"
    assert plans[0].source_keyframe_relative_path == "objects/product.png"
    assert plans[0].image_prompt_mentions[0].reference_asset_id == product_reference.id
    assert plans[0].exact_overlay_instructions[0]["asset_id"] == str(
        logo_reference.id
    )
    assert plans[0].exact_overlay_instructions[0]["asset_sha256"] == "b" * 64
