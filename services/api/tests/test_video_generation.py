from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from viral_dna_api.models import (
    ImageExecutionMode,
    ProductionProject,
    ShotPlan,
    VideoGenerationCreate,
    VideoGenerationInputMode,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
    VideoGenerationReference,
    VideoPromptMention,
    VideoPromptReferenceKind,
    VideoPromptReferenceRole,
)
from viral_dna_api.video_generation import (
    OrderedReferenceFrame,
    VideoGenerationGateway,
    VideoGenerationGatewayError,
)
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.gateway import _positive_prompt
from viral_dna_api.workspace import WorkspaceManager


def write_fake_video(
    image_path: Path,
    output_path: Path,
    duration_seconds: float,
    width: int,
    height: int,
) -> None:
    assert image_path.is_file()
    assert duration_seconds > 0
    assert width > 0 and height > 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42viral-dna-simulated-video")


class FakeStillVideoProcessor:
    async def create_still_video(
        self,
        image_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> None:
        await asyncio.to_thread(
            write_fake_video,
            image_path,
            output_path,
            duration_seconds,
            width,
            height,
        )


def filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    return Path(f"{chr(92)}{chr(92)}?{chr(92)}{path}")


def test_video_input_plan_is_composable_and_never_contains_audio() -> None:
    reference_id = uuid4()
    prompt_only = VideoGenerationInputPlan()
    approved_frame = VideoGenerationInputPlan(sources=[VideoGenerationInputSource.APPROVED_IMAGES])
    composed = VideoGenerationInputPlan(
        sources=[
            VideoGenerationInputSource.PROJECT_ASSETS,
            VideoGenerationInputSource.DEPTH_CONTROL,
        ],
        references=[
            VideoGenerationReference(
                reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
                reference_id=reference_id,
                label="asset/person",
                role=VideoPromptReferenceRole.ACTOR_IDENTITY,
            )
        ],
    )
    video_only = VideoGenerationInputPlan(sources=[VideoGenerationInputSource.DEPTH_CONTROL])

    assert prompt_only.input_mode == VideoGenerationInputMode.TEXT_TO_VIDEO
    assert approved_frame.input_mode == VideoGenerationInputMode.IMAGE_TO_VIDEO
    assert composed.input_mode == VideoGenerationInputMode.HYBRID_REFERENCE_TO_VIDEO
    assert video_only.input_mode == VideoGenerationInputMode.VIDEO_TO_VIDEO
    assert composed.references[0].reference_id == reference_id
    assert "audio" not in {item.value for item in VideoGenerationInputSource}

    capabilities = load_video_model_catalog().option("minimax_h3").capability
    assert VideoGenerationInputSource.PROJECT_ASSETS in capabilities.supported_input_sources
    assert VideoGenerationInputSource.DEPTH_CONTROL in capabilities.supported_input_sources
    assert "audio" not in capabilities.model_dump(mode="json")["supported_input_sources"]


def test_video_prompt_mentions_keep_stable_ids_and_compile_reference_roles() -> None:
    reference_id = uuid4()
    mention = VideoPromptMention(
        reference_kind=VideoPromptReferenceKind.PROJECT_ASSET,
        reference_id=reference_id,
        label="@资产/小喵酱/面部",
        role=VideoPromptReferenceRole.ACTOR_IDENTITY,
        order=1,
    )
    shot = ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-reference-001",
        index=1,
        start_seconds=0,
        end_seconds=3,
        duration_seconds=3,
        image_prompt="保持构图",
        video_prompt="使用 @资产/小喵酱/面部 作为唯一人物身份来源。",
        video_prompt_mentions=[mention],
    )

    assert shot.video_prompt_mentions[0].reference_id == reference_id
    assert shot.video_prompt_mentions[0].label == "资产/小喵酱/面部"
    compiled = _positive_prompt(shot, ())
    assert "@资产/小喵酱/面部：人物身份" in compiled
    assert "不得与其他引用交换身份、外观、动作或空间职责" in compiled

    with pytest.raises(ValidationError):
        ShotPlan(
            project_id=uuid4(),
            revision_id=uuid4(),
            source_shot_id="shot-reference-duplicate",
            index=1,
            start_seconds=0,
            end_seconds=3,
            duration_seconds=3,
            image_prompt="保持构图",
            video_prompt="重复引用",
            video_prompt_mentions=[mention, mention.model_copy(update={"order": 2})],
        )


def test_selected_depth_and_managed_references_compile_separated_responsibilities() -> None:
    shot = ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-reference-policy-001",
        index=1,
        start_seconds=0,
        end_seconds=3,
        duration_seconds=3,
        image_prompt="保持公园场景",
        video_prompt=(
            "@托管角色/小喵酱 是画面中唯一的人物身份来源。"
            "人物的面部、年龄、发型、体型和身份特征必须来自该托管角色，"
            "不继承深度视频或其他参考画面中的人物身份。"
            "@深度视频/分镜动作1 是唯一的动作、姿态、运动节奏、空间位置、"
            "镜头关系和遮挡转场来源。严格逐帧遵循深度视频中的身体姿态、"
            "手臂轨迹、动作顺序、速度、停顿、主体位置、景别变化和镜头运动。"
            "不得重新设计、简化、增加、删除、交换或提前任何动作。"
            "【目标画面】 人物抬手调整口罩。"
        ),
    )
    input_plan = VideoGenerationInputPlan(
        sources=[
            VideoGenerationInputSource.DEPTH_CONTROL,
            VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS,
        ],
        references=[
            VideoGenerationReference(
                reference_kind=VideoPromptReferenceKind.DEPTH_CONTROL,
                reference_id=uuid4(),
                label="深度视频/分镜动作1",
                role=VideoPromptReferenceRole.DEPTH,
                order=1,
            ),
            VideoGenerationReference(
                reference_kind=VideoPromptReferenceKind.PROVIDER_MANAGED_ASSET,
                reference_id=uuid4(),
                label="托管角色/小喵酱",
                role=VideoPromptReferenceRole.ACTOR_IDENTITY,
                order=2,
            ),
        ],
    )

    compiled = _positive_prompt(shot, (), input_plan=input_plan)

    assert "@深度视频/分镜动作1 是唯一的动作、姿态、运动节奏" in compiled
    assert "严格逐帧遵循深度视频中的身体姿态、手臂轨迹、动作顺序" in compiled
    assert "不得重新设计、简化、增加、删除、交换或提前任何动作" in compiled
    assert "@托管角色/小喵酱 是画面中唯一的人物身份来源" in compiled
    assert "不得继承深度视频或其他参考画面中的人物身份" in compiled
    assert "人物身份以托管角色为准" in compiled
    assert "镜头关系以深度视频为准" in compiled
    assert compiled.count("是画面中唯一的人物身份来源") == 1
    assert compiled.count("是唯一的动作、姿态、运动节奏") == 1
    assert "用户视频提示词：【目标画面】 人物抬手调整口罩。" in compiled


def test_approved_image_metadata_never_adds_image_prompt_semantics() -> None:
    shot = ShotPlan(
        project_id=uuid4(),
        revision_id=uuid4(),
        source_shot_id="shot-image-metadata-isolation",
        index=1,
        start_seconds=0,
        end_seconds=3,
        duration_seconds=3,
        video_prompt="黑色滤芯平滑推进，画面中无任何文字。",
    )
    frames = (
        OrderedReferenceFrame(
            visual_beat_id=uuid4(),
            ordinal=1,
            title="滤芯推进与文字显现",
            candidate_id=uuid4(),
            path=Path("approved-1.jpg"),
            relative_path="approved-1.jpg",
            sha256="a" * 64,
            start_ratio=0,
            end_ratio=0.5,
            transition_to_next_type="model_generated",
            transition_to_next_duration_seconds=0.5,
            transition_to_next_prompt="文字逐渐显现为“大师兄”",
        ),
        OrderedReferenceFrame(
            visual_beat_id=uuid4(),
            ordinal=2,
            title="文字完整出现",
            candidate_id=uuid4(),
            path=Path("approved-2.jpg"),
            relative_path="approved-2.jpg",
            sha256="b" * 64,
            start_ratio=0.5,
            end_ratio=1,
            transition_to_next_type="cut",
            transition_to_next_duration_seconds=0,
        ),
    )

    compiled = _positive_prompt(shot, frames)

    assert "用户视频提示词：黑色滤芯平滑推进，画面中无任何文字。" in compiled
    assert "图1（分镜图/图1）" in compiled
    assert "图2（分镜图/图2）" in compiled
    assert "滤芯推进与文字显现" not in compiled
    assert "文字完整出现" not in compiled
    assert "文字逐渐显现为“大师兄”" not in compiled


def test_video_gateway_creates_persistent_simulated_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(root))
        workspace = WorkspaceManager()
        project = ProductionProject(
            record_id=uuid4(),
            video_id=uuid4(),
            base_analysis_id=uuid4(),
            source_prompt_package_id=uuid4(),
            name="视频基础架构测试",
            output_aspect_ratio="9:16",
            output_width=1080,
            output_height=1920,
        )
        revision_id = uuid4()
        shot = ShotPlan(
            project_id=project.id,
            revision_id=revision_id,
            source_shot_id="shot-001",
            index=1,
            start_seconds=0,
            end_seconds=3,
            duration_seconds=3,
            image_prompt="保持原始人物与构图",
            video_prompt="人物向镜头走近，镜头缓慢后退",
        )
        image_path = workspace.root / "approved-1.jpg"
        second_image_path = workspace.root / "approved-2.jpg"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (720, 1280), (96, 82, 220)).save(image_path, "JPEG")
        Image.new("RGB", (720, 1280), (56, 170, 132)).save(
            second_image_path,
            "JPEG",
        )
        references = (
            OrderedReferenceFrame(
                visual_beat_id=uuid4(),
                ordinal=1,
                title="室内近景",
                candidate_id=uuid4(),
                path=image_path,
                relative_path="approved-1.jpg",
                sha256="a" * 64,
                start_ratio=0,
                end_ratio=0.45,
                transition_to_next_type="model_generated",
                transition_to_next_duration_seconds=0.5,
            ),
            OrderedReferenceFrame(
                visual_beat_id=uuid4(),
                ordinal=2,
                title="户外远景",
                candidate_id=uuid4(),
                path=second_image_path,
                relative_path="approved-2.jpg",
                sha256="b" * 64,
                start_ratio=0.45,
                end_ratio=1,
                transition_to_next_type="cut",
                transition_to_next_duration_seconds=0,
            ),
        )
        gateway = VideoGenerationGateway(
            workspace,
            media_processor=FakeStillVideoProcessor(),
        )

        run, candidates = await gateway.generate(
            project,
            shot,
            revision_id,
            references,
            candidate_count=2,
            duration_seconds=3,
            execution_mode="simulated",
            seed=42,
        )

        assert run.kind == "video"
        assert run.input_mode == VideoGenerationInputMode.MULTI_IMAGE_TO_VIDEO
        assert run.execution_mode == ImageExecutionMode.SIMULATED
        assert run.status == "completed"
        assert run.cost_estimate_known is True
        assert run.estimated_cost_micros == 0
        assert run.actual_cost_micros == 0
        assert len(candidates) == 2
        assert all(candidate.kind == "video" for candidate in candidates)
        assert all(candidate.duration_seconds == 3 for candidate in candidates)
        assert all(
            filesystem_path(workspace.resolve(candidate.relative_path)).is_file()
            for candidate in candidates
        )
        assert all(
            filesystem_path(workspace.resolve(candidate.thumbnail_relative_path)).is_file()
            for candidate in candidates
            if candidate.thumbnail_relative_path
        )
        input_payload = json.loads(
            filesystem_path(workspace.resolve(run.input_snapshot_relative_path)).read_text("utf-8")
        )
        assert input_payload["schema_version"] == "viral-dna-video-generation/v4"
        assert [item["ordinal"] for item in input_payload["reference_images"]] == [1, 2]
        assert input_payload["reference_images"][0]["candidate_id"] == str(
            references[0].candidate_id
        )
        assert input_payload["reference_images"][1]["sha256"] == "b" * 64
        assert input_payload["output"]["native_audio"] is False
        assert input_payload["prompt"]["positive"].startswith("用户视频提示词")
        assert "使用下列有序安全参考画面" in input_payload["prompt"]["positive"]
        assert "图1到图2由视频模型结合前后画面和用户转场意图" in input_payload["prompt"]["positive"]
        assert "不得默认改成硬切" in input_payload["prompt"]["positive"]

    asyncio.run(scenario())


def test_video_gateway_exposes_remote_seam_but_rejects_unconfigured_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    gateway = VideoGenerationGateway(
        WorkspaceManager(),
        media_processor=FakeStillVideoProcessor(),
    )

    with pytest.raises(VideoGenerationGatewayError) as remote:
        gateway.validate_execution_mode(ImageExecutionMode.REMOTE_API)
    assert remote.value.code == "video_remote_provider_not_configured"
    assert "Batch 4.5.2" in str(remote.value)

    with pytest.raises(VideoGenerationGatewayError) as local:
        gateway.validate_execution_mode(ImageExecutionMode.LOCAL_TOOL)
    assert local.value.code == "video_local_tool_not_supported"

    with pytest.raises(ValidationError):
        VideoGenerationCreate.model_validate(
            {
                "expected_revision_id": str(uuid4()),
                "execution_mode": "local_tool",
            }
        )
