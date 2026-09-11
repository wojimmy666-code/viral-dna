"""All writes are confined to pytest fixtures; no deployment or live account is opened."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.accounts import migrate_workspaces as migration
from viral_dna_api.accounts import workspace_layout as layout
from viral_dna_api.accounts.repository import AccountError, AccountRepository


def identity(root, account_id, workspace_id):
    metadata = root / ".viraldna"
    metadata.mkdir(parents=True)
    (metadata / "workspace.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "account_id": str(account_id),
                "workspace_id": str(workspace_id),
                "name": "已有企业资产",
                "custom": {"keep": True},
            }
        ),
        encoding="utf-8",
    )


def seed_media(root):
    (root / "objects").mkdir()
    (root / "objects" / "original.bin").write_bytes(b"original media\x00\x01")
    database = root / ".viraldna" / "workspace.db"
    db = sqlite3.connect(database)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE assets(id TEXT, name TEXT)")
    db.execute("INSERT INTO assets VALUES('stable-id', '空气滤芯')")
    db.commit()
    return db


def first_account(repo, source, account_id, workspace_id, **kwargs):
    repo.bootstrap(
        admin_password="12345678",
        owner_password="abcdefgh",
        name="企业",
        kind="enterprise",
        username="13800000001",
        display_name="负责人",
        legacy_root=source,
        account_id=account_id,
        workspace_id=workspace_id,
        location_id=uuid4(),
        **kwargs,
    )


def test_first_and_later_account_use_one_rule(tmp_path):
    repo = AccountRepository(tmp_path / "auth.db", tmp_path / "accounts")
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "nonexistent-legacy"
    first_account(repo, source, account_id, workspace_id)
    assert not source.exists()
    owner = repo.runtime_accounts()[0]
    assert owner.workspace_root == tmp_path / "accounts" / str(account_id)
    other = repo.create_account(
        kind="personal", name="个人", username="13900000001", display_name="乙", actor="admin"
    )
    roots = {str(a.account_id): a.workspace_root for a in repo.runtime_accounts()}
    assert roots[other["id"]] == tmp_path / "accounts" / other["id"]
    assert json.loads((owner.workspace_root / ".viraldna/workspace.json").read_text("utf-8"))[
        "workspace_id"
    ] == str(workspace_id)


def test_bootstrap_copies_media_committed_wal_and_updates_catalog(tmp_path):
    repo = AccountRepository(tmp_path / "auth.db", tmp_path / "accounts")
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "legacy"
    identity(source, account_id, workspace_id)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "custom": "preserved",
                "registrations": [{"workspace_id": str(workspace_id), "local_root": str(source)}],
            }
        ),
        encoding="utf-8",
    )
    database = seed_media(source)
    try:
        first_account(repo, source, account_id, workspace_id, catalog_path=catalog)
        target = repo.runtime_accounts()[0].workspace_root
        assert source.is_dir()
        assert (target / "objects/original.bin").read_bytes() == b"original media\x00\x01"
        with sqlite3.connect(target / ".viraldna/workspace.db") as copied:
            assert copied.execute("SELECT * FROM assets").fetchall() == [("stable-id", "空气滤芯")]
        result = json.loads(catalog.read_text("utf-8"))
        assert result["custom"] == "preserved"
        assert result["registrations"][0]["local_root"] == str(target)
        assert json.loads((target / ".viraldna/workspace.json").read_text("utf-8"))["custom"] == {
            "keep": True
        }
    finally:
        database.close()


def test_failed_auth_commit_restores_catalog_and_keeps_source(tmp_path, monkeypatch):
    repo = AccountRepository(tmp_path / "auth.db", tmp_path / "accounts")
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "legacy"
    identity(source, account_id, workspace_id)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "registrations": [{"workspace_id": str(workspace_id), "local_root": str(source)}],
            }
        ),
        encoding="utf-8",
    )
    original = catalog.read_bytes()
    connect = repo.connect

    @contextmanager
    def fail_commit(*, write=False):
        with connect(write=write) as db:
            yield db
            if write:
                raise sqlite3.OperationalError("fixture commit failure")

    monkeypatch.setattr(repo, "connect", fail_commit)
    with pytest.raises(AccountError, match="原数据保留"):
        first_account(repo, source, account_id, workspace_id, catalog_path=catalog)
    assert not repo.initialized()
    assert catalog.read_bytes() == original
    assert source.is_dir()
    assert not (tmp_path / "accounts" / str(account_id)).exists()
    assert list((tmp_path / "accounts").glob(".layout-*.pending"))


@pytest.mark.parametrize("case", ["target_exists", "overlap", "wrong_identity", "junction"])
def test_unsafe_copy_targets_fail_closed(tmp_path, monkeypatch, case):
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "legacy"
    identity(source, account_id, workspace_id)
    root = tmp_path / "accounts"
    target = root / str(account_id)
    if case == "target_exists":
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("user file")
    elif case == "overlap":
        root = source / "accounts"
    elif case == "wrong_identity":
        workspace_id = uuid4()
    else:
        lstat = Path.lstat

        def fake_junction(path):
            if path == source:
                return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
            return lstat(path)

        monkeypatch.setattr(Path, "lstat", fake_junction)
    with pytest.raises(layout.WorkspaceLayoutError):
        with layout.provision_workspace(root, account_id, workspace_id, source=source):
            pytest.fail("Unsafe target was accepted")
    if case == "target_exists":
        assert (target / "keep.txt").read_text() == "user file"


@pytest.mark.parametrize("mutation", ["file", "database"])
def test_source_changes_abort_before_binding(tmp_path, monkeypatch, mutation):
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "legacy"
    identity(source, account_id, workspace_id)
    database = seed_media(source)
    try:
        if mutation == "file":
            copy = layout.shutil.copy2

            def mutate(path, destination):
                result = copy(path, destination)
                if path.name == "original.bin":
                    path.write_bytes(b"changed by another writer")
                return result

            monkeypatch.setattr(layout.shutil, "copy2", mutate)
        else:
            backup = layout._backup

            def mutate(reader, writer):
                backup(reader, writer)
                database.execute("INSERT INTO assets VALUES('new', 'new data')")
                database.commit()

            monkeypatch.setattr(layout, "_backup", mutate)
        with pytest.raises(layout.WorkspaceLayoutError, match="变化|写入"):
            with layout.provision_workspace(
                tmp_path / "accounts", account_id, workspace_id, source=source
            ):
                pytest.fail("Concurrent changes should abort")
        assert not (tmp_path / "accounts" / str(account_id)).exists()
    finally:
        database.close()


@pytest.fixture
def old_account(tmp_path):
    repo = AccountRepository(tmp_path / "auth.db", tmp_path / "accounts")
    account_id, workspace_id = uuid4(), uuid4()
    source = tmp_path / "legacy"
    identity(source, account_id, workspace_id)
    db = seed_media(source)
    db.close()
    with repo.connect(write=True) as auth:
        auth.execute(
            "INSERT INTO auth_accounts VALUES(?,?,?,?,?,?,?,?,?)",
            (
                str(account_id),
                "enterprise",
                "旧企业",
                "active",
                str(workspace_id),
                str(uuid4()),
                str(source),
                1,
                1,
            ),
        )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "registrations": [
                    {"workspace_id": str(workspace_id), "local_root": str(source)},
                    {"workspace_id": str(uuid4()), "local_root": str(tmp_path / "unrelated")},
                ],
            }
        ),
        encoding="utf-8",
    )
    return repo, account_id, workspace_id, source, catalog


def test_offline_preview_preserves_data_and_apply_preserves_ids_and_files(old_account, tmp_path):
    repo, account_id, workspace_id, source, catalog = old_account

    def persistent_files():
        # A mode=ro SQLite reader may create its shared-memory/WAL sidecars;
        # these are not account writes or newly initialized databases.
        return {
            p.relative_to(tmp_path): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file() and not p.name.endswith(("-shm", "-wal"))
        }

    before = persistent_files()
    plan = migration.migration_plan(repo.path, repo.tenant_root)
    assert plan[0]["status"] == "needs_migration"
    assert before == persistent_files()
    result = migration.migrate_account(
        repo.path,
        repo.tenant_root,
        account_id=account_id,
        expected_source=source,
        catalog_path=catalog,
        confirm_api_stopped=True,
    )
    assert result["changed"] is True
    target = repo.tenant_root / str(account_id)
    access = repo.runtime_accounts()[0]
    assert access.workspace_root == target
    assert access.workspace_id == workspace_id
    assert source.is_dir()
    assert (target / "objects/original.bin").read_bytes() == (
        source / "objects/original.bin"
    ).read_bytes()
    saved_catalog = json.loads(catalog.read_text("utf-8"))
    assert saved_catalog["registrations"][0]["local_root"] == str(target)
    assert saved_catalog["registrations"][1]["local_root"] == str(tmp_path / "unrelated")
    with sqlite3.connect(Path(result["backup"]) / "accounts.sqlite3") as saved:
        assert saved.execute("SELECT workspace_root FROM auth_accounts").fetchone()[0] == str(
            source
        )
    repeated = migration.migrate_account(
        repo.path,
        repo.tenant_root,
        account_id=account_id,
        expected_source=target,
        catalog_path=catalog,
        confirm_api_stopped=True,
    )
    assert not repeated["changed"]


@pytest.mark.parametrize("case", ["not_stopped", "active_api", "wrong_source", "target_exists"])
def test_existing_account_migration_requires_explicit_safe_conditions(old_account, case):
    repo, account_id, _, source, catalog = old_account
    kwargs = dict(
        account_id=account_id,
        expected_source=source,
        catalog_path=catalog,
        confirm_api_stopped=True,
    )
    if case == "not_stopped":
        kwargs["confirm_api_stopped"] = False
    elif case == "wrong_source":
        kwargs["expected_source"] = source.parent / "different"
    elif case == "target_exists":
        (repo.tenant_root / str(account_id)).mkdir(parents=True)
    if case == "active_api":
        with layout.layout_lock(repo.path), pytest.raises(layout.WorkspaceLayoutError, match="API"):
            migration.migrate_account(repo.path, repo.tenant_root, **kwargs)
    else:
        with pytest.raises(layout.WorkspaceLayoutError):
            migration.migrate_account(repo.path, repo.tenant_root, **kwargs)
    assert repo.runtime_accounts()[0].workspace_root == source


def test_migration_commit_failure_restores_all_bindings(old_account, monkeypatch):
    repo, account_id, _, source, catalog = old_account
    original = catalog.read_bytes()
    connect = migration._connect

    class FailedCommit:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def commit(self):
            raise sqlite3.OperationalError("fixture commit failure")

    monkeypatch.setattr(
        migration,
        "_connect",
        lambda path, readonly=True: (
            connect(path) if readonly else FailedCommit(connect(path, readonly=False))
        ),
    )
    with pytest.raises(sqlite3.OperationalError):
        migration.migrate_account(
            repo.path,
            repo.tenant_root,
            account_id=account_id,
            expected_source=source,
            catalog_path=catalog,
            confirm_api_stopped=True,
        )
    assert repo.runtime_accounts()[0].workspace_root == source
    assert catalog.read_bytes() == original
    assert source.exists()
    assert not (repo.tenant_root / str(account_id)).exists()


def test_cli_missing_config_never_initializes_empty_databases(tmp_path, capsys):
    assert migration.main(["--env-file", str(tmp_path / "missing.env")]) == 1
    assert not list(tmp_path.iterdir())
    assert "绝对路径" in capsys.readouterr().err
