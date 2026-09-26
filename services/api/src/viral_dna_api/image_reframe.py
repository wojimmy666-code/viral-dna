"""Deterministic geometry for whole-image shrink + outpaint.

The subject box is a human measurement, not a detector result. Only the outer
environment is generative; the resized original is restored losslessly.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageChops, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(ge=0.01, le=1, allow_inf_nan=False)
    height: float = Field(ge=0.01, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def in_canvas(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("人物框必须完全位于画面内")
        return self


class ImageReframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    request_id: UUID
    source_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    source_box: ImageBox
    target_box: ImageBox


@dataclass(frozen=True)
class ReframePlan:
    width: int
    height: int
    scaled_width: int
    scaled_height: int
    left: int
    top: int
    feather: int
    source_box: ImageBox
    target_box: ImageBox
    actual_box: ImageBox

    def audit(self) -> dict:
        return {
            "version": 1,
            "method": "whole_image_scale_outpaint_restore",
            "measurement": "manual_source_box_transformed_not_detection",
            "output_size": [self.width, self.height],
            "original_region": [self.left, self.top, self.scaled_width, self.scaled_height],
            "feather_pixels": self.feather,
            "source_box": self.source_box.model_dump(),
            "target_box": self.target_box.model_dump(),
            "actual_box": self.actual_box.model_dump(),
            "width_policy": "preserve_original_proportions",
            "environment_review": "manual_required",
        }


def plan_reframe(
    source_size: tuple[int, int], width: int, height: int, spec: ImageReframe
) -> ReframePlan:
    sw, sh = source_size
    if min(sw, sh, width, height) <= 0 or max(sw * sh, width * height) > 64_000_000:
        raise ValueError("图片尺寸超过安全处理范围")
    source, target = spec.source_box, spec.target_box
    # Whole-image relative size: output resolution is independent of framing.
    factor = height * target.height / (sh * source.height)
    # Match Math.round in the interactive preview, including half-pixel ties.
    rw, rh = max(1, math.floor(sw * factor + 0.5)), max(1, math.floor(sh * factor + 0.5))
    left = math.floor(
        width * (target.x + target.width / 2) - rw * (source.x + source.width / 2) + 0.5
    )
    top = math.floor(height * target.y - rh * source.y + 0.5)
    if rw >= width and rh >= height:
        raise ValueError("缩放扩图需要缩小原图并留出待补全区域，请减小目标人物高度")
    if left < 0 or top < 0 or left + rw > width or top + rh > height:
        raise ValueError("目标位置会裁掉原图，请减小人物高度或将目标位置向画面中心移动")
    actual = ImageBox(
        x=(left + rw * source.x) / width,
        y=(top + rh * source.y) / height,
        width=rw * source.width / width,
        height=rh * source.height / height,
    )
    # Never feather over any pixel of the annotated subject (plus 2px margin).
    margin = min(
        source.x * rw,
        source.y * rh,
        (1 - source.x - source.width) * rw,
        (1 - source.y - source.height) * rh,
    )
    feather = max(0, min(round(min(width, height) * 0.026), math.floor(margin) - 2))
    return ReframePlan(width, height, rw, rh, left, top, feather, source, target, actual)


def read_source(path: Path, spec: ImageReframe) -> Image.Image:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != spec.source_sha256.lower():
        raise ValueError("原图已变化，请重新选择并标记人物")
    with Image.open(BytesIO(payload)) as source:
        if source.width * source.height > 64_000_000:
            raise ValueError("原图尺寸超过安全处理范围")
        return ImageOps.exif_transpose(source).convert("RGB")


def prepare_reframe(source: Image.Image, plan: ReframePlan) -> tuple[Image.Image, Image.Image]:
    resized = source.resize((plan.scaled_width, plan.scaled_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (plan.width, plan.height), (232, 232, 232))
    canvas.paste(resized, (plan.left, plan.top))
    return canvas, resized


def restore_reframe(raw: bytes, resized: Image.Image, plan: ReframePlan) -> tuple[bytes, dict]:
    with Image.open(BytesIO(raw)) as source:
        if source.width * source.height > 64_000_000:
            raise ValueError("扩图结果尺寸超过安全处理范围")
        generated = ImageOps.exif_transpose(source).convert("RGB")
    if abs((generated.width / generated.height) / (plan.width / plan.height) - 1) > 0.015:
        raise ValueError("模型返回画幅不符，已保留原始结果，未发布构图候选")
    raw_size = generated.size
    generated = generated.resize((plan.width, plan.height), Image.Resampling.LANCZOS)
    mask = Image.new("L", resized.size, 255)
    if plan.feather:
        draw = ImageDraw.Draw(mask)
        for inset in range(plan.feather):
            t = inset / plan.feather
            alpha = round(255 * t * t * (3 - 2 * t))
            draw.rectangle(
                (inset, inset, resized.width - 1 - inset, resized.height - 1 - inset), outline=alpha
            )
    generated.paste(resized, (plan.left, plan.top), mask)
    # Validate the entire protected core, not just the subject rectangle.
    f = plan.feather
    core = (f, f, resized.width - f, resized.height - f)
    result_core = generated.crop(
        (plan.left + f, plan.top + f, plan.left + resized.width - f, plan.top + resized.height - f)
    )
    if ImageChops.difference(resized.crop(core), result_core).getbbox() is not None:
        raise ValueError("原图保护区域校验失败，未发布构图候选")
    output = BytesIO()
    generated.save(output, format="PNG")
    audit = {
        **plan.audit(),
        "protected_region_max_pixel_difference": 0,
        "model_output_size": list(raw_size),
        "lossless_output": True,
    }
    return output.getvalue(), audit


def outpaint_prompt(plan: ReframePlan) -> str:
    return (
        "本次任务仅为整图缩放后的环境扩图，不是重新拍摄或重新绘制主体。"
        f"输出画幅 {plan.width}×{plan.height}。输入中原照片区域为像素矩形："
        f"左 {plan.left}，上 {plan.top}，宽 {plan.scaled_width}，高 {plan.scaled_height}。"
        "只把原照片四周的浅灰色空白连续补全成同一个真实场景。"
        "原照片中的人物、姿态、脸、衣服、全部景物及其尺寸位置完全保持不变。"
        "延续原照片的建筑结构、透视消失点、地面纹理、天空、自然光向、阴影、"
        "色彩、锐度与噪点；接缝自然。整图是一个连续画面，没有边框或画中画。"
        "不得放大主体、移动主体、重新取景、裁切、增加前景人物、文字或水印。"
        "不要将灰色空白保留为墙面、边框或纯色块。"
    )
