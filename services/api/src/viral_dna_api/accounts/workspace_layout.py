"""Canonical account paths and copy-first, identity-preserving workspace relocation.

No source files are removed. Callers must stop writers before relocating an
existing account, and publish the new database binding only after verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import time
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from uuid import UUID, uuid4


class WorkspaceLayoutError(RuntimeError):
    pass


def atomic_bytes(path: Path, content: bytes):
    checked_path(path)
    temporary = checked_path(path.with_name(f".{path.name}.{uuid4().hex}.tmp"))
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def catalog_update(path: Path | None, workspace_id, source: Path, target: Path):
    if path is None or not path.exists():
        return None, None
    original = checked_path(path).read_bytes()
    value = json.loads(original.decode("utf-8-sig"))
    if value.get("schema_version") != 1:
        raise WorkspaceLayoutError("账户目录版本不受支持，未修改登记")
    changed = False
    for entry in value.get("registrations", []):
        if entry.get("workspace_id") == str(workspace_id) and entry.get("local_root"):
            if checked_path(Path(entry["local_root"])) == source and source != target:
                entry["local_root"] = str(target)
                changed = True
    return original, (
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if changed
        else original
    )


@contextmanager
def relocate_catalog(path: Path | None, workspace_id, source: Path, target: Path):
    original, updated = catalog_update(path, workspace_id, source, target)
    changed = original is not None and original != updated
    try:
        if changed:
            if checked_path(path).read_bytes() != original:
                raise WorkspaceLayoutError("账户目录登记发生变化，未覆盖")
            atomic_bytes(path, updated)
        yield
    except BaseException:
        if changed and checked_path(path).read_bytes() in (original, updated):
            atomic_bytes(path, original)
        raise


def checked_path(path: Path) -> Path:
    """Reject links/junctions before resolve() can hide their real destination."""
    candidate = Path(os.path.abspath(path))
    for item in (*reversed(candidate.parents), candidate):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise WorkspaceLayoutError(f"工作区路径不能包含符号链接或目录联接：{item}")
    return candidate.resolve()


def account_workspace(root: Path, account_id: UUID | str) -> Path:
    parent = checked_path(root)
    if parent == Path(parent.anchor):
        raise WorkspaceLayoutError("账户根目录不能是磁盘根目录")
    target = checked_path(parent / str(UUID(str(account_id))))
    if target.parent != parent:
        raise WorkspaceLayoutError("账户路径超出指定根目录")
    return target


@contextmanager
def layout_lock(auth_database: Path, *, allow_incomplete_import=False):
    """Held for the API lifetime, or exclusively by the offline migration tool."""
    path = checked_path(auth_database).with_suffix(".workspace-layout.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if not path.stat().st_size:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WorkspaceLayoutError(
                "账户数据正在被 API 或迁移工具使用，请先停止本项目 API"
            ) from exc
        try:
            marker = checked_path(auth_database.with_suffix(".installation-migration.json"))
            if marker.exists() and not allow_incomplete_import:
                raise WorkspaceLayoutError(
                    "发现未完成的跨机账户导入；禁止启动 API，"
                    "请用 transfer-installation.py recover 预览恢复"
                )
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_identity(root: Path, account_id: UUID | str, workspace_id: UUID | str):
    marker = checked_path(root / ".viraldna" / "workspace.json")
    if not marker.is_file():
        return
    try:
        data = json.loads(marker.read_text("utf-8-sig"))
        if str(UUID(data["workspace_id"])) != str(workspace_id) or (
            data.get("account_id") and str(UUID(data["account_id"])) != str(account_id)
        ):
            raise ValueError("identity mismatch")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise WorkspaceLayoutError("工作区身份与账户登记不一致，未迁移任何绑定") from exc


def _files(root: Path):
    result = {}
    if not root.exists():
        return result
    if not root.is_dir():
        raise WorkspaceLayoutError("工作区必须是目录")
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            path = checked_path(Path(directory) / name)
            if not path.is_relative_to(root):
                raise WorkspaceLayoutError("文件超出工作区范围")
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise WorkspaceLayoutError("工作区包含不支持的特殊文件")
            result[path.relative_to(root).as_posix()] = (
                stat.S_ISDIR(info.st_mode),
                info.st_size,
                info.st_mtime_ns,
            )
    return result


def _digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _is_database(path: Path):
    with path.open("rb") as stream:
        return stream.read(16) == b"SQLite format 3\x00"


def backup_database(source: Path, target: Path):
    """SQLite backup includes committed WAL pages; never copy a live .db alone."""
    with closing(sqlite3.connect(checked_path(source).as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(target)) as writer:
            _backup(reader, writer)


def _backup(reader, writer):
    deadline = time.monotonic() + 120

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise WorkspaceLayoutError("数据库备份超时，请确认所有写入任务已经停止")

    reader.backup(writer, pages=256, progress=progress, sleep=0.05)
    if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise WorkspaceLayoutError("数据库副本校验失败，未切换账户目录")


@contextmanager
def provision_workspace(tenant_root: Path, account_id, workspace_id, *, source: Path | None = None):
    """Create a standard workspace, retaining failed copies rather than deleting data."""
    target = account_workspace(tenant_root, account_id)
    source = checked_path(source) if source is not None else None
    if source == target:
        read_identity(target, account_id, workspace_id)
        yield target
        return
    if source and (source.is_relative_to(target) or target.is_relative_to(source)):
        raise WorkspaceLayoutError("旧工作区与目标账户目录不能相互包含")
    if target.exists():
        raise WorkspaceLayoutError(f"目标账户目录已存在，不覆盖或合并：{target}")
    if source:
        read_identity(source, account_id, workspace_id)
    inventory = _files(source) if source else {}
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = checked_path(target.parent / f".layout-{account_id}-{uuid4().hex}.pending")
    stage.mkdir()
    published = False
    try:
        databases = {
            name
            for name, (directory, _, _) in inventory.items()
            if not directory and _is_database(source / name)
        }
        sidecars = {name + suffix for name in databases for suffix in ("-wal", "-shm", "-journal")}
        hashes = {}
        with ExitStack() as stack:
            readers = {}
            for name in databases:
                reader = sqlite3.connect((source / name).as_uri() + "?mode=ro", uri=True)
                stack.callback(reader.close)
                readers[name] = (reader, reader.execute("PRAGMA data_version").fetchone()[0])
            for name, (directory, _, _) in inventory.items():
                destination = stage / name
                if directory:
                    destination.mkdir(parents=True, exist_ok=True)
                elif name not in sidecars:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if name in readers:
                        with closing(sqlite3.connect(destination)) as writer:
                            _backup(readers[name][0], writer)
                    else:
                        shutil.copy2(source / name, destination)
                        hashes[name] = _digest(destination)
                        if hashes[name] != _digest(source / name):
                            raise WorkspaceLayoutError("文件在复制期间发生变化，请停止写入后重试")
            after = _files(source) if source else {}

            def ordinary(tree):
                return {
                    name: value
                    for name, value in tree.items()
                    if name not in sidecars and name not in databases and not value[0]
                }

            if set(after) - sidecars != set(inventory) - sidecars or ordinary(after) != ordinary(
                inventory
            ):
                raise WorkspaceLayoutError("工作区在复制期间发生变化，未切换账户目录")
            for reader, version in readers.values():
                if reader.execute("PRAGMA data_version").fetchone()[0] != version:
                    raise WorkspaceLayoutError("数据库仍有写入，未切换账户目录")
        metadata = stage / ".viraldna"
        metadata.mkdir(exist_ok=True)
        identity = metadata / "workspace.json"
        data = json.loads(identity.read_text("utf-8-sig")) if identity.exists() else {}
        data.update(account_id=str(account_id), workspace_id=str(workspace_id))
        identity.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        receipt = {
            "schema_version": 1,
            "account_id": str(account_id),
            "workspace_id": str(workspace_id),
            "source": str(source) if source else None,
            "target": str(target),
            "files_verified": len(hashes),
            "databases_verified": sorted(databases),
            "completed_at": time.time(),
            "source_retained": source is not None,
        }
        (metadata / "account-layout.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        checked_path(target)
        if target.exists():
            raise WorkspaceLayoutError("目标目录在复制期间出现，拒绝覆盖")
        stage.rename(target)
        published = True
        yield target
    except BaseException:
        if published:
            # Only the exact directory just published by this call; retain it.
            checked_path(target)
            if target.parent != checked_path(tenant_root):
                raise WorkspaceLayoutError("副本路径已变化，需要人工处理") from None
            target.rename(stage)
        raise
