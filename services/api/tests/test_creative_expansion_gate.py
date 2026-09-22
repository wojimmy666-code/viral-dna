"""Historical evidence gaps must not force an extra paid rewrite before expansion."""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_creative_concepts import finish, plan, setup
from test_creative_review import BRIEF, response

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import (
    CreativeActionRequest,
    CreativeGenerateRequest,
    CreativeIdea,
)
from viral_dna_api.viral_insights.creative_brief import freeze_brief
from viral_dna_api.viral_insights.creative_prompts import PlanResponse
from viral_dna_api.viral_insights.creative_review import idea_can_expand, idea_ready, review_idea
from viral_dna_api.viral_insights.creative_review_models import CreativeReviewIssue
from viral_dna_api.viral_insights.routes import create_viral_insight_router


def legacy_ideas():
    return [
        CreativeIdea(
            **item.model_dump(exclude={"brief_checks", "common_rules", "requirement_checks"})
        )
        for item in response().ideas
    ]


@pytest.mark.parametrize(
    "case,allowed",
    [
        ("legacy", True),
        ("ready", True),
        ("no_plan", False),
        ("order", False),
        ("blank_scene", False),
        ("stale_brief", False),
        ("no_details", False),
        ("content_conflict", False),
        ("semantic_uncertain", False),
        ("check_missing", False),
        ("mixed", False),
        ("severity", False),
    ],
)
def test_expansion_only_relaxes_missing_legacy_evidence(case, allowed):
    idea = review_idea(legacy_ideas()[0], freeze_brief(BRIEF))
    brief = BRIEF
    assert idea.review_state == "needs_review"
    assert {issue.code for issue in idea.review_details} == {"legacy_evidence_missing"}
    if case == "ready":
        draft = response()
        idea = review_idea(draft.ideas[0], freeze_brief(BRIEF), draft.requirement_rules)
    elif case == "no_plan":
        idea.scene_plan = []
    elif case == "order":
        idea.scene_plan[1].index = 1
    elif case == "blank_scene":
        idea.scene_plan[1].description = " "
    elif case == "stale_brief":
        brief += "，新的要求"
    elif case == "no_details":
        idea.review_details = []
    elif case == "severity":
        idea.review_details[0].severity = "revision"
    elif case in {"content_conflict", "semantic_uncertain", "check_missing"}:
        idea.review_details[0].code = case
    elif case == "mixed":
        idea.review_details.append(
            CreativeReviewIssue(
                code="scene_count",
                severity="revision",
                message="场景数量错误",
            )
        )
        idea.review_issues.append("场景数量错误")
    before = idea.model_dump(mode="json")
    assert idea_can_expand(idea, brief) is allowed
    assert idea.model_dump(mode="json") == before
    assert idea_ready(idea, brief) is (case == "ready")


async def historical_batch(repo, report, categories, service):
    batch = await finish(
        service,
        await service.generate(
            report.analysis_id,
            CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id),
        ),
    )
    batch.ideas = legacy_ideas()
    batch.feedback = BRIEF
    batch.input_snapshot["creative_brief"] = freeze_brief(BRIEF)
    batch.status = "failed"
    batch.error_code = "creative_brief_unmet"
    batch.error_message = "旧批次缺少核对记录"
    await repo.save_viral_concept_set(batch)
    return batch


def expanded_response(mode):
    source = response()
    concept = plan().model_dump()
    concept["common_rules"] = source.ideas[0].common_rules
    concept["requirement_checks"] = source.ideas[0].requirement_checks
    concept["brief_checks"] = []
    for shot, scene in zip(concept["shots"], source.ideas[0].scene_plan):
        shot["description"] = scene.description
    if mode == "conflict":
        concept["requirement_checks"][0].satisfied = False
        concept["requirement_checks"][0].conflicting_scenes = [3]
    if mode == "count":
        concept["shots"].pop()
    return PlanResponse(concept=concept, requirement_rules=source.requirement_rules)


@pytest.mark.parametrize("mode", ["valid", "conflict", "count"])
def test_legacy_expansion_is_one_explicit_call_with_fresh_validation_and_unchanged_history(
    tmp_path, mode
):
    async def scenario():
        repo, report, categories, provider, service = await setup(SQLiteStore(tmp_path / "case.db"))
        batch = await historical_batch(repo, report, categories, service)
        before = (await repo.get_viral_concept_set(batch.id)).model_dump(mode="json")
        original_generate = provider.generate

        async def generate(request, schema):
            result = await original_generate(request, schema)
            if schema is PlanResponse:
                result = replace(result, data=expanded_response(mode))
            return result

        provider.generate = generate
        api = FastAPI()
        api.include_router(create_viral_insight_router(service.insights, service))
        # Use the currently edited full brief, not a forced rewrite or stale source text.
        current_brief = BRIEF.replace("向左走", "向左匀速走")
        body = {"request_id": str(uuid4()), "feedback": current_brief}
        path = f"/viral-concept-sets/{batch.id}/ideas/{batch.ideas[0].id}/expand"
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            history = await client.get(f"/analyses/{report.analysis_id}/viral-concepts/history")
            assert history.status_code == 200
            assert len(provider.requests) == 1
            assert history.json()[0]["ideas"][0]["review_state"] == "needs_review"
            submitted = await client.post(path, json=body)
            assert submitted.status_code == 202, submitted.text
            result = await finish(service, await service.get(UUID(submitted.json()["id"])))
            assert result.status == ("completed" if mode == "valid" else "failed")
            if mode != "valid":
                assert result.error_code == "creative_brief_unmet"
            retried = await client.post(path, json=body)
            assert retried.status_code == 202
            assert retried.json()["id"] == submitted.json()["id"]
        assert len(provider.requests) == 2
        context = json.loads(
            provider.requests[-1].user_prompt.split("创作资料：\n")[1].split("\nJSON Schema：")[0]
        )
        assert context["selected_idea"]["id"] == str(batch.ideas[0].id)
        assert context["effective_creative_brief"]["text"] == current_brief
        assert result.input_snapshot["creative_brief"]["text"] == current_brief
        assert result.phase == "expanded" and result.operation == "expand"
        assert (await repo.get_viral_concept_set(batch.id)).model_dump(mode="json") == before

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["conflict", "count", "uncertain"])
def test_real_blockers_are_rejected_before_any_model_call_with_actionable_error(case):
    async def scenario():
        repo, report, categories, provider, service = await setup()
        batch = await historical_batch(repo, report, categories, service)
        data = response()
        if case == "conflict":
            data.ideas[0].requirement_checks[0].conflicting_scenes = [3]
            data.ideas[0].requirement_checks[0].explanation = "场景 3 的人物偏离中心"
        elif case == "count":
            data.ideas[0].scene_plan.pop()
        else:
            data.ideas[0].requirement_checks[0].uncertain = True
        batch.ideas[0] = review_idea(data.ideas[0], freeze_brief(BRIEF), data.requirement_rules)
        await repo.save_viral_concept_set(batch)
        api = FastAPI()
        api.include_router(create_viral_insight_router(service.insights, service))
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            result = await client.post(
                f"/viral-concept-sets/{batch.id}/ideas/{batch.ideas[0].id}/expand",
                json=CreativeActionRequest(request_id=uuid4()).model_dump(mode="json"),
            )
            assert result.status_code == 409
            assert result.json()["detail"]["code"] == "idea_review_required"
            message = result.json()["detail"]["message"]
            assert "AI 修订本条" in message
            assert (
                "偏离中心"
                if case == "conflict"
                else "应为 5 个"
                if case == "count"
                else "需要人工核对"
            ) in message
        assert len(provider.requests) == 1

    asyncio.run(scenario())
