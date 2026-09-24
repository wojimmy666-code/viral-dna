"""Normalized, versioned composition guidance, not a promise of exact placement."""
from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompositionGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    aspect_ratio: float = Field(gt=0.1, le=10, allow_inf_nan=False)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(ge=0.03, le=1, allow_inf_nan=False)
    height: float = Field(ge=0.05, le=1, allow_inf_nan=False)
    subject_reference_id: UUID | None = None
    subject_label: str = Field(default="主要人物", min_length=1, max_length=80)
    facing: Literal["auto", "left", "right", "front"] = "auto"

    @model_validator(mode="after")
    def inside_canvas(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("人物定位框必须完整位于画布内")
        return self


class CompositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_context_id: UUID
    expected_revision_id: UUID
    operation: Literal["apply", "inherit", "disable", "default", "clear_default"] = "apply"
    visual_beat_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    guide: CompositionGuide | None = None


def effective_composition(context, project_id, beat_id):
    entries = context.image_compositions
    return entries.get(str(beat_id), entries.get(f"default:{project_id}"))


def guide_matches_aspect(guide, width, height):
    # Supported resolutions can round by a few pixels; changing landscape to
    # portrait is never silently stretched into another composition.
    return abs(width / height / guide.aspect_ratio - 1) <= 0.02


def guide_png(guide: CompositionGuide, width: int, height: int) -> bytes:
    """A deterministic measurement diagram; no private asset pixels are copied."""
    scale = min(1, 1024 / max(width, height))
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    image = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(image)
    x, y, bw, bh = guide.x * w, guide.y * h, guide.width * w, guide.height * h
    cx, bottom = x + bw / 2, y + bh
    stroke = max(2, round(min(bw, bh) * 0.07))
    draw.rectangle((x, y, x + bw, bottom), outline=(140, 140, 140), width=2)
    # Head, torso, arms and legs are schematic geometry only. The prompt
    # explicitly excludes this pose, appearance, box and white background.
    radius = min(bw * 0.18, bh * 0.075)
    draw.ellipse((cx - radius, y, cx + radius, y + radius * 2), fill=(80, 80, 80))
    shoulder, hip = y + bh * 0.23, y + bh * 0.56
    draw.line((cx, y + radius * 2, cx, hip), fill=(80, 80, 80), width=stroke)
    draw.line((x + bw * 0.13, y + bh * 0.49, cx, shoulder, x + bw * 0.87, y + bh * 0.49), fill=(80, 80, 80), width=stroke)
    draw.line((x + bw * 0.28, bottom - 2, cx, hip, x + bw * 0.72, bottom - 2), fill=(80, 80, 80), width=stroke)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def build_guide_reference(workspace, project, shot, guide, width, height):
    from .image_generation.contracts import ImageReferenceInput
    from .image_generation.gateway import _filesystem_path, _write_atomic
    content = guide_png(guide, width, height)
    digest = hashlib.sha256(content).hexdigest()
    root = workspace.production_shot_root(project.record_id, project.id, shot.id) / "images" / "composition-guides"
    path = root / f"{digest}.png"
    readable_path = _filesystem_path(path)
    if not readable_path.exists():
        # Share the gateway's atomic, Windows-long-path-safe artifact writer.
        _write_atomic(path, content)
    direction = {"auto": "朝向按正文要求", "left": "人物面向画面左侧", "right": "人物面向画面右侧", "front": "人物面向镜头"}[guide.facing]
    return ImageReferenceInput(
        asset_id=uuid5(NAMESPACE_URL, f"viraldna:composition:{digest}"), name="人物构图引导图", role="layout",
        path=readable_path, relative_path=workspace.relative(path), sha256=digest, weight=1,
        notes=(f"这是构图示意，不是人物身份或风格参考。只将{guide.subject_label}的躯干中线、头顶、脚底和画面占比对齐示意区域。"
               f"人物水平中心为画宽的{(guide.x + guide.width / 2) * 100:.1f}%，头顶为画高的{guide.y * 100:.1f}%，"
               f"人物高度为画高的{guide.height * 100:.1f}%，脚底为画高的{(guide.y + guide.height) * 100:.1f}%。{direction}。"
               "构图位置以此图为准，人物身份、衣服、动作与场景以各自资产和正文为准；不要复制示意人的姿态、轮廓或颜色，"
               "不得输出白底、定位框、辅助线、文字或示意人。"),
    )
