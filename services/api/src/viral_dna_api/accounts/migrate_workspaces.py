"""Offline account-directory migration. Preview by default; never removes sources.

Run with --help. This module deliberately does not import the API, workspace
manager, or AccountRepository (whose constructor initializes the auth schema).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ..runtime_config import read_local_env
from .workspace_layout import (
    WorkspaceLayoutError,
    account_workspace,
    backup_database,
    catalog_update,
    checked_path,
    layout_lock,
    provision_workspace,
    read_identity,
)
from .workspace_layout import (
    atomic_bytes as _atomic_bytes,
)


def _connect(path: Path, *, readonly=True):
    selected = checked_path(path)
    if not selected.is_file():
        raise WorkspaceLayoutError("身份数据库不存在；不会创建空数据库")
    db = sqlite3.connect(selected.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True)
    db.row_factory = sqlite3.Row
    return db


def migration_plan(auth_db: Path, accounts_root: Path, *, account_id=None):
    with closing(_connect(auth_db)) as db:
        rows = db.execute(
            "SELECT id,name,workspace_id,workspace_root FROM auth_accounts"
        ).fetchall()
    result = []
    for row in rows:
        if account_id is not None and row["id"] != str(UUID(str(account_id))):
            continue
        source = checked_path(Path(row["workspace_root"]))
        target = account_workspace(accounts_root, row["id"])
        result.append(
            {
                "account_id": row["id"],
                "account_name": row["name"],
                "workspace_id": row["workspace_id"],
                "source": str(source),
                "target": str(target),
                "status": "standard" if source == target else "needs_migration",
                "source_exists": source.is_dir(),
                "target_exists": target.exists(),
            }
        )
    if account_id is not None and not result:
        raise WorkspaceLayoutError("指定账户不存在")
    return result


def _catalog_update(path: Path | None, item):
    return catalog_update(path, item["workspace_id"], Path(item["source"]), Path(item["target"]))


def migrate_account(
    auth_db: Path,
    accounts_root: Path,
    *,
    account_id,
    expected_source: Path,
    catalog_path: Path | None = None,
    confirm_api_stopped=False,
):
    if not confirm_api_stopped:
        raise WorkspaceLayoutError("必须先停止 API 和所有写入任务，并显式确认停服")
    auth_db = checked_path(auth_db)
    with layout_lock(auth_db):
        item = migration_plan(auth_db, accounts_root, account_id=account_id)[0]
        if checked_path(expected_source) != Path(item["source"]):
            raise WorkspaceLayoutError("当前来源路径与确认值不同，请重新预览")
        if item["status"] == "standard":
            return {**item, "changed": False}
        source = Path(item["source"])
        if not source.is_dir() or not (source / ".viraldna" / "workspace.json").is_file():
            raise WorkspaceLayoutError("来源工作区或身份文件缺失，不能用空目录替代")
        read_identity(source, item["account_id"], item["workspace_id"])
        target = Path(item["target"])
        if target.exists():
            raise WorkspaceLayoutError("目标目录已存在，禁止覆盖或静默合并")
        if source.is_relative_to(target) or target.is_relative_to(source):
            raise WorkspaceLayoutError("来源和目标不能相互包含")
        for protected in (auth_db, catalog_path):
            if protected and checked_path(protected).is_relative_to(source):
                raise WorkspaceLayoutError("身份数据库与账户目录登记不能位于待迁移的工作区内部")
        original, updated = _catalog_update(catalog_path, item)
        backup = checked_path(
            auth_db.parent
            / "workspace-layout-backups"
            / (datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex)
        )
        backup.mkdir(parents=True, mode=0o700)
        backup_database(auth_db, backup / "accounts.sqlite3")
        if original is not None:
            (backup / "account-catalog.json").write_bytes(original)
        _atomic_bytes(
            backup / "migration.json",
            json.dumps(
                {
                    **item,
                    "state": "prepared",
                    "source_retained": True,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        catalog_changed = False
        with provision_workspace(
            accounts_root, item["account_id"], item["workspace_id"], source=source
        ) as destination:
            with closing(_connect(auth_db, readonly=False)) as db:
                try:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT workspace_root FROM auth_accounts WHERE id=?", (item["account_id"],)
                    ).fetchone()
                    if not row or checked_path(Path(row[0])) != source:
                        raise WorkspaceLayoutError("账户绑定在复制期间发生变化，未切换")
                    if original is not None:
                        if checked_path(catalog_path).read_bytes() != original:
                            raise WorkspaceLayoutError("账户目录登记被其他程序修改，未覆盖")
                        catalog_changed = True
                        _atomic_bytes(catalog_path, updated)
                    db.execute(
                        "UPDATE auth_accounts SET workspace_root=?,updated_at=? WHERE id=?",
                        (
                            str(destination),
                            time.time(),
                            item["account_id"],
                        ),
                    )
                    db.execute(
                        "INSERT INTO auth_audit VALUES(?,?,?,?,?,?)",
                        (
                            str(uuid4()),
                            "offline-maintenance",
                            "account_workspace_relocated",
                            item["account_id"],
                            str(backup),
                            time.time(),
                        ),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    if catalog_changed:
                        current = checked_path(catalog_path).read_bytes()
                        if current in (updated, original):
                            _atomic_bytes(catalog_path, original)
                        else:
                            raise WorkspaceLayoutError(
                                f"目录登记被外部程序再次修改，保留原件及备份，请人工核对：{backup}"
                            ) from None
                    raise
        result = {
            **item,
            "changed": True,
            "state": "completed",
            "backup": str(backup),
            "source_retained": True,
        }
        # Binding is already committed. A report-write error must not move back
        # the destination or claim the database transaction was rolled back.
        try:
            _atomic_bytes(
                backup / "migration.json",
                json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        except OSError:
            result["warning"] = "账户已切换，但完成报告写入失败；请核对备份与当前登记"
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--account-id", type=UUID)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-api-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        values = read_local_env(checked_path(args.env_file))
        names = (
            "VIRAL_DNA_AUTH_DB_PATH",
            "VIRAL_DNA_ACCOUNTS_ROOT",
            "VIRAL_DNA_ACCOUNT_CATALOG_PATH",
        )
        if any(not values.get(name) or not Path(values[name]).is_absolute() for name in names):
            raise WorkspaceLayoutError(
                "配置文件必须明确指定身份库、账户根目录及账户目录登记的绝对路径"
            )
        auth_db, root, catalog = (checked_path(Path(values[name])) for name in names)
        if args.apply:
            if args.account_id is None or args.source is None:
                raise WorkspaceLayoutError("实际迁移必须指定 --account-id 和预览中的 --source")
            result = migrate_account(
                auth_db,
                root,
                account_id=args.account_id,
                expected_source=args.source,
                catalog_path=catalog,
                confirm_api_stopped=args.confirm_api_stopped,
            )
        else:
            result = {
                "preview": True,
                "accounts": migration_plan(auth_db, root, account_id=args.account_id),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkspaceLayoutError, OSError, sqlite3.DatabaseError, ValueError) as exc:
        print(f"未完成迁移：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
