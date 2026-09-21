"""Explicit, idempotent, unbilled idea revisions; source batches remain immutable."""

from uuid import uuid4

from ..access_context import account_access
from .contracts import CreativeIdea, utc_now
from .creative_brief import freeze_brief, resolve_brief
from .creative_review import fingerprint, present_reviews, review_idea
from .creative_review_models import CreativeHumanReview
from .service import ViralInsightServiceError


def editable_content(idea):
    return {
        name: getattr(idea, name)
        for name in (
            "name",
            "summary",
            "visual_memory",
            "scene_plan",
            "common_rules",
            "rhythm",
            "category_fit",
            "borrowed",
            "changed",
            "creative_intent",
            "visual_organization",
            "product_role",
            "assumptions",
        )
    }


def unresolved_conflicts(source, proposed, feedback):
    if source.review_brief != feedback:
        return []
    before = {scene.index: scene.description for scene in source.scene_plan}
    after = {scene.index: scene.description for scene in proposed.scene_plan}
    old_common = {
        item.requirement_index: (item.image_rule, item.video_rule) for item in source.common_rules
    }
    new_common = {
        item.requirement_index: (item.image_rule, item.video_rule) for item in proposed.common_rules
    }
    checks = {item.requirement_index: item for item in source.requirement_checks}
    pending = []
    for issue in source.review_details:
        if issue.severity != "revision":
            continue
        index = issue.requirement_index
        affected = checks[index].conflicting_scenes if index in checks else []
        common_changed = old_common.get(index) != new_common.get(index)
        changed = (
            all(before.get(i) != after.get(i) for i in affected) if affected else before != after
        )
        if not (common_changed or changed):
            pending.append(issue)
    return pending


async def edit_idea(service, set_id, idea_id, payload):
    parent = await service.get(set_id)
    async with service.lock(parent.analysis_id):
        signature = {"operation": "edit", "parent": str(set_id), "idea": str(idea_id)}
        previous = await service._deduplicate(parent.analysis_id, payload, **signature)
        if previous:
            return present_reviews(previous)
        parent = await service.get(set_id)
        if (
            parent.phase != "ideas"
            or parent.status not in {"completed", "failed"}
            or not parent.ideas
        ):
            raise ViralInsightServiceError(409, "ideas_not_ready", "当前批次没有可修订的创意")
        if (
            parent.revision != payload.expected_revision
            or parent.review_source_fingerprint != payload.source_fingerprint
        ):
            raise ViralInsightServiceError(
                409, "idea_changed", "创意或核对依据已变化，请保留草稿并重新读取"
            )
        source = next((item for item in parent.ideas if item.id == idea_id), None)
        if source is None:
            raise ViralInsightServiceError(404, "idea_not_found", "该创意不属于所选批次")
        feedback = resolve_brief(payload.feedback, parent)
        if not payload.idea.scene_plan:
            raise ViralInsightServiceError(
                422, "scene_plan_required", "修订前请填写至少一个完整场景"
            )
        brief = freeze_brief(feedback)
        expected = {item["index"] for item in brief["requirements"]}
        confirmed = set(payload.confirmed_requirements)
        if len(confirmed) != len(payload.confirmed_requirements) or confirmed - expected:
            raise ViralInsightServiceError(
                422, "review_requirement_invalid", "人工核对项目不属于当前补充想法"
            )
        unresolved = unresolved_conflicts(source, payload.idea, feedback)
        if any(item.requirement_index in confirmed for item in unresolved):
            raise ViralInsightServiceError(
                422,
                "content_revision_required",
                "内容存在明确冲突，请先修改对应场景，不能只勾选确认",
            )
        # Never accept client-supplied model claims or computed review status as authority.
        draft = CreativeIdea(
            **payload.idea.model_dump(exclude={"requirement_checks"}), requirement_checks=[]
        )
        revised = review_idea(draft, brief, payload.requirement_rules, manual_confirmed=confirmed)
        if unresolved:
            revised.review_details.extend(unresolved)
            revised.review_issues = list(
                dict.fromkeys([*revised.review_issues, *(item.message for item in unresolved)])
            )[:24]
            revised.review_state = "needs_revision"
            # Keep conflict locations across unconfirmed drafts; claims are not re-used for approval.
            revised.requirement_checks = [
                item
                for item in source.requirement_checks
                if item.conflicting_scenes or not item.satisfied
            ]
        if confirmed:
            access = account_access.get()
            revised.human_review = CreativeHumanReview(
                user_id=str(access.user_id) if access and access.user_id else None,
                reviewed_at=utc_now().isoformat(),
                content_fingerprint=fingerprint(
                    {
                        "content": editable_content(revised),
                        "rules": payload.requirement_rules,
                        "brief": brief,
                    }
                ),
                brief_text=feedback,
                confirmed_requirements=sorted(confirmed),
            )
        job = parent.model_copy(
            deep=True,
            update={
                "id": uuid4(),
                "parent_set_id": parent.id,
                "source_idea_id": idea_id,
                "request_id": payload.request_id,
                "request_signature": fingerprint({**signature, **payload.model_dump(mode="json")}),
                "operation": "edit",
                "status": "completed",
                "feedback": feedback,
                "ideas": [revised if item.id == idea_id else item for item in parent.ideas],
                "requirement_rules": payload.requirement_rules,
                "review_source_fingerprint": None,
                "created_at": utc_now(),
                "started_at": None,
                "completed_at": utc_now(),
                "model_runs": [],
                "model_cost_micros": 0,
                "estimated_cost_micros": 0,
                "model_elapsed_ms": 0,
                "cost_status": "not_started",
                "requested_model": None,
                "resolved_model": None,
                "error_code": None,
                "error_message": None,
                "revision": 1,
                "recovery": None,
                "published_result": None,
            },
        )
        job.input_snapshot["creative_brief"] = brief
        job.input_fingerprint = fingerprint(
            {
                "brief": brief,
                "content": editable_content(revised),
                "rules": payload.requirement_rules,
            }
        )
        # No source revision/status/cost mutation. Competing edits create separate descendants.
        await service.repository.save_viral_concept_set(job)
        return await service.get(job.id)
