"""Cross-machine migration tests use only temporary databases, files and mocked failures."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.account_storage.catalog import StorageCatalog
from viral_dna_api.accounts import installation_bundle as bundle_lib
from viral_dna_api.accounts import installation_transfer as transfer
from viral_dna_api.accounts import repository as auth
from viral_dna_api.accounts.workspace_layout import WorkspaceLayoutError, layout_lock
from viral_dna_api.asset_library import Asset, AssetFolder
from viral_dna_api.models import AnalysisRecord, Video
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.storage_objects import ObjectReplica, StorageObject
from viral_dna_api.workspace_catalog import AccountCatalogState

cached_password = lru_cache()(auth.password_hash)


def settings(base):
    return bundle_lib.Settings(
        base / "accounts.sqlite3", base / "account-catalog.json", base / "accounts", base / "legacy"
    )


def env_file(base, cfg):
    file = base / "migration.env"
    file.write_text(
        f"VIRAL_DNA_AUTH_DB_PATH={cfg.auth}\n"
        f"VIRAL_DNA_ACCOUNT_CATALOG_PATH={cfg.catalog}\n"
        f"VIRAL_DNA_ACCOUNTS_ROOT={cfg.accounts}\n"
        f"VIRAL_DNA_WORKSPACE_ROOT={cfg.legacy}\n",
        encoding="utf-8",
    )
    return file


@pytest.fixture
def source(tmp_path_factory, monkeypatch):
    # Keep fixture roots comparable to C:\Projects\ViralDNA\.server\data;
    # pytest's full test-name directory can itself exceed legacy Windows limits.
    tmp_path = tmp_path_factory.mktemp("xm")
    monkeypatch.setattr(auth, "password_hash", cached_password)
    cfg = settings(tmp_path / "test-data")
    repo = auth.AccountRepository(cfg.auth, cfg.accounts)
    account_id, workspace_id = uuid4(), uuid4()
    repo.bootstrap(
        admin_password="password123",
        owner_password="password123",
        kind="enterprise",
        name="迁移企业",
        username="13800000001",
        display_name="负责人",
        legacy_root=cfg.legacy,
        account_id=account_id,
        workspace_id=workspace_id,
        location_id=uuid4(),
        device_id=uuid4(),
    )
    member = repo.invite(
        str(account_id), username="13800000002", display_name="成员", actor="admin"
    )
    repo.activate(member["activation_token"], "password123")
    other = repo.create_account(
        kind="personal", name="个人", username="13900000001", display_name="个人用户", actor="admin"
    )
    repo.activate(other["activation_token"], "password123")
    token = repo.login("13800000001", "password123", admin=False, remote="fixture")
    roots = []
    record_id = str(uuid4())
    for access in repo.runtime_accounts():
        root = access.workspace_root
        roots.append(root)
        (root / ".viraldna").mkdir(parents=True, exist_ok=True)
        (root / ".viraldna/workspace.json").write_text(
            json.dumps(
                {
                    "schema_version": 18,
                    "account_id": str(access.account_id),
                    "workspace_id": str(access.workspace_id),
                    "name": access.account_name,
                }
            ),
            encoding="utf-8",
        )
        store = SQLiteStore(root / ".viraldna/workspace.db")
        video = Video(source_type="upload", title="原项目视频", record_id=record_id)
        store._upsert("videos", str(video.id), video.model_dump_json())
        record = AnalysisRecord(
            id=record_id, name="已有项目", video_id=video.id, source_type="upload"
        )
        payload = json.loads(record.model_dump_json())
        payload["source_path"] = str(root / "objects/original.bin")
        payload["prompt"] = f"不要修改提示词里的路径：{root}"
        store._upsert("records", record_id, json.dumps(payload, ensure_ascii=False))
        (root / "objects").mkdir()
        (root / "objects/original.bin").write_bytes(b"original-image-or-video\x00")
        ledger = StorageCatalog(root, str(access.account_id), access.account_kind)
        digest = hashlib.sha256(b"original-image-or-video\x00").hexdigest()
        folder = AssetFolder(
            workspace_id=access.workspace_id, account_id=access.account_id, name="测试资产目录"
        )
        obj = StorageObject(
            workspace_id=access.workspace_id,
            account_id=access.account_id,
            object_type="asset_image",
            original_filename="original.bin",
            mime_type="application/octet-stream",
            size_bytes=24,
            sha256=digest,
        )
        replica = ObjectReplica(
            storage_object_id=obj.id,
            storage_location_id=access.storage_location_id,
            account_id=access.account_id,
            object_key="objects/original.bin",
            state="available",
            checksum=digest,
        )
        asset = Asset(
            workspace_id=access.workspace_id,
            account_id=access.account_id,
            folder_id=folder.id,
            content_object_id=obj.id,
            thumbnail_object_id=obj.id,
            type="product",
            name="已有资产",
            width=1,
            height=1,
        )
        for table, model in (
            ("asset_folders", folder),
            ("storage_objects", obj),
            ("object_replicas", replica),
            ("assets", asset),
        ):
            store._upsert(table, str(model.id), model.model_dump_json())
        with ledger.connect(write=True) as db:
            db.execute(
                "INSERT INTO blobs VALUES(?,?,?,?,?)",
                (digest, 24, "objects/original.bin", 1, time.time()),
            )
            db.execute(
                "INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "history:stable-id",
                    "generated_image",
                    digest,
                    None,
                    '{"prompt":"画面要求"}',
                    time.time(),
                    time.time(),
                    None,
                    123,
                ),
            )
            db.execute("UPDATE settings SET value='12345678901' WHERE key='limit_bytes'")
        ledger.set_setting("connection", {"confirmed": True, "server_url": "https://old.example"})
        ledger.set_setting("remote_generation_runs", ["old-run"])
        ledger.reserve("stale", 100, "generation")
    cfg.catalog.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    gc.collect()  # Match a stopped API: close SQLiteStore's otherwise GC-owned connections.
    return SimpleNamespace(
        cfg=cfg,
        repo=repo,
        roots=roots,
        token=token,
        record_id=record_id,
        account_id=str(account_id),
        member_id=member["id"],
        tmp=tmp_path,
    )


@pytest.fixture
def exported(source):
    path = source.tmp / "source.vdna-migration"
    result = transfer.export_bundle(source.cfg, path, confirm_api_stopped=True)
    return SimpleNamespace(
        source=source, path=path, digest=result["manifest_sha256"], result=result
    )


def apply_import(exported, cfg, **kwargs):
    return transfer.import_bundle(
        cfg,
        exported.path,
        expected_digest=exported.digest,
        confirm_api_stopped=True,
        confirm_empty_target=True,
        **kwargs,
    )


def test_round_trip_accounts_passwords_ids_paths_history_and_capacity(exported):
    source = exported.source
    destination = settings(source.tmp / "production/data")
    snapshot = bundle_lib.inventory(exported.path, hashes=True)
    report = transfer.import_plan(destination, exported.path, expected_digest=exported.digest)
    assert report["target_empty"] and len(report["accounts"]) == 2
    assert not destination.auth.parent.exists(), "Preview must not create target files"
    result = apply_import(exported, destination)
    assert result["accounts"] == 2 and result["users"] == 3
    repo = auth.AccountRepository(destination.auth, destination.accounts)
    for username, admin in [
        ("admin", True),
        ("13800000001", False),
        ("13800000002", False),
        ("13900000001", False),
    ]:
        assert repo.login(username, "password123", admin=admin, remote="new-server")
    assert source.member_id in {row["id"] for row in repo.members(source.account_id)}
    with repo.connect() as db, source.repo.connect() as old:
        for table in ("auth_accounts", "auth_users", "auth_admins"):
            assert {r[0] for r in db.execute(f"SELECT id FROM {table}")} == {
                r[0] for r in old.execute(f"SELECT id FROM {table}")
            }
        assert (
            db.execute(
                "SELECT 1 FROM auth_sessions WHERE token_hash=?", (auth.token_hash(source.token),)
            ).fetchone()
            is None
        )
        for table in ("project_edit_leases", "auth_storage_tokens", "auth_invitations"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert set(r[0] for r in db.execute("SELECT device_id FROM auth_account_runtime")) != set(
            r[0] for r in old.execute("SELECT device_id FROM auth_account_runtime")
        )
    catalog = AccountCatalogState.model_validate(bundle_lib.read_json(destination.catalog))
    assert len(catalog.accounts) == 2
    for row in bundle_lib.accounts_in(destination.auth):
        root = destination.accounts / row["id"]
        assert Path(row["workspace_root"]) == root
        assert (root / "objects/original.bin").read_bytes() == b"original-image-or-video\x00"
        with closing(bundle_lib.connect(root / ".viraldna/workspace.db")) as db:
            record = json.loads(db.execute("SELECT payload FROM records").fetchone()[0])
            assert record["id"] == source.record_id
            assert record["source_path"] == str(root / "objects/original.bin")
            assert str(source.cfg.accounts) in record["prompt"], "Do not rewrite prompt prose"
        ledger = StorageCatalog(root, row["id"], row["kind"])
        assert ledger.usage()["limit_bytes"] == 12345678901
        assert ledger.usage()["used_bytes"] == 24
        assert ledger.usage()["reserved_bytes"] == 0
        assert not ledger.setting("connection", {})
        with ledger.connect() as db:
            assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == 1
    assert bundle_lib.inventory(exported.path, hashes=True) == snapshot
    assert not transfer.marker_path(destination).exists()
    assert source.repo.initialized() and all(root.exists() for root in source.roots)


def test_preview_and_cli_do_not_create_files_or_import_api(source):
    target = source.tmp / "preview.vdna-migration"
    report = transfer.source_plan(source.cfg, target)
    assert report["preview"] and not target.exists()
    config = env_file(source.tmp, source.cfg)
    script = Path(__file__).resolve().parents[3] / "scripts/maintenance/transfer-installation.py"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(script),
            "export",
            "--env-file",
            str(config),
            "--bundle",
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    assert '"preview": true' in result.stdout


@pytest.mark.parametrize("kind", ["account", "orphan-file", "catalog", "legacy-file", "legacy-db"])
def test_nonempty_target_is_never_overwritten(exported, kind):
    target = settings(exported.source.tmp / "nonempty")
    repo = auth.AccountRepository(target.auth, target.accounts)
    if kind == "account":
        repo.create_account(
            kind="personal",
            name="Must keep",
            username="13700000001",
            display_name="keep",
            actor="admin",
        )
    elif kind == "orphan-file":
        target.accounts.mkdir()
        (target.accounts / "must-keep.bin").write_bytes(b"must keep")
    elif kind == "catalog":
        target.catalog.write_text(
            '{"schema_version":1,"accounts":[{"id":"keep"}]}', encoding="utf-8"
        )
    else:
        target.legacy.mkdir()
        if kind == "legacy-file":
            (target.legacy / "must-keep.bin").write_bytes(b"must keep")
        else:
            backend = SQLiteStore(target.legacy / ".viraldna/workspace.db")
            backend._upsert("records", "keep", "{}")
    gc.collect()
    before = bundle_lib.inventory(target.auth.parent, hashes=True)
    with pytest.raises(WorkspaceLayoutError):
        apply_import(exported, target)
    after = bundle_lib.inventory(target.auth.parent, hashes=True)
    after.pop("accounts.workspace-layout.lock", None)
    before = {k: v for k, v in before.items() if not k.endswith(("-wal", "-shm"))}
    after = {k: v for k, v in after.items() if not k.endswith(("-wal", "-shm"))}
    assert before == after


def test_empty_initialized_schema_allowed_and_originals_preserved(exported):
    target = settings(exported.source.tmp / "empty-schemas")
    auth.AccountRepository(target.auth, target.accounts)
    target.accounts.mkdir()
    target.catalog.write_text('{"schema_version":1}', encoding="utf-8")
    SQLiteStore(target.legacy / ".viraldna/workspace.db")
    old_auth = target.auth.read_bytes()
    result = apply_import(exported, target)
    assert (Path(result["backup"]) / "auth").read_bytes() == old_auth
    assert (Path(result["backup"]) / "catalog").read_text("utf-8") == '{"schema_version":1}'


@pytest.mark.parametrize("kind", ["file", "extra", "manifest-path", "identity", "code"])
def test_tampered_bundle_refused(exported, kind):
    if kind == "file":
        (
            exported.path
            / "accounts"
            / exported.result["accounts"][0]["id"]
            / "objects/original.bin"
        ).write_bytes(b"changed")
    elif kind == "extra":
        (exported.path / "unexpected.bin").write_bytes(b"extra")
    else:
        manifest = bundle_lib.read_json(exported.path / "manifest.json")
        if kind == "manifest-path":
            manifest["files"]["../escape"] = {"bytes": 0, "sha256": "0" * 64}
        elif kind == "identity":
            manifest["accounts"][0]["id"] = str(uuid4())
        else:
            manifest["code_fingerprint"] = "0" * 64
        (exported.path / "manifest.json").write_bytes(bundle_lib.json_bytes(manifest))
    with pytest.raises(WorkspaceLayoutError):
        transfer.import_plan(settings(exported.source.tmp / "tampered"), exported.path)


@pytest.mark.parametrize(
    "path", ["../bad", "/abs", "C:/absolute", "a\\b", "a//b", "NUL.txt", "x.", "a/../b"]
)
def test_portable_paths_reject_windows_escape_forms(path):
    with pytest.raises(WorkspaceLayoutError):
        bundle_lib.portable_name(path)


def test_confirmation_digest_and_active_api_lock(exported):
    target = settings(exported.source.tmp / "locked")
    with pytest.raises(WorkspaceLayoutError, match="显式确认"):
        transfer.import_bundle(target, exported.path, expected_digest=exported.digest)
    with pytest.raises(WorkspaceLayoutError, match="SHA-256"):
        transfer.import_plan(target, exported.path, expected_digest="0" * 64)
    with layout_lock(target.auth), pytest.raises(WorkspaceLayoutError, match="正在被"):
        apply_import(exported, target)
    with layout_lock(exported.source.cfg.auth), pytest.raises(WorkspaceLayoutError, match="正在被"):
        transfer.export_bundle(
            exported.source.cfg,
            exported.source.tmp / "locked.vdna-migration",
            confirm_api_stopped=True,
        )


@pytest.mark.parametrize("fail_role", ["accounts", "catalog", "auth"])
def test_failure_rolls_back_and_keeps_originals(exported, monkeypatch, fail_role):
    target = settings(exported.source.tmp / "rollback")
    auth.AccountRepository(target.auth, target.accounts)
    original = target.auth.read_bytes()
    real_move = transfer.install_move

    def fail_install(source, destination):
        if source.parent.name == "prepared" and source.name == fail_role:
            raise OSError("fixture failure")
        real_move(source, destination)

    monkeypatch.setattr(transfer, "install_move", fail_install)
    with pytest.raises(OSError, match="fixture failure"):
        apply_import(exported, target)
    assert target.auth.read_bytes() == original
    assert not target.catalog.exists() and not target.accounts.exists()
    assert not transfer.marker_path(target).exists()
    assert list(target.auth.parent.glob("installation-migrations/*/operation.json"))


def test_crash_marker_blocks_startup_then_recovers(exported, monkeypatch):
    target = settings(exported.source.tmp / "crash")
    auth.AccountRepository(target.auth, target.accounts)
    original = target.auth.read_bytes()
    real_move = transfer.install_move
    real_rollback = transfer.rollback

    def crash(source, destination):
        real_move(source, destination)
        if source.parent.name == "prepared" and source.name == "catalog":
            raise OSError("power loss")

    def unavailable_rollback(*args):
        raise OSError("process killed")

    monkeypatch.setattr(transfer, "install_move", crash)
    monkeypatch.setattr(transfer, "rollback", unavailable_rollback)
    with pytest.raises(OSError, match="process killed"):
        apply_import(exported, target)
    assert transfer.marker_path(target).exists()
    with pytest.raises(WorkspaceLayoutError, match="未完成"):
        with layout_lock(target.auth):
            pytest.fail("Incomplete import must prevent API startup")
    monkeypatch.setattr(transfer, "install_move", real_move)
    monkeypatch.setattr(transfer, "rollback", real_rollback)
    preview = transfer.recover_import(target)
    with pytest.raises(WorkspaceLayoutError):
        transfer.recover_import(
            target, apply=True, confirm_api_stopped=True, operation=str(uuid4())
        )
    media = next(target.accounts.glob("*/objects/original.bin"))
    original_media = media.read_bytes()
    media.write_bytes(b"an external writer changed this file")
    with pytest.raises(WorkspaceLayoutError, match="未预期变化"):
        transfer.recover_import(
            target, apply=True, confirm_api_stopped=True, operation=preview["operation"]
        )
    assert media.read_bytes() == b"an external writer changed this file"
    assert transfer.marker_path(target).exists()
    media.write_bytes(original_media)  # Restore only this test fixture, then retry recovery.
    transfer.recover_import(
        target, apply=True, confirm_api_stopped=True, operation=preview["operation"]
    )
    assert target.auth.read_bytes() == original
    assert not target.accounts.exists() and not target.catalog.exists()
    assert not transfer.marker_path(target).exists()


def test_workspace_with_live_tasks_and_missing_blob_refused(source):
    backend = SQLiteStore(source.roots[0] / ".viraldna/workspace.db")
    backend._upsert("generation_runs", "running", '{"status":"running"}')
    with pytest.raises(WorkspaceLayoutError, match="未结束"):
        transfer.source_plan(source.cfg, source.tmp / "busy.vdna-migration")
    with closing(bundle_lib.connect(backend.database_path, writable=True)) as db:
        db.execute("DELETE FROM generation_runs")
        db.commit()
    (source.roots[0] / "objects/original.bin").unlink()
    with pytest.raises(WorkspaceLayoutError, match="原件"):
        transfer.source_plan(source.cfg, source.tmp / "missing.vdna-migration")


def test_source_change_between_accounts_aborts_export(source, monkeypatch):
    real_backup = transfer.backup_database

    def changing_backup(original, destination):
        real_backup(original, destination)
        source.cfg.catalog.write_text('{"schema_version":1,"changed":true}', encoding="utf-8")

    monkeypatch.setattr(transfer, "backup_database", changing_backup)
    target = source.tmp / "changing.vdna-migration"
    with pytest.raises(WorkspaceLayoutError, match="仍有写入"):
        transfer.export_bundle(source.cfg, target, confirm_api_stopped=True)
    assert not target.exists()
    assert list(source.tmp.glob("changing.vdna-migration.pending-*"))


def test_bad_config_missing_source_and_target_defaults_refused(tmp_path):
    file = tmp_path / "empty.env"
    file.write_text("", encoding="utf-8")
    with pytest.raises(WorkspaceLayoutError, match="明确指定"):
        bundle_lib.Settings.from_env(file, target=True)
    missing = settings(tmp_path / "missing")
    with pytest.raises(WorkspaceLayoutError, match="不存在"):
        transfer.source_plan(missing, tmp_path / "empty.vdna-migration")
    assert not missing.auth.parent.exists()


def test_committed_wal_pages_are_included_without_changing_source(source):
    database = source.roots[0] / ".viraldna/workspace.db"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO records(record_key,payload) VALUES('wal-only','{}')")
        writer.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        path = source.tmp / "wal.vdna-migration"
        transfer.export_bundle(source.cfg, path, confirm_api_stopped=True)
        copied = path / "accounts" / source.roots[0].name / ".viraldna/workspace.db"
        with closing(bundle_lib.connect(copied)) as db:
            assert (
                db.execute("SELECT payload FROM records WHERE record_key='wal-only'").fetchone()[0]
                == "{}"
            )
        assert writer.execute("SELECT count(*) FROM records").fetchone()[0] == 2


def test_repeat_import_never_replaces_existing_installation(exported):
    target = settings(exported.source.tmp / "repeat")
    apply_import(exported, target)
    with pytest.raises(WorkspaceLayoutError, match="非空"):
        apply_import(exported, target)


def test_insufficient_disk_space_fails_before_copy(exported, monkeypatch):
    target = settings(exported.source.tmp / "no-space")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(WorkspaceLayoutError, match="空间不足"):
        apply_import(exported, target)
    assert not target.auth.exists() and not target.accounts.exists()


def test_directory_junction_in_bundle_is_refused(exported, monkeypatch):
    original = Path.lstat
    target = exported.path / "accounts"

    def pretend_junction(path):
        info = original(path)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", pretend_junction)
    with pytest.raises(WorkspaceLayoutError, match="联接"):
        bundle_lib.verify_bundle(exported.path)


def test_wrong_ownership_or_remote_only_original_cannot_be_exported(source):
    root = source.roots[0]
    with closing(bundle_lib.connect(root / ".viraldna/workspace.db", writable=True)) as db:
        db.execute("DELETE FROM object_replicas")
        db.commit()
    with pytest.raises(WorkspaceLayoutError, match="本地原件"):
        transfer.source_plan(source.cfg, source.tmp / "remote-only.vdna-migration")


def test_real_app_login_assets_media_and_isolation_after_import(exported):
    target = settings(exported.source.tmp / "app")
    apply_import(exported, target)
    config = env_file(target.auth.parent, target)
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIRAL_DNA_")}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "LOCALAPPDATA": str(target.auth.parent / "local-appdata"),
            "APPDATA": str(target.auth.parent / "appdata"),
            "VIRAL_DNA_ENV_FILE": str(config),
            "VIRAL_DNA_STORE": "sqlite",
            "VIRAL_DNA_AUTH_MODE": "password",
            "VIRAL_DNA_AUTH_DB_PATH": str(target.auth),
            "VIRAL_DNA_ACCOUNT_CATALOG_PATH": str(target.catalog),
            "VIRAL_DNA_ACCOUNTS_ROOT": str(target.accounts),
            "VIRAL_DNA_WORKSPACE_ROOT": str(target.legacy),
            "VIRAL_DNA_NOTIFICATION_DB_PATH": str(target.auth.parent / "notifications.sqlite3"),
            "VIRAL_DNA_PLATFORM_CONNECTIONS_PATH": str(target.auth.parent / "connections.json"),
            "VIRAL_DNA_PLATFORM_SECRET_ROOT": str(target.auth.parent / "secrets"),
        }
    )
    script = r"""
import os
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from viral_dna_api.main import app
calls = []
async def forbidden_request(*args, **kwargs):
    calls.append(True)
    raise AssertionError("No external network during migration verification")
httpx.AsyncClient.request = forbidden_request
with TestClient(app, base_url="http://127.0.0.1", headers={"Origin":"http://127.0.0.1"}) as client:
    assert client.get("/api/v1/auth/status").json()["initialized"] is True
    owner_asset = None
    for phone in ("13800000001", "13800000002", "13900000001"):
        client.cookies.clear()
        login = client.post("/api/v1/auth/login", json={"username":phone,"password":"password123"})
        assert login.status_code == 200, login.text
        context = client.get("/api/v1/context").json()
        wid = context["active_workspace"]["id"]
        root = Path(context["registration"]["local_root"])
        assert root.parent == Path(os.environ["VIRAL_DNA_ACCOUNTS_ROOT"])
        folders = client.get(f"/api/v1/workspaces/{wid}/asset-folders")
        assert folders.status_code == 200 and len(folders.json()) == 1, folders.text
        assets = client.get(f"/api/v1/workspaces/{wid}/assets")
        assert assets.status_code == 200, assets.text
        item = assets.json()["items"][0]
        content = client.get(item["content_url"])
        assert content.status_code == 200 and content.content == b"original-image-or-video\x00"
        projects = client.get("/api/v1/projects")
        assert projects.status_code == 200 and projects.json()["items"], projects.text
        if owner_asset is None:
            owner_asset = item
        elif phone == "13800000002":
            assert item["id"] == owner_asset["id"], "Enterprise members share assets"
        else:
            assert item["id"] != owner_asset["id"]
            assert client.get(owner_asset["content_url"]).status_code == 404
    client.cookies.clear()
    admin_login = client.post("/api/v1/admin/auth/login", json={
        "username":"admin", "password":"password123"})
    assert admin_login.status_code == 200, admin_login.text
assert not calls
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_extra_empty_directory_is_detected(exported):
    (exported.path / "accounts/unlisted-empty").mkdir()
    with pytest.raises(WorkspaceLayoutError, match="目录结构"):
        bundle_lib.verify_bundle(exported.path)


def test_control_file_path_collisions_and_relative_targets_are_rejected(tmp_path):
    cfg = settings(tmp_path / "collision")
    for catalog in (transfer.marker_path(cfg), Path(str(cfg.auth) + "-wal")):
        wrong = bundle_lib.Settings(cfg.auth, catalog, cfg.accounts)
        with pytest.raises(WorkspaceLayoutError, match="相互包含"):
            transfer.target_layout(wrong)
    with pytest.raises(WorkspaceLayoutError, match="绝对路径"):
        transfer.target_layout(settings(Path("relative")))


def test_target_account_committed_only_in_wal_is_not_considered_empty(exported):
    cfg = settings(exported.source.tmp / "wal-target")
    auth.AccountRepository(cfg.auth, cfg.accounts)
    with closing(sqlite3.connect(cfg.auth)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO auth_admins VALUES(?,1,'admin',?)",
            (str(uuid4()), cached_password("password123")),
        )
        writer.commit()
        assert Path(str(cfg.auth) + "-wal").stat().st_size > 0
        with pytest.raises(WorkspaceLayoutError, match="非空"):
            apply_import(exported, cfg)
        assert writer.execute("SELECT count(*) FROM auth_admins").fetchone()[0] == 1


def test_orphan_auth_wal_is_not_silently_discarded(exported):
    cfg = settings(exported.source.tmp / "orphan-wal")
    cfg.auth.parent.mkdir()
    orphan = Path(str(cfg.auth) + "-wal")
    orphan.write_bytes(b"unknown previous installation")
    with pytest.raises(WorkspaceLayoutError, match="辅助文件"):
        apply_import(exported, cfg)
    assert orphan.read_bytes() == b"unknown previous installation"
    assert not cfg.auth.exists()


def test_original_catalog_registration_and_storage_ids_survive(source):
    rows = bundle_lib.accounts_in(source.cfg.auth)
    old = transfer.canonical_catalog(
        {"schema_version": 1},
        rows,
        {r["id"]: Path(r["workspace_root"]) for r in rows},
        {r["id"]: r["device_id"] for r in rows},
    )
    source.cfg.catalog.write_bytes(bundle_lib.json_bytes(old))
    path = source.tmp / "registered.vdna-migration"
    result = transfer.export_bundle(source.cfg, path, confirm_api_stopped=True)
    target = settings(source.tmp / "registered-target")
    transfer.import_bundle(
        target,
        path,
        expected_digest=result["manifest_sha256"],
        confirm_api_stopped=True,
        confirm_empty_target=True,
    )
    new = bundle_lib.read_json(target.catalog)
    for key in ("accounts", "workspaces", "registrations", "storage_locations"):
        assert {r["id"] for r in old[key]} == {r["id"] for r in new[key]}
    assert {r["id"] for r in old["devices"]}.isdisjoint({r["id"] for r in new["devices"]})
