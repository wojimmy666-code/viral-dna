from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from viral_dna_api.ai.catalog import load_model_plan
from viral_dna_api.ai.contracts import ModelProviderError, ModelRequest
from viral_dna_api.ai.providers.dashscope import DashScopeProvider
from viral_dna_api.models import AnalysisProfile, ModelTask, ShotVisualFacts


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
            image_paths=(image_path,),
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
    assert captured["payload"]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


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

    monkeypatch.setattr(
        "viral_dna_api.ai.providers.dashscope.httpx.AsyncClient", FakeClient
    )
    provider = DashScopeProvider(api_key="test-key")
    request = ModelRequest(ModelTask.SHOT_FACTS, target, "system", "user", (image_path,))
    with pytest.raises(ModelProviderError) as raised:
        await provider.generate(request, ShotVisualFacts)
    assert raised.value.usage is not None
    assert raised.value.usage.total_tokens == 900
    assert raised.value.provider_request_id == "charged-invalid-response"
