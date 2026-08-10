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
)
from viral_dna_api.video_generation import (
    OrderedReferenceFrame,
    VideoGenerationGateway,
    VideoGenerationGatewayError,
)
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
        assert input_payload["schema_version"] == "viral-dna-video-generation/v2"
        assert [item["ordinal"] for item in input_payload["reference_images"]] == [1, 2]
        assert input_payload["reference_images"][0]["candidate_id"] == str(
            references[0].candidate_id
        )
        assert input_payload["reference_images"][1]["sha256"] == "b" * 64
        assert input_payload["output"]["native_audio"] is False
        assert input_payload["prompt"]["positive"].startswith(
            "使用下列有序参考图生成一段连续视频"
        )
        assert "图1到图2" in input_payload["prompt"]["positive"]

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
