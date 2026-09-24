"""Editable production style is separate from immutable creative-generation input."""
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..project_prompts import ProjectPromptUpdate
from ..visual_styles import VisualStyle, freeze_style


class ProductionStyleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=80)
    visual_style: VisualStyle


async def production_style(creative, identifier, payload=None):
    async with creative.lock(identifier):
        batch = await creative.get(identifier)
        if batch.phase != "expanded" or batch.status != "completed":
            raise HTTPException(409, "请先完成分镜方案")
        if batch.published_result:
            production = creative.insights.publisher.production_service
            project_id = batch.published_result.project_id
            context = await production.get_prompt_context(project_id)
            if payload:
                context = await production.update_prompt_context(project_id, ProjectPromptUpdate(
                    expected_revision_id=UUID(payload.expected_revision),
                    common_image_prompt=context.common_image_prompt,
                    common_video_prompt=context.common_video_prompt,
                    visual_style=payload.visual_style,
                ))
            return {"revision": str(context.id), "selection": context.visual_style.model_dump(mode="json"),
                    "snapshot": context.visual_style_snapshot}
        if payload:
            if payload.expected_revision != str(batch.production_style_revision):
                raise HTTPException(409, "制作风格已更新，请重新读取后核对")
            batch.production_visual_style_snapshot = freeze_style(payload.visual_style)
            batch.production_style_revision += 1
            await creative.repository.save_viral_concept_set(batch)
        frozen = batch.production_visual_style_snapshot
        if frozen is None:
            frozen = batch.visual_style_snapshot
        return {"revision": str(batch.production_style_revision),
                "selection": frozen.get("selection", {"preset": "original"}), "snapshot": frozen}
