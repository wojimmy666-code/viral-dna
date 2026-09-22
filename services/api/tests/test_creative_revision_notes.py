"""Per-idea directions are separate from the shared brief; never call a live model."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from test_creative_concepts import finish, setup

from viral_dna_api.viral_insights.contracts import CreativeActionRequest, CreativeGenerateRequest
from viral_dna_api.viral_insights.creative_service import digest
from viral_dna_api.viral_insights.routes import create_viral_insight_router
from viral_dna_api.viral_insights.service import ViralInsightServiceError


def prompt_data(request):
    return json.loads(request.user_prompt.split("创作资料：\n")[1].split("\nJSON Schema：")[0])


async def initial_batch(service, report, categories):
    return await finish(
        service,
        await service.generate(
            report.analysis_id,
            CreativeGenerateRequest(
                request_id=uuid4(), category_profile_id=categories.profile.id, feedback="保留冷光"
            ),
        ),
    )


def test_notes_reach_model_and_snapshot_without_changing_other_ideas_or_shared_brief(tmp_path):
    from viral_dna_api.sqlite_store import SQLiteStore

    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "db.sqlite")
        )
        first = await initial_batch(service, report, categories)
        before = first.model_dump(mode="json")
        notes = "把第一处场景改为雨夜巴黎，强调裙摆与灯光呼应。"
        result = await finish(
            service,
            await service.act(
                first.id,
                first.ideas[0].id,
                CreativeActionRequest(request_id=uuid4(), revision_notes=notes),
                expand=False,
            ),
        )
        assert result.status == "completed"
        request = provider.requests[-1]
        data = prompt_data(request)
        assert data["revision_notes"] == notes
        assert data["effective_creative_brief"]["text"] == first.feedback
        assert data["selected_idea"]["id"] == str(first.ideas[0].id)
        assert [item["id"] for item in data["existing_ideas"]] == [
            str(i.id) for i in first.ideas[1:]
        ]
        assert data["count"] == 1
        assert "revision_notes" not in data["source_and_category"]
        assert "落实到实际 summary、scene_plan" in request.user_prompt
        assert request.target.prompt_version == "creative-ideas-revision-v1"
        assert result.revision_notes == result.input_snapshot["revision_notes"] == notes
        assert result.feedback == first.feedback
        assert result.ideas[1:] == first.ideas[1:]
        assert first.model_dump(mode="json") == before
        assert (await service.get(first.id)).model_dump(mode="json") == before
        stored = await repo.get_viral_concept_set(result.id)
        assert stored.revision_notes == notes
        assert len(provider.requests) == 2

    asyncio.run(scenario())


def test_notes_are_idempotent_and_do_not_leak_into_later_actions():
    async def scenario():
        _, report, categories, provider, service = await setup()
        first = await initial_batch(service, report, categories)
        payload = CreativeActionRequest(request_id=uuid4(), revision_notes="改为雨夜")
        revised = await finish(
            service, await service.act(first.id, first.ideas[0].id, payload, expand=False)
        )
        same = await service.act(first.id, first.ideas[0].id, payload, expand=False)
        assert same.id == revised.id and len(provider.requests) == 2
        with pytest.raises(ViralInsightServiceError, match="不同内容"):
            await service.act(
                first.id,
                first.ideas[0].id,
                payload.model_copy(update={"revision_notes": "改为晴天"}),
                expand=False,
            )
        for expand in (False, True):
            result = await finish(
                service,
                await service.act(
                    revised.id,
                    revised.ideas[1].id,
                    CreativeActionRequest(request_id=uuid4()),
                    expand=expand,
                ),
            )
            assert result.revision_notes is None
            assert "revision_notes" not in result.input_snapshot
            assert "revision_notes" not in prompt_data(provider.requests[-1])
            assert "按用户修改意见修订一条" not in provider.requests[-1].user_prompt

    asyncio.run(scenario())


def test_old_action_signature_is_still_retryable():
    async def scenario():
        repo, report, categories, provider, service = await setup()
        first = await initial_batch(service, report, categories)
        payload = CreativeActionRequest(request_id=uuid4())
        revised = await finish(
            service, await service.act(first.id, first.ideas[0].id, payload, expand=False)
        )
        old_signature = digest(
            {
                "operation": "regenerate",
                "parent": str(first.id),
                "idea": str(first.ideas[0].id),
                "request_id": str(payload.request_id),
                "feedback": None,
            }
        )
        assert revised.request_signature == old_signature
        raw = revised.model_dump(mode="json")
        raw.pop("revision_notes")
        await repo.save_viral_concept_set(type(revised).model_validate(raw))
        assert (
            await service.act(first.id, first.ideas[0].id, payload, expand=False)
        ).id == revised.id
        assert len(provider.requests) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("notes", ["", " \r\n\t ", "改" * 2001])
def test_empty_or_oversized_notes_are_rejected(notes):
    with pytest.raises(ValidationError):
        CreativeActionRequest(request_id=uuid4(), revision_notes=notes)
    assert (
        CreativeActionRequest(request_id=uuid4(), revision_notes="  改为雨夜  ").revision_notes
        == "改为雨夜"
    )


def test_api_exposes_notes_support_and_accepts_notes_only_for_revision():
    async def scenario():
        _, report, categories, provider, service = await setup()
        first = await initial_batch(service, report, categories)
        api = FastAPI()
        api.include_router(create_viral_insight_router(service.insights, service))
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            history = await client.get(f"/analyses/{report.analysis_id}/viral-concepts/history")
            assert history.status_code == 200
            assert history.json()[0]["revision_notes"] is None
            base = f"/viral-concept-sets/{first.id}/ideas/{first.ideas[0].id}"
            body = {"request_id": str(uuid4()), "revision_notes": "改为雨夜"}
            invalid = await client.post(base + "/expand", json=body)
            assert invalid.status_code == 422
            assert len(provider.requests) == 1
            accepted = await client.post(base + "/regenerate", json=body)
            assert accepted.status_code == 202
            assert accepted.json()["revision_notes"] == body["revision_notes"]
            await finish(service, await service.get(UUID(accepted.json()["id"])))
            assert prompt_data(provider.requests[-1])["revision_notes"] == body["revision_notes"]

    asyncio.run(scenario())
