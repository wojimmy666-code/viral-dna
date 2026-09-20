"""Real response adapter + creative service, with HTTP stubbed before any paid call."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError
from test_creative_concepts import finish, ideas, plan, setup

from viral_dna_api.ai.contracts import ModelProviderError, ModelRequest
from viral_dna_api.ai.providers.dashscope import DashScopeProvider
from viral_dna_api.ai.response_diagnostics import response_diagnostics
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.models import ModelRun, ModelTask
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeActionRequest, CreativeGenerateRequest
from viral_dna_api.viral_insights.creative_errors import format_error_message
from viral_dna_api.viral_insights.creative_prompts import IdeaResponse, PlanResponse
from viral_dna_api.viral_insights.creative_service import CreativeConceptService
from viral_dna_api.viral_insights.routes import create_viral_insight_router


def idea_payload():
    return {
        "ideas": [item.model_dump(mode="json", exclude={"id"}) for item in ideas()],
        "diversity_rationale": "在情绪目标、商品角色及画面关系上各有不同。",
    }


def mock_model_http(monkeypatch, responses):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, headers, json):
            calls.append(json)
            assert len(calls) <= len(responses), "Unexpected model retry"
            content, finish_reason = responses[len(calls) - 1]
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "id": f"mock-response-{len(calls)}",
                    "model": json["model"],
                    "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                    "usage": {"prompt_tokens": 3650, "completion_tokens": 1466},
                },
            )

    monkeypatch.setattr("viral_dna_api.ai.providers.dashscope.httpx.AsyncClient", Client)
    return calls


def install_real_adapter(service):
    service.router = ModelRouter(
        {"dashscope": DashScopeProvider(api_key="test-only-key", base_url="https://model.test/v1")}
    )


def test_content_schemas_do_not_ask_for_internal_identifiers_or_legacy_strategy():
    for schema in (IdeaResponse, PlanResponse):
        document = schema.model_json_schema()
        for definition in document.get("$defs", {}).values():
            properties = definition.get("properties", {})
            assert "id" not in properties and "strategy" not in properties
        assert '"format": "uuid"' not in json.dumps(document)
    fields = IdeaResponse.model_json_schema()["$defs"]["IdeaDraft"]["properties"]
    assert fields["key_scenes"]["items"]["maxLength"] == 300
    assert fields["assumptions"]["items"]["minLength"] == 1


def test_wire_response_is_normalized_locally_and_ids_are_generated_by_server(monkeypatch):
    payload = idea_payload()
    for number, item in enumerate(payload["ideas"]):
        item["id"] = f"idea-{number}"
        item["assumptions"] = None
        item["name"] = "  " + item["name"] + "  "
    concept = plan().model_dump(mode="json")
    concept.update(id="not-a-uuid", strategy="not-a-strategy", risks=None, hook=None)
    for shot in concept["shots"]:
        shot.update(source_shot_id=None, retained_mechanisms=None, negative_constraints=None)
    calls = mock_model_http(
        monkeypatch,
        [
            ("\ufeff```json\n" + json.dumps(payload) + "\n```", "stop"),
            (json.dumps({"concept": concept}), "stop"),
        ],
    )

    async def scenario():
        repo, report, categories, _, service = await setup()
        install_real_adapter(service)
        first = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        assert first.status == "completed", first.error_message
        assert len(first.ideas) == 3
        assert len({item.id for item in first.ideas}) == 3
        assert all(isinstance(item.id, UUID) and item.assumptions == [] for item in first.ideas)
        assert first.ideas[0].name == payload["ideas"][0]["name"].strip()
        expanded = await finish(
            service,
            await service.act(
                first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=True
            ),
        )
        assert expanded.status == "completed", expanded.error_message
        assert expanded.concepts[0].strategy == "creative"
        assert isinstance(expanded.concepts[0].id, UUID)
        assert len(expanded.concepts[0].shots) == 5
        runs = await repo.list_model_runs(report.analysis_id)
        assert all(run.status == "completed" and run.measured_cost_micros > 0 for run in runs)
        assert all(run.schema_version == "creative-content-v3" for run in runs)

    asyncio.run(scenario())
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["missing", "too_long", "wrong_type", "json", "truncated"])
def test_bad_content_persists_safe_diagnostics_and_cost_without_retry(
    monkeypatch, tmp_path, failure
):
    payload = idea_payload()
    secret = "PRIVATE-CREATIVE-TEXT-api_key=should-not-be-logged"
    payload["ideas"][0]["summary"] = secret
    if failure == "missing":
        del payload["ideas"][0]["product_role"]
    elif failure == "too_long":
        payload["ideas"][0]["summary"] = secret * 10
    elif failure == "wrong_type":
        payload["ideas"][0]["key_scenes"] = {"token": secret}
    content = json.dumps(payload)
    if failure in {"json", "truncated"}:
        content = content[:-8]
    calls = mock_model_http(
        monkeypatch, [(content, "length" if failure == "truncated" else "stop")]
    )

    async def scenario():
        repo, report, categories, _, service = await setup(SQLiteStore(tmp_path / "failure.db"))
        install_real_adapter(service)
        targets = await service.targets()

        async def two_targets():
            return targets + targets

        service.targets = two_targets
        result = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        assert result.status == "failed" and result.error_code == "model_schema_invalid"
        assert result.model_cost_micros > 0 and result.cost_status == "measured"
        assert not result.ideas and not result.concepts
        assert "配置、额度或网络" not in result.error_message
        assert "不会自动重试" in result.error_message
        if failure == "missing":
            assert "ideas[0].product_role" in result.error_message
            assert "缺少必填字段" in result.error_message
        elif failure == "too_long":
            assert "ideas[0].summary" in result.error_message and "最多 220" in result.error_message
        elif failure == "wrong_type":
            assert (
                "ideas[0].key_scenes" in result.error_message and "应为数组" in result.error_message
            )
        elif failure == "json":
            assert "不是有效 JSON" in result.error_message
        else:
            assert "输出被截断" in result.error_message
        reopened = SQLiteStore(tmp_path / "failure.db")
        (run,) = await reopened.list_model_runs(report.analysis_id)
        assert run.status == "failed" and run.provider_request_id == "mock-response-1"
        assert run.usage.total_tokens == 5116 and run.measured_cost_micros > 0
        diagnostics = run.response_diagnostics
        assert diagnostics and diagnostics.response_chars == len(content)
        assert len(diagnostics.response_sha256) == 64 and diagnostics.issues
        assert diagnostics.stage == (
            "json_parse" if failure in {"json", "truncated"} else "schema_validation"
        )
        if failure in {"json", "truncated"}:
            assert diagnostics.json_line and diagnostics.json_column
        assert secret not in run.model_dump_json() and secret not in result.error_message
        assert not run.result_payload and not run.raw_response_ref
        restarted = CreativeConceptService(reopened, service.insights)
        assert (await restarted.get(result.id)).error_message == result.error_message

    asyncio.run(scenario())
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [("summary", None), ("summary", "   "), ("key_scenes", [])])
def test_normalization_does_not_invent_required_content(field, value):
    payload = idea_payload()
    payload["ideas"][0][field] = value
    with pytest.raises(ValidationError):
        IdeaResponse.model_validate(payload)


def test_optional_defaults_do_not_weaken_persisted_identity_validation():
    from viral_dna_api.viral_insights.contracts import CreativeIdea, ViralConcept

    with pytest.raises(ValidationError):
        CreativeIdea(**idea_payload()["ideas"][0], id="invalid")
    invalid = plan().model_dump(mode="json")
    invalid["id"] = "invalid"
    with pytest.raises(ValidationError):
        ViralConcept.model_validate(invalid)


def test_existing_failed_batch_reads_correctly_without_rewriting_or_rerunning():
    async def scenario():
        repo, report, categories, provider, service = await setup()
        provider.fail = True
        request = CreativeGenerateRequest(
            request_id=uuid4(), category_profile_id=categories.profile.id
        )
        failed = await finish(
            service,
            await service.generate(report.analysis_id, request),
        )
        failed.error_code = "model_schema_invalid"
        failed.error_message = "创意模型请求失败；请检查模型配置、额度或网络"
        await repo.save_viral_concept_set(failed)
        assert "格式校验失败" in (await service.get(failed.id)).error_message
        assert "格式校验失败" in (await service.history(report.analysis_id))[0].error_message
        replay = await service.generate(report.analysis_id, request)
        assert replay.id == failed.id and "格式校验失败" in replay.error_message
        app = FastAPI()
        app.include_router(create_viral_insight_router(service.insights, service))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            latest = await client.get(f"/analyses/{report.analysis_id}/viral-concepts/latest")
        assert latest.status_code == 200 and "格式校验失败" in latest.json()["error_message"]
        assert (await repo.get_viral_concept_set(failed.id)).error_message == failed.error_message
        assert len(provider.requests) == 1

    asyncio.run(scenario())


def test_diagnostics_cap_errors_and_omit_raw_values():
    content = '{"ideas": [{}, {}, {}], "secret": "do-not-log"}'
    with pytest.raises(ValidationError) as raised:
        IdeaResponse.model_validate_json(content)
    diagnostics = response_diagnostics(raised.value, IdeaResponse, content, "stop")
    assert len(diagnostics.issues) == 12
    serialized = diagnostics.model_dump_json()
    assert "do-not-log" not in serialized and "ctx" not in serialized
    assert "input" not in serialized and "message" not in serialized
    assert len(format_error_message(diagnostics)) <= 500
    # The new optional ledger field must not make historical model runs unreadable.
    old = ModelRun(
        analysis_id=uuid4(),
        video_id=uuid4(),
        task=ModelTask.VIRAL_REASONING,
        provider="dashscope",
        requested_model="test",
        prompt_version="v1",
        schema_version="v1",
        request_fingerprint="a" * 64,
    )
    assert (
        ModelRun.model_validate_json(
            old.model_dump_json(exclude={"response_diagnostics"})
        ).response_diagnostics
        is None
    )


def test_bad_response_envelope_has_safe_diagnostics(monkeypatch):
    async def scenario():
        _, _, _, _, service = await setup()
        target = (await service.targets())[0]
        provider = DashScopeProvider(api_key="test-only-key")

        async def malformed_response(*args, **kwargs):
            from viral_dna_api.models import ModelUsage

            return {"choices": [None]}, 12, "mock-envelope", ModelUsage(total_tokens=7)

        monkeypatch.setattr(provider, "_request_json", malformed_response)
        with pytest.raises(ModelProviderError) as raised:
            await provider.generate(
                ModelRequest(ModelTask.VIRAL_REASONING, target, "Return JSON", "test"), IdeaResponse
            )
        error = raised.value
        assert error.code == "model_schema_invalid" and error.usage.total_tokens == 7
        assert error.diagnostics.stage == "response_envelope"
        assert "缺少可读取的正文" in format_error_message(error.diagnostics)

    asyncio.run(scenario())


def test_diagnostics_do_not_leak_model_supplied_dictionary_keys():
    class ResponseWithMapping(BaseModel):
        entries: dict[str, int]

    content = '{"entries": {"sensitive-key": "sensitive-value"}}'
    with pytest.raises(ValidationError) as raised:
        ResponseWithMapping.model_validate_json(content)
    diagnostics = response_diagnostics(raised.value, ResponseWithMapping, content)
    assert diagnostics.issues[0].path == "entries.field"
    assert "sensitive" not in diagnostics.model_dump_json()
