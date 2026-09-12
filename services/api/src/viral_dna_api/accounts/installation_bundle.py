"""Portable, offline account bundles. Standard library only; never imports the API."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from ..runtime_config import read_local_env
from ..schema import WORKSPACE_SCHEMA_VERSION
from .workspace_layout import (
    WorkspaceLayoutError,
    _digest,
    _files,
    _is_database,
    backup_database,
    checked_path,
    io_path,
    read_identity,
)

FORMAT = "ViralDNA offline accounts"
VERSION = 1
TRANSIENT_AUTH = (
    "auth_sessions",
    "auth_invitations",
    "auth_login_attempts",
    "project_edit_leases",
    "auth_storage_tokens",
)
TASK_TABLES = {
    "generation_runs",
    "model_runs",
    "analyses",
    "skill_runs",
    "skill_step_runs",
    "depth_control_jobs",
    "video_enhancement_jobs",
    "image_batches",
    "video_clip_preparations",
    "video_provider_tasks",
}
ACTIVE_STATUSES = {"queued", "running", "pending", "submitted", "processing", "uploading"}
NOT_PORTABLE = (
    "平台 Cookie、OSS/同步 DPAPI 凭据和本机模型授权需在正式机重新配置",
    "不包含 .env、IIS、服务、工具、平台级模型/Skill/通知配置；已有项目快照随工作区保留",
    "账号密码保留；旧会话、邀请链接、编辑锁和同步令牌失效",
)


def fail(message):
    raise WorkspaceLayoutError(message)


def identifier(value):
    parsed = str(UUID(str(value)))
    if parsed != value:
        fail("账户/工作区 ID 必须是标准 UUID")
    return parsed


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path):
    value = json.loads(checked_path(path).read_text("utf-8-sig"))
    if not isinstance(value, dict):
        fail("JSON 必须是对象")
    return value


def connect(path, *, writable=False):
    path = checked_path(path)
    if not path.is_file():
        fail(f"数据库不存在，不会创建空库：{path}")
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True)
    db.row_factory = sqlite3.Row
    return db


def tables(db):
    return {
        r[0]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not r[0].startswith("sqlite_")
    }


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def healthy(db):
    if [tuple(r) for r in db.execute("PRAGMA quick_check")] != [("ok",)]:
        fail("数据库完整性检查失败")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        fail("数据库外键检查失败")
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1"
    ).fetchone():
        fail("迁移不接受包含自定义触发器或视图的数据库")


def auth_schema(db):
    """Compare to this checkout's schema without importing runtime dependencies."""
    module = ast.parse(Path(__file__).with_name("repository.py").read_text("utf-8-sig"))
    schema = next(
        ast.literal_eval(n.value)
        for n in module.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SCHEMA" for t in n.targets)
    )
    with closing(sqlite3.connect(":memory:")) as expected:
        expected.executescript(schema)
        if tables(db) != tables(expected):
            fail("身份库结构与当前工具不兼容，请先统一两端代码版本")
        for name in tables(expected):
            actual = [tuple(r) for r in db.execute(f"PRAGMA table_info({quote(name)})")]
            if actual != expected.execute(f"PRAGMA table_info({quote(name)})").fetchall():
                fail("身份库字段与当前工具不兼容")
    healthy(db)


def accounts_in(path):
    with closing(connect(path)) as db:
        auth_schema(db)
        admins = db.execute("SELECT username FROM auth_admins").fetchall()
        if len(admins) != 1 or admins[0][0] != "admin":
            fail("来源必须已经完成账户初始化且只有一个 admin")
        accounts = [dict(r) for r in db.execute("SELECT * FROM auth_accounts ORDER BY id")]
        if not accounts:
            fail("来源没有账户")
        for item in accounts:
            for field in ("id", "workspace_id", "location_id"):
                identifier(item[field])
            if (
                db.execute(
                    "SELECT count(*) FROM auth_users WHERE account_id=? AND role='owner'",
                    (item["id"],),
                ).fetchone()[0]
                != 1
            ):
                fail("账户缺少唯一负责人")
            runtime = db.execute(
                "SELECT device_id FROM auth_account_runtime WHERE account_id=?", (item["id"],)
            ).fetchone()
            if not runtime:
                fail("账户缺少运行身份，请先用兼容版本启动来源并完成初始化")
            identifier(runtime[0])
            item["device_id"] = runtime[0]
            item["users"] = db.execute(
                "SELECT count(*) FROM auth_users WHERE account_id=?", (item["id"],)
            ).fetchone()[0]
    return accounts


@dataclass(frozen=True)
class Settings:
    auth: Path
    catalog: Path
    accounts: Path
    legacy: Path | None = None

    @classmethod
    def from_env(cls, path, *, target=False):
        path = checked_path(path)
        if not path.is_file():
            fail("指定的环境配置文件不存在")
        values = read_local_env(path)
        if values.get("VIRAL_DNA_AUTH_MODE", "password").strip().lower() != "password":
            fail("只支持 password 账户模式")
        keys = (
            "VIRAL_DNA_AUTH_DB_PATH",
            "VIRAL_DNA_ACCOUNT_CATALOG_PATH",
            "VIRAL_DNA_ACCOUNTS_ROOT",
        )
        if target and any(not values.get(k) for k in keys):
            fail("正式端配置必须明确指定 AUTH_DB_PATH、ACCOUNT_CATALOG_PATH 和 ACCOUNTS_ROOT")
        appdata = os.getenv("LOCALAPPDATA", "") or os.getenv("APPDATA", "")
        default = Path(appdata) / "ViralDNA" if appdata else path.parent / ".viraldna"
        catalog = Path(values.get(keys[1]) or default / "account-catalog.json")
        auth = Path(values.get(keys[0]) or catalog.parent / "accounts.sqlite3")
        root = Path(values.get(keys[2]) or catalog.parent / "accounts")
        legacy = values.get("VIRAL_DNA_WORKSPACE_ROOT") or values.get("VIRAL_DNA_STORAGE_ROOT")
        paths = (auth, catalog, root) + ((Path(legacy),) if legacy else ())
        if any(not p.is_absolute() for p in paths):
            fail("迁移配置路径必须为绝对路径；请使用专用配置文件明确填写实际位置")
        return cls(*(checked_path(p) for p in paths))


def portable_name(name):
    if not isinstance(name, str) or not name or "\\" in name:
        fail("迁移包包含非法路径")
    parts = PurePosixPath(name).parts
    if PurePosixPath(name).is_absolute() or "/".join(parts) != name:
        fail("迁移包路径必须是规范相对路径")
    for part in parts:
        if (
            part in {".", ".."}
            or part.endswith((" ", "."))
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
        ):
            fail("迁移包包含越界路径、Windows 设备名或非法文件名")
    return name


def inventory(root, *, hashes=False):
    result = {}
    seen = set()
    for name, (directory, size, modified) in _files(root).items():
        portable_name(name)
        if name.casefold() in seen:
            fail("文件名大小写冲突，无法安全迁入 Windows")
        seen.add(name.casefold())
        if not directory:
            result[name] = (
                {"bytes": size, "sha256": _digest(root / name)} if hashes else (size, modified)
            )
    return result


def directory_names(root):
    return sorted(name for name, value in _files(root).items() if value[0])


def disjoint(paths):
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if first.is_relative_to(second) or second.is_relative_to(first):
                fail(f"来源、目标或备份路径相互包含：{first} / {second}")


@contextmanager
def frozen_sources(roots, files):
    """Catch changes spanning different account copies, not just within one copy."""
    with ExitStack() as stack:
        all_files = list(files)
        for root in roots:
            all_files += [root / name for name in inventory(root)]
        versions, sidecars = [], set()
        for path in all_files:
            if _is_database(path):
                db = stack.enter_context(closing(connect(path)))
                versions.append((db, db.execute("PRAGMA data_version").fetchone()[0]))
                sidecars.update(Path(str(path) + s) for s in ("-wal", "-shm", "-journal"))

        def state():
            result = {
                str(p): _digest(p) for p in files if p not in sidecars and not _is_database(p)
            }
            for root in roots:
                result[str(root) + ":names"] = sorted(
                    name for name in inventory(root) if root / name not in sidecars
                )
                result[str(root)] = {
                    name: info
                    for name, info in inventory(root).items()
                    if root / name not in sidecars and not _is_database(root / name)
                }
            return result

        before = state()
        yield
        if before != state() or any(
            db.execute("PRAGMA data_version").fetchone()[0] != version for db, version in versions
        ):
            fail("导出期间来源仍有写入，未发布迁移包；请停止全部 API 和写入任务后重试")


def code_fingerprint():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def snapshot_workspace(source, destination):
    """The enclosing bundle is already unpublished; avoid a second long staging path."""
    files = inventory(source)
    databases = {name for name in files if _is_database(source / name)}
    companions = {name + suffix for name in databases for suffix in ("-wal", "-shm", "-journal")}
    io_path(destination).mkdir(parents=True)
    for name, (directory, _, _) in _files(source).items():
        target = destination / name
        if directory:
            io_path(target).mkdir(parents=True, exist_ok=True)
        elif name not in companions:
            io_path(target.parent).mkdir(parents=True, exist_ok=True)
            if name in databases:
                backup_database(source / name, target)
                # A portable, closed snapshot has no WAL/SHM companions. This
                # also makes repeated read-only verification byte-for-byte stable.
                with closing(connect(target, writable=True)) as db:
                    db.execute("PRAGMA journal_mode=DELETE")
            else:
                shutil.copy2(
                    io_path(checked_path(source / name)), io_path(target), follow_symlinks=False
                )
                checked_path(target)
                if _digest(target) != _digest(source / name):
                    fail("复制校验失败，未发布迁移包")


def validate_workspace(root, account):
    marker = root / ".viraldna/workspace.json"
    if not marker.is_file():
        fail(f"来源工作区身份文件缺失：{root}")
    read_identity(root, account["id"], account["workspace_id"])
    database = root / ".viraldna/workspace.db"
    if not database.is_file():
        fail(f"工作区数据库缺失，请先核对该账户数据：{root}")
    with closing(connect(database)) as db:
        healthy(db)
        if "schema_migrations" not in tables(db):
            fail("工作区缺少版本信息，请先使用兼容应用升级来源数据")
        if (
            db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            != WORKSPACE_SCHEMA_VERSION
        ):
            fail("工作区数据库版本与迁移工具不一致")
        counts = {}
        for name in tables(db):
            counts[name] = db.execute(f"SELECT count(*) FROM {quote(name)}").fetchone()[0]
            if name in TASK_TABLES:
                columns = {r[1] for r in db.execute(f"PRAGMA table_info({quote(name)})")}
                if "payload" in columns:
                    for row in db.execute(f"SELECT payload FROM {quote(name)}"):
                        if json.loads(row[0]).get("status") in ACTIVE_STATUSES:
                            fail(f"账户仍有未结束任务（{name}），先等待或在原应用处理后再迁移")
        validate_objects(db, root, account)
    ledger = root / ".viraldna/durable-storage.sqlite3"
    if ledger.exists():
        with closing(connect(ledger)) as db:
            healthy(db)
            owner = db.execute("SELECT value FROM settings WHERE key='account_id'").fetchone()
            if not owner or owner[0] != account["id"]:
                fail("容量账本的账户归属不一致")
            for blob in db.execute("SELECT relative_path,size_bytes,sha256 FROM blobs"):
                path = checked_path(root / portable_name(blob[0]))
                if (
                    not path.is_relative_to(root)
                    or not io_path(path).is_file()
                    or io_path(path).stat().st_size != blob[1]
                ):
                    fail("容量账本登记的原件缺失或大小不一致")
                if _digest(path) != blob[2]:
                    fail("容量账本登记的原件校验失败")
    return counts


def validate_objects(db, root, account):
    """Do not call an export complete when active assets have only remote originals."""
    names = tables(db)
    if not {"storage_objects", "object_replicas"} <= names:
        fail("工作区缺少文件对象登记")
    objects = {
        v["id"]: v
        for row in db.execute("SELECT payload FROM storage_objects")
        for v in [json.loads(row[0])]
    }
    replicas = [json.loads(row[0]) for row in db.execute("SELECT payload FROM object_replicas")]
    for obj in objects.values():
        if obj.get("deleted_at"):
            continue
        if obj.get("workspace_id") != account["workspace_id"] or obj.get("account_id") not in (
            None,
            account["id"],
        ):
            fail("文件对象的账户/工作区归属不一致")
        candidates = [
            v
            for v in replicas
            if v.get("storage_object_id") == obj["id"]
            and v.get("storage_location_id") == account["location_id"]
            and v.get("state") == "available"
        ]
        found = False
        for replica in candidates:
            key = portable_name(replica["object_key"].replace("\\", "/"))
            path = checked_path(root / key)
            if (
                io_path(path).is_file()
                and io_path(path).stat().st_size == obj["size_bytes"]
                and _digest(path) == obj["sha256"]
            ):
                found = True
                break
        if not found:
            fail(f"文件对象 {obj['id']} 缺少已校验的本地原件；云端独有文件须先在来源补齐")
    if "assets" in names:
        for row in db.execute("SELECT payload FROM assets"):
            asset = json.loads(row[0])
            if asset.get("deleted_at"):
                continue
            if asset.get("workspace_id") != account["workspace_id"] or asset.get(
                "account_id"
            ) not in (None, account["id"]):
                fail("资产归属不一致")
            for field in ("content_object_id", "thumbnail_object_id"):
                if asset.get(field) not in objects or objects[asset[field]].get("deleted_at"):
                    fail("资产原件或缩略图索引缺失，未导出")


def validate_catalog(value):
    if value.get("schema_version") != 1:
        fail("账户目录版本不受支持")
    for key in ("accounts", "devices", "workspaces", "registrations", "storage_locations"):
        if not isinstance(value.get(key, []), list):
            fail("账户目录内容格式错误")
    return value


def verify_bundle(bundle, *, expected_digest=None):
    bundle = checked_path(bundle)
    raw = checked_path(bundle / "manifest.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        fail("迁移包清单 SHA-256 与测试端提供的值不同")
    manifest = read_json(bundle / "manifest.json")
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        fail("不是受支持的完整账户迁移包")
    if manifest.get("code_fingerprint") != code_fingerprint():
        fail("两端 API 源码不一致，请统一版本后重新导出/校验")
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        fail("迁移包没有文件清单")
    for name, item in entries.items():
        portable_name(name)
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] < 0
            or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256")))
        ):
            fail("迁移包文件清单格式错误")
    actual = inventory(bundle, hashes=True)
    actual.pop("manifest.json", None)
    if actual != entries:
        fail("迁移包缺少文件、增加了文件或文件内容发生变化")
    if manifest.get("directories") != directory_names(bundle):
        fail("迁移包目录结构发生变化")
    rows = accounts_in(bundle / "identity/accounts.sqlite3")
    listed = manifest.get("accounts")
    if not isinstance(listed, list) or rows != listed:
        fail("迁移包账户清单与身份数据库不一致")
    allowed = {"identity/accounts.sqlite3", "identity/account-catalog.json"}
    prefixes = tuple(f"accounts/{r['id']}/" for r in rows)
    if any(name not in allowed and not name.startswith(prefixes) for name in entries):
        fail("迁移包包含未登记账户或非业务文件")
    counts = {}
    for row in rows:
        counts[row["id"]] = validate_workspace(bundle / "accounts" / row["id"], row)
    validate_catalog(read_json(bundle / "identity/account-catalog.json"))
    return {
        "manifest_sha256": digest,
        "accounts": rows,
        "counts": counts,
        "bytes": sum(v["bytes"] for v in entries.values()),
        "files": len(entries),
    }
