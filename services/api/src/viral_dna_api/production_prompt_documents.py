"""A live projection of production prompts. Never a second prompt store."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models import (ProductionChangeKind, ShotLifecycleStatus, utc_now, PromptAssetMention,
                     VideoPromptMention, ReferenceBindingInput, VideoGenerationReference,
                     VideoGenerationInputSource)
from .production import ProductionServiceError
from .project_prompts import local_prompt, effective_style, prompt_snapshot
from .upstream_changes import changed_beat, changed_plan
from .viral_insights.creative_language import is_foreign_prose


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


class PromptImageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    prompt: str = Field(max_length=8000)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    mentions: list[PromptAssetMention] | None = Field(default=None, max_length=50)


class PromptShotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    images: list[PromptImageBody] = Field(min_length=1, max_length=200)
    video_prompt: str = Field(max_length=8000)
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    video_mentions: list[VideoPromptMention] | None = Field(default=None, max_length=50)


class PromptDocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    common_image_prompt: str = Field(max_length=8000)
    common_video_prompt: str = Field(max_length=8000)
    common_image_mentions: list[PromptAssetMention] | None = Field(default=None, max_length=50)
    common_video_mentions: list[VideoPromptMention] | None = Field(default=None, max_length=50)
    shots: list[PromptShotBody] = Field(min_length=1, max_length=200)


def document_bodies(document):
    return {
        "common_image_prompt": document["common_image_prompt"],
        "common_video_prompt": document["common_video_prompt"],
        **{key: document[key] for key in ("common_image_mentions", "common_video_mentions") if key in document},
        "shots": [
            {
                "id": shot["id"],
                "images": [
                    {key: image[key] for key in ("id", "prompt", "negative_constraints", "mentions") if key in image}
                    for image in shot["images"]
                ],
                "video_prompt": shot["video_prompt"],
                "video_negative_constraints": shot["video_negative_constraints"],
                **({"video_mentions": shot["video_mentions"]} if "video_mentions" in shot else {}),
            }
            for shot in document["shots"]
        ],
    }


def document_language_issues(document):
    issues = []
    for part, label in (("image", "图片"), ("video", "视频")):
        if is_foreign_prose(document[f"common_{part}_prompt"]):
            issues.append(f"全局{label}提示词")
    for shot in document["shots"]:
        for index, image in enumerate(shot["images"], 1):
            if is_foreign_prose(image["prompt"]) or any(
                map(is_foreign_prose, image["negative_constraints"])
            ):
                issues.append(f"分镜 {shot['index']} 图片 {index}")
        if is_foreign_prose(shot["video_prompt"]) or any(
            map(is_foreign_prose, shot["video_negative_constraints"])
        ):
            issues.append(f"分镜 {shot['index']} 视频")
    return issues


class ProductionPromptDocuments:
    def __init__(self, production):
        self.production = production
        self.repository = production.repository

    async def state(self, identifier):
        project = await self.production._require_project(identifier)
        context = await self.production.get_prompt_context(identifier)
        plans = await self.repository.list_shot_plans(identifier)
        drafts = {
            plan.id: await self.repository.get_video_generation_draft(plan.id) for plan in plans
        }
        return project, context, plans, drafts

    def project(self, project, context, plans, drafts):
        rows = []
        groups = []
        from .video_groups import members_for, execution_plan
        for group in project.video_generation_groups:
            row = group.model_dump(mode="json")
            try:
                members = members_for(project, group, plans)
                members = [p.model_copy(update={"video_prompt": local_prompt(drafts[p.id].video_prompt, context, "video"),
                    "video_prompt_mentions": drafts[p.id].video_prompt_mentions,
                    "video_negative_constraints": drafts[p.id].video_negative_constraints})
                    if drafts.get(p.id) else self.production._local_prompt_view(p, context) for p in members]
                compiled, _ = execution_plan(group, members, context=context)
                row.update(compiled_prompt=prompt_snapshot(compiled.video_prompt, context, "video", include_style=False)["compiled_prompt"], negative_constraints=compiled.video_negative_constraints,
                    target_duration_seconds=compiled.duration_seconds, error=None)
            except ProductionServiceError as exc:
                row.update(compiled_prompt=group.video_prompt, negative_constraints=[], error=str(exc))
            groups.append(row)
        for plan in plans:
            if plan.lifecycle_status != ShotLifecycleStatus.ACTIVE:
                continue
            draft = drafts.get(plan.id)
            view = self.production._local_prompt_view(plan, context)
            beats = sorted(view.visual_beats, key=lambda item: item.index)
            images = [
                {
                    "id": str(beat.id),
                    "prompt": beat.image_prompt,
                    "negative_constraints": beat.image_negative_constraints,
                    "mentions": [
                        item.model_dump(mode="json") for item in beat.image_prompt_mentions
                    ],
                }
                for beat in beats
            ] or [
                {
                    "id": str(plan.id),
                    "prompt": view.image_prompt,
                    "negative_constraints": view.image_negative_constraints,
                    "mentions": [
                        item.model_dump(mode="json") for item in view.image_prompt_mentions
                    ],
                }
            ]
            rows.append(
                {
                    "id": str(plan.id),
                    "index": plan.index,
                    "title": f"分镜 {plan.index}",
                    "visual_style_snapshot": effective_style(context, str(plan.id)),
                    "video_group_id": next((str(g.id) for g in project.video_generation_groups if plan.id in g.shot_plan_ids), None),
                    "duration_seconds": plan.end_seconds - plan.start_seconds,
                    "images": images,
                    "video_prompt": local_prompt(draft.video_prompt, context, "video")
                    if draft
                    else view.video_prompt,
                    "video_negative_constraints": draft.video_negative_constraints
                    if draft
                    else view.video_negative_constraints,
                    "video_mentions": [
                        item.model_dump(mode="json")
                        for item in (
                            draft.video_prompt_mentions if draft else plan.video_prompt_mentions
                        )
                    ],
                }
            )
        document = {
            "project_id": str(project.id),
            "record_id": str(project.record_id),
            "name": project.name,
            "revision_id": str(project.current_revision_id),
            "context_id": str(context.id),
            "visual_style_snapshot": context.visual_style_snapshot,
            "common_image_prompt": context.common_image_prompt,
            "common_video_prompt": context.common_video_prompt,
            "common_image_mentions": [item.model_dump(mode="json") for item in context.common_image_mentions],
            "common_video_mentions": [item.model_dump(mode="json") for item in context.common_video_mentions],
            "shots": rows,
            "video_groups": groups,
        }
        document["token"] = fingerprint(
            {
                "document": document,
                "drafts": {
                    str(key): value.draft_version if value else 0 for key, value in drafts.items()
                },
            }
        )
        document["language_issues"] = document_language_issues(document)
        return document

    async def get(self, identifier):
        return self.project(*await self.state(identifier))

    async def save(self, identifier, payload, *, translation_job=None):
        service = self.production
        async with await service._project_lock(identifier):
            project, context, plans, drafts = await self.state(identifier)
            document = self.project(project, context, plans, drafts)
            if payload.expected_token != document["token"]:
                raise ProductionServiceError(
                    409,
                    "prompt_document_changed",
                    "方案提示词或视频草稿已更新；当前内容已保留，请重新读取并核对",
                )
            incoming = payload.model_dump(mode="json", exclude={"expected_token"})
            before = document_bodies(document)
            await service._validate_global_mentions(project, payload)
            for part in ("image", "video"):
                key = f"common_{part}_mentions"
                if incoming[key] is None:
                    incoming[key] = before[key]
                incoming[key] = [item for item in incoming[key] if f"@{item['label']}" in incoming[f"common_{part}_prompt"]]
            if [item["id"] for item in incoming["shots"]] != [
                item["id"] for item in before["shots"]
            ]:
                raise ProductionServiceError(
                    422, "prompt_document_structure", "不能通过提示词文档增删或重排分镜"
                )
            for old, new in zip(before["shots"], incoming["shots"], strict=True):
                if [item["id"] for item in old["images"]] != [item["id"] for item in new["images"]]:
                    raise ProductionServiceError(
                        422, "prompt_document_structure", "画面列表已改变，请在分镜图片阶段调整"
                    )
                for first, second, metadata in [
                    (old["video_prompt"], new["video_prompt"], new["video_mentions"]),
                    *[
                        (a["prompt"], b["prompt"], b["mentions"])
                        for a, b in zip(old["images"], new["images"], strict=True)
                    ],
                ]:
                    if metadata is None and re.findall(r"@(?:\[[^\]\n]+\]|[^\s，。；、]+)", first) != re.findall(
                        r"@(?:\[[^\]\n]+\]|[^\s，。；、]+)", second
                    ):
                        raise ProductionServiceError(
                            422,
                            "prompt_references_changed",
                            "资产引用请在分镜编辑器中调整；当前文本已保留",
                        )
                plan = next(item for item in plans if str(item.id) == new["id"])
                if new["video_mentions"] is None:
                    new["video_mentions"] = old["video_mentions"]
                else:
                    validated = await service._validate_video_prompt_mentions(project, plan, [VideoPromptMention.model_validate(item) for item in new["video_mentions"]])
                    new["video_mentions"] = [item.model_dump(mode="json") for item in validated if f"@{item.label}" in new["video_prompt"]]
                for first, second in zip(old["images"], new["images"], strict=True):
                    if second["mentions"] is None:
                        second["mentions"] = first["mentions"]
                    else:
                        validated = await service._validate_prompt_mentions(project, [PromptAssetMention.model_validate(item) for item in second["mentions"]])
                        second["mentions"] = [item.model_dump(mode="json") for item in validated if f"@{item.label}" in second["prompt"]]
            if incoming == before:
                return document
            now, revision_id = utc_now(), uuid4()
            next_context = context.model_copy(
                update={
                    "id": uuid4(),
                    "revision_number": context.revision_number + 1,
                    "common_image_prompt": incoming["common_image_prompt"],
                    "common_video_prompt": incoming["common_video_prompt"],
                    "common_image_mentions": [PromptAssetMention.model_validate(item) for item in incoming["common_image_mentions"]],
                    "common_video_mentions": [VideoPromptMention.model_validate(item) for item in incoming["common_video_mentions"]],
                    "created_at": now,
                }
            )
            if all(
                incoming[key] == before[key]
                for key in ("common_image_prompt", "common_video_prompt", "common_image_mentions", "common_video_mentions")
            ):
                next_context = context
            by_id = {item["id"]: item for item in incoming["shots"]}
            previous = {item["id"]: item for item in before["shots"]}
            global_image_changed = any(incoming[key] != before[key] for key in ("common_image_prompt", "common_image_mentions"))
            global_video_changed = any(incoming[key] != before[key] for key in ("common_video_prompt", "common_video_mentions"))
            all_bindings = await service._all_bindings(plans)
            new_bindings, removed_bindings = [], []
            updated, next_drafts = [], []
            for plan in plans:
                row = by_id.get(str(plan.id))
                if not row:
                    updated.append(plan)
                    continue
                images = {item["id"]: item for item in row["images"]}
                old = previous[str(plan.id)]
                old_images = {item["id"]: item for item in old["images"]}
                image_changed = global_image_changed or row["images"] != old["images"]
                video_changed = global_video_changed or any(
                    row[key] != old[key] for key in ("video_prompt", "video_negative_constraints", "video_mentions")
                )
                if not image_changed and not video_changed:
                    updated.append(plan)
                    continue
                beats = [
                    (
                        changed_beat(beat)
                        if global_image_changed or images[str(beat.id)] != old_images[str(beat.id)]
                        else beat
                    ).model_copy(
                        update={
                            "image_prompt": images[str(beat.id)]["prompt"],
                            "image_prompt_mentions": [PromptAssetMention.model_validate(item) for item in images[str(beat.id)]["mentions"]],
                            "image_negative_constraints": images[str(beat.id)][
                                "negative_constraints"
                            ],
                        }
                    )
                    for beat in plan.visual_beats
                ]
                primary = row["images"][0]
                if any(first["mentions"] != second["mentions"] for first, second in zip(old["images"], row["images"], strict=True)):
                    mentions = [PromptAssetMention.model_validate(item) for image in row["images"] for item in image["mentions"]]
                    previous_ids = {UUID(item["reference_asset_id"]) for image in old["images"] for item in image["mentions"]}
                    retained = {item.reference_asset_id for item in mentions}
                    existing = [item for item in all_bindings if item.shot_plan_id == plan.id]
                    inputs = [ReferenceBindingInput(**item.model_dump()) for item in existing if item.reference_asset_id not in previous_ids or item.reference_asset_id in retained]
                    inputs = await service._append_mention_bindings(project, inputs, mentions)
                    built = await service._build_bindings(project, plan, inputs)
                    new_bindings.extend(built)
                    removed_bindings.extend(item.id for item in existing)
                    all_bindings = [item for item in all_bindings if item.shot_plan_id != plan.id] + built
                draft = drafts.get(plan.id)
                video_mentions = [VideoPromptMention.model_validate(item) for item in row["video_mentions"]]
                updated.append(
                    changed_plan(plan, image=image_changed, video=video_changed).model_copy(
                        update={
                            "revision_id": revision_id,
                            "image_prompt": primary["prompt"],
                            "image_prompt_mentions": [PromptAssetMention.model_validate(item) for item in primary["mentions"]],
                            "image_negative_constraints": primary["negative_constraints"],
                            "visual_beats": beats,
                            "video_prompt": row["video_prompt"],
                            "video_negative_constraints": row["video_negative_constraints"],
                            "video_prompt_mentions": video_mentions,
                            "updated_at": now,
                        }
                    )
                )
                if draft and video_changed:
                    keys = {(item.reference_kind, item.reference_id) for item in video_mentions}
                    removed = {(item.reference_kind, item.reference_id) for item in draft.video_prompt_mentions} - keys
                    selected = [item for item in draft.input_plan.references if (item.reference_kind, item.reference_id) not in removed]
                    selected_keys = {(item.reference_kind, item.reference_id) for item in selected}
                    selected.extend(VideoGenerationReference(**item.model_dump()) for item in video_mentions if (item.reference_kind, item.reference_id) not in selected_keys)
                    source_by_kind = {"project_asset": "project_assets", "approved_image": "approved_images", "provider_managed_asset": "provider_managed_assets", "reference_video": "reference_video", "depth_control": "depth_control"}
                    sources = list(dict.fromkeys([*draft.input_plan.sources, *(VideoGenerationInputSource(source_by_kind[item.reference_kind]) for item in selected)]))
                    exclusions = set(draft.auto_reference_exclusions)
                    for beat in plan.visual_beats:
                        if ("approved_image", beat.approved_image_candidate_id) in removed:
                            exclusions.add(beat.id)
                        elif ("approved_image", beat.approved_image_candidate_id) in keys:
                            exclusions.discard(beat.id)
                    next_drafts.append(
                        draft.model_copy(
                            update={
                                "video_prompt": row["video_prompt"],
                                "video_prompt_mentions": video_mentions,
                                "input_plan": draft.input_plan.model_copy(update={"references": selected, "sources": sources}),
                                "auto_reference_exclusions": list(exclusions),
                                "video_negative_constraints": row["video_negative_constraints"],
                                "prompt_manually_modified": True,
                                "draft_version": draft.draft_version + 1,
                                "updated_at": now,
                            }
                        )
                    )
            next_project, revision = await service._prepare_revision(
                project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                "应用中文提示词修订，保留历史素材与采用状态"
                if translation_job
                else "编辑方案提示词文档",
                revision_id=revision_id,
                shot_plans=updated,
                reference_bindings=all_bindings,
            )
            if translation_job:
                translation_job = translation_job.model_copy(
                    update={"language_applied_revision_id": revision_id}
                )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=updated,
                reference_bindings=new_bindings,
                remove_reference_binding_ids=removed_bindings,
                prompt_update={
                    "expected_revision_id": project.current_revision_id,
                    "expected_drafts": {
                        plan.id: drafts[plan.id].draft_version if drafts[plan.id] else 0
                        for plan in plans
                    },
                    # _prepare_revision retains the old context baseline if needed.
                    # Compare the captured ID, never a newly read concurrent version.
                    "expected_context_id": context.id,
                    "context": next_context,
                    "baseline": None,
                    "drafts": next_drafts,
                    "job": translation_job,
                },
            )
        return await self.get(identifier)
