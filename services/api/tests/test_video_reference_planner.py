from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.models import ShotPlan
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.contracts import (
    OrderedReferenceFrame,
    OrderedReferenceVideo,
    ProviderManagedAssetReference,
)
from viral_dna_api.video_references.domain import (
    PersonContentClass,
    VideoReferenceBinding,
    VideoReferenceMediaType,
    VideoReferenceRole,
    VideoReferenceSourceKind,
)
from viral_dna_api.video_references.planner import (
    VideoReferencePolicyError,
    resolve_video_reference_plan,
)


def _frame(ordinal: int) -> OrderedReferenceFrame:
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


def _shot(*, bindings: list[VideoReferenceBinding] | None = None) -> ShotPlan:
    return ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-001",
        index=1,
        start_seconds=0,
        end_seconds=4,
        duration_seconds=4,
        video_reference_bindings=bindings or [],
    )


def test_seedance_managed_identity_excludes_legacy_local_person_frames() -> None:
    frames = (_frame(1), _frame(2))
    capability = load_video_model_catalog().option("seedance_2_0").capability

    plan = resolve_video_reference_plan(
        capability=capability,
        shot=_shot(),
        reference_frames=frames,
        managed_asset_references=(_managed(),),
    )

    assert plan.strategy == "managed_identity_only"
    assert plan.reference_frames == ()
    assert len(plan.managed_asset_references) == 1
    assert len(plan.excluded_references) == 2
    assert all(
        item.reason_code == "local_identity_reference_excluded"
        for item in plan.excluded_references
    )


def test_seedance_can_submit_explicit_person_free_or_proxy_frames() -> None:
    frames = (_frame(1), _frame(2))
    bindings = [
        VideoReferenceBinding(
            role=VideoReferenceRole.SCENE,
            source_kind=VideoReferenceSourceKind.LOCAL_ORIGINAL,
            media_type=VideoReferenceMediaType.IMAGE,
            image_candidate_id=frames[1].candidate_id,
            person_class=PersonContentClass.NO_PERSON,
        )
    ]

    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("seedance_2_0_fast").capability,
        shot=_shot(bindings=bindings),
        reference_frames=frames,
        managed_asset_references=(_managed(),),
    )

    assert plan.strategy == "managed_identity_with_safe_references"
    assert [item.candidate_id for item in plan.reference_frames] == [frames[1].candidate_id]
    assert [item.ordinal for item in plan.reference_frames] == [1]
    assert len(plan.excluded_references) == 1


def test_seedance_requires_managed_identity_before_generation() -> None:
    with pytest.raises(VideoReferencePolicyError) as captured:
        resolve_video_reference_plan(
            capability=load_video_model_catalog().option("seedance_2_0_mini").capability,
            shot=_shot(),
            reference_frames=(_frame(1),),
            managed_asset_references=(),
        )

    assert captured.value.code == "video_managed_identity_required"


def test_seedance_can_use_video_motion_proxy_without_submitting_original_frames() -> None:
    proxy = OrderedReferenceVideo(
        proxy_asset_id=uuid4(),
        visual_beat_id=uuid4(),
        ordinal=1,
        title="无身份动作代理",
        path=Path("motion-proxy.mp4"),
        relative_path="motion-proxy.mp4",
        sha256="f" * 64,
    )

    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("seedance_2_0").capability,
        shot=_shot(),
        reference_frames=(_frame(1),),
        managed_asset_references=(_managed(),),
        proxy_reference_videos=(proxy,),
    )

    assert plan.strategy == "managed_identity_with_motion_proxy"
    assert plan.reference_frames == ()
    assert plan.reference_videos == (proxy,)
    assert len(plan.excluded_references) == 1
    assert plan.manifest()["submitted_proxy_videos"][0]["proxy_asset_id"] == str(
        proxy.proxy_asset_id
    )


def test_minimax_and_bailian_keep_original_reference_frames() -> None:
    frames = (_frame(1), _frame(2))
    for alias in ("minimax_h3", "bailian_wan_2_7_r2v"):
        plan = resolve_video_reference_plan(
            capability=load_video_model_catalog().option(alias).capability,
            shot=_shot(),
            reference_frames=frames,
            managed_asset_references=(),
        )
        assert plan.strategy == "raw_references"
        assert plan.reference_frames == frames
        assert plan.excluded_references == ()
