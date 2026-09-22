"""Deterministic structure checks, scoped evidence and explicit human review.

This is not a semantic oracle. Model attestations, missing evidence and human
confirmation stay distinct. Reading a historical batch never writes or bills.
"""

import hashlib
import json
import re

from .contracts import CreativeBriefFulfillment, CreativeIdea
from .creative_brief import CreativeBriefError, freeze_brief, validate_brief_checks
from .creative_review_models import CreativeRequirementRule, CreativeReviewIssue


def fingerprint(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def explicit_scene_count(text):
    """Only an unambiguous standalone exact count, never scene/category semantics."""
    match = re.fullmatch(
        r"(?:共|总共|一共|需要|使用|采用)?\s*([0-9]+|[一二三四五六七八九十两]+)\s*个?\s*(?:场景|分镜|镜头)(?:切换|之间切换)?",
        text.strip(),
    )
    if not match:
        return None
    value = match[1]
    if value.isascii() and value.isdigit():
        return int(value)
    digits = {char: i for i, char in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in value:
        left, right = value.split("十", 1)
        if len(left) <= 1 and len(right) <= 1:
            return (digits.get(left, 1) * 10) + digits.get(right, 0)
    return digits.get(value)


def rules_for_brief(brief, proposed=()):
    """One shared interpretation, with explicit numeric requirements authoritative."""
    mapped = {rule.requirement_index: rule for rule in proposed}
    rules = []
    for requirement in brief["requirements"]:
        index = requirement["index"]
        count = explicit_scene_count(requirement["text"])
        rules.append(
            CreativeRequirementRule(
                requirement_index=index, kind="structure", expected_scene_count=count
            )
            if count is not None and 1 <= count <= 200
            else mapped.get(index)
            or CreativeRequirementRule(requirement_index=index, kind="per_scene")
        )
    return rules


def scene_texts(draft, expanded=False):
    if expanded:
        return [shot.description for shot in draft.shots]
    return (
        [scene.description for scene in draft.scene_plan] if draft.scene_plan else draft.key_scenes
    )


def assess(draft, brief, rules=(), *, expanded=False, manual_confirmed=()):
    issues, fulfilled = [], []
    requirements = brief["requirements"]
    expected = {item["index"] for item in requirements}
    scenes = draft.shots if expanded else draft.scene_plan
    text_scenes = scene_texts(draft, expanded)
    structured = bool(rules or draft.requirement_checks or draft.common_rules)

    def issue(index, code, message, severity="review"):
        issues.append(
            CreativeReviewIssue(
                requirement_index=index, code=code, severity=severity, message=message
            )
        )

    if scenes and [scene.index for scene in scenes] != list(range(1, len(scenes) + 1)):
        issue(None, "scene_order", "场景编号必须按播放顺序连续排列", "revision")
    if structured and not scenes:
        issue(None, "scene_plan_missing", "缺少完整场景规划，精选画面不能代替全片", "revision")
    for name, entries in (
        ("要求分类", rules),
        ("公共设定", draft.common_rules),
        ("核对结果", draft.requirement_checks),
    ):
        ids = [item.requirement_index for item in entries]
        if len(ids) != len(set(ids)) or set(ids) - expected:
            issue(
                None, "requirement_mapping", f"{name}存在重复或不属于当前补充想法的编号", "revision"
            )
    mapped_rules = {item.requirement_index: item for item in rules_for_brief(brief, rules)}
    common = {item.requirement_index: item for item in draft.common_rules}
    checks = {item.requirement_index: item for item in draft.requirement_checks}
    legacy_checks = {item.requirement_index: item for item in getattr(draft, "brief_checks", [])}
    all_scenes = set(range(1, len(text_scenes) + 1))
    for shared in draft.common_rules:
        rule = mapped_rules.get(shared.requirement_index)
        if rule and (
            rule.kind not in {"shared", "per_scene"}
            or not (shared.image_rule.strip() or shared.video_rule.strip())
        ):
            issue(
                shared.requirement_index,
                "common_rule_invalid",
                "公共设定须填写明确内容，只能补充共同调度或逐场景要求，不能代替全片结构",
                "revision",
            )
    for requirement in requirements:
        index, text = requirement["index"], requirement["text"]
        prefix = f"要求 {index}「{text}」"
        rule = mapped_rules[index]
        literal_count = explicit_scene_count(text)
        count = literal_count if literal_count is not None else rule.expected_scene_count
        if count is not None:
            if literal_count is None and index not in manual_confirmed:
                issue(
                    index,
                    "count_interpretation",
                    f"{prefix}：模型将本项解释为精确 {count} 个场景，请人工核对，不能仅凭数量判定语义",
                )
                continue
            if len(text_scenes) != count:
                issue(
                    index,
                    "scene_count",
                    f"{prefix}：应为 {count} 个，实际为 {len(text_scenes)} 个场景",
                    "revision",
                )
            elif not scenes:
                issue(
                    index,
                    "scene_plan_missing",
                    f"{prefix}：需填写完整场景规划，不能只凭精选画面确定数量",
                    "revision",
                )
            else:
                fulfilled.append(
                    CreativeBriefFulfillment(
                        requirement_index=index,
                        requirement=text,
                        satisfied=True,
                        explanation=f"程序核对完整规划：共 {count} 个场景。",
                        scene_scope="selected",
                    )
                )
            continue
        if index in manual_confirmed:
            # The caller validates exact content/brief fingerprints and records the actor.
            fulfilled.append(
                CreativeBriefFulfillment(
                    requirement_index=index,
                    requirement=text,
                    satisfied=True,
                    explanation="用户已核对当前公共设定及各场景，人工确认本项要求。",
                    scene_scope="selected",
                )
            )
            continue
        if not structured:
            check = legacy_checks.get(index)
            if check is None:
                issue(
                    index,
                    "legacy_evidence_missing",
                    f"{prefix}：旧结果未保留完整核对依据，请查看场景后修订或人工核对",
                )
                continue
            try:
                fulfilled.extend(
                    validate_brief_checks(
                        draft.model_copy(update={"brief_checks": [check]}),
                        {"requirements": [requirement]},
                        label="当前创意",
                        expanded=expanded,
                    )
                )
            except CreativeBriefError as exc:
                issue(
                    index,
                    "legacy_evidence",
                    f"{prefix}：{exc}",
                    "review" if check.satisfied else "revision",
                )
            continue
        check = checks.get(index)
        if check is None:
            issue(index, "check_missing", f"{prefix}：模型未提供本项内容核对")
            continue
        if not check.satisfied or check.conflicting_scenes:
            locations = "、".join(map(str, check.conflicting_scenes))
            issue(
                index,
                "content_conflict",
                f"{prefix}：{check.explanation}" + (f"（场景 {locations}）" if locations else ""),
                "revision",
            )
            continue
        if check.uncertain:
            issue(index, "semantic_uncertain", f"{prefix}：{check.explanation}，需要人工核对")
            continue
        covered, has_common, invalid = set(), False, False
        for ref in check.references:
            if ref.field.startswith("common_"):
                value = common.get(index)
                field = "image_rule" if ref.field == "common_image" else "video_rule"
                if (
                    ref.scene_index is not None
                    or value is None
                    or not getattr(value, field).strip()
                    or rule.kind not in {"shared", "per_scene"}
                ):
                    invalid = True
                else:
                    # Per-scene summaries are supplementary, never scene evidence.
                    has_common = rule.kind == "shared"
            elif ref.scene_index not in all_scenes or (not expanded and ref.field != "description"):
                invalid = True
            else:
                scene = scenes[ref.scene_index - 1] if scenes else None
                if scene is None or not getattr(scene, ref.field, "").strip():
                    invalid = True
                else:
                    covered.add(ref.scene_index)
        if invalid:
            issue(index, "reference_invalid", f"{prefix}：部分字段引用不存在或不适用于此要求")
        elif rule.kind == "shared" and not has_common and covered != all_scenes:
            issue(
                index,
                "shared_missing",
                f"{prefix}：缺少明确的公共设定或逐场景依据，不能自动推定全片已落实",
            )
        elif rule.kind in {"per_scene", "structure"} and covered != all_scenes:
            missing = "、".join(map(str, sorted(all_scenes - covered)))
            issue(index, "scene_coverage", f"{prefix}：场景 {missing} 缺少对应正文依据")
        elif not check.references:
            issue(index, "reference_missing", f"{prefix}：缺少对应正文或公共设定")
        else:
            fulfilled.append(
                CreativeBriefFulfillment(
                    requirement_index=index,
                    requirement=text,
                    satisfied=True,
                    explanation=check.explanation,
                    scene_scope="all" if rule.kind != "structure" else "selected",
                )
            )
    return issues, fulfilled


def review_idea(draft, brief, rules=(), *, manual_confirmed=()):
    issues, checks = assess(draft, brief, rules, manual_confirmed=manual_confirmed)
    values = draft.model_dump(exclude={"brief_checks"})
    if draft.scene_plan:
        indices = draft.highlight_scene_indices or list(range(1, min(3, len(draft.scene_plan)) + 1))
        # Display only scenes that actually exist. Never let highlight prose form a second plan.
        highlights = [
            draft.scene_plan[index - 1].description[:300]
            for index in indices
            if 1 <= index <= len(draft.scene_plan)
        ]
        if highlights:
            values["key_scenes"] = highlights
    return CreativeIdea(
        **{
            **values,
            "brief_checks": checks,
            "review_details": issues,
            "review_state": "needs_revision"
            if any(i.severity == "revision" for i in issues)
            else "needs_review"
            if issues
            else "ready",
            "review_issues": [i.message for i in issues][:24],
            "review_brief": brief["text"],
        }
    )


def present_reviews(batch):
    """Read-only projection; never change legacy status, costs or persisted results."""
    result = batch.model_copy(deep=True)
    if (
        result.phase == "ideas"
        and result.ideas
        and result.status not in {"queued", "running", "cancelled"}
    ):
        brief = result.input_snapshot.get("creative_brief") or freeze_brief(result.feedback)
        for index, idea in enumerate(result.ideas):
            if idea.review_state == "unreviewed":
                result.ideas[index] = review_idea(idea, brief, result.requirement_rules)
            elif (
                idea.review_state == "needs_revision"
                and idea.review_brief == brief["text"]
                and idea.human_review is None
                and idea.review_details
                and len(idea.review_details) == len(idea.review_issues)
                and all(
                    item.code == "common_rule_invalid" and item.severity == "revision"
                    for item in idea.review_details
                )
            ):
                # Recheck only the old classification-only rejection. Preserve all
                # authored content and human/other review decisions; never write or bill.
                reviewed = review_idea(idea, brief, result.requirement_rules)
                result.ideas[index] = idea.model_copy(update={
                    key: getattr(reviewed, key)
                    for key in (
                        "brief_checks", "review_details", "review_state",
                        "review_issues", "review_brief",
                    )
                })
        # Return the same exact-count interpretation to the editor, without persisting it.
        result.requirement_rules = rules_for_brief(brief, result.requirement_rules)
        result.review_source_fingerprint = fingerprint(
            {
                "id": result.id,
                "revision": result.revision,
                "brief": brief,
                "ideas": result.ideas,
                "rules": result.requirement_rules,
            }
        )
    return result


def idea_ready(idea, brief_text):
    return (
        idea.review_state == "ready" and not idea.review_issues and idea.review_brief == brief_text
    )


def idea_can_expand(idea, brief_text):
    """Missing legacy attestations may be checked in the requested expansion.

    This does not approve the old idea or relax validation of the resulting plan.
    Known conflicts, modern review failures and incomplete plans remain blocked.
    """
    if idea_ready(idea, brief_text):
        return True
    return bool(
        idea.review_state == "needs_review"
        and idea.review_brief == brief_text
        and idea.scene_plan
        and [scene.index for scene in idea.scene_plan] == list(range(1, len(idea.scene_plan) + 1))
        and all(scene.description.strip() for scene in idea.scene_plan)
        and idea.review_details
        and len(idea.review_details) == len(idea.review_issues)
        and all(
            issue.code == "legacy_evidence_missing" and issue.severity == "review"
            for issue in idea.review_details
        )
    )


def compile_common_rules(concept):
    """Materialize explicit shared static/motion direction into downstream prompts."""
    result = concept.model_copy(deep=True)
    for shot in result.shots:
        for rule in result.common_rules:
            for source, target in (("image_rule", "image_prompt"), ("video_rule", "video_prompt")):
                text = getattr(rule, source).strip()
                if text and text not in getattr(shot, target):
                    setattr(shot, target, text + "\n" + getattr(shot, target))
    return type(concept).model_validate(result.model_dump())
