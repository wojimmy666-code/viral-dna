"""Input freshness is advisory and never revokes a human adoption decision."""

from __future__ import annotations

from .models import ShotPlan, ShotVisualBeat, WorkflowItemStatus, utc_now


def result_status(status, candidate_id, prompt=""):
    """Keep adoption pointers; a legacy stale result without one is not approved."""
    if candidate_id is not None:
        return WorkflowItemStatus.APPROVED
    if status in {WorkflowItemStatus.STALE, WorkflowItemStatus.APPROVED}:
        return WorkflowItemStatus.REVIEW_REQUIRED
    if status in {WorkflowItemStatus.DRAFT, WorkflowItemStatus.READY}:
        return WorkflowItemStatus.READY if prompt.strip() else WorkflowItemStatus.DRAFT
    return status


def has_result(status, candidate_id):
    return candidate_id is not None or status in {
        WorkflowItemStatus.APPROVED,
        WorkflowItemStatus.REVIEW_REQUIRED,
        WorkflowItemStatus.GENERATING,
        WorkflowItemStatus.STALE,
    }


def changed_beat(beat: ShotVisualBeat, *, now=None) -> ShotVisualBeat:
    now = now or utc_now()
    return beat.model_copy(
        update={
            "image_status": result_status(
                beat.image_status, beat.approved_image_candidate_id, beat.image_prompt
            ),
            "image_inputs_changed": beat.image_inputs_changed
            or has_result(beat.image_status, beat.approved_image_candidate_id),
            "image_inputs_updated_at": now,
        }
    )


def changed_plan(plan: ShotPlan, *, image=False, video=True, now=None) -> ShotPlan:
    now = now or utc_now()
    updates = {}
    if image:
        beats = [changed_beat(beat, now=now) for beat in plan.visual_beats]
        required = [beat for beat in beats if beat.required] or beats
        statuses = {beat.image_status for beat in required}
        image_status = result_status(plan.image_status, None, plan.image_prompt)
        if required:
            image_status = next(
                (
                    status
                    for status in (
                        WorkflowItemStatus.GENERATING,
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.FAILED,
                        WorkflowItemStatus.READY,
                        WorkflowItemStatus.DRAFT,
                    )
                    if status in statuses
                ),
                WorkflowItemStatus.APPROVED,
            )
        updates.update(
            visual_beats=beats,
            image_status=image_status,
            image_inputs_changed=plan.image_inputs_changed
            or any(beat.image_inputs_changed for beat in beats)
            or has_result(plan.image_status, plan.approved_image_candidate_id),
            image_inputs_updated_at=now,
        )
    if video:
        updates.update(
            video_status=result_status(
                plan.video_status, plan.approved_video_candidate_id, plan.video_prompt
            ),
            video_inputs_changed=plan.video_inputs_changed
            or has_result(plan.video_status, plan.approved_video_candidate_id),
            video_inputs_updated_at=now,
        )
    return plan.model_copy(update=updates)


def generated_before_input_change(run, target, part):
    updated_at = getattr(target, f"{part}_inputs_updated_at", None)
    if updated_at is None:
        return bool(getattr(target, f"{part}_inputs_changed", False))
    return run.created_at < updated_at
