"""Exclusive identity-source policy for reference-guided image generation.

The source keyframe controls staging.  When a person identity asset is bound,
that asset is the only allowed source for the generated person's identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..models import (
    ImageGenerationCapability,
    ImageGenerationInputMode,
    ReferenceAsset,
    ReferenceAssetType,
    ReferenceBinding,
    ReferenceRole,
)
from .contracts import ImageReferenceInput

IDENTITY_POLICY_VERSION = "exclusive-identity-source/v1"


class IdentityPolicyViolation(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class IdentityPolicyState:
    enabled: bool
    primary_asset_id: UUID | None


def validate_identity_bindings(
    bindings: Sequence[ReferenceBinding],
    assets: Iterable[ReferenceAsset] | None = None,
) -> IdentityPolicyState:
    identity_bindings = [
        item for item in bindings if item.role == ReferenceRole.IDENTITY
    ]
    if len(identity_bindings) > 1:
        raise IdentityPolicyViolation(
            422,
            "multiple_identity_references",
            "每个分镜只能绑定一个人物身份资产，请保留唯一身份来源后再生成",
        )
    primary_asset_id = (
        identity_bindings[0].reference_asset_id if identity_bindings else None
    )
    if primary_asset_id is not None and assets is not None:
        assets_by_id = {item.id: item for item in assets}
        asset = assets_by_id.get(primary_asset_id)
        if asset is None:
            raise IdentityPolicyViolation(
                409,
                "identity_asset_missing",
                "人物身份资产不存在或已归档，请重新选择身份来源",
            )
        if asset.type != ReferenceAssetType.PERSON:
            raise IdentityPolicyViolation(
                422,
                "identity_asset_type_invalid",
                "人物身份来源必须使用人物类型资产",
            )
    return IdentityPolicyState(
        enabled=primary_asset_id is not None,
        primary_asset_id=primary_asset_id,
    )


def validate_identity_generation(
    *,
    state: IdentityPolicyState,
    input_mode: ImageGenerationInputMode,
    source_present: bool,
    references: Sequence[ImageReferenceInput] = (),
    capability: ImageGenerationCapability | None = None,
) -> None:
    if not state.enabled:
        return
    if input_mode != ImageGenerationInputMode.KEYFRAME_EDIT:
        raise IdentityPolicyViolation(
            422,
            "identity_requires_reference_mode",
            "绑定人物身份资产后必须使用“关键帧编辑（文字 + 图片）”，不能使用纯文字生图",
        )
    if not source_present:
        raise IdentityPolicyViolation(
            409,
            "identity_source_keyframe_required",
            "人物身份替换需要图像1作为构图与动作控制图，请先选择原视频关键帧",
        )
    if capability is None:
        return
    identity_inputs = [
        item for item in references if item.role == ReferenceRole.IDENTITY.value
    ]
    if (
        len(identity_inputs) != 1
        or identity_inputs[0].asset_id != state.primary_asset_id
    ):
        raise IdentityPolicyViolation(
            409,
            "identity_reference_missing",
            "唯一人物身份资产未进入模型输入，请重新保存参考绑定后再生成",
        )
    if not capability.image_to_image or not capability.multi_reference:
        raise IdentityPolicyViolation(
            422,
            "identity_model_unsupported",
            "当前生图模型不能同时接收构图控制图和唯一人物身份图，请切换支持多图参考的模型",
        )
    if capability.max_reference_images < len(references):
        raise IdentityPolicyViolation(
            422,
            "reference_count_unsupported",
            (
                f"当前模型最多接收 {capability.max_reference_images} 张参考图，"
                f"当前已绑定 {len(references)} 张"
            ),
        )
    required_inputs = 1 + len(references)
    if capability.max_input_images < required_inputs:
        raise IdentityPolicyViolation(
            422,
            "identity_input_count_unsupported",
            (
                f"当前模型最多接收 {capability.max_input_images} 张输入图，"
                f"本次身份替换需要 {required_inputs} 张"
            ),
        )


def identity_reference(
    references: Sequence[ImageReferenceInput],
) -> ImageReferenceInput | None:
    matches = [item for item in references if item.role == ReferenceRole.IDENTITY.value]
    if len(matches) > 1:
        raise IdentityPolicyViolation(
            422,
            "multiple_identity_references",
            "每个分镜只能发送一个人物身份来源",
        )
    return matches[0] if matches else None


def build_input_manifest(
    *,
    source_present: bool,
    references: Sequence[ImageReferenceInput],
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    if source_present:
        manifest.append(
            {
                "input_index": 1,
                "kind": "source_keyframe",
                "responsibility": "composition_pose_action_camera",
                "label": "原视频关键帧",
                "identity_source": False,
                "restrictions": [
                    "不继承人物年龄",
                    "不继承人物五官与脸型",
                    "不继承人物肤色、发型或身份",
                ],
            }
        )
    start_index = 2 if source_present else 1
    for index, reference in enumerate(references, start=start_index):
        is_identity = reference.role == ReferenceRole.IDENTITY.value
        manifest.append(
            {
                "input_index": index,
                "kind": "reference_asset",
                "asset_id": str(reference.asset_id),
                "name": reference.name,
                "role": reference.role,
                "responsibility": (
                    "exclusive_person_identity_source"
                    if is_identity
                    else f"{reference.role}_reference"
                ),
                "identity_source": is_identity,
            }
        )
    return manifest


def policy_snapshot(
    *,
    state: IdentityPolicyState,
) -> dict[str, Any]:
    return {
        "version": IDENTITY_POLICY_VERSION,
        "enabled": state.enabled,
        "primary_identity_asset_id": (
            str(state.primary_asset_id) if state.primary_asset_id is not None else None
        ),
        "source_keyframe_identity_inheritance": (
            "forbidden" if state.enabled else "not_applicable"
        ),
        "identity_conflict_resolution": (
            "identity_reference_wins" if state.enabled else "not_applicable"
        ),
    }
