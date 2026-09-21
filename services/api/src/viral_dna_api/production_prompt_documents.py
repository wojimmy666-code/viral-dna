"""A live projection of production prompts. Never a second prompt store."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models import ProductionChangeKind, ShotLifecycleStatus, utc_now
from .production import ProductionServiceError
from .project_prompts import local_prompt
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


class PromptShotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    images: list[PromptImageBody] = Field(min_length=1, max_length=200)
    video_prompt: str = Field(max_length=8000)
    video_negative_constraints: list[str] = Field(default_factory=list, max_length=40)


class PromptDocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    common_image_prompt: str = Field(max_length=8000)
    common_video_prompt: str = Field(max_length=8000)
    shots: list[PromptShotBody] = Field(min_length=1, max_length=200)


def document_bodies(document):
    return {
        "common_image_prompt": document["common_image_prompt"],
        "common_video_prompt": document["common_video_prompt"],
        "shots": [
            {
                "id": shot["id"],
                "images": [
                    {key: image[key] for key in ("id", "prompt", "negative_constraints")}
                    for image in shot["images"]
                ],
                "video_prompt": shot["video_prompt"],
                "video_negative_constraints": shot["video_negative_constraints"],
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
                compiled, _ = execution_plan(group, members)
                row.update(compiled_prompt=compiled.video_prompt, negative_constraints=compiled.video_negative_constraints,
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
            "common_image_prompt": context.common_image_prompt,
            "common_video_prompt": context.common_video_prompt,
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
                for first, second in [
                    (old["video_prompt"], new["video_prompt"]),
                    *[
                        (a["prompt"], b["prompt"])
                        for a, b in zip(old["images"], new["images"], strict=True)
                    ],
                ]:
                    if re.findall(r"@(?:\[[^\]\n]+\]|[^\s，。；、]+)", first) != re.findall(
                        r"@(?:\[[^\]\n]+\]|[^\s，。；、]+)", second
                    ):
                        raise ProductionServiceError(
                            422,
                            "prompt_references_changed",
                            "资产引用请在分镜编辑器中调整；当前文本已保留",
                        )
            if incoming == before:
                return document
            now, revision_id = utc_now(), uuid4()
            next_context = context.model_copy(
                update={
                    "id": uuid4(),
                    "revision_number": context.revision_number + 1,
                    "common_image_prompt": incoming["common_image_prompt"],
                    "common_video_prompt": incoming["common_video_prompt"],
                    "created_at": now,
                }
            )
            if all(
                incoming[key] == before[key]
                for key in ("common_image_prompt", "common_video_prompt")
            ):
                next_context = context
            by_id = {item["id"]: item for item in incoming["shots"]}
            previous = {item["id"]: item for item in before["shots"]}
            global_image_changed = incoming["common_image_prompt"] != before["common_image_prompt"]
            global_video_changed = incoming["common_video_prompt"] != before["common_video_prompt"]
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
                    row[key] != old[key] for key in ("video_prompt", "video_negative_constraints")
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
                            "image_negative_constraints": images[str(beat.id)][
                                "negative_constraints"
                            ],
                        }
                    )
                    for beat in plan.visual_beats
                ]
                primary = row["images"][0]
                draft = drafts.get(plan.id)
                updated.append(
                    changed_plan(plan, image=image_changed, video=video_changed).model_copy(
                        update={
                            "revision_id": revision_id,
                            "image_prompt": primary["prompt"],
                            "image_negative_constraints": primary["negative_constraints"],
                            "visual_beats": beats,
                            "video_prompt": row["video_prompt"],
                            "video_negative_constraints": row["video_negative_constraints"],
                            "video_prompt_mentions": draft.video_prompt_mentions
                            if draft
                            else plan.video_prompt_mentions,
                            "updated_at": now,
                        }
                    )
                )
                if draft and video_changed:
                    next_drafts.append(
                        draft.model_copy(
                            update={
                                "video_prompt": row["video_prompt"],
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
                reference_bindings=await service._all_bindings(plans),
            )
            if translation_job:
                translation_job = translation_job.model_copy(
                    update={"language_applied_revision_id": revision_id}
                )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=updated,
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
