"""Offline export/import for an uninitialized, empty server. No network or service control."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from .installation_bundle import (
    FORMAT,
    NOT_PORTABLE,
    TRANSIENT_AUTH,
    VERSION,
    Settings,
    accounts_in,
    auth_schema,
    code_fingerprint,
    connect,
    directory_names,
    disjoint,
    fail,
    frozen_sources,
    healthy,
    inventory,
    json_bytes,
    quote,
    read_json,
    snapshot_workspace,
    tables,
    validate_catalog,
    validate_workspace,
    verify_bundle,
)
from .workspace_layout import (
    WorkspaceLayoutError,
    _digest,
    atomic_bytes,
    backup_database,
    checked_path,
    layout_lock,
)


def timestamp():
    return datetime.now(UTC).isoformat()


def bundle_path(path):
    path = checked_path(path)
    if not path.name.endswith(".vdna-migration"):
        fail("迁移包目录名称必须以 .vdna-migration 结尾；不直接解压或执行 ZIP 内容")
    return path


def space_for(path, required):
    parent = path
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < required + 32 * 1024 * 1024:
        fail("磁盘剩余空间不足以保存完整副本与安全余量")


def source_plan(settings, bundle):
    bundle = bundle_path(bundle)
    if bundle.exists():
        fail("迁移包目录已存在，不覆盖；请使用新的名称")
    rows = accounts_in(settings.auth)
    roots = [checked_path(Path(row["workspace_root"])) for row in rows]
    broad = {Path(__file__).resolve().parents[5], Path.home().resolve()}
    if any(root == Path(root.anchor) or root in broad for root in roots):
        fail("工作区不能是磁盘根目录、用户主目录或源码根目录，请先核对绑定")
    disjoint([*roots, settings.auth, settings.catalog, bundle])
    if settings.legacy and settings.legacy not in roots and settings.legacy.exists():
        if any(settings.legacy.iterdir()):
            # Old retained copies are not merged into the current account binding.
            legacy_note = str(settings.legacy)
        else:
            legacy_note = None
    else:
        legacy_note = None
    catalog = validate_catalog(read_json(settings.catalog))
    bound = {r["workspace_id"] for r in rows}
    if any(
        w.get("id") not in bound and not w.get("deleted_at") for w in catalog.get("workspaces", [])
    ):
        fail("目录登记含未绑定当前账号的旧工作区，请先核对；本工具不会静默遗漏或合并它们")
    summaries = []
    total = settings.auth.stat().st_size + settings.catalog.stat().st_size
    for row, root in zip(rows, roots, strict=True):
        counts = validate_workspace(root, row)
        items = inventory(root)
        size = sum(v[0] for v in items.values())
        total += size
        summaries.append(
            {
                "account_id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "users": row["users"],
                "source": str(root),
                "files": len(items),
                "bytes": size,
                "records": counts,
            }
        )
    return {
        "preview": True,
        "auth_database": str(settings.auth),
        "catalog": str(settings.catalog),
        "bundle": str(bundle),
        "accounts": summaries,
        "estimated_bytes": total,
        "excluded_legacy_copy": legacy_note,
        "notes": list(NOT_PORTABLE),
    }


def export_bundle(settings, bundle, *, confirm_api_stopped=False, progress=lambda _: None):
    if not confirm_api_stopped:
        fail("实际导出必须确认已停止测试端全部 API 和写入任务")
    bundle = bundle_path(bundle)
    with layout_lock(settings.auth):
        plan = source_plan(settings, bundle)
        space_for(bundle.parent, plan["estimated_bytes"])
        stage = checked_path(bundle.with_name(bundle.name + ".pending-" + uuid4().hex))
        stage.mkdir(parents=True)
        (stage / "identity").mkdir()
        rows = accounts_in(settings.auth)
        roots = [checked_path(Path(r["workspace_root"])) for r in rows]
        progress("正在导出一致性副本；原数据不会修改")
        with frozen_sources(roots, [settings.auth, settings.catalog]):
            backup_database(settings.auth, stage / "identity/accounts.sqlite3")
            shutil.copy2(settings.catalog, stage / "identity/account-catalog.json")
            for index, (row, root) in enumerate(zip(rows, roots, strict=True), 1):
                progress(f"复制账户 {index}/{len(rows)}：{row['id']}")
                snapshot_workspace(root, stage / "accounts" / row["id"])
            # Revoke temporary credentials in the COPY, not the test server.
            with closing(connect(stage / "identity/accounts.sqlite3", writable=True)) as db:
                for table in TRANSIENT_AUTH:
                    db.execute(f"DELETE FROM {quote(table)}")
                db.commit()
                db.execute("PRAGMA journal_mode=DELETE")
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "created_at": timestamp(),
            "code_fingerprint": code_fingerprint(),
            "accounts": accounts_in(stage / "identity/accounts.sqlite3"),
            "notes": list(NOT_PORTABLE),
            "files": inventory(stage, hashes=True),
            "directories": directory_names(stage),
        }
        atomic_bytes(stage / "manifest.json", json_bytes(manifest))
        verified = verify_bundle(stage)
        if bundle.exists():
            fail("导出期间目标目录出现，未覆盖；副本保留在 pending 目录")
        stage.rename(bundle)
        progress("迁移包已发布，请单独保存 manifest_sha256，不要把迁移包提交到 Git")
        return {"exported": True, "bundle": str(bundle), **verified, "notes": list(NOT_PORTABLE)}


def target_layout(settings):
    for path in (settings.auth, settings.catalog, settings.accounts):
        if not path.is_absolute():
            fail("目标必须使用绝对路径")
        checked_path(path)
    base = settings.auth.parent
    if (
        base == Path(base.anchor)
        or settings.catalog.parent != base
        or settings.accounts.parent != base
        or settings.accounts.name != "accounts"
    ):
        fail("正式端身份库、目录登记和 accounts 必须位于同一专用数据目录")
    protected = [
        *role_paths(settings).values(),
        marker_path(settings),
        base / "installation-migrations",
    ]
    disjoint(protected)
    if settings.legacy:
        checked_path(settings.legacy)
        disjoint([*protected, settings.legacy])
    return base


def empty_target(settings):
    target_layout(settings)
    if not settings.auth.exists() and any(
        Path(str(settings.auth) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        fail("正式端存在没有主库的 SQLite 辅助文件，不能确认数据为空")
    if settings.auth.exists():
        with closing(connect(settings.auth)) as db:
            auth_schema(db)
            if any(db.execute(f"SELECT 1 FROM {quote(t)} LIMIT 1").fetchone() for t in tables(db)):
                fail("正式端身份库非空，拒绝覆盖或合并任何已有账户")
    if settings.accounts.exists():
        if not settings.accounts.is_dir() or any(settings.accounts.iterdir()):
            fail("正式端 accounts 非空，拒绝覆盖")
    if settings.catalog.exists():
        catalog = validate_catalog(read_json(settings.catalog))
        if any(
            catalog.get(k)
            for k in ("accounts", "workspaces", "devices", "registrations", "storage_locations")
        ) or any(
            catalog.get(k) for k in ("active_account_id", "active_workspace_id", "active_device_id")
        ):
            fail("正式端目录登记非空，请勿用本工具合并或覆盖")
    # Some older API imports create an empty legacy database before setup.
    if settings.legacy and settings.legacy.exists():
        for name in inventory(settings.legacy):
            if name in {".viraldna/workspace.db-wal", ".viraldna/workspace.db-shm"}:
                continue
            if name != ".viraldna/workspace.db":
                fail("正式端旧工作区含已有文件，不能确认是空服务器")
            with closing(connect(settings.legacy / name)) as db:
                healthy(db)
                if any(
                    db.execute(f"SELECT 1 FROM {quote(t)} LIMIT 1").fetchone()
                    for t in tables(db) - {"schema_migrations"}
                ):
                    fail("正式端旧工作区已有业务记录，拒绝导入")


def marker_path(settings):
    return checked_path(settings.auth.with_suffix(".installation-migration.json"))


def import_plan(settings, bundle, *, expected_digest=None):
    bundle = bundle_path(bundle)
    base = target_layout(settings)
    disjoint(
        [
            bundle,
            settings.auth,
            settings.catalog,
            settings.accounts,
            base / "installation-migrations",
        ]
    )
    if marker_path(settings).exists():
        fail("发现未完成导入，请先执行 recover 预览，不要删除标记后启动服务")
    report = verify_bundle(bundle, expected_digest=expected_digest)
    empty_target(settings)
    space_for(base, report["bytes"])
    return {
        "preview": True,
        "target_empty": True,
        "target_data_root": str(base),
        "auth_database": str(settings.auth),
        "catalog": str(settings.catalog),
        "accounts_root": str(settings.accounts),
        **report,
        "notes": list(NOT_PORTABLE),
    }


def canonical_catalog(original, rows, roots, devices):
    catalog = copy.deepcopy(original)
    catalog.update(accounts=[], workspaces=[], devices=[], registrations=[], storage_locations=[])
    now = timestamp()
    for row in rows:
        aid, wid, did = row["id"], row["workspace_id"], devices[row["id"]]
        account = next(
            (copy.deepcopy(v) for v in original.get("accounts", []) if v["id"] == aid), {}
        )
        account.update(
            id=aid, display_name=row["name"], kind=row["kind"], status=row["status"], updated_at=now
        )
        workspace = next(
            (copy.deepcopy(v) for v in original.get("workspaces", []) if v["id"] == wid), {}
        )
        workspace.update(
            id=wid, account_id=aid, name=workspace.get("name", row["name"]), updated_at=now
        )
        registration = next(
            (
                copy.deepcopy(v)
                for v in original.get("registrations", [])
                if v.get("workspace_id") == wid and v.get("local_root") == row["workspace_root"]
            ),
            {},
        )
        registration.update(
            id=registration.get("id", str(uuid4())),
            workspace_id=wid,
            device_id=did,
            locator_type="local_directory",
            local_root=str(roots[aid]),
            availability="online",
            updated_at=now,
        )
        location = next(
            (
                copy.deepcopy(v)
                for v in original.get("storage_locations", [])
                if v["id"] == row["location_id"]
            ),
            {},
        )
        location.update(
            id=row["location_id"],
            workspace_id=wid,
            account_id=aid,
            device_id=did,
            name=location.get("name", "账户存储"),
            provider_type="local_filesystem",
            config_reference="workspace-registration:" + registration["id"],
            status="online",
        )
        catalog["accounts"].append(account)
        catalog["workspaces"].append(workspace)
        catalog["devices"].append(
            {
                "id": did,
                "account_id": aid,
                "name": "迁入服务器",
                "platform": sys.platform,
                "app_version": "offline-migration",
            }
        )
        catalog["registrations"].append(registration)
        catalog["storage_locations"].append(location)
        for old in original.get("storage_locations", []):
            if old.get("workspace_id") == wid and old["id"] != row["location_id"]:
                if old.get("provider_type") == "local_filesystem":
                    fail("发现额外本地存储位置，需先核对原件，不能只迁移默认目录")
                catalog["storage_locations"].append({**old, "status": "offline", "device_id": None})
    active = next((r for r in rows if r["id"] == original.get("active_account_id")), rows[0])
    catalog.update(
        active_account_id=active["id"],
        active_workspace_id=active["workspace_id"],
        active_device_id=devices[active["id"]],
        updated_at=now,
    )
    return catalog


def rebase_paths(value, source, target, key=""):
    if isinstance(value, dict):
        return {k: rebase_paths(v, source, target, k) for k, v in value.items()}
    if isinstance(value, list):
        return [rebase_paths(v, source, target, key) for v in value]
    if isinstance(value, str) and (key in {"path", "root"} or key.endswith(("_path", "_root"))):
        normalized, old = value.replace("\\", "/"), source.replace("\\", "/").rstrip("/")
        if normalized.casefold() == old.casefold():
            return str(target)
        if normalized.casefold().startswith(old.casefold() + "/"):
            return str(target / Path(normalized[len(old) + 1 :]))
    return value


def prepare_workspace(root, row, target):
    # Only typed JSON path fields in business rows change; prompts and media bytes do not.
    with closing(connect(root / ".viraldna/workspace.db", writable=True)) as db:
        for table in tables(db):
            columns = {r[1] for r in db.execute(f"PRAGMA table_info({quote(table)})")}
            if {"record_key", "payload"} <= columns:
                for key, raw in db.execute(
                    f"SELECT record_key,payload FROM {quote(table)}"
                ).fetchall():
                    old = json.loads(raw)
                    new = rebase_paths(old, row["workspace_root"], target)
                    if new != old:
                        db.execute(
                            f"UPDATE {quote(table)} SET payload=? WHERE record_key=?",
                            (json.dumps(new, ensure_ascii=False), key),
                        )
        if "media_access_leases" in tables(db):
            db.execute("DELETE FROM media_access_leases")
        db.commit()
        db.execute("PRAGMA journal_mode=DELETE")
        healthy(db)
    ledger = root / ".viraldna/durable-storage.sqlite3"
    if ledger.exists():
        with closing(connect(ledger, writable=True)) as db:
            # Old transfers must never resume against the test server from this machine.
            db.execute(
                "DELETE FROM settings WHERE key IN "
                "('connection','remote_generation_runs','retained_on_server')"
            )
            for table in ("jobs", "uploads", "reservations"):
                db.execute(f"DELETE FROM {quote(table)}")
            db.execute("UPDATE entries SET synced_version=0")
            db.execute("INSERT OR REPLACE INTO settings VALUES('inventory_state','\"scanning\"')")
            db.commit()
            db.execute("PRAGMA journal_mode=DELETE")
            healthy(db)


def signature(path):
    checked_path(path)
    if not path.exists():
        return None
    if path.is_dir():
        return {"directory": inventory(path, hashes=True), "folders": directory_names(path)}
    return {"bytes": path.stat().st_size, "sha256": _digest(path)}


def role_paths(settings):
    # Identity is installed LAST; all original SQLite companions are retained too.
    return {
        "accounts": settings.accounts,
        "catalog": settings.catalog,
        **{f"auth{s}": Path(str(settings.auth) + s) for s in ("-wal", "-shm", "-journal")},
        "auth": settings.auth,
    }


def install_move(source, target):
    checked_path(source)
    checked_path(target)
    if target.exists():
        fail("安装目标在操作期间出现，拒绝覆盖")
    source.rename(target)


def rollback(settings, job, journal):
    for role, target in reversed(list(role_paths(settings).items())):
        entry = journal["roles"][role]
        current = signature(target)
        original = job / "previous" / role
        failed = job / "rolled-back" / role
        if current == entry["old"] and not original.exists():
            continue  # This role was not touched before failure.
        if current is not None:
            if current != entry["new"] or entry["new"] is None:
                fail(f"恢复时目标出现未预期变化，未覆盖：{target}")
            install_move(target, failed)
        if original.exists():
            if signature(original) != entry["old"]:
                fail("原始备份校验不一致，停止自动恢复")
            install_move(original, target)
        elif entry["old"] is not None:
            fail("原始备份缺失，停止自动恢复")
    journal["state"] = "rolled_back"
    atomic_bytes(job / "operation.json", json_bytes(journal))
    marker_path(settings).unlink()


def import_bundle(
    settings,
    bundle,
    *,
    expected_digest,
    confirm_api_stopped=False,
    confirm_empty_target=False,
    progress=lambda _: None,
):
    if not confirm_api_stopped or not confirm_empty_target:
        fail("实际导入必须显式确认停服和目标为空")
    if not expected_digest:
        fail("实际导入必须提供测试端输出的 manifest_sha256")
    with layout_lock(settings.auth):
        report = import_plan(settings, bundle, expected_digest=expected_digest)
        bundle = checked_path(bundle)
        operation = str(uuid4())
        job = target_layout(settings) / "installation-migrations" / operation
        checked_path(job)
        job.mkdir(parents=True)
        for name in ("prepared", "previous", "rolled-back"):
            (job / name).mkdir()
        progress("预检通过，正在准备目标副本；当前身份库未启用")
        prepared = job / "prepared"
        shutil.copytree(bundle / "accounts", prepared / "accounts", symlinks=True)
        shutil.copy2(bundle / "identity/accounts.sqlite3", prepared / "auth")
        if inventory(prepared / "accounts", hashes=True) != inventory(
            bundle / "accounts", hashes=True
        ):
            fail("工作区副本校验失败，未安装")
        if _digest(prepared / "auth") != _digest(bundle / "identity/accounts.sqlite3"):
            fail("身份库副本校验失败，未安装")
        rows = report["accounts"]
        roots = {r["id"]: settings.accounts / r["id"] for r in rows}
        devices = {r["id"]: str(uuid4()) for r in rows}
        for index, row in enumerate(rows, 1):
            progress(f"准备账户 {index}/{len(rows)}：{row['id']}")
            root = prepared / "accounts" / row["id"]
            prepare_workspace(root, row, roots[row["id"]])
            validate_workspace(root, row)
        catalog = canonical_catalog(
            read_json(bundle / "identity/account-catalog.json"), rows, roots, devices
        )
        atomic_bytes(prepared / "catalog", json_bytes(catalog))
        with closing(connect(prepared / "auth", writable=True)) as db:
            for row in rows:
                db.execute(
                    "UPDATE auth_accounts SET workspace_root=? WHERE id=?",
                    (str(roots[row["id"]]), row["id"]),
                )
                db.execute(
                    "UPDATE auth_account_runtime SET device_id=? WHERE account_id=?",
                    (devices[row["id"]], row["id"]),
                )
            for table in TRANSIENT_AUTH:
                db.execute(f"DELETE FROM {quote(table)}")
            db.execute(
                "INSERT INTO auth_audit VALUES(?,?,?,?,?,strftime('%s','now'))",
                (str(uuid4()), "offline-maintenance", "installation_imported", None, operation),
            )
            db.commit()
            db.execute("PRAGMA journal_mode=DELETE")
            auth_schema(db)
        # The bundle may be on removable media. Verify it again before publishing.
        verify_bundle(bundle, expected_digest=expected_digest)
        empty_target(settings)
        journal = {
            "operation": operation,
            "state": "prepared",
            "created_at": timestamp(),
            "manifest_sha256": expected_digest,
            "roles": {
                role: {
                    "target": str(target),
                    "old": signature(target),
                    "new": signature(prepared / role),
                }
                for role, target in role_paths(settings).items()
            },
        }
        atomic_bytes(job / "operation.json", json_bytes(journal))
        atomic_bytes(marker_path(settings), json_bytes({"operation": operation}))
        progress("副本校验完成，正在安装；失败会回退，意外断电后可用 recover 恢复")
        try:
            for role, target in role_paths(settings).items():
                if signature(target) != journal["roles"][role]["old"]:
                    fail("目标在安装期间发生变化，停止导入")
                if target.exists():
                    install_move(target, job / "previous" / role)
                if (prepared / role).exists():
                    install_move(prepared / role, target)
            journal["state"] = "completed"
            atomic_bytes(job / "operation.json", json_bytes(journal))
            marker_path(settings).unlink()
        except BaseException:
            rollback(settings, job, journal)
            raise
        return {
            "imported": True,
            "operation": operation,
            "backup": str(job / "previous"),
            "accounts": len(rows),
            "users": sum(r["users"] for r in rows),
            "accounts_root": str(settings.accounts),
            "notes": list(NOT_PORTABLE),
        }


def recover_import(settings, *, apply=False, confirm_api_stopped=False, operation=None):
    base = target_layout(settings)
    marker = read_json(marker_path(settings))
    identifier = str(UUID(marker["operation"]))
    job = checked_path(base / "installation-migrations" / identifier)
    journal = read_json(job / "operation.json")
    if journal.get("operation") != identifier or set(journal["roles"]) != set(role_paths(settings)):
        fail("恢复清单不匹配")
    for role, target in role_paths(settings).items():
        if journal["roles"][role]["target"] != str(target):
            fail("恢复清单与当前配置的路径不一致")
    result = {
        "preview": True,
        "operation": identifier,
        "state": journal["state"],
        "action": "roll_back_import",
        "backup": str(job / "previous"),
    }
    if apply:
        if not confirm_api_stopped or operation != identifier:
            fail("恢复必须确认停服并指定预览中的 --operation")
        with layout_lock(settings.auth, allow_incomplete_import=True):
            if read_json(marker_path(settings)) != marker:
                fail("恢复标记变化，请重新预览")
            rollback(settings, job, journal)
        result.update(preview=False, recovered=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "verify", "import", "recover"):
        cmd = commands.add_parser(name)
        if name != "verify":
            cmd.add_argument("--env-file", type=Path, required=True)
            cmd.add_argument("--apply", action="store_true")
            cmd.add_argument("--confirm-api-stopped", action="store_true")
        if name != "recover":
            cmd.add_argument("--bundle", type=Path, required=True)
        if name in {"verify", "import"}:
            cmd.add_argument("--manifest-sha256")
        if name == "import":
            cmd.add_argument("--confirm-empty-target", action="store_true")
        if name == "recover":
            cmd.add_argument("--operation")
    args = parser.parse_args(argv)
    stopped = threading.Event()
    started = time.monotonic()

    def heartbeat():
        while not stopped.wait(15):
            print(
                f"{args.command} 仍在执行，已用 {int(time.monotonic() - started)} 秒；"
                "文件校验/复制可能需要较长时间",
                file=sys.stderr,
                flush=True,
            )

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        settings = (
            Settings.from_env(args.env_file, target=args.command != "export")
            if args.command != "verify"
            else None
        )

        def progress(message):
            print(message, file=sys.stderr, flush=True)

        if args.command == "verify":
            result = verify_bundle(bundle_path(args.bundle), expected_digest=args.manifest_sha256)
        elif args.command == "export":
            result = (
                export_bundle(
                    settings,
                    args.bundle,
                    confirm_api_stopped=args.confirm_api_stopped,
                    progress=progress,
                )
                if args.apply
                else source_plan(settings, args.bundle)
            )
        elif args.command == "import":
            result = (
                import_bundle(
                    settings,
                    args.bundle,
                    expected_digest=args.manifest_sha256,
                    confirm_api_stopped=args.confirm_api_stopped,
                    confirm_empty_target=args.confirm_empty_target,
                    progress=progress,
                )
                if args.apply
                else import_plan(settings, args.bundle, expected_digest=args.manifest_sha256)
            )
        else:
            result = recover_import(
                settings,
                apply=args.apply,
                operation=args.operation,
                confirm_api_stopped=args.confirm_api_stopped,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkspaceLayoutError, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"迁移未完成：{exc}", file=sys.stderr)
        return 1
    finally:
        stopped.set()
        worker.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
