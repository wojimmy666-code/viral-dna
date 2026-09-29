"""Regression: image-first Seedance jobs reach the real adapter with every image.

All HTTP is replaced with an in-process transport. No real generation or billing.
"""
import base64
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from test_image_batches import environment
from test_video_reference_planner import _frame, _managed, _shot

from viral_dna_api.models import VideoGenerationAudioStrategy, VideoGenerationInputPlan
from viral_dna_api.video_generation.catalog import load_video_model_catalog
from viral_dna_api.video_generation.gateway import VideoGenerationGateway, VideoGenerationGatewayError
from viral_dna_api.video_generation.settings import VideoGenerationSettingsService
from viral_dna_api.video_references.domain import VideoReferenceBinding
from viral_dna_api.video_references.planner import VideoReferencePolicyError, resolve_video_reference_plan


@pytest.mark.parametrize("alias", ["seedance_2_0", "seedance_2_0_fast", "seedance_2_0_mini"])
@pytest.mark.parametrize("count", [1, 5])
def test_image_first_seedance_preserves_all_images_without_actor_or_depth(alias, count):
    frames = tuple(_frame(i) for i in range(1, count + 1))
    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option(alias).capability, shot=_shot(),
        reference_frames=frames, managed_asset_references=(), input_policy="adopted_images_v1",
    )
    assert plan.reference_frames == frames
    assert not plan.managed_asset_references and not plan.depth_control_videos
    assert not plan.excluded_references
    assert plan.route_id == "ordered_multi_image"
    assert any("审核" in warning for warning in plan.warnings)


def test_optional_managed_actor_does_not_discard_adopted_images():
    frames = tuple(_frame(i) for i in range(1, 6))
    actor = _managed()
    plan = resolve_video_reference_plan(
        capability=load_video_model_catalog().option("seedance_2_0").capability, shot=_shot(),
        reference_frames=frames, managed_asset_references=(actor,), input_policy="adopted_images_v1",
    )
    assert plan.reference_frames == frames and plan.managed_asset_references == (actor,)
    assert not plan.excluded_references


def test_image_first_over_capacity_fails_without_dropping_images():
    with pytest.raises(VideoReferencePolicyError) as caught:
        resolve_video_reference_plan(
            capability=load_video_model_catalog().option("seedance_2_0").capability, shot=_shot(),
            reference_frames=tuple(_frame(i) for i in range(1, 11)),
            managed_asset_references=(), input_policy="adopted_images_v1",
        )
    assert caught.value.code == "provider_reference_limit"


def test_known_real_person_restriction_remains_scoped_to_selected_images():
    frame = _frame(1)
    shot = _shot().model_copy(update={"video_reference_bindings": [VideoReferenceBinding(
        role="composition", source_kind="local_original", media_type="image",
        image_candidate_id=frame.candidate_id, person_class="real_person",
    )]})
    args = dict(capability=load_video_model_catalog().option("seedance_2_0").capability,
                shot=shot, reference_frames=(frame,), managed_asset_references=(), input_policy="adopted_images_v1")
    with pytest.raises(VideoReferencePolicyError) as caught:
        resolve_video_reference_plan(**args)
    assert caught.value.code == "video_real_person_reference_unsupported"
    assert resolve_video_reference_plan(**{**args, "reference_frames": (_frame(1),)}).reference_frames


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["seedance_2_0", "seedance_2_0_fast"])
@pytest.mark.parametrize("accepted", [False, True])
async def test_five_images_reach_seedance_http_without_actor_then_report_provider_error(tmp_path, monkeypatch, alias, accepted):
    env = await environment(tmp_path, monkeypatch, count=1)
    monkeypatch.setenv("ARK_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("VIRAL_DNA_VIDEO_GENERATION_ENABLED", "true")
    posted = []
    provider_error = {"code": "InputImageSensitiveContentDetected.PrivacyInformation", "message": "The input image content[2] may contain real person."}

    def handle(request):
        if request.method == "POST":
            assert request.url.path.endswith("/contents/generations/tasks")
            posted.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "mock-seedance-task"}) if accepted else httpx.Response(400, json={"error": provider_error})
        assert accepted and request.method == "GET" and request.url.path.endswith("/mock-seedance-task")
        return httpx.Response(200, json={"id": "mock-seedance-task", "status": "failed", "error": provider_error})

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(**{**kwargs, "transport": httpx.MockTransport(handle), "trust_env": False}))
    frames = []
    for index in range(1, 6):
        path = env.service.workspace.root / f"test-frame-{index}.png"
        Image.new("RGB", (640, 360), (index * 30, 40, 60)).save(path)
        frames.append(replace(_frame(index), path=path, relative_path=env.service.workspace.relative(path),
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest(), start_ratio=(index - 1) / 5, end_ratio=index / 5))
    inputs = VideoGenerationInputPlan(input_policy="adopted_images_v1", sources=["approved_images"])
    gateway = VideoGenerationGateway(env.service.workspace, settings_service=VideoGenerationSettingsService(), repository=env.store)
    run_id = uuid4()
    with pytest.raises(VideoGenerationGatewayError) as caught:
        await gateway.generate(env.project, env.shots[0], env.project.current_revision_id, tuple(frames),
            candidate_count=1, duration_seconds=8, execution_mode="remote_api", model_alias=alias,
            resolution="720P", audio_strategy=VideoGenerationAudioStrategy.MUTED, allow_unknown_cost=True, input_plan=inputs, run_id=run_id)
    assert len(posted) == 1  # failure is remote, not the old preflight blocker
    images = [item for item in posted[0]["content"] if item["type"] == "image_url"]
    assert len(images) == 5
    assert all(item["role"] == "reference_image" for item in images)
    assert [base64.b64decode(item["image_url"]["url"].split(",", 1)[1]) for item in images] == [f.path.read_bytes() for f in frames]
    text = posted[0]["content"][0]["text"]
    assert all(f"图片{i} 是已采用的分镜画面" in text for i in range(1, 6))
    assert "唯一演员身份来源" not in text
    assert caught.value.code == "video_provider_content_rejected"
    tasks = await env.store.list_video_provider_tasks(run_id)
    assert len(tasks) == 1 and tasks[0].provider_error_code == provider_error["code"]
    assert bool(tasks[0].provider_task_id) == accepted


@pytest.mark.asyncio
async def test_seedance_connection_error_keeps_exact_transport_reason(monkeypatch):
    from viral_dna_api.video_generation.contracts import ProviderVideoRequest
    from viral_dna_api.video_generation.errors import VideoProviderError, video_failure_location
    from viral_dna_api.video_generation.providers.seedance.adapter import SeedanceVideoProvider
    from viral_dna_api.video_generation.providers.seedance.client import SeedanceClient

    async def offline_create(self, payload):
        raise httpx.ConnectError("DNS lookup failed")

    monkeypatch.setattr(SeedanceClient, "create_task", offline_create)
    request = ProviderVideoRequest(request_id=uuid4(), ordinal=1, model_alias="seedance_2_0",
        provider_model="doubao-seedance-2-0-260128", prompt="测试", negative_prompt="",
        reference_frames=(), duration_seconds=8, resolution="720P", aspect_ratio="16:9", width=1280, height=720)
    with pytest.raises(VideoProviderError) as caught:
        await SeedanceVideoProvider().submit(request, api_key="test-only", base_url="https://example.invalid")
    assert caught.value.code == "video_provider_unavailable"
    assert "ConnectError" in caught.value.technical_message
    assert "DNS lookup failed" in caught.value.technical_message
    assert video_failure_location(code=caught.value.code)["provider_submission_state"] == "unknown"
