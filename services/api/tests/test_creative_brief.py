import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_creative_concepts import finish, setup
from test_creative_responses import idea_payload, install_real_adapter, mock_model_http

from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import CreativeActionRequest, CreativeGenerateRequest
from viral_dna_api.viral_insights.creative_brief import (
    CreativeBriefEvidenceError,
    freeze_brief,
    inherited_brief,
    quote_is_grounded,
    resolve_brief,
    validate_brief_checks,
)
from viral_dna_api.viral_insights.creative_prompts import SYSTEM_PROMPT, IdeaResponse, build_prompt
from viral_dna_api.viral_insights.creative_service import CreativeConceptService

BRIEF = "多场景切换，并且都是全世界标志性的场景"


def landmark_response():
    payload = idea_payload()
    for item in payload["ideas"]:
        item["summary"] += "在巴黎埃菲尔铁塔和埃及吉萨金字塔之间以硬切切换。"
        item["key_scenes"] = [
            "巴黎埃菲尔铁塔下，以服装线条接到塔身线条，画面以硬切转往下一地点。",
            "埃及吉萨金字塔前，服装褶线与三角形轮廓呼应，人物保持画面中轴。",
        ]
        item["brief_checks"] = [
            {
                "requirement_index": requirement["index"],
                "satisfied": True,
                "explanation": "在两个不同国家的具名地标中，通过服装线条保持切换的视觉连续。",
                "scene_scope": "all",
                "evidence": [
                    {"scene_index": 1, "quote": "巴黎埃菲尔铁塔"},
                    {"scene_index": 2, "quote": "埃及吉萨金字塔"},
                ],
            }
            for requirement in freeze_brief(BRIEF)["requirements"]
        ]
    return payload


@pytest.mark.parametrize(
    "mode", ["valid", "ellipsis", "omitted", "one_direction", "fake_quote", "partial", "unmet"]
)
def test_every_generated_direction_needs_grounded_fulfillment(monkeypatch, tmp_path, mode):
    payload = landmark_response()
    if mode == "ellipsis":
        for item in payload["ideas"]:
            item["brief_checks"][0]["evidence"][0]["quote"] = (
                "巴黎埃菲尔铁塔下...画面以硬切转往下一地点。"
            )
            item["brief_checks"][0]["evidence"][1]["quote"] = "埃及吉萨金字塔前……人物保持画面中轴。"
    elif mode == "omitted":
        for item in payload["ideas"]:
            item.pop("brief_checks")
    elif mode == "one_direction":
        payload["ideas"][2]["brief_checks"] = []
    elif mode == "fake_quote":
        # The reported bug: general urban settings cannot be rescued by claiming landmarks.
        payload["ideas"][0]["key_scenes"] = [
            "普通地铁通道，人物向镜头走来。",
            "居民楼灰色水泥墙，人物倚墙。",
        ]
    elif mode == "partial":
        payload["ideas"][1]["brief_checks"][1]["evidence"].pop()
    elif mode == "unmet":
        payload["ideas"][2]["brief_checks"][1]["satisfied"] = False
    calls = mock_model_http(monkeypatch, [(json.dumps(payload, ensure_ascii=False), "stop")])

    async def scenario():
        repo, report, categories, _, service = await setup(SQLiteStore(tmp_path / "brief.db"))
        install_real_adapter(service)
        result = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id, feedback=BRIEF
                ),
            ),
        )
        if mode in {"valid", "ellipsis"}:
            assert result.status == "completed", result.error_message
            assert all(len(idea.brief_checks) == 2 for idea in result.ideas)
            assert result.ideas[0].brief_checks[1].requirement == "并且都是全世界标志性的场景"
            reopened = CreativeConceptService(SQLiteStore(tmp_path / "brief.db"), service.insights)
            assert (await reopened.get(result.id)).ideas == result.ideas
        elif mode == "omitted":
            assert result.status == "completed" and result.error_code is None
            assert all(idea.review_issues for idea in result.ideas)
            assert all(idea.review_state == "needs_review" for idea in result.ideas)
        else:
            assert result.status == "completed"
            rejected = [idea for idea in result.ideas if idea.review_issues]
            assert len(rejected) == 1
            assert len(rejected[0].brief_checks) < 2
            assert len([idea for idea in result.ideas if not idea.review_issues]) == 2
            with pytest.raises(Exception, match="需要修订"):
                await service.act(result.id, rejected[0].id, CreativeActionRequest(request_id=uuid4()), expand=True)
        assert result.model_cost_micros > 0 and result.cost_status == "measured"
        assert len(result.model_runs) == 1
        # The valid JSON response remains available for diagnosis, even if its meaning failed.
        (run,) = await repo.list_model_runs(report.analysis_id)
        assert run.result_payload["ideas"] and run.measured_cost_micros > 0
        assert len(calls) == 1
        context = json.loads(
            calls[0]["messages"][1]["content"][0]["text"]
            .split("创作资料：\n")[1]
            .split("\nJSON Schema：")[0]
        )
        assert context["effective_creative_brief"]["text"] == BRIEF
        assert len(context["effective_creative_brief"]["requirements"]) == 2

    asyncio.run(scenario())


def test_brief_inherits_across_rewrite_expansion_refresh_and_new_batch(tmp_path):
    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "inherit.db")
        )

        async def generate(feedback=None):
            return await finish(
                service,
                await service.generate(
                    report.analysis_id,
                    CreativeGenerateRequest(
                        request_id=uuid4(),
                        category_profile_id=categories.profile.id,
                        feedback=feedback,
                    ),
                ),
            )

        first = await generate(BRIEF)
        original = first.model_dump(mode="json")
        rewritten = await finish(
            service,
            await service.act(
                first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=False
            ),
        )
        assert rewritten.status == "completed" and rewritten.feedback == BRIEF
        assert rewritten.ideas[1:] == first.ideas[1:]
        new_brief = BRIEF + "；不出现校服群像"
        revised = await finish(
            service,
            await service.act(
                rewritten.id,
                rewritten.ideas[0].id,
                CreativeActionRequest(request_id=uuid4(), feedback=new_brief),
                expand=False,
            ),
        )
        assert revised.status == "completed" and len(revised.ideas[0].brief_checks) == 3
        assert revised.ideas[1:] == first.ideas[1:]
        assert revised.input_snapshot["original_creative_brief"] == BRIEF
        expanded = await finish(
            service,
            await service.act(
                revised.id,
                revised.ideas[0].id,
                CreativeActionRequest(request_id=uuid4()),
                expand=True,
            ),
        )
        assert expanded.status == "completed" and expanded.feedback == new_brief
        assert len(expanded.concepts[0].brief_checks) == 3
        assert len(expanded.concepts[0].brief_checks[0].evidence) == len(expanded.concepts[0].shots)
        refreshed = CreativeConceptService(SQLiteStore(tmp_path / "inherit.db"), service.insights)
        assert inherited_brief(await refreshed.get(expanded.id)) == new_brief
        next_batch = await generate()
        assert next_batch.feedback == new_brief and next_batch.status == "completed"
        cleared = await generate("")
        assert cleared.status == "completed" and cleared.feedback == ""
        assert all(idea.brief_checks == [] for idea in cleared.ideas)
        assert (await service.get(first.id)).model_dump(mode="json") == original
        assert len(provider.requests) == 6  # No hidden extractor, reviewer or retry model calls.

    asyncio.run(scenario())


def test_prompt_gives_current_brief_priority_and_does_not_restore_removed_requirements():
    prompt = build_prompt(
        {
            "category": {"display_name": "JK", "scenes": ["校园"]},
            "source_grammar": {"narrative_structure": "单场景"},
            "original_creative_brief": "旧要求不得重新注入",
            "creative_brief": freeze_brief(BRIEF),
        },
        phase="ideas",
        feedback=BRIEF,
    )
    data = json.loads(prompt.split("创作资料：\n")[1].split("\nJSON Schema：")[0])
    assert list(data)[0] == "effective_creative_brief"
    assert "旧要求不得重新注入" not in prompt
    assert "原片和品类常用场景不能覆盖" in SYSTEM_PROMPT
    assert "三条方向都必须满足共同要求" in SYSTEM_PROMPT
    assert "逐项落实" in prompt and "不得编造不存在的引文" in prompt
    # This is a general mechanism, not a built-in JK / Eiffel Tower template.
    assert "埃菲尔铁塔" not in SYSTEM_PROMPT and "金字塔" not in SYSTEM_PROMPT


def test_omitted_and_explicitly_cleared_briefs_are_distinct_and_legacy_is_readable():
    old = SimpleNamespace(
        phase="ideas", feedback="", input_snapshot={"original_creative_brief": BRIEF}
    )
    assert resolve_brief(None, old) == BRIEF
    assert resolve_brief("", old) == ""
    assert resolve_brief("  只在一个室内场景  ", old) == "只在一个室内场景"
    old.input_snapshot["creative_brief"] = freeze_brief("")
    assert inherited_brief(old) == ""
    assert CreativeActionRequest(request_id=uuid4()).feedback is None
    assert CreativeActionRequest(request_id=uuid4(), feedback="").feedback == ""


def test_long_brief_does_not_silently_drop_requirements():
    text = "；".join(f"要求{i:02d}" for i in range(60))
    snapshot = freeze_brief(text)
    assert snapshot["text"] == text and len(snapshot["requirements"]) <= 24
    combined = "；".join(item["text"] for item in snapshot["requirements"])
    assert combined == text


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("巴黎埃菲尔铁塔下", True),
        ("巴黎埃菲尔铁塔下...画面以硬切转往下一地点。", True),
        ("巴黎埃菲尔铁塔下……画面以硬切转往下一地点。", True),
        ("巴黎埃菲尔铁塔下...服装线条…下一地点。", True),
        ("  ...巴黎埃菲尔铁塔下……  ", True),
        ("画面以硬切转往下一地点。...巴黎埃菲尔铁塔下", False),
        ("巴黎埃菲尔铁塔下...埃及吉萨金字塔前", False),
        ("巴黎埃菲尔铁塔下...穿红色服装", False),
        ("巴黎埃菲尔铁塔下...巴黎埃菲尔铁塔下", False),
        ("巴黎埃菲尔铁塔下.*画面以硬切转往下一地点。", False),
        ("...……", False),
        ("巴...下", False),
        ("", False),
    ],
)
def test_ellipsis_keeps_fragments_literal_ordered_and_grounded(quote, expected):
    scene = landmark_response()["ideas"][0]["key_scenes"][0]
    assert quote_is_grounded(quote, scene) is expected


def test_ellipsis_cannot_borrow_evidence_from_another_scene():
    response = IdeaResponse.model_validate(landmark_response())
    idea = response.ideas[0]
    idea.brief_checks[0].evidence[0].quote = "巴黎埃菲尔铁塔下...埃及吉萨金字塔前"
    with pytest.raises(CreativeBriefEvidenceError, match="引用校验失败"):
        validate_brief_checks(idea, freeze_brief(BRIEF), label="第一条")
