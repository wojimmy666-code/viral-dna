from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from viral_dna_api.ai.catalog import load_model_plan
from viral_dna_api.ai.contracts import ModelProviderError, ModelRequest
from viral_dna_api.ai.providers.dashscope import DashScopeProvider
from viral_dna_api.models import (
    AnalysisProfile,
    ModelTask,
    ShotVisualBeatFact,
    ShotVisualFacts,
)


@pytest.mark.asyncio
async def test_dashscope_adapter_normalizes_json_and_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    plan = load_model_plan(AnalysisProfile.BALANCED)
    assert plan is not None
    target = plan.targets_for(ModelTask.SHOT_FACTS)[0]
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")
    second_image_path = tmp_path / "frame-2.jpg"
    second_image_path.write_bytes(b"fake-jpeg-2")
    captured: dict = {}

    facts = ShotVisualFacts(
        title="产品特写",
        subjects=["产品"],
        action="产品保持静止",
        scene="室内桌面",
        camera="固定特写",
        composition="产品居中",
        lighting="柔和侧光",
        color="暖色",
        transition="直接切入",
        narrative_role="展示细节",
        replication_prompt="竖屏产品特写，暖色柔和侧光。",
        confidence=0.9,
        visual_beats=[
            ShotVisualBeatFact(
                index=1,
                title="画面 1",
                start_seconds=0,
                end_seconds=3,
                source_timestamp_seconds=1.5,
                image_prompt="竖屏产品特写，暖色柔和侧光。",
            )
        ],
    )

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return httpx.Response(
                200,
                headers={"x-request-id": "request-header-id"},
                json={
                    "id": "response-id",
                    "model": target.model,
                    "choices": [
                        {
                            "message": {
                                "content": facts.model_dump_json(),
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1200,
                        "completion_tokens": 400,
                        "total_tokens": 1600,
                        "prompt_tokens_details": {"cached_tokens": 200},
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "viral_dna_api.ai.providers.dashscope.httpx.AsyncClient",
        FakeClient,
    )
    provider = DashScopeProvider(api_key="test-key", base_url="https://example.test/v1")
    result = await provider.generate(
        ModelRequest(
            task=ModelTask.SHOT_FACTS,
            target=target,
            system_prompt="请输出 JSON",
            user_prompt="分析这张图片并输出 JSON",
            image_paths=(image_path, second_image_path),
            image_labels=("候选 candidate_001", "候选 candidate_002"),
        ),
        ShotVisualFacts,
    )

    assert result.data == facts
    assert result.provider_request_id == "response-id"
    assert result.usage.input_tokens == 1200
    assert result.usage.cached_input_tokens == 200
    assert result.usage.output_tokens == 400
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["payload"]["enable_thinking"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    user_content = captured["payload"]["messages"][1]["content"]
    assert [item["type"] for item in user_content] == [
        "text",
        "text",
        "image_url",
        "text",
        "image_url",
    ]
    assert user_content[1]["text"] == "候选 candidate_001"
    assert user_content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert user_content[3]["text"] == "候选 candidate_002"
    assert result.usage.image_count == 2


@pytest.mark.asyncio
async def test_dashscope_adapter_sends_native_video_with_sampling_rate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    plan = load_model_plan(AnalysisProfile.BALANCED)
    assert plan is not None
    target = plan.targets_for(ModelTask.SHOT_FACTS)[0]
    video_path = tmp_path / "shot.mp4"
    video_path.write_bytes(b"fake-mp4")
    fallback_image = tmp_path / "frame.jpg"
    fallback_image.write_bytes(b"fake-jpeg")
    captured: dict = {}
    facts = ShotVisualFacts(
        title="continuous push-in",
        subjects=["ribbon"],
        action="ribbon approaches camera",
        scene="interior",
        camera="continuous push-in",
        composition="foreground expands",
        lighting="soft",
        color="green",
        transition="foreground occlusion",
        narrative_role="transition",
        replication_prompt="Push in until the ribbon fills the frame.",
        confidence=0.9,
        visual_beats=[
            ShotVisualBeatFact(
                index=1,
                title="ribbon",
                start_seconds=0,
                end_seconds=3,
                source_timestamp_seconds=1.5,
                image_prompt="green ribbon in foreground",
            )
        ],
    )

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return httpx.Response(
                200,
                json={
                    "id": "native-video-response",
                    "model": target.model,
                    "choices": [{"message": {"content": facts.model_dump_json()}}],
                    "usage": {
                        "prompt_tokens": 900,
                        "completion_tokens": 300,
                        "total_tokens": 1200,
                    },
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "viral_dna_api.ai.providers.dashscope.httpx.AsyncClient",
        FakeClient,
    )
    provider = DashScopeProvider(api_key="test-key", base_url="https://example.test/v1")
    result = await provider.generate(
        ModelRequest(
            task=ModelTask.SHOT_FACTS,
            target=target,
            system_prompt="Return JSON",
            user_prompt="Analyze temporal motion",
            image_paths=(fallback_image,),
            video_path=video_path,
            video_fps=6,
            video_duration_seconds=3.9,
        ),
        ShotVisualFacts,
    )

    user_content = captured["payload"]["messages"][1]["content"]
    assert [item["type"] for item in user_content] == ["video_url", "text"]
    assert user_content[0]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert user_content[0]["fps"] == 6
    assert result.usage.image_count == 0
    assert result.usage.video_seconds == pytest.approx(3.9)


@pytest.mark.asyncio
async def test_dashscope_schema_failure_preserves_billable_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    plan = load_model_plan(AnalysisProfile.BALANCED)
    assert plan is not None
    target = plan.targets_for(ModelTask.SHOT_FACTS)[0]
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"jpeg")

    class FakeResponse:
        status_code = 200
        headers = {"x-request-id": "header-id"}

        def json(self):
            return {
                "id": "charged-invalid-response",
                "model": target.model,
                "choices": [{"message": {"content": '{"title":"incomplete"}'}}],
                "usage": {
                    "prompt_tokens": 800,
                    "completion_tokens": 100,
                    "total_tokens": 900,
                },
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("viral_dna_api.ai.providers.dashscope.httpx.AsyncClient", FakeClient)
    provider = DashScopeProvider(api_key="test-key")
    request = ModelRequest(ModelTask.SHOT_FACTS, target, "system", "user", (image_path,))
    with pytest.raises(ModelProviderError) as raised:
        await provider.generate(request, ShotVisualFacts)
    assert raised.value.usage is not None
    assert raised.value.usage.total_tokens == 900
    assert raised.value.provider_request_id == "charged-invalid-response"
