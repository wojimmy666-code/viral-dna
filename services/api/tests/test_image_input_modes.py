from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from test_generation_jobs import _project, _run, _shot, _workspace

from viral_dna_api.image_generation.gateway import _filesystem_path
from viral_dna_api.models import (
    GenerationCandidate,
    GenerationKind,
    ImageGenerationCreate,
    ImageGenerationInputMode,
    ProductionRunStatus,
    ReferenceAsset,
    ReferenceBinding,
)
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.store import InMemoryStore


async def prepare(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    repository = InMemoryStore()
    project = _project()
    shot = _shot(project)
    await repository.save_production_project(project)
    await repository.save_shot_plan(shot)
    gateway = SimpleNamespace(
        settings_service=SimpleNamespace(
            get=lambda: SimpleNamespace(enabled=True, execution_mode="remote_api")
        )
    )
    service = ProductionService(repository, workspace, image_gateway=gateway)
    return workspace, repository, project, shot, service


async def save_base(workspace, repository, project, shot):
    run = _run(project, shot, ProductionRunStatus.COMPLETED)
    run = run.model_copy(update={"visual_beat_id": shot.visual_beats[0].id})
    raw_path = (
        workspace.production_shot_root(project.record_id, project.id, shot.id)
        / "images"
        / str(run.id)
        / "base.jpg"
    )
    path = _filesystem_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "purple").save(path)
    candidate = GenerationCandidate(
        generation_run_id=run.id,
        ordinal=1,
        kind=GenerationKind.IMAGE,
        relative_path=workspace.relative(raw_path),
        width=64,
        height=64,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        metadata_relative_path="metadata.json",
    )
    await repository.save_generation_run(run)
    await repository.save_generation_candidate(candidate)
    return candidate, path, run


@pytest.mark.asyncio
async def test_reference_job_is_queued_with_assets_but_without_keyframes(tmp_path, monkeypatch):
    workspace, repository, project, shot, service = await prepare(tmp_path, monkeypatch)
    asset = ReferenceAsset(
        project_id=project.id,
        type="person",
        name="指定人物",
        relative_path="references/person.jpg",
        mime_type="image/jpeg",
        width=64,
        height=64,
        sha256="a" * 64,
        rights_confirmed=True,
    )
    await repository.save_reference_asset(asset)
    await repository.save_reference_binding(
        ReferenceBinding(shot_plan_id=shot.id, reference_asset_id=asset.id, role="identity")
    )
    payload = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
        input_mode="reference_to_image",
        visual_beat_id=shot.visual_beats[0].id,
    )
    run = await service._enqueue_image_run(
        shot.id, payload, frozen_prompt={"compiled_prompt": "指定人物居中"}
    )
    assert run.input_mode == ImageGenerationInputMode.REFERENCE_TO_IMAGE
    assert run.request_payload["input_mode"] == "reference_to_image"
    assert run.request_payload["base_image_candidate_id"] is None
    assert run.request_payload["visual_beat_id"] == str(shot.visual_beats[0].id)
    assert (await repository.get_shot_plan(shot.id)).source_keyframe_url is None


@pytest.mark.asyncio
async def test_explicit_generated_base_is_queued_without_replacing_original_data(
    tmp_path, monkeypatch
):
    workspace, repository, project, shot, service = await prepare(tmp_path, monkeypatch)
    candidate, path, _ = await save_base(workspace, repository, project, shot)
    original_bytes = path.read_bytes()
    payload = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
        input_mode="keyframe_edit",
        base_image_candidate_id=candidate.id,
        visual_beat_id=shot.visual_beats[0].id,
    )
    assert await service._resolve_image_base(project, shot, shot, payload) == path
    run = await service._enqueue_image_run(
        shot.id, payload, frozen_prompt={"compiled_prompt": "替换服装"}
    )
    assert run.request_payload["base_image_candidate_id"] == str(candidate.id)
    assert (await repository.get_generation_candidate(candidate.id)) == candidate
    assert path.read_bytes() == original_bytes
    assert (await repository.get_shot_plan(shot.id)).source_keyframe_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "other_project",
        "other_shot",
        "other_beat",
        "archived",
        "missing_file",
        "changed_file",
        "video",
    ],
)
async def test_unavailable_or_out_of_scope_base_is_rejected_before_queue(
    tmp_path, monkeypatch, invalid
):
    workspace, repository, project, shot, service = await prepare(tmp_path, monkeypatch)
    candidate, path, run = await save_base(workspace, repository, project, shot)
    if invalid == "other_project":
        run = run.model_copy(update={"project_id": uuid4()})
    elif invalid == "other_shot":
        run = run.model_copy(update={"shot_plan_id": uuid4()})
    elif invalid == "other_beat":
        run = run.model_copy(update={"visual_beat_id": uuid4()})
    elif invalid == "archived":
        candidate = candidate.model_copy(update={"status": "archived"})
    elif invalid == "video":
        candidate = candidate.model_copy(update={"kind": "video"})
    elif invalid == "missing_file":
        path.unlink()
    elif invalid == "changed_file":
        path.write_bytes(b"changed test fixture")
    await repository.save_generation_run(run)
    await repository.save_generation_candidate(candidate)
    payload = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
        input_mode="keyframe_edit",
        base_image_candidate_id=candidate.id,
        visual_beat_id=shot.visual_beats[0].id,
    )
    with pytest.raises(ProductionServiceError):
        await service._enqueue_image_run(
            shot.id, payload, frozen_prompt={"compiled_prompt": "替换人物"}
        )
    assert len(await repository.list_generation_runs(project.id, shot.id)) == (
        0 if invalid in {"other_project", "other_shot"} else 1
    )


def test_base_image_cannot_be_silently_ignored_in_creation_mode():
    with pytest.raises(ValueError, match="底图编辑"):
        ImageGenerationCreate(
            expected_revision_id=uuid4(),
            input_mode="reference_to_image",
            base_image_candidate_id=uuid4(),
        )
