"""Shared, versioned creative context. Reads never rewrite historical shots or seeds."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from weakref import WeakKeyDictionary

from pydantic import BaseModel, Field

from .prompt_engine.punctuation import normalize_prompt_punctuation
from .prompt_engine.still_image import static_image_text


class PromptRevisionConflict(ValueError):
    pass


class ProjectPromptRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID  # Skill owner project, or an independent analysis production.
    revision_number: int = 0
    common_image_prompt: str = Field(default="", max_length=8000)
    common_video_prompt: str = Field(default="", max_length=8000)
    original_image_prompt: str = ""
    original_video_prompt: str = ""
    known_image_prompts: list[str] = Field(default_factory=list, exclude=True)
    known_video_prompts: list[str] = Field(default_factory=list, exclude=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectPromptUpdate(BaseModel):
    expected_revision_id: UUID
    common_image_prompt: str = Field(max_length=8000)
    common_video_prompt: str = Field(max_length=8000)


def sections(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?=【[^】]+】)", value.strip()) if part.strip()]


def local_prompt(value: str, context: ProjectPromptRevision, part: str) -> str:
    """Only exact known shared blocks are removed; ambiguous/manual prose stays local."""
    value = normalize_prompt_punctuation(value)
    if part == "image":
        value = static_image_text(value)
    shared = {
        text
        for source in (
            getattr(context, f"original_{part}_prompt"),
            getattr(context, f"common_{part}_prompt"),
            *getattr(context, f"known_{part}_prompts"),
        )
        for text in sections(
            static_image_text(source) if part == "image" else normalize_prompt_punctuation(source)
        )
    }
    parsed = sections(value)
    technical = {
        text
        for text in parsed
        if part == "video"
        and text.startswith(
            "【首帧约束】以当前分镜已采用的图片为唯一首帧、主体、场景、构图与明暗关系依据，"
        )
    }
    if not any(text in shared or text in technical for text in parsed):
        return value
    # Keep exact separators between surviving local sections. Reformatting them
    # would otherwise dirty untouched shots and invalidate adopted results.
    return "".join(
        block
        for block in re.split(r"(?=【[^】]+】)", value)
        if block.strip() not in shared and block.strip() not in technical
    ).strip()


def compose_prompt(local: str, common: str, part: str) -> str:
    if part == "image":
        local, common = static_image_text(local), static_image_text(common)
    return normalize_prompt_punctuation(
        "\n\n".join(text.strip() for text in (common, local) if text.strip())
    )


def production_local_token(plans, drafts) -> str:
    versions = [
        (
            str(plan.id),
            str(plan.revision_id),
            drafts[plan.id].draft_version if drafts.get(plan.id) else 0,
        )
        for plan in plans
    ]
    return hashlib.sha256(json.dumps(sorted(versions)).encode()).hexdigest()


def prompt_snapshot(value: str, context: ProjectPromptRevision, part: str) -> dict:
    body = local_prompt(value, context, part)
    common = getattr(context, f"common_{part}_prompt")
    compiled = compose_prompt(body, common, part)
    material = {
        "global_revision_id": str(context.id),
        "part": part,
        "global_prompt": common,
        "local_prompt": body,
        "compiled_prompt": compiled,
    }
    material["content_hash"] = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return material


def extract_shared(prompts: list[str], part: str) -> str:
    if not prompts:
        return ""
    parsed = [
        sections(static_image_text(text) if part == "image" else normalize_prompt_punctuation(text))
        for text in prompts
    ]
    common = set(parsed[0]).intersection(*(set(items) for items in parsed[1:]))
    return "\n\n".join(
        text for text in parsed[0] if text in common and re.match(r"【全片[^】]*】", text)
    )


_locks = WeakKeyDictionary()


def prompt_lock(repository, project_id):
    return _locks.setdefault(repository, {}).setdefault(project_id, asyncio.Lock())


class ProjectPromptService:
    def __init__(self, repository):
        self.repository = repository

    async def retain_baseline(self, project):
        """Before a user edit, retain legacy globals even when a local loses its prefix."""
        scope = project.owner_project_id if project.origin_type == "skill_run" else project.id
        async with prompt_lock(self.repository, scope):
            if not await self.repository.list_project_prompt_revisions(scope):
                current = await self.for_production(project)
                await self.repository.save_project_prompt_revision(current, current.id)

    async def for_production(self, project):
        scope = project.owner_project_id if project.origin_type == "skill_run" else project.id
        image, video = "", ""
        if project.origin_type == "skill_run":
            manifests = await self.repository.list_shot_manifest_revisions(scope)
            bibles = await self.repository.list_style_bible_revisions(scope)
            if manifests and bibles:
                from .skill_workflow.storyboard_prompts import factor_prompt_context

                manifest = factor_prompt_context(
                    max(manifests, key=lambda item: item.revision_number),
                    max(bibles, key=lambda item: item.revision_number),
                )
                image, video = manifest.common_image_prompt, manifest.common_video_prompt
        if not image and not video:
            plans = await self.repository.list_shot_plans(project.id)
            image = extract_shared([plan.image_prompt for plan in plans], "image")
            video = extract_shared([plan.video_prompt for plan in plans], "video")
        return await self.current(scope, image=image, video=video)

    async def current(self, scope_id: UUID, *, image="", video="") -> ProjectPromptRevision:
        revisions = await self.repository.list_project_prompt_revisions(scope_id)
        if revisions:
            current = max(revisions, key=lambda item: item.revision_number)
            return current.model_copy(
                update={
                    f"known_{part}_prompts": list(
                        dict.fromkeys(getattr(item, f"common_{part}_prompt") for item in revisions)
                    )
                    for part in ("image", "video")
                }
                | {
                    "common_image_prompt": static_image_text(current.common_image_prompt),
                    "common_video_prompt": normalize_prompt_punctuation(
                        current.common_video_prompt
                    ),
                }
            )
        image = static_image_text(image)
        digest = hashlib.sha256((image + "\0" + video).encode("utf-8")).hexdigest()
        return ProjectPromptRevision(
            id=uuid5(NAMESPACE_URL, f"viraldna:prompts:{scope_id}:{digest}"),
            project_id=scope_id,
            common_image_prompt=image,
            common_video_prompt=normalize_prompt_punctuation(video),
            original_image_prompt=image,
            original_video_prompt=video,
            created_at=datetime(2000, 1, 1, tzinfo=UTC),
        )

    async def save(self, current: ProjectPromptRevision, payload: ProjectPromptUpdate):
        if payload.expected_revision_id != current.id:
            raise PromptRevisionConflict("全局提示词已在其他页面更新，当前草稿已保留，请刷新后核对")
        image, video = (
            static_image_text(payload.common_image_prompt),
            normalize_prompt_punctuation(payload.common_video_prompt.strip()),
        )
        if (image, video) == (current.common_image_prompt, current.common_video_prompt):
            return current
        saved = current.model_copy(
            update={
                "id": uuid4(),
                "revision_number": current.revision_number + 1,
                "common_image_prompt": image,
                "common_video_prompt": video,
                "created_at": datetime.now(UTC),
            }
        )
        return await self.repository.save_project_prompt_revision(saved, current.id)
