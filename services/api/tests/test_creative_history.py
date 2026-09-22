import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_creative_brief import BRIEF, landmark_response
from test_creative_concepts import finish, setup

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeGenerateRequest, CreativeIdea
from viral_dna_api.viral_insights.creative_brief import (
    CreativeBriefEvidenceError,
    freeze_brief,
    validate_brief_checks,
)
from viral_dna_api.viral_insights.creative_prompts import IdeaResponse
from viral_dna_api.viral_insights.routes import create_viral_insight_router


def stored_ideas():
    brief = freeze_brief(BRIEF)
    return [
        CreativeIdea(
            **draft.model_dump(exclude={"brief_checks"}),
            brief_checks=validate_brief_checks(draft, brief, label="历史创意"),
        )
        for draft in IdeaResponse.model_validate(landmark_response()).ideas
    ]


@pytest.mark.parametrize("saved_label", [None, "旧记录中的要求标签"])
def test_revalidate_persisted_fulfillment_uses_frozen_brief_without_mutation(saved_label):
    idea = CreativeIdea.model_validate_json(stored_ideas()[0].model_dump_json())
    if saved_label:
        idea.brief_checks[0].requirement = saved_label
    original = idea.model_dump_json()
    brief = freeze_brief(BRIEF)
    checks = validate_brief_checks(idea, brief, label="历史创意")
    assert [check.requirement for check in checks] == [
        item["text"] for item in brief["requirements"]
    ]
    assert idea.model_dump_json() == original
    idea.brief_checks = checks
    assert validate_brief_checks(idea, brief, label="再次读取") == checks


def test_persisted_fulfillment_still_rejects_invalid_evidence():
    idea = stored_ideas()[0]
    idea.brief_checks[0].evidence[0].quote = "画面中不存在的地标"
    with pytest.raises(CreativeBriefEvidenceError, match="引用校验失败"):
        validate_brief_checks(idea, freeze_brief(BRIEF), label="历史创意")


def test_mixed_legacy_history_api_and_new_generation_remain_available(tmp_path):
    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "history.db")
        )

        async def generate():
            return await finish(
                service,
                await service.generate(
                    report.analysis_id,
                    CreativeGenerateRequest(
                        request_id=uuid4(),
                        category_profile_id=categories.profile.id,
                        feedback=BRIEF,
                    ),
                ),
            )

        current = await generate()
        batches = [current]
        for status in ("completed", "failed"):
            legacy = current.model_copy(
                deep=True,
                update={
                    "id": uuid4(),
                    "request_id": None,
                    "status": status,
                    "requirement_rules": [],
                    "review_source_fingerprint": None,
                    "ideas": stored_ideas(),
                    "error_code": "creative_brief_unmet" if status == "failed" else None,
                },
            )
            if status == "failed":
                legacy.ideas[0].brief_checks[1].evidence.pop()
            await repo.save_viral_concept_set(legacy)
            batches.append(legacy)
        before = {
            str(item.id): (await repo.get_viral_concept_set(item.id)).model_dump_json()
            for item in batches
        }
        calls_before_read = len(provider.requests)
        app = FastAPI()
        app.include_router(create_viral_insight_router(service.insights, service), prefix="/api/v1")
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            path = f"/api/v1/analyses/{report.analysis_id}/viral-concepts/history"
            for suffix in ("", f"?category_profile_id={categories.profile.id}", ""):
                response = await client.get(path + suffix)
                assert response.status_code == 200, response.text
                items = {item["id"]: item for item in response.json()}
                assert set(items) == set(before)
                assert items[str(batches[1].id)]["ideas"][0]["review_state"] == "ready"
                assert items[str(batches[2].id)]["status"] == "failed"
                assert items[str(batches[2].id)]["ideas"][0]["review_state"] == "needs_review"
            for batch in batches:
                response = await client.get(f"/api/v1/viral-concept-sets/{batch.id}")
                assert response.status_code == 200, response.text
            response = await client.get(path + f"?category_profile_id={uuid4()}")
            assert response.status_code == 200 and response.json() == []
        assert len(provider.requests) == calls_before_read
        assert {
            str(item.id): (await repo.get_viral_concept_set(item.id)).model_dump_json()
            for item in batches
        } == before
        # Starting a new batch also reads history; it must not fail on the old fulfillment shape.
        next_batch = await generate()
        assert next_batch.status == "completed"
        assert len(provider.requests) == calls_before_read + 1
        assert {
            str(item.id): (await repo.get_viral_concept_set(item.id)).model_dump_json()
            for item in batches
        } == before

    asyncio.run(scenario())
