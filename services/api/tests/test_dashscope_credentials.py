from __future__ import annotations

import httpx
import pytest

from viral_dna_api.ai.providers.dashscope import DashScopeProvider


@pytest.mark.asyncio
async def test_dashscope_credential_validation_uses_minimal_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

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
                    "id": "validation-id",
                    "model": json["model"],
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 1,
                        "total_tokens": 9,
                    },
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "viral_dna_api.ai.providers.dashscope.httpx.AsyncClient",
        FakeClient,
    )
    result = await DashScopeProvider(
        api_key="credential-secret",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).validate_credentials("qwen3.7-plus-2026-05-26")

    assert captured["payload"]["max_tokens"] == 1
    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["enable_thinking"] is False
    assert captured["headers"]["Authorization"] == "Bearer credential-secret"
    assert result.provider_request_id == "validation-id"
    assert result.usage.total_tokens == 9
