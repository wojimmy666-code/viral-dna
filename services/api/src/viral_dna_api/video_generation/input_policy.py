"""Video inputs are adopted images plus explicitly selected video references.

Image provenance remains on the source shot; it is not a generation input.
Legacy frozen requests are deliberately handled by their original path.
"""

import hashlib
import json

from ..project_prompts import prompt_snapshot

VIDEO_INPUT_POLICY = "adopted_images_v1"


def video_prompt_snapshot(value, context, *, shot_key=None):
    snapshot = prompt_snapshot(value, context, "video", shot_key=shot_key, include_style=False)
    snapshot.pop("visual_style_snapshot", None)
    snapshot.pop("shot_style_snapshots", None)
    snapshot["input_policy"] = VIDEO_INPUT_POLICY
    snapshot.pop("content_hash", None)
    snapshot["content_hash"] = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return snapshot


def selected_video_plan(plan, input_plan):
    """Keep source metadata for history, but expose only selected controls."""
    managed_ids = {r.reference_id for r in input_plan.references
                   if r.reference_kind == "provider_managed_asset"}
    depth_ids = {r.reference_id for r in input_plan.references if r.reference_kind == "depth_control"}
    return plan.model_copy(update={
        "managed_asset_bindings": [b for b in plan.managed_asset_bindings if b.id in managed_ids],
        "depth_control_assets": [a for a in plan.depth_control_assets if a.id in depth_ids],
        # Stale metadata without a token is provenance, not an active reference.
        # Tokens still present in authored text remain subject to validation.
        "video_prompt_mentions": [m for m in plan.video_prompt_mentions
                                  if f"@{m.label}" in plan.video_prompt],
    })
