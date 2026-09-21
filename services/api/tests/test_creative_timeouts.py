"""Scoped HTTP budgets and safe timeout diagnostics; all HTTP calls are stubbed."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from test_creative_concepts import finish, setup
from test_creative_responses import idea_payload

from viral_dna_api.ai.contracts import ModelProviderError, ModelRequest
from viral_dna_api.ai.providers.dashscope import DashScopeProvider
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.models import ModelTask
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeGenerateRequest
from viral_dna_api.viral_insights.creative_errors import request_error_message
from viral_dna_api.viral_insights.creative_prompts import IdeaResponse
from viral_dna_api.viral_insights.creative_service import CREATIVE_MODEL_TIMEOUTS


def mock_http(monkeypatch, handler):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.timeout = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            calls.append((self.timeout, json))
            return await handler(self.timeout, json)

    monkeypatch.setattr("viral_dna_api.ai.providers.dashscope.httpx.AsyncClient", Client)
    return calls


@pytest.mark.asyncio
async def test_creative_timeout_override_does_not_change_shared_provider_defaults(monkeypatch):
    import json

    async def respond(timeout, payload):
        await asyncio.sleep(0)
        return httpx.Response(200, json={
            "model": payload["model"],
            "choices": [{"message": {"content": json.dumps(idea_payload())}}],
        })

    calls = mock_http(monkeypatch, respond)
    _, _, _, _, service = await setup()
    target = (await service.targets())[0]
    provider = DashScopeProvider(api_key="test-only", timeout_seconds=37)
    creative = ModelRequest(ModelTask.VIRAL_REASONING, target, "system", "user",
                            timeouts=CREATIVE_MODEL_TIMEOUTS)
    ordinary = ModelRequest(ModelTask.VIRAL_REASONING, target, "system", "user")
    await asyncio.gather(provider.generate(creative, IdeaResponse),
                         provider.generate(ordinary, IdeaResponse))
    assert [t.as_dict() for t, _ in calls] == [
        {"connect": 10, "read": 180, "write": 30, "pool": 10},
        {"connect": 37, "read": 37, "write": 37, "pool": 37},
    ]
    assert provider.timeout_seconds == 37
    assert service.timeout_seconds == 240
    assert all("timeouts" not in payload for _, payload in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,phase,seconds", [
    (httpx.ConnectTimeout, "connect", 10),
    (httpx.ReadTimeout, "read", 180),
    (httpx.WriteTimeout, "write", 30),
    (httpx.PoolTimeout, "pool", 10),
    (httpx.TimeoutException, "unknown", None),
])
async def test_timeout_phase_persists_without_fallback_or_secret_leaks(
    monkeypatch, tmp_path, exception, phase, seconds
):
    secret = "PRIVATE-api_key=never-log-request-body"

    async def fail(timeout, payload):
        raise exception(secret)

    calls = mock_http(monkeypatch, fail)
    database = tmp_path / "timeout.db"
    repo, report, categories, _, service = await setup(SQLiteStore(database))
    service.router = ModelRouter({"dashscope": DashScopeProvider(api_key="test-only")})
    targets = await service.targets()

    async def with_fallback():
        return targets + targets

    service.targets = with_fallback
    request = CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id)
    result = await finish(service, await service.generate(report.analysis_id, request))
    assert result.status == "failed" and result.error_code == "model_timeout"
    assert "模型请求超时" in result.error_message
    assert "不会自动重试" in result.error_message
    assert "配置、额度或网络" not in result.error_message
    assert result.cost_status == "unreported" and not result.ideas
    assert (await service.generate(report.analysis_id, request)).id == result.id
    assert (await service.get(result.id)).status == "failed"
    assert (await service.history(report.analysis_id))[0].id == result.id
    assert len(calls) == 1
    assert calls[0][0].read == 180
    (run,) = await SQLiteStore(database).list_model_runs(report.analysis_id)
    assert run.error_code == "model_timeout" and run.status == "failed"
    diagnostics = run.response_diagnostics
    assert diagnostics.stage == "request_timeout" and diagnostics.timeout_phase == phase
    assert diagnostics.timeout_seconds == seconds and diagnostics.elapsed_ms >= 0
    assert not run.result_payload and not run.provider_request_id
    assert secret not in run.model_dump_json() and secret not in result.model_dump_json()
    assert len(request_error_message("model_timeout", diagnostics)) <= 500


@pytest.mark.asyncio
async def test_transport_failure_is_not_replayed_on_another_model():
    repo, report, categories, provider, service = await setup()
    targets = await service.targets()

    async def with_fallback():
        return targets + targets

    async def fail(request, schema):
        provider.requests.append(request)
        raise ModelProviderError("model_transport_error", "private-request-body", retryable=True)

    service.targets = with_fallback
    provider.generate = fail
    result = await finish(service, await service.generate(report.analysis_id, CreativeGenerateRequest(
        request_id=uuid4(), category_profile_id=categories.profile.id)))
    assert result.error_code == "model_transport_error"
    assert "模型连接异常" in result.error_message and "private" not in result.error_message
    assert len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_total_deadline_stops_waiting_and_is_distinct_from_user_cancel(cancel):
    repo, report, categories, provider, service = await setup(timeout_seconds=0.2)
    provider.wait = asyncio.Event()
    job = await service.generate(report.analysis_id, CreativeGenerateRequest(
        request_id=uuid4(), category_profile_id=categories.profile.id))
    if cancel:
        while not provider.requests:
            await asyncio.sleep(0)
        await service.cancel(job.id)
    result = await finish(service, job)
    assert result.error_code == ("creative_cancelled" if cancel else "creative_timeout")
    assert result.cost_status == "unreported" and len(provider.requests) == 1
    assert not service.tasks
    (run,) = await repo.list_model_runs(report.analysis_id)
    assert run.status == "failed"
    if cancel:
        assert run.error_code == "creative_interrupted" and run.response_diagnostics is None
    else:
        assert run.error_code == "creative_timeout"
        assert run.response_diagnostics.timeout_phase == "total"
        assert run.response_diagnostics.timeout_seconds == 0.2
        assert "总上限" in result.error_message and "不会自动重试" in result.error_message


@pytest.mark.asyncio
async def test_old_timeout_batch_message_is_read_only_and_does_not_guess_phase():
    repo, report, categories, provider, service = await setup()
    provider.fail = True
    request = CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id)
    failed = await finish(service, await service.generate(report.analysis_id, request))
    failed.error_code = "model_timeout"
    failed.error_message = "创意模型请求失败；请检查模型配置、额度或网络"
    await repo.save_viral_concept_set(failed)
    before = failed.model_dump(mode="json")
    for visible in [await service.get(failed.id), (await service.history(report.analysis_id))[0],
                    await service.generate(report.analysis_id, request)]:
        assert "模型请求超时" in visible.error_message and "180" not in visible.error_message
        assert visible.model_cost_micros == failed.model_cost_micros
    assert (await repo.get_viral_concept_set(failed.id)).model_dump(mode="json") == before
    assert len(provider.requests) == 1
