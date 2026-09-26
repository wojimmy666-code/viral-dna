"""Explicit multi-shot generation, with reviewed source ranges for editing.

No paid calls, implicit grouping or media copies occur when reading this service.
Generation reuses the durable production queue; a synthetic shot is execution-only.
"""

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from .models import (
    GenerationKind, GenerationCandidateStatus, ProductionChangeKind,
    ProductionRunStatus, ShotLifecycleStatus, WorkflowItemStatus, utc_now,
    ApprovalEvent, ApprovalDecision, VideoClipPreparationStatus,
    VideoPromptMention,
)
from .video_group_models import VideoGroupUpdate, VideoGroupAdopt, VideoGroupClip
from .project_prompts import effective_style, prompt_snapshot
from .visual_styles import style_prompt


def fail(message, status=409):
    from .production import ProductionServiceError
    raise ProductionServiceError(status, "video_group_invalid", message)


def group_for(project, identifier):
    group = next((g for g in project.video_generation_groups if g.id == identifier), None)
    if group is None:
        fail("视频生成组不存在或已拆分", 404)
    return group


def members_for(project, group, plans):
    active = [p for p in sorted(plans, key=lambda p: p.index)
              if p.lifecycle_status == ShotLifecycleStatus.ACTIVE
              and (project.video_stage_shot_ids is None or p.id in project.video_stage_shot_ids)]
    lookup = {p.id: p for p in active}
    if any(identifier not in lookup for identifier in group.shot_plan_ids):
        fail("生成组包含已移除或未选入视频阶段的分镜，请重新分组")
    positions = [active.index(lookup[identifier]) for identifier in group.shot_plan_ids]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        fail("仅可合并按成片顺序排列的相邻分镜；请先调整分镜顺序")
    return [lookup[identifier] for identifier in group.shot_plan_ids]


def input_fingerprint(project, group, members, common_prompt, context=None):
    data = {
        "group": group.model_dump(mode="json"), "common_prompt": common_prompt,
        "size": [project.output_width, project.output_height],
        "shots": [{"id": str(p.id), "duration": p.duration_seconds,
                   "prompt": p.video_prompt, "negative": p.video_negative_constraints,
                   "mentions": [m.model_dump(mode="json") for m in p.video_prompt_mentions],
                   "assets": [a.model_dump(mode="json") for a in p.managed_asset_bindings],
                   "images": [{"id": str(b.id), "candidate": str(b.approved_image_candidate_id),
                               "prompt": b.image_prompt, "changed": b.image_inputs_changed,
                               "status": b.image_status, "index": b.index}
                              for b in p.visual_beats if b.approved_image_candidate_id]}
                  for p in members],
    }
    styles = {str(p.id): effective_style(context, str(p.id)) for p in members} if context else {}
    if any(styles.values()):
        data["visual_styles"] = styles
    if context and context.common_video_mentions:
        data["global_mentions"] = [item.model_dump(mode="json") for item in context.common_video_mentions]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def execution_plan(group, members, generation_duration=None, *, context=None):
    """Transient aggregate. Never persist this object over its anchor shot."""
    total = sum(p.duration_seconds for p in members)
    scale = float(generation_duration or total) / total
    cursor, beats, lines, owners, mentions = 0.0, [], [], {}, {}
    # Declare each distinct style once, then bind it to its temporal segment.
    # Repeating a whole preset per short shot can exceed provider prompt limits.
    style_rules = {p.id: style_prompt(effective_style(context, str(p.id)), "video") for p in members} if context else {}
    if context:
        reference_keys = {
            json.dumps((effective_style(context, str(p.id)) or {}).get("reference_image"), sort_keys=True)
            if "video" in (effective_style(context, str(p.id)) or {}).get("applies_to", []) else "null"
            for p in members
        }
        if len(reference_keys) > 1:
            fail("组内风格生成参考图不一致，请统一风格或拆组生成；不会忽略某个分段的风格参考图")
    definitions = list(dict.fromkeys(text for text in style_rules.values() if text))
    for p in members:
        adopted = [b for b in sorted(p.visual_beats, key=lambda b: b.index) if b.approved_image_candidate_id]
        if not adopted:
            fail(f"分镜 {p.index} 没有已采用图片")
        start = cursor
        for beat_index, b in enumerate(adopted):
            beat_duration = p.duration_seconds / len(adopted)
            owners[b.id] = p
            beats.append(b.model_copy(update={
                "index": len(beats) + 1, "start_ratio": cursor / total,
                "end_ratio": min(1.0, (cursor + beat_duration) / total),
                "transition_to_next_type": ({"continuous": "model_generated"}.get(group.transition, group.transition)
                    if beat_index == len(adopted) - 1 else b.transition_to_next_type),
                "transition_to_next_duration_seconds": ((0 if group.transition == "cut" else 0.3)
                    if beat_index == len(adopted) - 1 else b.transition_to_next_duration_seconds),
            }))
            cursor += beat_duration
        tokens = "、".join(f"图{b.index}" for b in beats[-len(adopted):])
        prompt = p.video_prompt
        if definitions:
            rules = style_rules[p.id]
            prompt += (f"\n本分段应用风格配置 {definitions.index(rules) + 1}。" if rules
                       else "\n本分段沿用自身正文风格，不应用其他分段的风格配置。")
        for mention in p.video_prompt_mentions:
            if mention.reference_kind.value in {"depth_control", "reference_video"}:
                fail("含深度或参考视频控制的分镜请独立生成，不能作为多场景组隐式合并")
            if mention.reference_kind.value == "approved_image":
                target = next((b for b in beats if b.approved_image_candidate_id == mention.reference_id), None)
                if target is None:
                    fail("分镜提示词引用了未采用图片，请先核对引用")
                prompt = prompt.replace(f"@{mention.label}", f"图{target.index}")
                continue
            key = (mention.reference_kind, mention.reference_id)
            if key not in mentions:
                mentions[key] = mention.model_copy(update={"label": f"分镜{p.index}-{mention.label}"})
            prompt = prompt.replace(f"@{mention.label}", f"@{mentions[key].label}")
        lines.append(f"成片分镜 {p.index}：生成目标 {start * scale:.3f}～{cursor * scale:.3f} 秒，参考{tokens}。{prompt}")
    if len(beats) > 20:
        fail("本组采用图片超过 20 张，请拆分生成组")
    transition = {"cut": "场景之间直接硬切，不融合、不渐变；允许不同地理空间。",
                  "continuous": "按用户动作与运镜要求连续衔接。",
                  "dissolve": "按分段规划使用短叠化转场。"}[group.transition]
    group_prompt = group.video_prompt
    for item in group.video_prompt_mentions:
        mention = VideoPromptMention.model_validate(item.model_dump())
        key = (mention.reference_kind, mention.reference_id)
        if key not in mentions:
            mentions[key] = mention
        group_prompt = group_prompt.replace(f"@{mention.label}", f"@{mentions[key].label}")
    prompt = "\n".join([group_prompt, transition,
                        "人物位置、动作与景别以各分镜要求为准，不强制继承原片。", *lines]).strip()
    if definitions:
        prompt += "\n" + "\n".join(f"风格配置 {i}（仅用于上方指定分段）：\n{text}" for i, text in enumerate(definitions, 1))
    if len(prompt) > 8000:
        fail("合并后的分段提示词超过 8000 字，请精简提示词或拆组")
    bindings = {b.asset_id: b for p in members for b in p.managed_asset_bindings}
    plan = members[0].model_copy(update={
        "visual_beats": beats, "duration_seconds": total, "video_prompt": prompt,
        "video_prompt_mentions": list(mentions.values()), "locks": [],
        "managed_asset_bindings": list(bindings.values()),
        "video_negative_constraints": list(dict.fromkeys(n for p in members for n in p.video_negative_constraints))[:40],
    })
    return plan, owners


class VideoGroups:
    def __init__(self, production):
        self.production = production
        self.repository = production.repository

    async def projection(self, project, group_id):
        group = group_for(project, group_id)
        members = members_for(project, group, await self.repository.list_shot_plans(project.id))
        current = []
        for member in members:
            draft = await self.repository.get_video_generation_draft(member.id)
            current.append(member.model_copy(update={"video_prompt": draft.video_prompt,
                "video_prompt_mentions": draft.video_prompt_mentions,
                "video_negative_constraints": draft.video_negative_constraints}) if draft else member)
        members = current
        context = await self.production.get_prompt_context(project.id)
        fingerprint = input_fingerprint(project, group, members, context.common_video_prompt, context)
        plan, owners = execution_plan(group, members, context=context)
        return group, members, plan, owners, fingerprint

    async def require_idle(self, project, identifiers):
        runs = await self.repository.list_generation_runs(project.id)
        if any(r.kind == GenerationKind.VIDEO and r.shot_plan_id in identifiers
               and r.status in {ProductionRunStatus.QUEUED, ProductionRunStatus.RUNNING,
                                ProductionRunStatus.CANCELLATION_REQUESTED} for r in runs):
            fail("相关分镜仍有生成任务，请等待结束或取消后再修改分组")

    async def update(self, project_id, payload):
        async with await self.production._project_lock(project_id):
            project = await self.production._require_project(project_id)
            self.production._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            used, group_ids = set(), set()
            for group in payload.groups:
                members = members_for(project, group, plans)
                mentions = [VideoPromptMention.model_validate(item.model_dump()) for item in group.video_prompt_mentions]
                await self.production._validate_video_prompt_mentions(project, members[0], mentions)
                if any(f"@{item.label}" not in group.video_prompt for item in mentions):
                    fail("组要求的资产标签已不在正文中，请重新引用或移除", 422)
                if used.intersection(group.shot_plan_ids) or group.id in group_ids:
                    fail("同一分镜不能同时属于两个生成组，生成组 ID 不能重复", 422)
                used.update(group.shot_plan_ids)
                group_ids.add(group.id)
            affected = used | {i for g in project.video_generation_groups for i in g.shot_plan_ids}
            await self.require_idle(project, affected)
            updated = project.model_copy(update={"video_generation_groups": payload.groups})
            next_plans = [p.model_copy(update={"video_inputs_changed": True}) if p.id in affected else p for p in plans]
            updated, revision = await self.production._prepare_revision(
                updated, ProductionChangeKind.SHOT_PLAN_CHANGED, "更新视频生成分组，保留原分镜与历史素材", shot_plans=next_plans)
            await self.repository.save_production_bundle(updated, revision, shot_plans=next_plans)
        return await self.state(project_id)

    async def state(self, project_id):
        project = await self.production._require_project(project_id)
        rows = []
        for group in project.video_generation_groups:
            row = group.model_dump(mode="json")
            runs = await self.repository.list_generation_runs(project.id, group.shot_plan_ids[0])
            matching = sorted([r for r in runs if str(r.request_payload.get("generation_group_id")) == str(group.id)], key=lambda r: r.created_at, reverse=True)
            row["runs"] = [await self.production._run_response(r) for r in matching[:8]]
            row["stale_run_ids"] = [str(r.id) for r in matching]
            try:
                _, members, plan, _, fingerprint = await self.projection(project, group.id)
                references = [{"reference_kind": "approved_image", "reference_id": str(b.approved_image_candidate_id),
                               "label": f"图{b.index}", "role": "composition", "order": b.index,
                               "visual_beat_id": str(b.id)} for b in plan.visual_beats]
                for mention in plan.video_prompt_mentions:
                    references.append({"reference_kind": mention.reference_kind, "reference_id": str(mention.reference_id),
                                       "label": mention.label, "role": mention.role, "order": len(references) + 1})
                context = await self.production.get_prompt_context(project.id)
                for mention in context.common_video_mentions:
                    if not any(item["reference_kind"] == mention.reference_kind and item["reference_id"] == str(mention.reference_id) for item in references):
                        references.append({"reference_kind": mention.reference_kind, "reference_id": str(mention.reference_id), "label": mention.label, "role": mention.role, "order": len(references) + 1})
                sources = ["approved_images"]
                if any(r["reference_kind"] == "project_asset" for r in references):
                    sources.append("project_assets")
                if plan.managed_asset_bindings:
                    sources.append("provider_managed_assets")
                row.update(input_fingerprint=fingerprint, target_duration_seconds=plan.duration_seconds,
                           input_plan={"sources": sources, "references": references},
                           compiled_prompt=prompt_snapshot(plan.video_prompt, await self.production.get_prompt_context(project.id), "video", include_style=False)["compiled_prompt"], anchor_shot_id=str(plan.id),
                           shots=[{"id": str(p.id), "index": p.index, "duration_seconds": p.duration_seconds} for p in members],
                           images=[{"id": str(b.approved_image_candidate_id), "index": b.index,
                                    "url": f"/api/v1/generation-candidates/{b.approved_image_candidate_id}/content"} for b in plan.visual_beats])
                row["stale_run_ids"] = [str(r.id) for r in matching if r.request_payload.get("expected_group_fingerprint") != fingerprint]
                row["error"] = None
            except Exception as exc:
                from .production import ProductionServiceError
                if not isinstance(exc, ProductionServiceError):
                    raise
                row["error"] = str(exc)
            rows.append(row)
        return {"expected_revision_id": str(project.current_revision_id), "groups": rows}

    async def adopt(self, project_id, group_id, payload):
        async with await self.production._project_lock(project_id):
            project = await self.production._require_project(project_id)
            self.production._require_expected_revision(project, payload.expected_revision_id)
            _, members, _, _, fingerprint = await self.projection(project, group_id)
            await self.require_idle(project, {p.id for p in members})
            candidate = await self.repository.get_generation_candidate(payload.candidate_id)
            run = await self.repository.get_generation_run(candidate.generation_run_id) if candidate else None
            if not candidate or not run or run.project_id != project.id or run.kind != GenerationKind.VIDEO or candidate.kind != GenerationKind.VIDEO:
                fail("视频候选不属于本项目生成组", 404)
            if (str(run.request_payload.get("generation_group_id")) != str(group_id)
                    or run.request_payload.get("expected_group_fingerprint") != fingerprint
                    or run.status not in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
                    or candidate.status not in {GenerationCandidateStatus.READY, GenerationCandidateStatus.SELECTED}):
                fail("候选视频与当前分组、图片或提示词不匹配，请重新生成或恢复原输入")
            await self.production.resolve_candidate_content(candidate.id)
            if [c.shot_plan_id for c in payload.cuts] != [p.id for p in members]:
                fail("请为组内每个分镜按顺序确认一个实际时间范围", 422)
            end = 0.0
            for cut in payload.cuts:
                if cut.trim_in_seconds < end or cut.trim_out_seconds <= cut.trim_in_seconds or cut.trim_out_seconds > float(candidate.duration_seconds or 0) + 0.001:
                    fail("切点不可重叠、倒序或超过视频实际时长", 422)
                end = cut.trim_out_seconds
            cuts = {c.shot_plan_id: c for c in payload.cuts}
            revision_id = uuid4()
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [p.model_copy(update={
                "revision_id": revision_id, "updated_at": utc_now(),
                "video_group_clip": VideoGroupClip(group_id=group_id, candidate_id=candidate.id,
                    input_fingerprint=fingerprint, trim_in_seconds=cuts[p.id].trim_in_seconds,
                    trim_out_seconds=cuts[p.id].trim_out_seconds),
                "approved_video_candidate_id": candidate.id, "video_status": WorkflowItemStatus.APPROVED,
                "video_inputs_changed": False,
            }) if p.id in cuts else p for p in plans]
            selected = candidate.model_copy(update={"status": GenerationCandidateStatus.SELECTED})
            preparations = await self.repository.list_video_clip_preparations(project.id)
            updated_preparations = [p.model_copy(update={"status": VideoClipPreparationStatus.STALE,
                "revision_id": revision_id, "updated_at": utc_now()}) if p.shot_plan_id in cuts else p for p in preparations]
            events = [ApprovalEvent(project_id=project.id, revision_id=revision_id,
                shot_plan_id=p.id, candidate_id=candidate.id, target_kind=GenerationKind.VIDEO,
                decision=ApprovalDecision.APPROVED, reason="已人工核对生成组场景、顺序与实际切点") for p in members]
            updated, revision = await self.production._prepare_revision(project,
                ProductionChangeKind.VIDEO_APPROVED, "确认生成组场景与实际切点，采用同一视频的不同片段",
                revision_id=revision_id, shot_plans=next_plans, video_clip_preparations=updated_preparations)
            await self.repository.save_production_bundle(updated, revision, shot_plans=next_plans,
                generation_candidates=[selected], approval_events=events, video_clip_preparations=updated_preparations)
        return await self.state(project_id)


def create_video_groups_router(production):
    router = APIRouter()
    service = VideoGroups(production)

    async def handle(coroutine):
        from .production import ProductionServiceError
        try:
            return await coroutine
        except ProductionServiceError as exc:
            raise HTTPException(exc.status_code, detail=str(exc)) from exc

    @router.get("/productions/{project_id}/video-groups")
    async def read_groups(project_id: UUID):
        return await handle(service.state(project_id))

    @router.put("/productions/{project_id}/video-groups")
    async def save_groups(project_id: UUID, payload: VideoGroupUpdate):
        return await handle(service.update(project_id, payload))

    @router.post("/productions/{project_id}/video-groups/{group_id}/adopt")
    async def adopt_group(project_id: UUID, group_id: UUID, payload: VideoGroupAdopt):
        return await handle(service.adopt(project_id, group_id, payload))

    return router
