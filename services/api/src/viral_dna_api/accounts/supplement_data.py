"""Strict, dependency-free contracts for an incremental account supplement."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID

from .installation_bundle import connect, fail, inventory, portable_name
from .workspace_layout import checked_path, io_path

FORMAT = "ViralDNA account supplement"
VERSION = 1
KEY_NAMES = frozenset({"DASHSCOPE_API_KEY", "ARK_API_KEY", "MINIMAX_API_KEY", "GEMINI_API_KEY"})
MEDIA_NAMES = frozenset(
    {"asset.json", "source.bin", "preview.mp4", "preview.webp", "first-frame.jpg"}
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def uuid_text(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        fail("ID 必须为标准 UUID")
    return value


def read_bytes(path):
    path = io_path(checked_path(path))
    if path.exists() and not path.is_file():
        fail("预期文件位置被目录占用，未修改")
    return path.read_bytes() if path.is_file() else None


def decode(data):
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        fail("补充数据必须是 JSON 对象")
    return value


def read_json(path):
    raw = read_bytes(path)
    if raw is None:
        fail("补充数据文件缺失")
    return decode(raw)


def account_ids(settings):
    with closing(connect(settings.auth)) as db:
        rows = db.execute("SELECT id FROM auth_accounts").fetchall()
    ids = {uuid_text(row[0]) for row in rows}
    if not ids:
        fail("补充导入只适用于已有账户的服务器，不能代替初始化")
    return ids


def profiles(value):
    if value.get("schema_version") != 1 or not isinstance(value.get("profiles"), list):
        fail("品类库格式或版本不受支持")
    seen, names = set(), set()
    for item in value["profiles"]:
        if not isinstance(item, dict):
            fail("品类档案格式错误")
        identity = uuid_text(item.get("id"))
        aid = uuid_text(item.get("account_id"))
        if identity in seen:
            fail("品类档案 ID 重复")
        seen.add(identity)
        allowed = {
            "id",
            "account_id",
            "revision",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
            "deleted_at",
            "display_name",
            "category_name",
            "brand_name",
            "brief",
            "audiences",
            "selling_points",
            "scenes",
            "forbidden_claims",
            "visual_style",
        }
        if not set(item).issubset(allowed):
            fail("品类档案包含未知字段")
        for field in ("display_name", "category_name", "brief", "created_at", "updated_at"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                fail("品类档案缺少必填字段")
        if type(item.get("revision")) is not int or item["revision"] < 1:
            fail("品类档案版本无效")
        for field, limit in {
            "display_name": 80,
            "category_name": 80,
            "brief": 240,
            "brand_name": 120,
            "visual_style": 500,
        }.items():
            field_value = item.get(field)
            if field_value is not None and (
                not isinstance(field_value, str) or len(field_value) > limit
            ):
                fail("品类文本字段过长或格式错误")
        for field in ("created_at", "updated_at", "last_used_at", "deleted_at"):
            if item.get(field) is not None:
                datetime.fromisoformat(item[field])
        usage = item.get("usage_count", 0)
        if type(usage) is not int or usage < 0:
            fail("品类使用次数无效")
        for field in ("audiences", "selling_points"):
            if not isinstance(item.get(field), list) or not item[field]:
                fail("品类档案缺少人群或卖点")
            if any(not isinstance(text, str) or not text.strip() for text in item[field]):
                fail("品类档案内容格式错误")
        for field, limit in {
            "audiences": 12,
            "selling_points": 16,
            "scenes": 16,
            "forbidden_claims": 20,
        }.items():
            values = item.get(field, [])
            if (
                not isinstance(values, list)
                or len(values) > limit
                or any(not isinstance(text, str) for text in values)
            ):
                fail("品类列表字段格式错误")
        if not item.get("deleted_at"):
            key = (aid, "".join(item["display_name"].split()).casefold())
            if key in names:
                fail("同一账户包含重复的有效品类名称")
            names.add(key)
    return value


def presentation(value):
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "viraldna.skill-presentation/v1"
    ):
        fail("Skill 展示配置版本不受支持")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > 1:
        fail("Skill 展示项格式错误")
    if type(value.get("revision")) is not int or value["revision"] < 0:
        fail("Skill 展示版本无效")
    if not items:
        if value.get("primary_item_id"):
            fail("空展示配置不能引用封面")
        return set()
    item = items[0]
    if not isinstance(item, dict) or not set(item).issubset(
        {"id", "image_asset_id", "video_asset_id", "poster_asset_id", "sort_order"}
    ):
        fail("Skill 展示项含未知字段")
    if type(item.get("sort_order", 0)) is not int or item.get("sort_order", 0) < 0:
        fail("Skill 展示排序无效")
    if uuid_text(item.get("id")) != value.get("primary_item_id"):
        fail("Skill 主展示项引用无效")
    if not (item.get("image_asset_id") or item.get("video_asset_id")):
        fail("Skill 展示项没有媒体")
    return {
        uuid_text(item[field])
        for field in ("image_asset_id", "video_asset_id", "poster_asset_id")
        if item.get(field)
    }


def canonical_presentation(value):
    # Computed URLs and transport serialization are not editable state.
    result = {
        key: copy.deepcopy(value.get(key))
        for key in ("schema_version", "revision", "primary_item_id", "items")
    }
    result["items"] = [
        {
            "id": item["id"],
            "image_asset_id": item.get("image_asset_id"),
            "video_asset_id": item.get("video_asset_id"),
            "poster_asset_id": item.get("poster_asset_id"),
            "sort_order": item.get("sort_order", 0),
        }
        for item in value["items"]
    ]
    return result


def media_graph(root, displays):
    """Return only ready, complete assets reachable from selected Skill presentations."""
    selected, owners, metadata_by_id = {}, {}, {}
    for display in displays:
        sid = display["skill_id"]
        pending = list(presentation(display["presentation"]))
        while pending:
            identity = pending.pop()
            if identity in selected:
                if owners[identity] != sid:
                    fail("封面媒体不能跨 Skill 引用")
                continue
            folder = checked_path(root / identity)
            if not io_path(folder).is_dir():
                fail("Skill 展示媒体缺失")
            metadata = read_json(folder / "asset.json")
            if (
                metadata.get("id") != identity
                or metadata.get("skill_id") != sid
                or metadata.get("status") != "ready"
                or metadata.get("kind") not in {"image", "video"}
            ):
                fail("Skill 媒体未完成或归属不符，请先完成封面处理")
            if not isinstance(metadata.get("original_filename"), str):
                fail("Skill 媒体缺少原文件名称")
            for field in ("created_at", "updated_at"):
                datetime.fromisoformat(metadata[field])
            entries = inventory(folder, hashes=True)
            if not set(entries).issubset(MEDIA_NAMES):
                fail("Skill 媒体目录含未知文件")
            preview = "preview.mp4" if metadata["kind"] == "video" else "preview.webp"
            if preview not in entries or entries[preview]["bytes"] == 0:
                fail("Skill 预览文件缺失")
            if metadata.get("source_size", 0) or metadata["kind"] == "video":
                source = entries.get("source.bin", {})
                if source.get("bytes") != metadata.get("source_size") or source.get(
                    "sha256"
                ) != metadata.get("source_sha256"):
                    fail("Skill 原始文件校验失败")
            for link in ("poster_asset_id", "parent_asset_id"):
                if metadata.get(link):
                    pending.append(uuid_text(metadata[link]))
            selected[identity], owners[identity] = entries, sid
            metadata_by_id[identity] = metadata
    for display in displays:
        for item in display["presentation"]["items"]:
            for field, kind in (
                ("image_asset_id", "image"),
                ("video_asset_id", "video"),
                ("poster_asset_id", "image"),
            ):
                if item.get(field) and metadata_by_id[item[field]]["kind"] != kind:
                    fail("Skill 展示引用的媒体类型不匹配")
            if item.get("video_asset_id"):
                video = metadata_by_id[item["video_asset_id"]]
                poster_id = video.get("poster_asset_id")
                if (
                    not poster_id
                    or poster_id != item.get("poster_asset_id")
                    or metadata_by_id[poster_id].get("parent_asset_id") != video["id"]
                ):
                    fail("Skill 视频与首帧封面引用不完整")
    for metadata in metadata_by_id.values():
        for field, kind in (("poster_asset_id", "image"), ("parent_asset_id", "video")):
            if metadata.get(field) and metadata_by_id[metadata[field]]["kind"] != kind:
                fail("Skill 媒体的封面或父资源类型不匹配")
    return selected


def verify_bundle(bundle: Path, expected_digest=None, *, allow_pending=False):
    bundle = checked_path(bundle)
    proper_name = bundle.name.endswith(".vdna-supplement")
    if allow_pending and ".vdna-supplement.pending-" in bundle.name:
        uuid_text(bundle.name.split(".vdna-supplement.pending-", 1)[1])
        proper_name = True
    if not proper_name or not io_path(bundle).is_dir():
        fail("请选择已解压的 .vdna-supplement 目录")
    manifest_raw = read_bytes(bundle / "manifest.json")
    if manifest_raw is None:
        fail("补充包缺少清单")
    checksum = digest(manifest_raw)
    if expected_digest and checksum != expected_digest:
        fail("补充包清单摘要不一致")
    manifest = decode(manifest_raw)
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        fail("补充包格式或版本不受支持")
    uuid_text(manifest.get("id"))
    aids = manifest.get("account_ids")
    if not isinstance(aids, list) or not aids or len(aids) != len(set(aids)):
        fail("账户清单无效")
    for aid in aids:
        uuid_text(aid)
    entries = inventory(bundle, hashes=True)
    entries.pop("manifest.json", None)
    if entries != manifest.get("files"):
        fail("补充包缺失、增加或修改了文件")
    for name in entries:
        portable_name(name)
        parts = name.split("/")
        if name in {"category-profiles.json", "presentations.json", "model-keys.vdna-secrets"}:
            continue
        if len(parts) != 3 or parts[0] != "media" or parts[2] not in MEDIA_NAMES:
            fail("补充包包含范围外文件")
        uuid_text(parts[1])
    categories = profiles(read_json(bundle / "category-profiles.json"))
    if any(item["account_id"] not in aids for item in categories["profiles"]):
        fail("补充包包含未登记账户的品类")
    displays = read_json(bundle / "presentations.json").get("items")
    if not isinstance(displays, list):
        fail("展示清单无效")
    if any(not isinstance(item, dict) for item in displays):
        fail("展示项必须为对象")
    sids = [item.get("skill_id") for item in displays]
    if any(not isinstance(sid, str) or not sid for sid in sids) or len(sids) != len(set(sids)):
        fail("展示清单 Skill ID 无效或重复")
    selected = media_graph(bundle / "media", displays)
    expected_media = {f"media/{aid}/{name}" for aid, files in selected.items() for name in files}
    if expected_media != {name for name in entries if name.startswith("media/")}:
        fail("补充包包含未被展示引用的媒体")
    return manifest, categories, displays, selected, checksum


def merge_profiles(target, source):
    result = copy.deepcopy(profiles(target))
    existing = {item["id"]: item for item in result["profiles"]}
    names = {
        (item["account_id"], "".join(item["display_name"].split()).casefold())
        for item in result["profiles"]
        if not item.get("deleted_at")
    }
    actions, conflicts = [], []
    for item in source["profiles"]:
        old = existing.get(item["id"])
        key = (item["account_id"], "".join(item["display_name"].split()).casefold())
        if old is not None and canonical_profile(old) == canonical_profile(item):
            continue
        if old is not None or (not item.get("deleted_at") and key in names):
            conflicts.append({"kind": "category", "id": item["id"], "reason": "target_differs"})
            continue
        result["profiles"].append(copy.deepcopy(item))
        existing[item["id"]] = item
        if not item.get("deleted_at"):
            names.add(key)
        actions.append(item["id"])
    return result, actions, conflicts


def canonical_profile(value):
    result = copy.deepcopy(value)
    for key, default in {
        "brand_name": None,
        "visual_style": None,
        "scenes": [],
        "forbidden_claims": [],
        "usage_count": 0,
        "last_used_at": None,
        "deleted_at": None,
    }.items():
        result.setdefault(key, default)
    for key in ("created_at", "updated_at", "last_used_at", "deleted_at"):
        if result.get(key):
            result[key] = datetime.fromisoformat(result[key]).isoformat()
    return result


def env_values(raw):
    """Parse a captured snapshot using the application's .env rules."""
    result = {}
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def merge_env(original, updates):
    lines = original.decode("utf-8-sig").splitlines()
    output, written = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key not in updates:
            output.append(line)
        elif key not in written:
            output.append(f"{key}={updates[key]}")
            written.add(key)
    for key in sorted(set(updates) - written):
        output.append(f"{key}={updates[key]}")
    return ("\n".join(output).rstrip("\n") + "\n").encode("utf-8")


def validated_keys(value):
    if value.get("format") != "ViralDNA model keys" or value.get("version") != 1:
        fail("模型密钥包格式不受支持")
    keys = value.get("keys")
    if not isinstance(keys, dict) or not set(keys).issubset(KEY_NAMES):
        fail("模型密钥包包含范围外配置")
    for text in keys.values():
        if not isinstance(text, str) or not text.strip() or len(text) > 16384:
            fail("模型密钥格式无效")
        if any(character in text for character in ("\r", "\n", "\0")):
            fail("模型密钥包含非法字符")
    return keys
