from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..accounts.repository import AccountError

GB = 1_000_000_000
DEFAULT_LIMITS = {"personal": 2 * GB, "enterprise": 10 * GB}
CHUNK_BYTES = 4 * 1024 * 1024
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blobs (
 sha256 TEXT PRIMARY KEY,size_bytes INTEGER NOT NULL,relative_path TEXT NOT NULL,
 chargeable INTEGER NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entries (
 key TEXT PRIMARY KEY,kind TEXT NOT NULL,sha256 TEXT NOT NULL,
 thumbnail_sha256 TEXT,metadata TEXT NOT NULL,created_at REAL NOT NULL,
 updated_at REAL NOT NULL,deleted_at REAL,synced_version REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS removed_entries (key TEXT PRIMARY KEY,removed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
 relative_path TEXT PRIMARY KEY,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reservations (
 id TEXT PRIMARY KEY,bytes INTEGER NOT NULL,kind TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,details TEXT NOT NULL,
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,
 error TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS uploads (
 id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
 received INTEGER NOT NULL DEFAULT 0,chargeable INTEGER NOT NULL,
 filename TEXT NOT NULL,mime_type TEXT NOT NULL,UNIQUE(batch_id,sha256));
"""


def file_hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class StorageCatalog:
    """One durable transactional ledger per account workspace, never per browser.

    Files are immutable and addressed by content within this account only. A
    separate catalog deliberately survives deletion of a project's database rows.
    """

    def __init__(self, root: Path, account_id: str, kind: str = "personal"):
        self.root = root.resolve()
        self.account_id = str(account_id)
        directory = self.root / ".viraldna"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "durable-storage.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        with self.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO settings VALUES('account_id',?)", (self.account_id,))
            owner = db.execute("SELECT value FROM settings WHERE key='account_id'").fetchone()[0]
            if owner != self.account_id:
                raise AccountError(409, "storage_owner_mismatch", "存储目录已属于其他账户")
            db.execute(
                "INSERT OR IGNORE INTO settings VALUES('limit_bytes',?)",
                (str(DEFAULT_LIMITS.get(kind, DEFAULT_LIMITS["personal"])),),
            )

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise AccountError(400, "storage_path_invalid", "文件路径不在账户工作区内")
        return candidate

    def setting(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    @staticmethod
    def _usage(db):
        limit = int(db.execute("SELECT value FROM settings WHERE key='limit_bytes'").fetchone()[0])
        used = db.execute(
            "SELECT coalesce(sum(size_bytes),0) FROM blobs WHERE chargeable=1"
        ).fetchone()[0]
        reserved = db.execute("SELECT coalesce(sum(bytes),0) FROM reservations").fetchone()[0]
        return {
            "limit_bytes": limit,
            "used_bytes": used,
            "reserved_bytes": reserved,
            "available_bytes": max(0, limit - used - reserved),
            "over_limit": used + reserved > limit,
        }

    def usage(self):
        with self.connect() as db:
            result = self._usage(db)
            result["file_count"] = db.execute(
                "SELECT count(*) FROM blobs WHERE chargeable=1"
            ).fetchone()[0]
            result["pending_count"] = db.execute(
                "SELECT count(*) FROM entries WHERE kind!='object' "
                "AND key NOT LIKE 'remote:%' AND updated_at>synced_version AND deleted_at IS NULL"
            ).fetchone()[0]
            return result

    def set_limit(self, limit_bytes: int, actor: str, note: str = ""):
        if isinstance(limit_bytes, bool) or not 1 <= limit_bytes <= 100_000 * GB:
            raise AccountError(422, "storage_limit_invalid", "容量必须大于零且不超过 100 TB")
        with self.connect(write=True) as db:
            usage = self._usage(db)
            if limit_bytes < usage["used_bytes"] + usage["reserved_bytes"]:
                raise AccountError(
                    409, "storage_limit_below_usage", "容量不能低于已用与任务预留空间之和"
                )
            db.execute("UPDATE settings SET value=? WHERE key='limit_bytes'", (str(limit_bytes),))
            db.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                (
                    str(uuid4()),
                    actor,
                    "quota_changed",
                    json.dumps(
                        {"previous": usage["limit_bytes"], "next": limit_bytes, "note": note}
                    ),
                    time.time(),
                ),
            )
        return self.usage()

    def reserve(self, reservation_id: str, size: int, kind: str = "upload", *, enforce=True):
        if size < 0:
            raise ValueError("negative reservation")
        with self.connect(write=True) as db:
            current = db.execute(
                "SELECT bytes FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if current:
                return
            if enforce and size > self._usage(db)["available_bytes"]:
                raise AccountError(
                    409, "storage_quota_exceeded", "存储空间不足，请清理文件或联系管理员扩容"
                )
            db.execute(
                "INSERT INTO reservations VALUES(?,?,?,?)",
                (reservation_id, size, kind, time.time()),
            )

    def release(self, reservation_id: str):
        with self.connect(write=True) as db:
            db.execute("DELETE FROM reservations WHERE id=?", (reservation_id,))

    def blob(self, sha256: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM blobs WHERE sha256=?", (sha256,)).fetchone()
            return dict(row) if row else None

    def valid_blob(self, digest: str):
        blob = self.blob(digest)
        if blob:
            path = self.resolve(blob["relative_path"])
            if path.is_file() and file_hash(path) == (digest, blob["size_bytes"]):
                return blob
        return None

    def removed(self, key: str):
        with self.connect() as db:
            return (
                db.execute("SELECT 1 FROM removed_entries WHERE key=?", (key,)).fetchone()
                is not None
            )

    def keep_file(
        self,
        source: Path,
        *,
        chargeable=True,
        expected_sha256=None,
        reservation_id=None,
        preserve=False,
    ):
        source = self.resolve(str(source))
        digest, size = file_hash(source)
        if expected_sha256 and digest != expected_sha256:
            raise AccountError(409, "storage_checksum_mismatch", "文件校验失败，请重新同步")
        suffix = source.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            suffix = ".bin"
        relative = f"objects/durable/{digest[:2]}/{digest}{suffix}"
        target = self.resolve(relative)
        with self.connect(write=True) as db:
            old = db.execute("SELECT * FROM blobs WHERE sha256=?", (digest,)).fetchone()
            extra = size if chargeable and (old is None or not old["chargeable"]) else 0
            held = db.execute(
                "SELECT bytes FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if not preserve and extra > self._usage(db)["available_bytes"] + (
                held[0] if held else 0
            ):
                raise AccountError(
                    409, "storage_quota_exceeded", "存储空间不足，请清理文件或联系管理员扩容"
                )
            if old:
                relative = old["relative_path"]
                target = self.resolve(relative)
            if not target.is_file() or file_hash(target) != (digest, size):
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{uuid4().hex}.pending")
                try:
                    try:
                        os.link(source, temporary)
                    except OSError:
                        shutil.copyfile(source, temporary)
                    if file_hash(temporary) != (digest, size):
                        raise AccountError(
                            409, "storage_source_changed", "文件在归档时发生变化，请重试"
                        )
                    with temporary.open("r+b") as handle:
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            db.execute(
                "INSERT INTO blobs VALUES(?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET "
                "chargeable=max(blobs.chargeable,excluded.chargeable)",
                (digest, size, relative, int(chargeable), time.time()),
            )
            db.execute(
                "INSERT INTO sources VALUES(?,?) ON CONFLICT(relative_path) "
                "DO UPDATE SET sha256=excluded.sha256",
                (str(source.relative_to(self.root)).replace("\\", "/"), digest),
            )
            if held:
                db.execute(
                    "UPDATE reservations SET bytes=max(0,bytes-?) WHERE id=?",
                    (extra, reservation_id),
                )
        return self.blob(digest)

    def entry(self, key: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM entries WHERE key=?", (key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["metadata"] = json.loads(result["metadata"])
            return result

    def put_entry(self, key: str, kind: str, digest: str, metadata: dict, thumbnail=None):
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM removed_entries WHERE key=?", (key,)).fetchone():
                return
            old = db.execute("SELECT * FROM entries WHERE key=?", (key,)).fetchone()
            if (
                old
                and old["sha256"] == digest
                and old["metadata"] == encoded
                and old["thumbnail_sha256"] == thumbnail
            ):
                return
            now = time.time()
            asset = metadata.get("asset")
            date = metadata.get("created_at") or (
                asset.get("created_at") if isinstance(asset, dict) else None
            )
            try:
                created_at = min(now, datetime.fromisoformat(date).timestamp()) if date else now
            except (ValueError, TypeError, OverflowError):
                created_at = now
            db.execute(
                "INSERT INTO entries VALUES(?,?,?,?,?,?,?,NULL,0) ON CONFLICT(key) DO UPDATE SET "
                "sha256=excluded.sha256,thumbnail_sha256=excluded.thumbnail_sha256,metadata=excluded.metadata,"
                "updated_at=excluded.updated_at",
                (key, kind, digest, thumbnail, encoded, created_at, now),
            )

    def entries(self, *, kind=None, trash=False, limit=100, offset=0):
        where = "deleted_at IS NOT NULL" if trash else "deleted_at IS NULL"
        values = []
        if kind:
            where += " AND kind=?"
            values.append(kind)
        with self.connect() as db:
            count = db.execute(f"SELECT count(*) FROM entries WHERE {where}", values).fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM entries WHERE {where} "
                "ORDER BY created_at DESC,key LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
            return {
                "total": count,
                "items": [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows],
            }

    def mark_synced(self, key: str, version: float):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE entries SET synced_version=max(synced_version,?) WHERE key=?",
                (version, key),
            )

    def pending_entries(self, *, created_after=0, excluded=(), limit=100):
        excluded = set(excluded)
        result = []
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM entries WHERE deleted_at IS NULL AND kind!='object' "
                "AND key NOT LIKE 'remote:%' AND updated_at>synced_version AND created_at>=? "
                "ORDER BY created_at,key",
                (created_after,),
            )
            for row in rows:
                if row["key"] in excluded:
                    continue
                result.append({**dict(row), "metadata": json.loads(row["metadata"])})
                if len(result) >= limit:
                    break
        return result

    def select_sync_target(self, target: str):
        with self.connect(write=True) as db:
            old = db.execute("SELECT value FROM settings WHERE key='last_sync_target'").fetchone()
            if old and json.loads(old[0]) != target:
                db.execute("UPDATE entries SET synced_version=0")
                db.execute(
                    "UPDATE jobs SET status='cancelled' "
                    "WHERE id LIKE 'send:%' AND status!='completed'"
                )
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES('last_sync_target',?)",
                (json.dumps(target),),
            )

    def trash(self, key: str, *, restore=False):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE entries SET deleted_at=? WHERE key=?",
                (None if restore else time.time(), key),
            )

    def purge(self, key: str):
        with self.connect(write=True) as db:
            entry = db.execute("SELECT * FROM entries WHERE key=?", (key,)).fetchone()
            if entry is None or entry["deleted_at"] is None:
                raise AccountError(409, "storage_trash_required", "请先将记录移入回收站")
            for digest in {entry["sha256"], entry["thumbnail_sha256"]} - {None}:
                shared = db.execute(
                    "SELECT 1 FROM entries WHERE key!=? AND (sha256=? OR thumbnail_sha256=?)",
                    (key, digest, digest),
                ).fetchone()
                if shared:
                    continue
                blob = db.execute("SELECT * FROM blobs WHERE sha256=?", (digest,)).fetchone()
                if blob:
                    paths = [
                        row[0]
                        for row in db.execute(
                            "SELECT relative_path FROM sources WHERE sha256=?", (digest,)
                        )
                    ]
                    paths.append(blob["relative_path"])
                    for relative in set(paths):
                        path = self.resolve(relative)
                        if path.is_file() and file_hash(path)[0] == digest:
                            path.unlink()
                    db.execute("DELETE FROM sources WHERE sha256=?", (digest,))
                    db.execute("DELETE FROM blobs WHERE sha256=?", (digest,))
            db.execute("DELETE FROM entries WHERE key=?", (key,))
            db.execute("INSERT OR REPLACE INTO removed_entries VALUES(?,?)", (key, time.time()))
        return self.usage()

    def forget_object_guards(self, digests: set[str]):
        """Used only after checking all live model references to these originals."""
        with self.connect(write=True) as db:
            for digest in digests:
                db.execute("DELETE FROM entries WHERE kind='object' AND sha256=?", (digest,))

    def audit(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM audit ORDER BY created_at DESC LIMIT 100")
            ]

    def save_job(self, job_id, status, payload, *, completed=0, total=0, error=None):
        now = time.time()
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "status=excluded.status,payload=excluded.payload,completed=excluded.completed,total=excluded.total,"
                "error=excluded.error,updated_at=excluded.updated_at",
                (
                    job_id,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    completed,
                    total,
                    error,
                    now,
                    now,
                ),
            )

    def jobs(self, *, internal=False):
        with self.connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM jobs WHERE status NOT IN ('completed','cancelled') "
                    "ORDER BY created_at DESC"
                    if internal
                    else "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100"
                )
            ]
            for row in rows:
                payload = json.loads(row.pop("payload"))
                if internal:
                    row["payload"] = payload
            return rows
