from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.asset_library import AssetLibraryService
from viral_dna_api.asset_promotion.routes import create_generated_asset_promotion_router
from viral_dna_api.asset_promotion.service import GeneratedAssetPromotionService
from viral_dna_api.asset_routes import create_asset_router
from viral_dna_api.control_assets.domain import DepthControlAsset
from viral_dna_api.models import GenerationCandidate, GenerationKind, GenerationRun, ShotPlan
from viral_dna_api.storage_objects import StorageManager
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import (
    AccountContextService,
    LocalAccountCatalogRepository,
)


def _test_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, InMemoryStore, Path]:
    workspace_root = tmp_path / "generated-assets-workspace"
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    manager = WorkspaceManager()
    context = AccountContextService(
        LocalAccountCatalogRepository(tmp_path / "account-catalog.json"),
        manager,
    )
    repository = InMemoryStore()
    storage = StorageManager(repository, manager)
    assets = AssetLibraryService(repository, storage, context)
    promotion = GeneratedAssetPromotionService(
        repository=repository,
        account_context=context,
        workspace=manager,
        storage=storage,
        assets=assets,
    )
    app = FastAPI()
    app.include_router(create_asset_router(assets), prefix="/api/v1")
    app.include_router(create_generated_asset_promotion_router(promotion), prefix="/api/v1")
    return TestClient(app), repository, workspace_root


def _seed_image_candidate(repository: InMemoryStore, workspace_root: Path):
    project_id = uuid4()
    revision_id = uuid4()
    plan = ShotPlan.model_construct(
        id=uuid4(),
        project_id=project_id,
        revision_id=revision_id,
        index=1,
        image_prompt="一名人物站在湖边，保持构图与动作。",
        video_prompt="人物缓慢向镜头转身。",
        depth_control_assets=[],
    )
    run = GenerationRun.model_construct(
        id=uuid4(),
        project_id=project_id,
        shot_plan_id=plan.id,
        revision_id=revision_id,
        kind=GenerationKind.IMAGE,
        provider="local_tool",
        model="gpt-image",
        actual_cost_micros=0,
        request_payload={"input_asset_ids": [str(uuid4())]},
    )
    payload = b"generated-image-bytes"
    thumbnail = b"generated-thumbnail-bytes"
    relative_path = "generated/candidates/image-candidate.png"
    thumbnail_path = "generated/candidates/image-candidate-thumbnail.webp"
    (workspace_root / relative_path).parent.mkdir(parents=True, exist_ok=True)
    (workspace_root / relative_path).write_bytes(payload)
    (workspace_root / thumbnail_path).write_bytes(thumbnail)
    candidate = GenerationCandidate.model_construct(
        id=uuid4(),
        generation_run_id=run.id,
        ordinal=1,
        kind=GenerationKind.IMAGE,
        relative_path=relative_path,
        thumbnail_relative_path=thumbnail_path,
        width=1080,
        height=1920,
        duration_seconds=None,
        sha256=hashlib.sha256(payload).hexdigest(),
        metadata_relative_path="generated/candidates/image-candidate.json",
        quality_report={},
    )
    repository.shot_plans[plan.id] = plan
    repository.generation_runs[run.id] = run
    repository.generation_candidates[candidate.id] = candidate
    return plan, candidate, payload, relative_path


def test_generated_image_promotion_is_idempotent_and_survives_source_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, repository, workspace_root = _test_client(tmp_path, monkeypatch)
    plan, candidate, payload, relative_path = _seed_image_candidate(
        repository,
        workspace_root,
    )
    request_payload = {
        "kind": "image_candidate",
        "source_entity_id": str(candidate.id),
        "shot_plan_id": str(plan.id),
        "asset_type": "person",
        "name": "分镜人物候选",
    }

    with client:
        first = client.post("/api/v1/assets/from-generated-artifact", json=request_payload)
        second = client.post("/api/v1/assets/from-generated-artifact", json=request_payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["already_existed"] is True
        assert second.json()["asset"]["id"] == first.json()["asset"]["id"]
        assert first.json()["asset"]["account_id"]
        assert first.json()["asset"]["origin_kind"] == "generated_image"
        assert first.json()["asset"]["rights_basis"] == "system_generated"
        assert first.json()["provenance"]["prompt_snapshot"] == plan.image_prompt

        (workspace_root / relative_path).unlink()
        content = client.get(first.json()["asset"]["content_url"])
        assert content.status_code == 200
        assert content.content == payload

        status = client.post(
            "/api/v1/assets/generated-artifact-status",
            json={
                "kind": "image_candidate",
                "source_entity_id": str(candidate.id),
            },
        )
        assert status.status_code == 200
        assert status.json()["promoted"] is True

    assert len(repository.generated_artifacts) == 1
    assert len(repository.assets) == 1
    assert len(repository.asset_provenance) == 1
    assert len(repository.storage_object_references) == 4
    serialized = json.dumps(
        next(iter(repository.asset_provenance.values())).model_dump(mode="json"),
        ensure_ascii=False,
    )
    assert "一名人物站在湖边" in serialized


def test_generated_video_and_depth_control_keep_media_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, repository, workspace_root = _test_client(tmp_path, monkeypatch)
    project_id = uuid4()
    revision_id = uuid4()

    video_payload = b"generated-video-bytes"
    video_relative_path = "generated/candidates/video-candidate.mp4"
    video_thumbnail_path = "generated/candidates/video-candidate.webp"
    depth_payload = b"generated-depth-video-bytes"
    depth_relative_path = "generated/depth/depth-control.mp4"
    depth_thumbnail_path = "generated/depth/depth-control.webp"
    for relative_path, content in (
        (video_relative_path, video_payload),
        (video_thumbnail_path, b"video-thumbnail"),
        (depth_relative_path, depth_payload),
        (depth_thumbnail_path, b"depth-thumbnail"),
    ):
        target = workspace_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    depth = DepthControlAsset.model_construct(
        id=uuid4(),
        relative_path=depth_relative_path,
        thumbnail_relative_path=depth_thumbnail_path,
        sha256=hashlib.sha256(depth_payload).hexdigest(),
        engine="video_depth_anything",
        model_variant="vits",
        width=720,
        height=1280,
        fps=24.0,
        duration_seconds=5.0,
    )
    plan = ShotPlan.model_construct(
        id=uuid4(),
        project_id=project_id,
        revision_id=revision_id,
        index=1,
        image_prompt="人物关键帧",
        video_prompt="人物完成连续动作。",
        depth_control_assets=[depth],
    )
    run = GenerationRun.model_construct(
        id=uuid4(),
        project_id=project_id,
        shot_plan_id=plan.id,
        revision_id=revision_id,
        kind=GenerationKind.VIDEO,
        provider="minimax",
        model="minimax-h3",
        actual_cost_micros=2_000_000,
        request_payload={"input_asset_ids": []},
    )
    candidate = GenerationCandidate.model_construct(
        id=uuid4(),
        generation_run_id=run.id,
        ordinal=1,
        kind=GenerationKind.VIDEO,
        relative_path=video_relative_path,
        thumbnail_relative_path=video_thumbnail_path,
        width=720,
        height=1280,
        duration_seconds=4.0,
        sha256=hashlib.sha256(video_payload).hexdigest(),
        metadata_relative_path="generated/candidates/video-candidate.json",
        quality_report={"fps": 25.0, "codec": "h264"},
    )
    repository.shot_plans[plan.id] = plan
    repository.generation_runs[run.id] = run
    repository.generation_candidates[candidate.id] = candidate

    with client:
        video_response = client.post(
            "/api/v1/assets/from-generated-artifact",
            json={
                "kind": "video_candidate",
                "source_entity_id": str(candidate.id),
                "shot_plan_id": str(plan.id),
                "name": "生成视频",
            },
        )
        depth_response = client.post(
            "/api/v1/assets/from-generated-artifact",
            json={
                "kind": "depth_control",
                "source_entity_id": str(depth.id),
                "shot_plan_id": str(plan.id),
                "name": "深度视频",
            },
        )

    assert video_response.status_code == 200
    assert video_response.json()["asset"]["media_kind"] == "video"
    assert video_response.json()["asset"]["type"] == "motion_reference"
    assert video_response.json()["asset"]["duration_seconds"] == 4.0
    assert video_response.json()["provenance"]["provider"] == "minimax"
    assert video_response.json()["asset"]["codec"] == "h264"

    assert depth_response.status_code == 200
    assert depth_response.json()["asset"]["media_kind"] == "depth_video"
    assert depth_response.json()["asset"]["type"] == "spatial_depth"
    assert depth_response.json()["asset"]["duration_seconds"] == 5.0
    assert depth_response.json()["provenance"]["provider"] == "local_depth"
    assert depth_response.json()["asset"]["fps"] == 24.0
