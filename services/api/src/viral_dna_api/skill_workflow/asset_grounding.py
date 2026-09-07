"""Conservative, ID-scoped asset choices produced together with shot authoring."""

from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

from pydantic import BaseModel, Field

from ..models import PromptAssetMention


class AuthoredAssetReference(BaseModel):
    asset_usage_id: str = ""
    asset_name: str = ""
    purpose: str = Field(default="", max_length=500)
    certain: bool = False


def asset_label(asset: dict) -> str:
    return f"{asset.get('folder_name') or '未分类'}/{asset.get('name') or '参考资产'}"


def uninformative_name(name: str) -> bool:
    stem = re.sub(r"\.(png|jpe?g|webp|gif)$", "", name.strip(), flags=re.I)
    return bool(
        re.fullmatch(
            r"(?:图片|产品图|素材|参考图|未命名|image|img|photo|dsc|screenshot)[\s_\-\d（）()]*",
            stem,
            flags=re.I,
        )
    )


def select_shot_assets(choices, facts: list[dict], *, required_ids=()):
    """Never rotate/pad. Confidence alone cannot bypass ID/name/eligibility checks."""
    candidates = {str(item["id"]): item for item in facts if item.get("image_eligible")}
    labels = Counter(asset_label(item).casefold() for item in candidates.values())
    names = Counter(item["name"].casefold() for item in candidates.values())
    selected, seen = [], set()
    for usage_id in required_ids:
        item = candidates.get(str(usage_id))
        if item and item["id"] not in seen:
            selected.append((item, "用户指定的画面参考"))
            seen.add(item["id"])
    for choice in choices:
        item = candidates.get(str(choice.asset_usage_id))
        if not item or item["id"] in seen or not choice.certain or not choice.purpose.strip():
            continue
        name, label = item["name"].casefold(), asset_label(item).casefold()
        supplied = choice.asset_name.strip().casefold()
        if supplied not in {name, label} or uninformative_name(item["name"]):
            continue
        if labels[label] > 1 or (names[name] > 1 and supplied != label):
            continue
        selected.append((item, choice.purpose.strip()))
        seen.add(item["id"])
    return selected


def compile_asset_references(prompt: str, selected):
    mentions = [
        PromptAssetMention(
            reference_asset_id=UUID(item["asset_id"]),
            label=asset_label(item),
        )
        for item, _ in selected
    ]
    if not mentions:
        return prompt, mentions
    lines = [
        f"参考 @{mention.label}，用于{purpose}。"
        for mention, (_, purpose) in zip(mentions, selected, strict=True)
    ]
    return "【参考素材】" + "\n".join(lines) + "\n\n" + prompt, mentions
