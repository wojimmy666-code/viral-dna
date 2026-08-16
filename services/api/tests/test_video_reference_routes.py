from __future__ import annotations

from uuid import uuid4

import pytest

from viral_dna_api.reference_routes import (
    IdentityReferenceTransport,
    MotionReferenceSemantics,
    MotionReferenceTransport,
    VideoReferenceRouteId,
    resolve_reference_route,
)
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.contracts import ProviderVideoRequest
from viral_dna_api.video_generation.errors import VideoProviderError
from viral_dna_api.video_generation.providers.bailian.request_mapper import (
    build_bailian_request,
)


def _resolve(alias: str, **overrides: bool):
    capability = load_video_model_catalog().option(
        alias,
        require_available=False,
    ).capability.reference_route
    inputs = {
        "has_managed_identity": False,
        "has_raw_reference_image": True,
        "has_pose_proxy_image": False,
        "has_motion_proxy_video": False,
        "public_media_transport_ready": False,
    }
    inputs.update(overrides)
    return resolve_reference_route(capability, **inputs)


def test_seedance_requires_managed_actor_and_never_uses_raw_identity() -> None:
    blocked = _resolve("seedance_2_0")
    assert blocked.generation_allowed is False
    assert blocked.blocker_code == "video_managed_identity_required"

    resolved = _resolve(
        "seedance_2_0",
        has_managed_identity=True,
        has_motion_proxy_video=True,
        public_media_transport_ready=True,
    )
    assert resolved.generation_allowed is True
    assert resolved.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET
    assert resolved.identity_source == "provider_managed_asset"
    assert resolved.motion_transport == MotionReferenceTransport.REFERENCE_VIDEO
    assert resolved.motion_source == "motion_proxy_video"
    assert resolved.motion_semantics == MotionReferenceSemantics.GUIDED_REFERENCE


def test_minimax_h3_uses_video_when_transport_is_ready_and_falls_back_honestly() -> None:
    primary = _resolve(
        "minimax_h3",
        has_motion_proxy_video=True,
        public_media_transport_ready=True,
    )
    assert primary.generation_allowed is True
    assert primary.fallback_applied is False
    assert primary.motion_source == "motion_proxy_video"
    assert primary.motion_semantics == MotionReferenceSemantics.GUIDED_REFERENCE

    fallback = _resolve("minimax_h3")
    assert fallback.generation_allowed is True
    assert fallback.fallback_applied is True
    assert fallback.effective_route_id == VideoReferenceRouteId.POSE_IMAGE_TEXT_FALLBACK
    assert fallback.motion_source == "prompt_motion_description"
    assert fallback.motion_semantics == MotionReferenceSemantics.SUGGESTIVE
    assert fallback.warnings

    transport_fallback = _resolve("minimax_h3", has_motion_proxy_video=True)
    assert transport_fallback.generation_allowed is True
    assert transport_fallback.fallback_applied is True
    assert transport_fallback.motion_source == "prompt_motion_description"
    assert any("公网媒体 URL" in warning for warning in transport_fallback.warnings)


def test_hailuo_never_exposes_video_proxy_transport() -> None:
    route = _resolve("minimax_hailuo_2_3", has_motion_proxy_video=True)
    capability = load_video_model_catalog().option(
        "minimax_hailuo_2_3"
    ).capability.reference_route

    assert capability.show_motion_proxy_controls is False
    assert capability.supports_motion_proxy_video is False
    assert route.motion_transport == MotionReferenceTransport.POSE_IMAGE_TEXT
    assert route.motion_source == "prompt_motion_description"


def test_wan_vace_stays_reserved_until_public_media_transport_exists() -> None:
    capability = load_video_model_catalog().option(
        "bailian_wan_vace_posebody",
        require_available=False,
    ).capability.reference_route.model_copy(update={"enabled": True})

    blocked = resolve_reference_route(
        capability,
        has_managed_identity=False,
        has_raw_reference_image=True,
        has_pose_proxy_image=False,
        has_motion_proxy_video=True,
        public_media_transport_ready=False,
    )
    assert blocked.generation_allowed is False
    assert blocked.blocker_code == "video_public_media_transport_required"

    resolved = resolve_reference_route(
        capability,
        has_managed_identity=False,
        has_raw_reference_image=True,
        has_pose_proxy_image=False,
        has_motion_proxy_video=True,
        public_media_transport_ready=True,
    )
    assert resolved.generation_allowed is True
    assert resolved.motion_transport == MotionReferenceTransport.CONTROL_VIDEO
    assert resolved.motion_semantics == MotionReferenceSemantics.STRUCTURAL_CONTROL


def _vace_request(reference_manifest: dict[str, object]) -> ProviderVideoRequest:
    return ProviderVideoRequest(
        request_id=uuid4(),
        ordinal=1,
        model_alias="bailian_wan_vace_posebody",
        provider_model="wanx2.1-vace-plus",
        prompt="目标人物完成参考动作",
        negative_prompt="",
        reference_frames=(),
        duration_seconds=5,
        resolution="720P",
        aspect_ratio="9:16",
        width=720,
        height=1280,
        route_id="wan_vace_posebody_repaint",
        effective_route_id="wan_vace_posebody_repaint",
        motion_semantics="structural_control",
        control_condition="posebody",
        reference_manifest=reference_manifest,
    )


def test_wan_vace_mapper_requires_provider_reachable_urls() -> None:
    with pytest.raises(VideoProviderError) as error:
        build_bailian_request(_vace_request({}))
    assert error.value.code == "video_public_media_transport_required"

    payload = build_bailian_request(
        _vace_request(
            {
                "provider_media_urls": {
                    "identity_image_url": "https://media.example/actor.png",
                    "control_video_url": "https://media.example/motion.mp4",
                }
            }
        )
    )
    assert payload["input"]["function"] == "video_repainting"
    assert payload["input"]["ref_images_url"] == [
        "https://media.example/actor.png"
    ]
    assert payload["input"]["video_url"] == "https://media.example/motion.mp4"
    assert payload["parameters"]["control_condition"] == "posebody"
