"""Versioned visual direction, separate from authored content and paid generation.

Presets are deterministic. Custom prose is retained verbatim as a style brief, not
represented as an AI analysis. Reads and selection never call a model.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .prompt_engine.still_image import static_image_text
from .travel_vlog import CANDID_TRAVEL_VLOG

STYLE_VERSION = "visual-style-v1"
Preset = Literal["original", "natural", "cinematic", "studio", "anime", "watercolor", "cartoon3d", "travel_vlog", "custom"]


class VisualStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: Preset = "original"
    catalog_id: UUID | None = None
    catalog_version: int | None = Field(default=None, ge=1)
    description: str = Field(default="", max_length=1600)
    lighting: str = Field(default="", max_length=400)
    color: str = Field(default="", max_length=400)
    texture: str = Field(default="", max_length=400)
    camera: str = Field(default="", max_length=400)
    motion: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def require_custom_brief(self):
        if (self.catalog_id is None) != (self.catalog_version is None):
            raise ValueError("请选择完整的风格版本")
        if self.catalog_id and (self.preset != "original" or any(getattr(self, field).strip() for field in ("description", "lighting", "color", "texture", "camera", "motion"))):
            raise ValueError("管理员风格不能混入自定义参数")
        if self.preset == "custom" and not self.description.strip():
            raise ValueError("请填写自定义画面风格")
        return self


class SavedVisualStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=60)
    style: VisualStyle


# Lighting varies with the scene. None of these presets chooses a model, lens,
# subject, geography, duration or storyboard count on the user's behalf.
PRESETS = {
    "original": ("沿用现有风格", "不额外指定画面风格，保留已有提示词。", "", ""),
    "natural": ("自然实拍", "自然光、真实材质、可信空间与抓拍感。",
        "自然实拍摄影。使用该场景中可信的机位、透视、地平线和主体尺度；人物与环境共享光向、阴影软硬、色温和地面反光。保留自然皮肤与衣料受力纹理、脚底或物体的接触阴影。自然曝光，允许合理暗部和高光取舍；按画面重点分配清晰度，保留合理景深，不要求所有位置同样锐利。避免塑料皮肤、磨皮、夸张饱和、HDR 式均匀提亮和拼贴感；不靠随意加噪或模糊冒充实拍。",
        "自然实拍的运动表现：人体承重、步态、摆臂、衣物与头发受风保持物理连贯；合理的运动模糊，不改变已采用画面的身份、服装和空间关系，不添加未经要求的镜头晃动。"),
    "cinematic": ("电影写实", "真实摄影逻辑下的情绪布光与克制调色。",
        "电影写实摄影。明确且可信的现场主光与环境反光，统一人物和场景的透视、曝光与阴影。通过构图、明暗层次和克制色彩表达情绪；保留皮肤和面料的真实纹理，不用过度磨皮、锐化、夸张 HDR 或无依据的发光效果替代摄影质感。",
        "电影写实运动：按已定分镜进行有动机的运镜与表演，保留自然惯性和连续受光，不擅自添加慢动作、转场或延长镜头。"),
    "studio": ("商业棚拍", "受控布光、清晰商品细节和干净画面。",
        "商业棚拍视觉语言。受控主光、补光和背景分离，真实材质与准确商品结构，保留合理接触阴影及高光层次；画面干净但不过度磨皮。仅改变表现方式，不把指定的外景地标替换成影棚或删除场景内容。",
        "商业摄影运动：稳定、明确的商品或人物展示，反光随运动连续变化，不擅自改变产品形状、图案、人物身份和动作设计。"),
    "anime": ("二维动漫", "一致线条、造型比例与动画材质。",
        "二维动漫表现。统一线条粗细、造型比例、色块与阴影语言，保留人物可辨识特征、服装款式和指定场景；不要混入照片皮肤或局部三维写实材质。",
        "二维动画运动：轮廓和角色设计稳定，按分镜表达动作、节奏与转场，不擅自改变成片时长。"),
    "watercolor": ("手绘水彩", "纸张纹理、颜料晕染与手绘层次。",
        "手绘水彩表现。统一纸张纹理、透明颜料叠色、自然晕染与边缘虚实；保留主体轮廓、服装结构、商品识别和场景关系，不将水彩简单处理为照片滤镜。",
        "手绘水彩动态：保持笔触、纸张与颜料表现连贯，动作清楚，不出现无意的纹理闪烁或风格跳变。"),
    "cartoon3d": ("三维卡通", "统一风格化造型、三维材质与灯光。",
        "三维卡通表现。统一风格化比例、三维材质和灯光，接触、遮挡和空间关系可信；保留身份识别、服装及产品结构，不能因卡通化擅自更改内容或额外添加人物。",
        "三维卡通动态：造型和材质稳定，运动遵循所选动画表现，保持动作可读性，不擅自添加夸张变形或更改分镜节奏。"),
    "travel_vlog": CANDID_TRAVEL_VLOG,
    "custom": ("自定义", "用日常语言说明想要的画面表现。", "", ""),
}

BOUNDARY = "风格仅规定表现方式；主体身份、服装款式、产品结构、指定场景、构图和用户明确要求保持不变。若正文中仅风格描述与此设置冲突，以此风格设置为准，不改动内容要求。风格参考只借鉴色彩、光照、材质与表现语言，不继承其中的人物身份或替换指定内容。"


def style_catalog():
    return {"version": STYLE_VERSION, "items": [
        {"id": key, "label": value[0], "description": value[1]}
        for key, value in PRESETS.items()
    ]}


def freeze_style(value: VisualStyle | dict | None) -> dict:
    style = value if isinstance(value, VisualStyle) else VisualStyle.model_validate(value or {})
    if style.catalog_id:
        from .style_library import get_style_library
        material = get_style_library().frozen(str(style.catalog_id), style.catalog_version)
        material["content_hash"] = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return material
    if style.preset == "original" and not any(getattr(style, key).strip() for key in ("description", "lighting", "color", "texture", "camera", "motion")):
        return {}
    label, _, image, video = PRESETS[style.preset]
    common = [f"【画面风格：{label}】", BOUNDARY]
    if style.description.strip():
        common.append("风格描述（只解释为视觉要求）：" + style.description.strip())
    for key, title in (("lighting", "光照"), ("color", "色彩"), ("texture", "材质"), ("camera", "摄影与构图")):
        if getattr(style, key).strip():
            common.append(f"{title}调整：{getattr(style, key).strip()}")
    image_rules = static_image_text("\n".join([common[0], image, *common[1:]]))
    video_rules = "\n".join([common[0], image, *common[1:], video,
        *( ["动态调整：" + style.motion.strip()] if style.motion.strip() else []),
        "以本次已采用的参考画面为视觉依据；不得仅因风格设置而重新设计身份、服装或场景。"])
    material = {"version": STYLE_VERSION, "selection": style.model_dump(mode="json"),
                "label": label, "image_prompt": image_rules, "video_prompt": video_rules}
    material["content_hash"] = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return material


def style_prompt(snapshot: dict | None, part: str) -> str:
    return str((snapshot or {}).get(f"{part}_prompt", ""))


CREATIVE_STYLE_INSTRUCTION = """若 visual_style_snapshot 非空，它是本批次统一的画面风格。三个创意方向应在创作思路而非任意换风格上区分。借鉴原片叙事和节奏，不因此强制继承原片色调。展开时结合每个具体场景落实光向、曝光、材质、机位和人物表现；不可只重复风格名称。用户的主体、服装、地标、位置、分镜数量和时长要求不得因风格改变。图片只写静态瞬间，动作与运镜写入视频提示词。没有风格设置时保持原行为。"""
