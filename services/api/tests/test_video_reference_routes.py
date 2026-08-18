from __future__ import annotations

from uuid import uuid4

import pytest

from viral_dna_api.reference_routes import (
    IdentityReferenceTransport,
    SpatialControlSemantics,
    SpatialControlTransport,
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
        "has_depth_control_video": False,
        "public_media_transport_ready": False,
    }
    inputs.update(overrides)
    return resolve_reference_route(capability, **inputs)


def test_seedance_requires_managed_actor_depth_and_public_transport() -> None:
    identity_blocked = _resolve("seedance_2_0")
    assert identity_blocked.blocker_code == "video_managed_identity_required"

    depth_blocked = _resolve("seedance_2_0", has_managed_identity=True)
    assert depth_blocked.blocker_code == "depth_control_required"

    transport_blocked = _resolve(
        "seedance_2_0",
        has_managed_identity=True,
        has_depth_control_video=True,
    )
    assert transport_blocked.blocker_code == "depth_control_public_url_required"

    resolved = _resolve(
        "seedance_2_0",
        has_managed_identity=True,
        has_depth_control_video=True,
        public_media_transport_ready=True,
    )
    assert resolved.generation_allowed is True
    assert resolved.identity_transport == IdentityReferenceTransport.PROVIDER_MANAGED_ASSET
    assert resolved.spatial_control_transport == SpatialControlTransport.REFERENCE_VIDEO
    assert resolved.spatial_control_source == "full_scene_depth_video"
    assert resolved.spatial_control_semantics == SpatialControlSemantics.GUIDED_DEPTH_REFERENCE


def test_minimax_requires_identity_and_depth_without_legacy_fallback() -> None:
    missing_identity = _resolve("minimax_h3", has_raw_reference_image=False)
    assert missing_identity.blocker_code == "video_identity_image_required"

    missing_depth = _resolve("minimax_h3")
    assert missing_depth.blocker_code == "depth_control_required"

    resolved = _resolve(
        "minimax_h3",
        has_depth_control_video=True,
        public_media_transport_ready=True,
    )
    assert resolved.generation_allowed is True
    assert resolved.identity_source == "approved_reference_image"
    assert resolved.spatial_control_source == "full_scene_depth_video"


def test_hailuo_never_exposes_depth_control() -> None:
    capability = load_video_model_catalog().option(
        "minimax_hailuo_2_3"
    ).capability.reference_route
    route = _resolve("minimax_hailuo_2_3", has_depth_control_video=True)

    assert capability.show_depth_control_controls is False
    assert capability.supports_depth_control_video is False
    assert route.spatial_control_transport == SpatialControlTransport.NONE
    assert route.spatial_control_source == "none"


def _vace_request(reference_manifest: dict[str, object]) -> ProviderVideoRequest:
    return ProviderVideoRequest(
        request_id=uuid4(),
        ordinal=1,
        model_alias="bailian_wan_vace_depth",
        provider_model="wanx2.1-vace-plus",
        prompt="目标人物按深度控制完成动作",
        negative_prompt="",
        reference_frames=(),
        duration_seconds=5,
        resolution="720P",
        aspect_ratio="9:16",
        width=720,
        height=1280,
        route_id=VideoReferenceRouteId.WAN_VACE_DEPTH_CONTROL.value,
        effective_route_id=VideoReferenceRouteId.WAN_VACE_DEPTH_CONTROL.value,
        spatial_control_semantics=SpatialControlSemantics.STRICT_DEPTH_CONTROL.value,
        control_condition="depth",
        reference_manifest=reference_manifest,
    )


def test_wan_vace_mapper_uses_identity_and_depth_urls() -> None:
    with pytest.raises(VideoProviderError) as error:
        build_bailian_request(_vace_request({}))
    assert error.value.code == "video_public_media_transport_required"

    payload = build_bailian_request(
        _vace_request(
            {
                "provider_media_urls": {
                    "identity_image_url": "https://media.example/actor.png",
                    "control_video_url": "https://media.example/depth.mp4",
                }
            }
        )
    )
    assert payload["input"]["function"] == "video_repainting"
    assert payload["input"]["video_url"].endswith("/depth.mp4")
    assert payload["parameters"]["control_condition"] == "depth"
