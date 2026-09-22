"""Supplementary direction must not replace per-scene evidence or force paid repairs."""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_creative_concepts import finish, setup
from test_creative_expansion_gate import expanded_response, historical_batch
from test_creative_review import BRIEF, response

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeIdea
from viral_dna_api.viral_insights.creative_brief import freeze_brief
from viral_dna_api.viral_insights.creative_prompts import PlanResponse
from viral_dna_api.viral_insights.creative_review import (
    assess,
    compile_common_rules,
    idea_can_expand,
    present_reviews,
    review_idea,
)
from viral_dna_api.viral_insights.creative_review_models import (
    CreativeCommonRule,
    CreativeFieldReference,
    CreativeHumanReview,
    CreativeReviewIssue,
)
from viral_dna_api.viral_insights.routes import create_viral_insight_router


def supplementary_rule():
    return CreativeCommonRule(
        requirement_index=6,
        image_rule="背景为可辨认的世界标志性建筑或自然景观。",
    )


def supplementary_response():
    data = response()
    data.ideas[0].common_rules.append(supplementary_rule())
    return data


def old_rejection(draft):
    issue = CreativeReviewIssue(
        requirement_index=6,
        code="common_rule_invalid",
        severity="revision",
        message="公共设定必须属于贯穿全片的要求，并填写明确内容",
    )
    return CreativeIdea(
        **draft.model_dump(exclude={"brief_checks"}),
        review_state="needs_revision",
        review_brief=BRIEF,
        review_details=[issue],
        review_issues=[issue.message],
    )


@pytest.mark.parametrize(
    "case,code",
    [
        ("valid", None), ("extra_common_ref", None),
        ("common_only", "scene_coverage"), ("missing_scene", "scene_coverage"),
        ("bad_ref", "reference_invalid"), ("empty_ref", "reference_invalid"),
        ("conflict", "content_conflict"), ("uncertain", "semantic_uncertain"),
        ("missing_check", "check_missing"), ("wrong_count", "scene_count"),
        ("empty_common", "common_rule_invalid"), ("structure", "common_rule_invalid"),
        ("duplicate", "requirement_mapping"), ("unknown", "requirement_mapping"),
    ],
)
def test_supplementary_rules_require_complete_real_scene_checks(case, code):
    data = supplementary_response()
    draft = data.ideas[0]
    check = draft.requirement_checks[5]
    common_ref = CreativeFieldReference(field="common_image")
    if case == "extra_common_ref":
        check.references.append(common_ref)
    elif case == "common_only":
        check.references = [common_ref]
    elif case == "missing_scene":
        check.references.pop()
        check.references.append(common_ref)
    elif case == "bad_ref":
        check.references[0].scene_index = 99
    elif case == "empty_ref":
        check.references.append(CreativeFieldReference(field="common_video"))
    elif case == "conflict":
        check.conflicting_scenes = [3]
    elif case == "uncertain":
        check.uncertain = True
    elif case == "missing_check":
        draft.requirement_checks.pop()
    elif case == "wrong_count":
        draft.scene_plan.pop()
    elif case == "empty_common":
        draft.common_rules[-1].image_rule = " "
    elif case == "structure":
        draft.common_rules[-1].requirement_index = 5
    elif case == "duplicate":
        draft.common_rules.append(supplementary_rule())
    elif case == "unknown":
        draft.common_rules[-1].requirement_index = 7
    original = draft.model_dump_json()
    reviewed = review_idea(draft, freeze_brief(BRIEF), data.requirement_rules)
    assert draft.model_dump_json() == original
    assert reviewed.common_rules == draft.common_rules
    if code:
        assert code in {issue.code for issue in reviewed.review_details}
        assert not idea_can_expand(reviewed, BRIEF)
    else:
        assert reviewed.review_state == "ready"
        assert not reviewed.review_details
        assert len(reviewed.brief_checks) == 6
        assert idea_can_expand(reviewed, BRIEF)


@pytest.mark.parametrize("case", ["valid", "missing_scene", "conflict", "wrong_count"])
def test_expanded_plan_keeps_per_scene_validation_and_supplementary_prompts(case):
    data = expanded_response("valid")
    data.concept.common_rules.append(supplementary_rule())
    if case == "missing_scene":
        data.concept.requirement_checks[5].references.pop()
    elif case == "conflict":
        data.concept.requirement_checks[5].satisfied = False
    elif case == "wrong_count":
        data.concept.shots.pop()
    compiled = compile_common_rules(data.concept)
    issues, checks = assess(compiled, freeze_brief(BRIEF), data.requirement_rules, expanded=True)
    assert bool(issues) is (case != "valid")
    if case == "valid":
        assert len(checks) == 6
    for shot in compiled.shots:
        assert supplementary_rule().image_rule in shot.image_prompt
        assert supplementary_rule().image_rule not in shot.video_prompt
    assert compiled.common_rules == data.concept.common_rules


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_existing_classification_rejection_recovers_read_only_and_expands_once(tmp_path, status):
    async def scenario():
        repo, report, categories, provider, service = await setup(SQLiteStore(tmp_path / "case.db"))
        batch = await historical_batch(repo, report, categories, service)
        data = supplementary_response()
        batch.ideas[0] = old_rejection(data.ideas[0])
        batch.requirement_rules = data.requirement_rules
        batch.status = status
        await repo.save_viral_concept_set(batch)
        before = (await repo.get_viral_concept_set(batch.id)).model_dump_json()
        original_generate = provider.generate

        async def generate(request, schema):
            result = await original_generate(request, schema)
            if schema is PlanResponse:
                content = expanded_response("valid")
                content.concept.common_rules.append(supplementary_rule())
                result = replace(result, data=content)
            return result

        provider.generate = generate
        api = FastAPI()
        api.include_router(create_viral_insight_router(service.insights, service))
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            for path in (
                f"/analyses/{report.analysis_id}/viral-concepts/history",
                f"/viral-concept-sets/{batch.id}",
            ):
                result = await client.get(path)
                assert result.status_code == 200, result.text
                view = result.json()[0] if path.endswith("history") else result.json()
                assert view["ideas"][0]["review_state"] == "ready"
                assert view["ideas"][0]["scene_plan"] == batch.ideas[0].model_dump(mode="json")["scene_plan"]
                assert view["ideas"][0]["common_rules"] == batch.ideas[0].model_dump(mode="json")["common_rules"]
                assert view["status"] == status
                assert view["model_cost_micros"] == batch.model_cost_micros
            assert len(provider.requests) == 1
            body = {"request_id": str(uuid4()), "feedback": BRIEF}
            path = f"/viral-concept-sets/{batch.id}/ideas/{batch.ideas[0].id}/expand"
            submitted = await client.post(path, json=body)
            assert submitted.status_code == 202, submitted.text
            finished = await finish(service, await service.get(UUID(submitted.json()["id"])))
            assert finished.status == "completed"
            retried = await client.post(path, json=body)
            assert retried.json()["id"] == submitted.json()["id"]
        assert len(provider.requests) == 2
        context = json.loads(provider.requests[-1].user_prompt.split("创作资料：\n")[1].split("\nJSON Schema：")[0])
        assert context["selected_idea"]["scene_plan"] == batch.ideas[0].model_dump(mode="json")["scene_plan"]
        assert context["selected_idea"]["common_rules"] == batch.ideas[0].model_dump(mode="json")["common_rules"]
        assert (await repo.get_viral_concept_set(batch.id)).model_dump_json() == before

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["conflict", "missing_scene", "empty_common", "changed_brief", "other_issue", "human"])
def test_history_recheck_does_not_erase_real_or_human_decisions(case):
    async def scenario():
        repo, report, categories, _, service = await setup()
        batch = await historical_batch(repo, report, categories, service)
        data = supplementary_response()
        draft = data.ideas[0]
        if case == "conflict":
            draft.requirement_checks[5].conflicting_scenes = [3]
        elif case == "missing_scene":
            draft.requirement_checks[5].references.pop()
        elif case == "empty_common":
            draft.common_rules[-1].image_rule = ""
        idea = old_rejection(draft)
        if case == "changed_brief":
            idea.review_brief += "，不同要求"
        elif case == "other_issue":
            idea.review_details.append(CreativeReviewIssue(code="content_conflict", severity="revision", message="保留已有冲突"))
            idea.review_issues.append("保留已有冲突")
        elif case == "human":
            idea.human_review = CreativeHumanReview(user_id="reviewer", reviewed_at="2026-09-22T00:00:00Z", content_fingerprint="a" * 64, brief_text=BRIEF, confirmed_requirements=[1])
        batch.ideas[0] = idea
        batch.requirement_rules = data.requirement_rules
        before = batch.model_dump_json()
        view = present_reviews(batch)
        assert not idea_can_expand(view.ideas[0], BRIEF)
        assert batch.model_dump_json() == before
        if case in {"changed_brief", "other_issue", "human"}:
            assert view.ideas[0] == idea

    asyncio.run(scenario())
