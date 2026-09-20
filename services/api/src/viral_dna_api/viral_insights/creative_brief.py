"""Explicit, immutable user brief and grounded, per-result fulfillment checks.

Meaning is interpreted by the creative model, not a category/landmark keyword table.
Local checks enforce coverage and real scene quotations; they are not a semantic oracle.
"""

import re
from math import ceil

from .contracts import CreativeBriefFulfillment


class CreativeBriefError(ValueError):
    code = "creative_brief_unmet"


class CreativeBriefEvidenceError(CreativeBriefError):
    code = "creative_brief_evidence_invalid"


def quote_is_grounded(quote, scene):
    """Accept exact quotations or ordered literal excerpts from this scene only.

    An ellipsis may omit words, but cannot substitute invented words, reorder
    fragments, reuse an occurrence, or borrow text from another scene. Never
    modify the actual scene or treat matching as semantic requirement approval.
    """
    quote = quote.strip()
    if len(quote) < 2:
        return False
    if quote in scene:
        return True
    fragments = [part.strip() for part in re.split(r"\.{3,}|…+", quote) if part.strip()]
    if not fragments or any(len(part) < 2 for part in fragments):
        return False
    cursor = 0
    for fragment in fragments:
        position = scene.find(fragment, cursor)
        if position < 0:
            return False
        cursor = position + len(fragment)
    return True


def inherited_brief(batch):
    if batch is None or batch.phase == "legacy":
        return ""
    frozen = batch.input_snapshot.get("creative_brief")
    if isinstance(frozen, dict) and isinstance(frozen.get("text"), str):
        return frozen["text"]
    return (batch.feedback or batch.input_snapshot.get("original_creative_brief") or "").strip()


def resolve_brief(feedback, parent=None):
    # Omitted/null means inherit; an explicitly edited empty string means clear.
    return inherited_brief(parent) if feedback is None else feedback.strip()


def freeze_brief(text):
    # Split for traceability only, not semantic rewriting; never silently drop a clause.
    clauses = [item.strip() for item in re.split(r"[，,；;。\n]+", text) if item.strip()]
    if not clauses and text.strip():
        clauses = [text.strip()]
    group_size = max(1, ceil(len(clauses) / 24))
    groups = ["；".join(clauses[i : i + group_size]) for i in range(0, len(clauses), group_size)]
    return {
        "version": "creative-brief-v1",
        "text": text,
        "requirements": [{"index": i + 1, "text": value} for i, value in enumerate(groups)],
    }


def validate_brief_checks(draft, brief, *, label, expanded=False):
    requirements = brief["requirements"]
    if not requirements:
        # No request, no fabricated claim that a user's requirement was checked.
        return []
    checks = draft.brief_checks
    expected = {item["index"] for item in requirements}
    if len(checks) != len(expected) or {item.requirement_index for item in checks} != expected:
        raise CreativeBriefError(
            f"{label}没有逐项落实全部补充想法，已停止；请调整想法或手动重新生成"
        )
    scenes = (
        [
            "\n".join((shot.description, shot.image_prompt, shot.video_prompt))
            for shot in draft.shots
        ]
        if expanded
        else draft.key_scenes
    )
    mapped = {item.requirement_index: item for item in checks}
    result = []
    for requirement in requirements:
        check = mapped[requirement["index"]]
        message = f"{label}的第 {requirement['index']} 项补充要求缺少可核对的画面依据"
        if not check.satisfied or not check.evidence:
            raise CreativeBriefError(message + "；本次结果未采用，不会自动重试")
        covered = set()
        for evidence in check.evidence:
            if evidence.scene_index > len(scenes) or not quote_is_grounded(
                evidence.quote, scenes[evidence.scene_index - 1]
            ):
                raise CreativeBriefEvidenceError(
                    f"{label}的第 {requirement['index']} 项落实说明引用校验失败；"
                    "引用片段须按顺序来自同一指定画面，本批次未采用"
                )
            covered.add(evidence.scene_index)
        if check.scene_scope == "all" and covered != set(range(1, len(scenes) + 1)):
            raise CreativeBriefError(message + "；全场景要求不能只在部分画面实现")
        result.append(
            CreativeBriefFulfillment(**check.model_dump(), requirement=requirement["text"])
        )
    return result
