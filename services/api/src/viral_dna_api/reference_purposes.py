"""Explicit per-use reference responsibilities, shared by prompt surfaces."""
from __future__ import annotations

from .models import ReferenceRole

SPATIAL_REFERENCE_INSTRUCTION = (
    "空间参考仅提供机位、景别、主体与环境的比例、画面位置和脚部落地关系；"
    "不继承其中的人物身份、服装、道具、具体背景、文字或黑边。"
    "主体身份与服装服从相应资产，地点与动作方向服从本次分镜内容。"
    "本次空间构图以空间参考为主要依据，不采用正文中与之冲突的旧人物占比、位置或机位默认描述。"
    "这是视觉引导而非像素级位置锁定。"
)

STYLE_REFERENCE_INSTRUCTION = (
    "仅参考现场光照、曝光、色彩、材质和成像质感；"
    "不继承参考图中的人物身份、服装、姿势、地标或构图。"
)


def scoped_bindings(bindings, mentions):
    """A shared shot binding can have different purposes in different frames."""
    roles = {item.reference_asset_id: item.role for item in mentions if item.role is not None}
    return [item.model_copy(update={"role": roles[item.reference_asset_id]})
            if item.reference_asset_id in roles else item for item in bindings]


def spatial_references(items):
    return [item for item in items if str(item.role) == ReferenceRole.SPATIAL.value]
