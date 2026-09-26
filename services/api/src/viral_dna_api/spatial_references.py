"""Atomic per-visual-beat spatial-reference application. Never touches generated media."""
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .composition import effective_composition
from .models import PromptAssetMention, ReferenceBindingInput, ReferenceRole, ProductionChangeKind, utc_now
from .project_prompts import ProjectPromptService, prompt_lock
from .reference_purposes import spatial_references
from .upstream_changes import changed_beat


class SpatialReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_id: UUID
    expected_context_id: UUID
    visual_beat_ids: list[UUID] = Field(min_length=1, max_length=1000)
    reference_asset_id: UUID
    replace_existing: bool = False


async def spatial_reference_state(service, project_id):
    state = await service.get_composition(project_id)
    context = await service.get_prompt_context(project_id)
    plans = await service.repository.list_shot_plans(project_id)
    by_id = {}
    for plan in plans:
        bindings = await service.repository.list_reference_bindings(plan.id)
        for beat in plan.visual_beats:
            refs = spatial_references(service._image_bindings_for_beat(plan, beat, bindings))
            by_id[str(beat.id)] = [str(item.reference_asset_id) for item in refs]
    return {**state, "targets": [{**item, "spatial_reference_ids": by_id.get(item["id"], []),
                                  "has_composition": bool(effective_composition(context, project_id, item["id"]))}
                                 for item in state["targets"]]}


async def apply_spatial_reference(service, project_id, payload):
    from .production import _fail, _reference_asset_mention_label, _sync_image_prompt_reference_tokens, _sync_shot_visual_beats
    async with await service._project_lock(project_id):
        project = await service._require_project(project_id)
        service._require_expected_revision(project, payload.expected_revision_id)
        # Retain outside the context lock: _prepare_revision ordinarily takes
        # that same non-reentrant lock while retaining legacy prompt baselines.
        await ProjectPromptService(service.repository).retain_baseline(project)
        context = await service.get_prompt_context(project_id)
        async with prompt_lock(service.repository, context.project_id):
            context = await service.get_prompt_context(project_id)
            if context.id != payload.expected_context_id:
                raise _fail(409, "spatial_context_stale", "全局设置已更新，请重新打开批量应用后核对")
            assets = {item.id: item for item in await service._list_reference_assets(project_id)}
            asset = assets.get(payload.reference_asset_id)
            if not asset or asset.archived_at or not asset.rights_confirmed:
                raise _fail(422, "spatial_asset_unavailable", "空间参考资产不可用，请重新选择")
            global_spatial = spatial_references(context.common_image_mentions)
            if any(item.reference_asset_id != asset.id for item in global_spatial):
                raise _fail(409, "spatial_global_conflict", "全局提示词已有不同的空间参考，请先移除或更换全局引用")
            plans = await service.repository.list_shot_plans(project_id)
            allowed = {beat.id for plan in plans if str(plan.lifecycle_status) != "discarded" for beat in plan.visual_beats}
            targets = set(payload.visual_beat_ids)
            if targets - allowed or len(targets) != len(payload.visual_beat_ids):
                raise _fail(422, "spatial_target_invalid", "所选画面不存在、已归档或重复")
            if any(effective_composition(context, project_id, target) for target in targets):
                raise _fail(409, "spatial_composition_conflict", "所选画面启用了构图引导，请先停用对应画面的构图引导")
            all_bindings = await service._all_bindings(plans)
            revised, replacements, removed = [], [], []
            revision_id = uuid4()
            for plan in plans:
                if not any(beat.id in targets for beat in plan.visual_beats):
                    continue
                bindings = [item for item in all_bindings if item.shot_plan_id == plan.id]
                beats, removed_assets = [], set()
                for beat in plan.visual_beats:
                    if beat.id not in targets:
                        beats.append(beat)
                        continue
                    old = spatial_references(service._image_bindings_for_beat(plan, beat, bindings))
                    if any(item.reference_asset_id != asset.id for item in old) and not payload.replace_existing:
                        raise _fail(409, "spatial_replace_confirmation", "所选画面已有其他空间参考，请确认替换后再应用")
                    old_ids = {item.reference_asset_id for item in old}
                    removed_assets.update(old_ids - {asset.id})
                    mentions = [item for item in beat.image_prompt_mentions if item.reference_asset_id not in old_ids | {asset.id}]
                    mentions.append(PromptAssetMention(reference_asset_id=asset.id, label=_reference_asset_mention_label(asset), role=ReferenceRole.SPATIAL))
                    if mentions == beat.image_prompt_mentions:
                        beats.append(beat)
                        continue
                    beats.append(changed_beat(beat).model_copy(update={
                        "image_prompt_mentions": mentions,
                        "image_prompt": _sync_image_prompt_reference_tokens(beat.image_prompt, beat.image_prompt_mentions, mentions),
                        "updated_at": utc_now(),
                    }))
                if beats == plan.visual_beats:
                    continue
                used = {m.reference_asset_id for b in beats for m in b.image_prompt_mentions}
                inputs = [ReferenceBindingInput(**item.model_dump(include={"reference_asset_id", "role", "weight", "crop_hint", "notes"}))
                          for item in bindings if item.reference_asset_id not in removed_assets or item.reference_asset_id in used]
                inputs = await service._append_mention_bindings(project, inputs, [m for b in beats for m in b.image_prompt_mentions])
                new_bindings = await service._build_bindings(project, plan, inputs)
                replacements.extend(new_bindings)
                removed.extend(item.id for item in bindings)
                all_bindings = [item for item in all_bindings if item.shot_plan_id != plan.id] + new_bindings
                revised.append(_sync_shot_visual_beats(plan, beats, revision_id=revision_id, invalidate_video=True))
            if revised:
                by_id = {item.id: item for item in revised}
                next_project, revision = await service._prepare_revision(
                    project.model_copy(update={"updated_at": utc_now()}), ProductionChangeKind.SHOT_PLAN_CHANGED,
                    f"为 {len(targets)} 个画面应用空间参考", revision_id=revision_id,
                    prompt_baseline_retained=True,
                    shot_plans=[by_id.get(item.id, item) for item in plans], reference_bindings=all_bindings)
                await service.repository.save_production_bundle(next_project, revision, shot_plans=revised,
                                                               reference_bindings=replacements, remove_reference_binding_ids=removed)
    return await spatial_reference_state(service, project_id)
