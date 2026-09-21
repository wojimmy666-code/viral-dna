import asyncio
from uuid import uuid4

import pytest
from test_creative_concepts import finish, ideas, plan, setup

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import (
    CreativeActionRequest,
    CreativeGenerateRequest,
    CreativeIdea,
    CreativeIdeaEdit,
)
from viral_dna_api.viral_insights.creative_brief import freeze_brief
from viral_dna_api.viral_insights.creative_idea_edit import edit_idea, unresolved_conflicts
from viral_dna_api.viral_insights.creative_prompts import IdeaResponse
from viral_dna_api.viral_insights.creative_review import (
    compile_common_rules,
    explicit_scene_count,
    review_idea,
)
from viral_dna_api.viral_insights.creative_review_models import CreativeRequirementRule
from viral_dna_api.viral_insights.service import ViralInsightServiceError

BRIEF = "女孩在画面中间位置，向左走，女孩相对于镜头位置不变，背景移动，5个场景切换，并且都是全世界标志性的场景"


def response():
    rules = [
        {
            "requirement_index": i,
            "kind": "shared" if i < 5 else "structure" if i == 5 else "per_scene",
            "expected_scene_count": 5 if i == 5 else None,
        }
        for i in range(1, 7)
    ]
    directions = []
    for original in ideas():
        draft = original.model_dump()
        draft["scene_plan"] = [
            {
                "index": i,
                "description": f"{name}的可辨认建筑轮廓与服装线条呼应。",
                "duration_seconds": 1.2,
                "transition": "cut",
            }
            for i, name in enumerate(
                ["巴黎埃菲尔铁塔", "纽约自由女神像", "伦敦大本钟", "悉尼歌剧院", "吉萨金字塔"], 1
            )
        ]
        draft["common_rules"] = [
            {"requirement_index": 1, "image_rule": "女孩位于画面正中心"},
            {"requirement_index": 2, "video_rule": "女孩向左匀速行走"},
            {"requirement_index": 3, "video_rule": "摄影机跟随，人物相对镜头位置保持不变"},
            {"requirement_index": 4, "video_rule": "背景随步伐向右移动"},
        ]
        draft["requirement_checks"] = [
            {
                "requirement_index": i,
                "satisfied": True,
                "explanation": "公共调度覆盖全片，具体场景保持一致。",
                "references": [{"field": "common_image" if i == 1 else "common_video"}]
                if i < 5
                else []
                if i == 5
                else [{"field": "description", "scene_index": j} for j in range(1, 6)],
            }
            for i in range(1, 7)
        ]
        directions.append(draft)
    return IdeaResponse.model_validate(
        {"ideas": directions, "requirement_rules": rules, "diversity_rationale": "三种不同组织方式"}
    )


def test_shared_direction_and_structure_do_not_require_repeated_quotes():
    result = response()
    for idea in result.ideas:
        reviewed = review_idea(idea, freeze_brief(BRIEF), result.requirement_rules)
        assert reviewed.review_state == "ready"
        assert len(reviewed.brief_checks) == 6
        assert reviewed.key_scenes[0] == idea.scene_plan[0].description
        assert not reviewed.review_issues


@pytest.mark.parametrize(
    "case,code,state",
    [
        ("missing_scene", "scene_coverage", "needs_review"),
        ("bad_ref", "reference_invalid", "needs_review"),
        ("conflict", "content_conflict", "needs_revision"),
        ("uncertain", "semantic_uncertain", "needs_review"),
        ("no_common", "reference_invalid", "needs_review"),
        ("wrong_count", "scene_count", "needs_revision"),
    ],
)
def test_real_problems_remain_visible_and_blocked(case, code, state):
    result = response()
    idea = result.ideas[0]
    if case == "missing_scene":
        idea.requirement_checks[5].references.pop()
    elif case == "bad_ref":
        idea.requirement_checks[5].references[0].scene_index = 99
    elif case == "conflict":
        idea.requirement_checks[0].conflicting_scenes = [3]
    elif case == "uncertain":
        idea.requirement_checks[5].uncertain = True
    elif case == "no_common":
        idea.common_rules.pop(0)
    else:
        idea.scene_plan.pop()
    reviewed = review_idea(idea, freeze_brief(BRIEF), result.requirement_rules)
    assert reviewed.review_state == state
    assert code in {issue.code for issue in reviewed.review_details}


def test_explicit_count_cannot_be_overridden_or_confirmed_away():
    result = response()
    result.requirement_rules[4].expected_scene_count = 4
    assert (
        review_idea(result.ideas[0], freeze_brief(BRIEF), result.requirement_rules).review_state
        == "ready"
    )
    result.ideas[0].scene_plan.pop()
    reviewed = review_idea(
        result.ideas[0], freeze_brief(BRIEF), result.requirement_rules, manual_confirmed=range(1, 7)
    )
    assert reviewed.review_state == "needs_revision"
    assert explicit_scene_count("至少5个场景") is None
    assert explicit_scene_count("原片9个镜头，新片自由设计") is None
    assert explicit_scene_count("五个场景切换") == 5


def test_common_rules_are_materialized_into_the_correct_prompt_only():
    concept = plan()
    concept.common_rules = response().ideas[0].common_rules
    compiled = compile_common_rules(concept)
    for shot in compiled.shots:
        assert "女孩位于画面正中心" in shot.image_prompt
        assert "向左匀速行走" not in shot.image_prompt
        assert "向左匀速行走" in shot.video_prompt
    assert "女孩位于画面正中心" not in concept.shots[0].image_prompt
    assert compile_common_rules(compiled) == compiled


def test_model_cannot_satisfy_semantics_by_inventing_a_count():
    result = response()
    result.requirement_rules[5] = CreativeRequirementRule(
        requirement_index=6, kind="structure", expected_scene_count=5
    )
    reviewed = review_idea(result.ideas[0], freeze_brief(BRIEF), result.requirement_rules)
    assert reviewed.review_state == "needs_review"
    assert "count_interpretation" in {item.code for item in reviewed.review_details}


def test_renaming_or_unrelated_scene_edits_do_not_clear_known_conflict():
    result = response()
    result.ideas[0].requirement_checks[0].conflicting_scenes = [3]
    source = review_idea(result.ideas[0], freeze_brief(BRIEF), result.requirement_rules)
    edited = source.model_copy(deep=True)
    edited.name = "只修改片名"
    assert unresolved_conflicts(source, edited, BRIEF)
    edited.scene_plan[0].description += "新的无关细节"
    assert unresolved_conflicts(source, edited, BRIEF)
    edited.scene_plan[2].description += "女孩位于画面正中心，修正偏离位置。"
    assert not unresolved_conflicts(source, edited, BRIEF)


def test_failed_history_projection_and_explicit_manual_revision_are_unbilled(tmp_path):
    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "review.db")
        )
        batch = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        original_response = response()
        batch.ideas = [
            CreativeIdea(
                **item.model_dump(exclude={"brief_checks"}), review_issues=["旧版全场景引用不足"]
            )
            for item in original_response.ideas
        ]
        batch.feedback = BRIEF
        batch.input_snapshot["creative_brief"] = freeze_brief(BRIEF)
        batch.status, batch.error_code = "failed", "creative_brief_unmet"
        # Historical v5 had no common direction or field-based assessments.
        for idea in batch.ideas:
            idea.common_rules, idea.requirement_checks = [], []
        await repo.save_viral_concept_set(batch)
        saved = (await repo.get_viral_concept_set(batch.id)).model_dump(mode="json")
        call_count = len(provider.requests)
        view = await service.get(batch.id)
        assert view.status == "failed"
        assert all(idea.review_state == "needs_review" for idea in view.ideas)
        assert view.requirement_rules[4].kind == "structure"
        assert view.requirement_rules[4].expected_scene_count == 5
        assert all(
            any(check.requirement_index == 5 for check in idea.brief_checks) for idea in view.ideas
        )
        assert (await repo.get_viral_concept_set(batch.id)).model_dump(mode="json") == saved
        payload = CreativeIdeaEdit(
            request_id=uuid4(),
            expected_revision=view.revision,
            source_fingerprint=view.review_source_fingerprint,
            feedback=BRIEF,
            idea=original_response.ideas[0],
            requirement_rules=original_response.requirement_rules,
            confirmed_requirements=list(range(1, 7)),
        )
        revised = await edit_idea(service, batch.id, view.ideas[0].id, payload)
        assert revised.id != batch.id and revised.parent_set_id == batch.id
        assert revised.ideas[0].review_state == "ready" and revised.ideas[0].human_review
        assert revised.ideas[1:] == view.ideas[1:]
        assert revised.model_runs == [] and revised.model_cost_micros == 0
        assert len(provider.requests) == call_count
        assert (await edit_idea(service, batch.id, view.ideas[0].id, payload)).id == revised.id
        assert (await repo.get_viral_concept_set(batch.id)).model_dump(mode="json") == saved
        payload.request_id, payload.source_fingerprint = uuid4(), "0" * 64
        with pytest.raises(ViralInsightServiceError, match="已变化"):
            await edit_idea(service, batch.id, view.ideas[0].id, payload)
        with pytest.raises(ViralInsightServiceError, match="需要修订"):
            await service.act(
                batch.id, view.ideas[1].id, CreativeActionRequest(request_id=uuid4()), expand=True
            )
        assert len(provider.requests) == call_count

    asyncio.run(scenario())


def test_known_conflict_survives_unconfirmed_draft_and_requires_relevant_change(tmp_path):
    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "conflicts.sqlite3")
        )
        batch = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    category_profile_id=categories.profile.id, request_id=uuid4()
                ),
            ),
        )
        result = response()
        result.ideas[0].requirement_checks[0].conflicting_scenes = [3]
        batch.feedback = BRIEF
        batch.input_snapshot["creative_brief"] = freeze_brief(BRIEF)
        batch.requirement_rules = result.requirement_rules
        batch.ideas = [
            review_idea(item, freeze_brief(BRIEF), result.requirement_rules)
            for item in result.ideas
        ]
        await repo.save_viral_concept_set(batch)
        view = await service.get(batch.id)
        original_calls = len(provider.requests)
        draft = CreativeIdeaEdit(
            request_id=uuid4(),
            expected_revision=view.revision,
            source_fingerprint=view.review_source_fingerprint,
            feedback=BRIEF,
            idea=view.ideas[0],
            requirement_rules=view.requirement_rules,
            confirmed_requirements=[],
        )
        saved = await edit_idea(service, view.id, view.ideas[0].id, draft)
        assert saved.ideas[0].review_state == "needs_revision"
        assert saved.ideas[0].requirement_checks[0].conflicting_scenes == [3]
        confirm = draft.model_copy(
            deep=True,
            update={
                "request_id": uuid4(),
                "source_fingerprint": saved.review_source_fingerprint,
                "expected_revision": saved.revision,
                "idea": saved.ideas[0],
                "confirmed_requirements": list(range(1, 7)),
            },
        )
        with pytest.raises(ViralInsightServiceError, match="不能只勾选"):
            await edit_idea(service, saved.id, saved.ideas[0].id, confirm)
        confirm.idea.scene_plan[2].description += "女孩始终位于画面正中心。"
        revised = await edit_idea(service, saved.id, saved.ideas[0].id, confirm)
        assert revised.ideas[0].review_state == "ready"
        assert revised.ideas[0].human_review
        assert len(provider.requests) == original_calls

    asyncio.run(scenario())
