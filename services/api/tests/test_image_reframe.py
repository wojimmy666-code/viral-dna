from __future__ import annotations

import hashlib
import json
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image, ImageChops, ImageDraw
from pydantic import ValidationError
from test_image_batches import environment
from test_image_input_modes import prepare, save_base

from viral_dna_api.image_generation.catalog import load_image_model_catalog
from viral_dna_api.image_generation.contracts import AdapterIdentity, AdapterResult, GeneratedImage
from viral_dna_api.image_generation.gateway import (
    ImageGenerationGateway,
    ImageGenerationGatewayError,
    _filesystem_path,
)
from viral_dna_api.image_reframe import ImageReframe, plan_reframe, prepare_reframe, restore_reframe
from viral_dna_api.models import (
    AnalysisJob,
    GenerationCostSource,
    ImageExecutionMode,
    ImageGenerationCreate,
    Video,
    WorkflowItemStatus,
)
from viral_dna_api.pipeline import build_simulated_report
from viral_dna_api.production import ProductionServiceError


def spec(**changes):
    values = dict(
        request_id=uuid4(),
        source_sha256="a" * 64,
        source_box=dict(x=0.39354, y=0.24017, width=0.1896, height=0.66846),
        target_box=dict(x=0.458324341, y=0.251285674, width=0.124360684, height=0.499327903),
    )
    return ImageReframe(**(values | changes))


def png(image):
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_normal_generation_preserves_legacy_cache_fingerprint():
    payload = dict(
        schema_version="viral-dna-image-generation/v2",
        input_mode="text_to_image",
        execution={"model": "test-model"},
        output={"width": 1024, "height": 1024},
        prompt={"positive": "测试画面"},
        seed=None,
        source=None,
        references=[],
        locks=[],
        identity_policy={},
    )
    expected = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert ImageGenerationGateway._fingerprint(payload) == expected
    assert ImageGenerationGateway._fingerprint(payload | {"composition_reframe": None}) == expected
    assert (
        ImageGenerationGateway._fingerprint(
            payload | {"composition_reframe": spec().model_dump(mode="json")}
        )
        != expected
    )


def test_verified_case_geometry_and_lossless_restoration():
    plan = plan_reframe((1672, 941), 1920, 1080, spec())
    assert (plan.scaled_width, plan.scaled_height, plan.left, plan.top) == (1433, 807, 300, 78)
    assert abs(plan.actual_box.height - 0.499327903) < 1 / 1080
    assert abs(plan.actual_box.y - 0.251285674) < 1 / 1080
    assert 0.141 < plan.actual_box.width < 0.142  # never distort to requested 12.4%
    original = Image.new("RGB", (1672, 941), "navy")
    ImageDraw.Draw(original).rectangle((658, 226, 975, 855), fill="gold")
    canvas, resized = prepare_reframe(original, plan)
    assert canvas.size == (1920, 1080)
    result, audit = restore_reframe(png(Image.new("RGB", (1672, 941), "red")), resized, plan)
    final = Image.open(BytesIO(result))
    assert final.format == "PNG"
    f = plan.feather
    assert (
        ImageChops.difference(
            resized.crop((f, f, resized.width - f, resized.height - f)),
            final.crop((300 + f, 78 + f, 300 + resized.width - f, 78 + resized.height - f)),
        ).getbbox()
        is None
    )
    assert final.getpixel((0, 0)) == (255, 0, 0)
    assert audit["protected_region_max_pixel_difference"] == 0
    assert audit["measurement"] == "manual_source_box_transformed_not_detection"
    assert audit["environment_review"] == "manual_required"


@pytest.mark.parametrize(
    "box", [dict(x=0.2, y=0.2, width=0.1, height=0.8), dict(x=0, y=0, width=0.1, height=0.5)]
)
def test_invalid_geometry_rejects_crop_or_enlargement(box):
    with pytest.raises(ValueError):
        plan_reframe((1672, 941), 1920, 1080, spec(target_box=box))


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (1024, 1024)])
def test_all_aspects_are_proportional(size):
    s = spec(
        source_box=dict(x=0.3, y=0.1, width=0.4, height=0.8),
        target_box=dict(x=0.4, y=0.25, width=0.2, height=0.5),
    )
    p = plan_reframe(size, *size, s)
    assert abs((p.scaled_width / p.scaled_height) / (size[0] / size[1]) - 1) < 0.002
    assert abs(p.actual_box.height - 0.5) < 1 / size[1]


def test_bad_output_aspect_and_nonfinite_boxes_are_rejected():
    p = plan_reframe((1672, 941), 1920, 1080, spec())
    _, resized = prepare_reframe(Image.new("RGB", (1672, 941)), p)
    with pytest.raises(ValueError, match="画幅"):
        restore_reframe(png(Image.new("RGB", (512, 512))), resized, p)
    with pytest.raises(ValidationError):
        spec(source_box=dict(x=float("nan"), y=0.1, width=0.1, height=0.8))
    with pytest.raises(ValidationError, match="单次生成"):
        ImageGenerationCreate(expected_revision_id=uuid4(), composition_reframe=spec())


@pytest.mark.asyncio
async def test_queue_freezes_geometry_checks_source_and_deduplicates_completed_requests(
    tmp_path, monkeypatch
):
    workspace, repo, project, shot, service = await prepare(tmp_path, monkeypatch)
    candidate, path, _ = await save_base(workspace, repo, project, shot)
    original = path.read_bytes()
    s = spec(
        source_sha256=candidate.sha256,
        source_box=dict(x=0.3, y=0.1, width=0.4, height=0.8),
        target_box=dict(x=0.4, y=0.25, width=0.2, height=0.5),
    )
    payload = ImageGenerationCreate(
        expected_revision_id=project.current_revision_id,
        visual_beat_id=shot.visual_beats[0].id,
        input_mode="keyframe_edit",
        base_image_candidate_id=candidate.id,
        composition_reframe=s,
        width=1024,
        height=1024,
    )
    run = await service._enqueue_image_run(shot.id, payload)
    assert run.request_payload["composition_reframe"] == s.model_dump(mode="json")
    assert (await service._enqueue_image_run(shot.id, payload)).id == run.id
    await repo.save_generation_run(run.model_copy(update={"status": "completed"}))
    assert (await service._enqueue_image_run(shot.id, payload)).id == run.id
    with pytest.raises(ProductionServiceError, match="内容已变化"):
        await service._enqueue_image_run(shot.id, payload.model_copy(update={"width": 512}))
    assert path.read_bytes() == original
    assert (await repo.get_shot_plan(shot.id)).visual_beats[0].approved_image_candidate_id is None
    bad = payload.model_copy(
        update={
            "composition_reframe": s.model_copy(
                update={"request_id": uuid4(), "source_sha256": "b" * 64}
            )
        }
    )
    with pytest.raises(ProductionServiceError, match="原图已变化"):
        await service._enqueue_image_run(shot.id, bad)
    with pytest.raises(ProductionServiceError, match="不属于当前"):
        wrong = (await repo.get_generation_run(candidate.generation_run_id)).model_copy(
            update={"project_id": uuid4()}
        )
        await repo.save_generation_run(wrong)
        await service._enqueue_image_run(shot.id, bad)


async def gateway_fixture(tmp_path, monkeypatch, *, wrong_aspect=False, supports_edit=True):
    workspace, repo, project, shot, service = await prepare(tmp_path, monkeypatch)
    project = project.model_copy(
        update={"output_width": 1024, "output_height": 1024, "output_aspect_ratio": "1:1"}
    )
    candidate, path, _ = await save_base(workspace, repo, project, shot)
    option = load_image_model_catalog().option("qwen_image_2_pro")
    cap = option.capabilities.model_copy(update={"image_to_image": supports_edit})
    identity = AdapterIdentity(
        execution_mode=ImageExecutionMode.REMOTE_API,
        provider=option.provider,
        model=option.model,
        model_snapshot=option.model,
        adapter_id="test",
        adapter_version="1",
        protocol_version="test",
        capability=cap,
        model_option=option,
        estimated_cost_micros=100,
        cost_estimate_known=True,
        cost_source=GenerationCostSource.CONFIGURED_RATE,
    )
    result = AdapterResult(
        images=(
            GeneratedImage(
                payload=png(Image.new("RGB", (320, 180) if wrong_aspect else (512, 512), "red")),
                media_type="image/png",
            ),
        ),
        actual_cost_micros=123,
        provider_request_id="provider-test",
        usage={"image_count": 1},
    )
    adapter = SimpleNamespace(generate=AsyncMock(return_value=result))
    gateway = ImageGenerationGateway(
        workspace,
        SimpleNamespace(
            get=lambda: SimpleNamespace(
                enabled=True, execution_mode="remote_api", semantic_quality_enabled=True
            )
        ),
    )
    gateway._adapter = AsyncMock(return_value=(identity, adapter))
    gateway.semantic_quality_service.assess = AsyncMock(
        side_effect=AssertionError("no additional paid QA for reframe")
    )
    s = spec(
        source_sha256=candidate.sha256,
        source_box=dict(x=0.3, y=0.1, width=0.4, height=0.8),
        target_box=dict(x=0.4, y=0.25, width=0.2, height=0.5),
    )
    return SimpleNamespace(
        workspace=workspace,
        repo=repo,
        project=project,
        shot=shot,
        gateway=gateway,
        adapter=adapter,
        candidate=candidate,
        path=path,
        spec=s,
        service=service,
    )


async def generate(env, **extra):
    return await env.gateway.generate(
        env.project,
        env.shot,
        env.project.current_revision_id,
        [],
        [],
        candidate_count=1,
        source_path=env.path,
        base_image_candidate_id=env.candidate.id,
        input_mode="keyframe_edit",
        composition_reframe=env.spec,
        **extra,
    )


@pytest.mark.asyncio
async def test_gateway_uses_only_prepared_canvas_and_publishes_lossless_candidate(
    tmp_path, monkeypatch
):
    env = await gateway_fixture(tmp_path, monkeypatch)
    run, candidates = await generate(env)
    assert run.status == "completed" and run.actual_cost_micros == 123
    call = env.adapter.generate.call_args.args[0]
    assert call.references == () and call.on_image is None
    assert call.source_path != env.path
    assert "浅灰色空白" in call.positive_prompt
    assert "替换" not in call.positive_prompt
    candidate = candidates[0]
    final = Image.open(_filesystem_path(env.workspace.resolve(candidate.relative_path)))
    assert final.format == "PNG" and final.size == (1024, 1024)
    assert final.getpixel((512, 512)) == Image.open(env.path).convert("RGB").getpixel((32, 32))
    assert (
        candidate.quality_report["composition_reframe"]["protected_region_max_pixel_difference"]
        == 0
    )
    snapshot = json.loads(
        _filesystem_path(env.workspace.resolve(run.input_snapshot_relative_path)).read_text("utf8")
    )
    assert snapshot["composition_reframe"] == env.spec.model_dump(mode="json")
    assert snapshot["source"]["sha256"] == hashlib.sha256(call.source_path.read_bytes()).hexdigest()
    assert run.execution_summary["semantic_quality"]["enabled"] is False


@pytest.mark.asyncio
async def test_failed_restoration_keeps_actual_charge_and_never_publishes_raw_output(
    tmp_path, monkeypatch
):
    env = await gateway_fixture(tmp_path, monkeypatch, wrong_aspect=True)
    callback = AsyncMock()
    run, candidates = await generate(env, on_candidate=callback)
    assert run.status == "failed" and candidates == []
    assert run.error_code == "reframe_restoration_failed"
    assert run.actual_cost_micros == 123 and run.provider_request_id == "provider-test"
    callback.assert_not_called()
    assert _filesystem_path(
        env.workspace.resolve(run.input_snapshot_relative_path).parent / "outpaint-raw-001.bin"
    ).is_file()


@pytest.mark.asyncio
async def test_model_without_edit_support_is_blocked_before_charge(tmp_path, monkeypatch):
    env = await gateway_fixture(tmp_path, monkeypatch, supports_edit=False)
    with pytest.raises(ImageGenerationGatewayError, match="不支持"):
        await generate(env)
    env.adapter.generate.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_always_restores_the_frozen_original_without_another_model_call(
    tmp_path, monkeypatch
):
    env = await gateway_fixture(tmp_path, monkeypatch)
    run, _ = await generate(env)
    raw = _filesystem_path(
        env.workspace.resolve(run.input_snapshot_relative_path).parent / "recovery.png"
    )
    raw.write_bytes(png(Image.new("RGB", (512, 512), "red")))
    monkeypatch.setattr(env.gateway, "recoverable_local_tool_artifacts", lambda _: (raw,))
    recovered, candidates = await env.gateway.recover_local_tool_output(
        run.model_copy(update={"status": "failed"})
    )
    env.adapter.generate.assert_awaited_once()
    assert recovered.status == "completed" and recovered.actual_cost_micros == 123
    image = Image.open(_filesystem_path(env.workspace.resolve(candidates[0].relative_path)))
    assert image.format == "PNG" and image.size == (1024, 1024)
    assert image.getpixel((512, 512)) == Image.open(env.path).convert("RGB").getpixel((32, 32))
    env.path.write_bytes(png(Image.new("RGB", (64, 64), "green")))
    with pytest.raises(ImageGenerationGatewayError, match="原图已变化"):
        await env.gateway.recover_local_tool_output(run)


@pytest.mark.asyncio
async def test_cancellation_after_provider_keeps_cost_without_publishing(tmp_path, monkeypatch):
    env = await gateway_fixture(tmp_path, monkeypatch)
    cancel = Event()
    response = env.adapter.generate.return_value

    async def completed(_):
        cancel.set()
        return response

    env.adapter.generate.side_effect = completed
    run, candidates = await generate(env, cancel_event=cancel)
    assert run.error_code == "generation_cancelled" and candidates == []
    assert run.actual_cost_micros == 123 and run.actual_cost_known


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", [False, True])
async def test_shared_job_pipeline_keeps_approval_and_records_new_candidate(
    tmp_path, monkeypatch, skill
):
    env = await gateway_fixture(tmp_path, monkeypatch)
    if skill:
        skill_env = await environment(tmp_path, monkeypatch, count=1)
        env.service, env.repo = skill_env.service, skill_env.store
        env.project = skill_env.project.model_copy(
            update={"output_width": 1024, "output_height": 1024, "output_aspect_ratio": "1:1"}
        )
        env.shot = skill_env.shots[0]
        env.candidate, env.path, _ = await save_base(env.workspace, env.repo, env.project, env.shot)
        env.spec = env.spec.model_copy(update={"source_sha256": env.candidate.sha256})
    else:
        video = Video(
            id=env.project.video_id,
            record_id=env.project.record_id,
            source_type="upload",
            title="构图测试源视频",
        )
        analysis = AnalysisJob(
            id=env.project.base_analysis_id, record_id=env.project.record_id, video_id=video.id
        )
        await env.repo.save_report(build_simulated_report(video, analysis))
    await env.repo.save_production_project(env.project)
    beat = env.shot.visual_beats[0].model_copy(
        update={
            "approved_image_candidate_id": env.candidate.id,
            "image_status": WorkflowItemStatus.APPROVED,
        }
    )
    env.shot = env.shot.model_copy(
        update={
            "visual_beats": [beat],
            "image_status": WorkflowItemStatus.APPROVED,
            "approved_image_candidate_id": env.candidate.id,
        }
    )
    await env.repo.save_shot_plan(env.shot)
    env.service.image_gateway = env.gateway
    payload = ImageGenerationCreate(
        expected_revision_id=env.project.current_revision_id,
        visual_beat_id=beat.id,
        input_mode="keyframe_edit",
        base_image_candidate_id=env.candidate.id,
        composition_reframe=env.spec,
        width=1024,
        height=1024,
        model_alias="qwen_image_2_pro",
        execution_mode="remote_api",
    )
    queued = await env.service._enqueue_image_run(env.shot.id, payload)
    env.service._schedule_image_run(queued.id)
    await env.service._generation_tasks[queued.id]
    completed = await env.repo.get_generation_run(queued.id)
    assert completed.status == "completed", completed.error_message
    candidates = await env.repo.list_generation_candidates(queued.id)
    assert len(candidates) == 1 and candidates[0].relative_path.endswith(".png")
    assert (await env.repo.get_shot_plan(env.shot.id)).visual_beats[
        0
    ].approved_image_candidate_id == env.candidate.id
    assert (await env.repo.get_production_project(env.project.id)).actual_cost_micros == 123
    assert (await env.service._enqueue_image_run(env.shot.id, payload)).id == queued.id
    env.adapter.generate.assert_awaited_once()
