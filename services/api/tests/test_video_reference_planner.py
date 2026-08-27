from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.models import ShotPlan
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.contracts import (
    DepthControlVideo,
    OrderedReferenceFrame,
    ProviderManagedAssetReference,
)
from viral_dna_api.video_references.planner import (
    VideoReferencePolicyError,
    resolve_video_reference_plan,
)


def _frame(
    ordinal: int,
    *,
    role: str = "composition",
    source_kind: str = "approved_frame",
) -> OrderedReferenceFrame:
    return OrderedReferenceFrame(
        visual_beat_id=uuid4(),
        ordinal=ordinal,
        title=f"画面 {ordinal}",
        candidate_id=uuid4(),
        path=Path(f"frame-{ordinal}.webp"),
        relative_path=f"frame-{ordinal}.webp",
        sha256=str(ordinal) * 64,
        start_ratio=(ordinal - 1) / 2,
        end_ratio=ordinal / 2,
        transition_to_next_type="cut",
        transition_to_next_duration_seconds=0,
        role=role,
        source_kind=source_kind,
    )


def _managed() -> ProviderManagedAssetReference:
    return ProviderManagedAssetReference(
        binding_id=uuid4(),
        provider="volc_ark",
        asset_id="virtual-person-001",
        group_id="group-001",
        kind="virtual_person",
        role="actor_identity",
        name="小喵酱",
        media_type="image",
        project_name="default",
        uri="asset://virtual-person-001",
    )


def _depth(*, public: bool = True) -> DepthControlVideo:
    return DepthControlVideo(
        control_asset_id=uuid4(),
        source_video_id=uuid4(),
        ordinal=1,
        title="原分镜全场景深度",
        path=Path("depth.mp4"),
        relative_path="depth-controls/depth.mp4",
        sha256="f" * 64,
        public_url="https://media.example.test/depth.mp4" if public else None,
    )


def _shot() -> ShotPlan:
    return ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-001",
        index=1,
        start_seconds=0,
        end_seconds=4,
        duration_seconds=4,
    )


def test_seedance_uses_managed_actor_depth_and_non_identity_appearance_assets() -> None:
    original = _frame(1)
    scene = _frame(2, role="scene", source_kind="project_asset")
    wardrobe = _frame(3, role="wardrobe", source_kind="project_asset")
    depth = _depth()

    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("seedance_2_0").capability,
        shot=_shot(),
        reference_frames=(original, scene, wardrobe),
        managed_asset_references=(_managed(),),
        depth_control_videos=(depth,),
        public_media_transport_ready=True,
    )

    assert plan.strategy == "managed_actor_with_depth_and_appearance_assets"
    assert [item.role for item in plan.reference_frames] == ["scene", "wardrobe"]
    assert plan.depth_control_videos == (depth,)
    assert len(plan.managed_asset_references) == 1
    assert [item.candidate_id for item in plan.excluded_references] == [
        str(original.candidate_id)
    ]
    assert plan.spatial_control_source == "full_scene_depth_video"
    assert plan.spatial_control_semantics == "guided_depth_reference"
    assert plan.manifest()["submitted_depth_controls"][0]["kind"] == (
        "full_scene_depth_video"
    )


@pytest.mark.parametrize(
    ("managed", "depth", "transport_ready", "error_code"),
    [
        ((), (_depth(),), True, "video_managed_identity_required"),
        ((_managed(),), (), True, "depth_control_required"),
        ((_managed(),), (_depth(public=False),), False, "depth_control_public_url_required"),
    ],
)
def test_seedance_missing_required_inputs_fails_closed(
    managed: tuple[ProviderManagedAssetReference, ...],
    depth: tuple[DepthControlVideo, ...],
    transport_ready: bool,
    error_code: str,
) -> None:
    with pytest.raises(VideoReferencePolicyError) as captured:
        resolve_video_reference_plan(
            capability=load_video_model_catalog().option("seedance_2_0_fast").capability,
            shot=_shot(),
            reference_frames=(_frame(1),),
            managed_asset_references=managed,
            depth_control_videos=depth,
            public_media_transport_ready=transport_ready,
        )

    assert captured.value.code == error_code


def test_minimax_uses_identity_and_appearance_assets_with_depth() -> None:
    identity = _frame(1, role="actor_identity", source_kind="project_asset")
    scene = _frame(2, role="scene", source_kind="project_asset")
    depth = _depth()

    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("minimax_h3").capability,
        shot=_shot(),
        reference_frames=(identity, scene),
        managed_asset_references=(),
        depth_control_videos=(depth,),
        public_media_transport_ready=True,
    )

    assert plan.strategy == "identity_and_appearance_assets_with_depth"
    assert [item.role for item in plan.reference_frames] == ["actor_identity", "scene"]
    assert plan.depth_control_videos == (depth,)
    assert plan.managed_asset_references == ()


def test_minimax_does_not_fallback_when_depth_is_missing() -> None:
    with pytest.raises(VideoReferencePolicyError) as captured:
        resolve_video_reference_plan(
            capability=load_video_model_catalog().option("minimax_h3").capability,
            shot=_shot(),
            reference_frames=(
                _frame(1, role="actor_identity", source_kind="project_asset"),
            ),
            managed_asset_references=(),
            depth_control_videos=(),
            public_media_transport_ready=True,
        )

    assert captured.value.code == "depth_control_required"


def test_bailian_ordered_multi_image_route_keeps_ordered_frames() -> None:
    frames = (_frame(1), _frame(2))
    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("bailian_wan_2_7_r2v").capability,
        shot=_shot(),
        reference_frames=frames,
        managed_asset_references=(),
    )

    assert plan.strategy == "identity_and_appearance_assets"
    assert plan.reference_frames == frames
    assert plan.depth_control_videos == ()
    assert plan.managed_asset_references == ()


def test_reference_planner_blocks_capacity_overflow_without_dropping_frames() -> None:
    capability = load_video_model_catalog().option(
        "bailian_wan_2_7_r2v"
    ).capability.model_copy(update={"maximum_reference_images": 1})

    with pytest.raises(VideoReferencePolicyError) as captured:
        resolve_video_reference_plan(
            capability=capability,
            shot=_shot(),
            reference_frames=(_frame(1), _frame(2)),
            managed_asset_references=(),
        )

    assert captured.value.code == "provider_reference_limit"
    assert "不会自动丢弃参考" in str(captured.value)


def test_non_managed_route_never_submits_unrelated_provider_actor() -> None:
    frame = _frame(1)
    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("bailian_wan_2_7_r2v").capability,
        shot=_shot(),
        reference_frames=(frame,),
        managed_asset_references=(_managed(),),
    )

    assert plan.managed_asset_references == ()
    assert plan.reference_frames == (frame,)
