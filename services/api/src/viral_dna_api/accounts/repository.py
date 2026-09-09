from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ..access_context import AccountAccess

SESSION_SECONDS = 12 * 60 * 60
ADMIN_SESSION_SECONDS = 2 * 60 * 60
LEASE_SECONDS = 120
INVITATION_SECONDS = 72 * 60 * 60
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
PHONE_PATTERN = r"^1[3-9][0-9]{9}$"


class AccountError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(token.encode(), b"viraldna-csrf-v1", "sha256").hexdigest()


def validate_password_length(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AccountError(422, "password_length", "密码需要 8–128 个字符")


def password_hash(password: str) -> str:
    validate_password_length(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=32768,
        r=8,
        p=3,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )
    return f"scrypt$32768$8$3${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str | None) -> bool:
    try:
        algorithm, n, r, p, salt, expected = (encoded or "").split("$")
        if algorithm != "scrypt" or (n, r, p) != ("32768", "8", "3"):
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=64 * 1024 * 1024,
            dklen=32,
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def username_key(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(PHONE_PATTERN, normalized):
        raise AccountError(422, "username_invalid", "手机号必须为 11 位中国大陆手机号")
    return normalized


SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_accounts (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('personal','enterprise')),
 name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', workspace_id TEXT NOT NULL UNIQUE,
 location_id TEXT NOT NULL UNIQUE, workspace_root TEXT NOT NULL UNIQUE,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_users (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES auth_accounts(id),
 username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('owner','member')), password_hash TEXT,
 status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_users_account ON auth_users(account_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_account_owner ON auth_users(account_id)
 WHERE role='owner';
CREATE TABLE IF NOT EXISTS auth_admins (
 id TEXT PRIMARY KEY, singleton INTEGER NOT NULL UNIQUE CHECK(singleton=1),
 username TEXT NOT NULL UNIQUE CHECK(username='admin'), password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
 principal_type TEXT NOT NULL CHECK(principal_type IN ('user','platform_admin')),
 expires_at REAL NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_principal ON auth_sessions(principal_id);
CREATE TABLE IF NOT EXISTS auth_invitations (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES auth_users(id),
 expires_at REAL NOT NULL, used_at REAL, created_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_invitations_user ON auth_invitations(user_id);
CREATE TABLE IF NOT EXISTS auth_login_attempts (
 attempt_key TEXT PRIMARY KEY, failures INTEGER NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_edit_leases (
 account_id TEXT NOT NULL REFERENCES auth_accounts(id), project_id TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES auth_users(id), session_hash TEXT NOT NULL,
 editor_id TEXT NOT NULL, token_hash TEXT NOT NULL, generation INTEGER NOT NULL,
 expires_at REAL NOT NULL, PRIMARY KEY(account_id,project_id)
);
CREATE TABLE IF NOT EXISTS auth_storage_tokens (
 token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES auth_accounts(id),
 user_id TEXT NOT NULL REFERENCES auth_users(id),device_id TEXT NOT NULL,
 expires_at REAL NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_audit (
 id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL,
 account_id TEXT, subject_id TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_user_reads (
 user_id TEXT NOT NULL, notification_id TEXT NOT NULL, event_version TEXT NOT NULL,
 read_at REAL NOT NULL, PRIMARY KEY(user_id,notification_id)
);
CREATE TABLE IF NOT EXISTS auth_account_runtime (
 account_id TEXT PRIMARY KEY REFERENCES auth_accounts(id), device_id TEXT NOT NULL,
 managed_asset_project TEXT UNIQUE
);
"""


class AccountRepository:
    def __init__(self, path: Path, tenant_root: Path):
        self.path = path.resolve()
        self.tenant_root = tenant_root.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
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

    @staticmethod
    def audit(db, actor: str, action: str, account: str | None = None, subject: str | None = None):
        db.execute(
            "INSERT INTO auth_audit VALUES(?,?,?,?,?,?)",
            (str(uuid4()), actor, action, account, subject, time.time()),
        )

    def initialized(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM auth_admins").fetchone() is not None

    def issue_storage_token(self, access, device_id: str):
        if access.role != "owner":
            raise AccountError(403, "owner_required", "请由账户负责人连接同步设备")
        token = "vdst_" + secrets.token_urlsafe(48)
        now = time.time()
        with self.connect(write=True) as db:
            db.execute(
                "DELETE FROM auth_storage_tokens WHERE account_id=? AND device_id=?",
                (str(access.account_id), device_id),
            )
            db.execute(
                "INSERT INTO auth_storage_tokens VALUES(?,?,?,?,?,?)",
                (
                    token_hash(token),
                    str(access.account_id),
                    str(access.user_id),
                    device_id,
                    now + 30 * 86400,
                    now,
                ),
            )
            self.audit(
                db,
                str(access.user_id),
                "storage_device_connected",
                str(access.account_id),
                device_id,
            )
        return {
            "token": token,
            "expires_at": now + 30 * 86400,
            "account_id": str(access.account_id),
            "account_name": access.account_name,
            "account_kind": access.account_kind,
        }

    def storage_token_session(self, token: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT t.* FROM auth_storage_tokens t JOIN auth_accounts a ON a.id=t.account_id "
                "JOIN auth_users u ON u.id=t.user_id WHERE t.token_hash=? AND t.expires_at>? "
                "AND a.status='active' AND u.status='active' AND u.role='owner'",
                (token_hash(token), time.time()),
            ).fetchone()
            if row is None:
                raise AccountError(
                    401, "storage_device_expired", "服务器连接已失效，请重新登录连接"
                )
            account = db.execute(
                "SELECT * FROM auth_accounts WHERE id=?", (row["account_id"],)
            ).fetchone()
            user = db.execute("SELECT * FROM auth_users WHERE id=?", (row["user_id"],)).fetchone()
        return {
            "access": self.access(account, user),
            "username": user["username"],
            "csrf_token": "",
            "storage_device_id": row["device_id"],
        }

    def revoke_storage_token(self, access, device_id: str):
        with self.connect(write=True) as db:
            db.execute(
                "DELETE FROM auth_storage_tokens WHERE account_id=? AND device_id=?",
                (str(access.account_id), device_id),
            )
            self.audit(
                db, str(access.user_id), "storage_device_revoked", str(access.account_id), device_id
            )

    def bootstrap(
        self,
        *,
        admin_password: str,
        name: str,
        kind: str,
        username: str,
        display_name: str,
        owner_password: str,
        legacy_root: Path,
        account_id: UUID,
        workspace_id: UUID,
        location_id: UUID,
        device_id: UUID | None = None,
        managed_asset_project: str = "default",
    ) -> None:
        """Explicitly bind the existing workspace; never move/delete its files."""
        admin_encoded = password_hash(admin_password)
        owner_encoded = password_hash(owner_password)
        login = username_key(username)
        if kind not in {"personal", "enterprise"}:
            raise AccountError(422, "account_kind_invalid", "请选择个人或企业账户")
        now = time.time()
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM auth_admins").fetchone():
                raise AccountError(409, "already_initialized", "账户系统已经初始化")
            db.execute(
                "INSERT INTO auth_admins VALUES(?,1,'admin',?)", (str(uuid4()), admin_encoded)
            )
            db.execute(
                "INSERT INTO auth_accounts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    str(account_id),
                    kind,
                    name,
                    "active",
                    str(workspace_id),
                    str(location_id),
                    str(legacy_root.resolve()),
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO auth_account_runtime VALUES(?,?,?)",
                (str(account_id), str(device_id or workspace_id), managed_asset_project),
            )
            owner_id = str(uuid4())
            db.execute(
                "INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?)",
                (
                    owner_id,
                    str(account_id),
                    login,
                    display_name,
                    "owner",
                    owner_encoded,
                    "active",
                    now,
                ),
            )
            self.audit(db, owner_id, "legacy_workspace_claimed", str(account_id))

    def accounts(self) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT a.id,a.kind,a.name,a.status,a.created_at,a.updated_at,"
                    "(SELECT managed_asset_project FROM auth_account_runtime r "
                    "WHERE r.account_id=a.id) "
                    "AS managed_asset_project,"
                    "(SELECT count(*) FROM auth_users u WHERE u.account_id=a.id "
                    "AND u.status!='disabled') AS member_count FROM auth_accounts a "
                    "ORDER BY a.created_at DESC"
                )
            ]

    def runtime_accounts(self) -> list[AccountAccess]:
        with self.connect() as db:
            return [self.access(row) for row in db.execute("SELECT * FROM auth_accounts")]

    def access(self, row, user=None, session_hash="") -> AccountAccess:
        with self.connect() as db:
            runtime = db.execute(
                "SELECT device_id FROM auth_account_runtime WHERE account_id=?", (row["id"],)
            ).fetchone()
        return AccountAccess(
            account_id=UUID(row["id"]),
            account_name=row["name"],
            account_kind=row["kind"],
            workspace_id=UUID(row["workspace_id"]),
            storage_location_id=UUID(row["location_id"]),
            workspace_root=Path(row["workspace_root"]),
            user_id=UUID(user["id"]) if user else None,
            display_name=user["display_name"] if user else "后台任务",
            role=user["role"] if user else "member",
            session_hash=session_hash,
            device_id=UUID(runtime["device_id"]) if runtime else UUID(row["workspace_id"]),
        )

    def managed_asset_project(self, account_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT managed_asset_project FROM auth_account_runtime WHERE account_id=?",
                (account_id,),
            ).fetchone()
            return row["managed_asset_project"] if row else None

    def _invitation(self, db, user_id: str, actor: str) -> str:
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM auth_invitations WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO auth_invitations VALUES(?,?,?,NULL,?)",
            (token_hash(token), user_id, time.time() + INVITATION_SECONDS, actor),
        )
        return token

    def create_account(
        self, *, kind: str, name: str, username: str, display_name: str, actor: str
    ) -> dict:
        login = username_key(username)
        account_id, user_id = str(uuid4()), str(uuid4())
        now = time.time()
        root = self.tenant_root / account_id
        try:
            with self.connect(write=True) as db:
                workspace_id = str(uuid4())
                db.execute(
                    "INSERT INTO auth_accounts VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        account_id,
                        kind,
                        name,
                        "active",
                        workspace_id,
                        str(uuid4()),
                        str(root),
                        now,
                        now,
                    ),
                )
                db.execute(
                    "INSERT INTO auth_account_runtime VALUES(?,?,NULL)", (account_id, workspace_id)
                )
                db.execute(
                    "INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, account_id, login, display_name, "owner", None, "pending", now),
                )
                token = self._invitation(db, user_id, actor)
                self.audit(db, actor, "account_created", account_id, user_id)
        except sqlite3.IntegrityError as exc:
            raise AccountError(
                409, "username_exists", "该手机号已被使用，请使用独立手机号"
            ) from exc
        return {"id": account_id, "activation_token": token, "username": login}

    def update_account(
        self,
        account_id: str,
        *,
        actor: str,
        name: str | None = None,
        status: str | None = None,
        managed_asset_project: str | None = None,
    ) -> None:
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM auth_accounts WHERE id=?", (account_id,)).fetchone()
            if not row:
                raise AccountError(404, "account_missing", "账户不存在")
            if managed_asset_project is not None:
                project = managed_asset_project.strip() or None
                used = db.execute(
                    "SELECT 1 FROM auth_account_runtime WHERE managed_asset_project=? "
                    "AND account_id!=?",
                    (project, account_id),
                ).fetchone()
                if used:
                    raise AccountError(409, "catalog_assigned", "该真人资产目录已属于其他账户")
                db.execute(
                    "INSERT INTO auth_account_runtime VALUES(?,?,?) ON CONFLICT(account_id) "
                    "DO UPDATE SET managed_asset_project=excluded.managed_asset_project",
                    (account_id, row["workspace_id"], project),
                )
            db.execute(
                "UPDATE auth_accounts SET name=?,status=?,updated_at=? WHERE id=?",
                (name or row["name"], status or row["status"], time.time(), account_id),
            )
            if status == "disabled":
                db.execute("DELETE FROM auth_storage_tokens WHERE account_id=?", (account_id,))
                db.execute(
                    "DELETE FROM auth_sessions WHERE principal_id IN "
                    "(SELECT id FROM auth_users WHERE account_id=?)",
                    (account_id,),
                )
                db.execute("DELETE FROM project_edit_leases WHERE account_id=?", (account_id,))
            self.audit(db, actor, "account_updated", account_id)

    def members(self, account_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,username,display_name,role,status,created_at FROM auth_users "
                    "WHERE account_id=? ORDER BY role DESC,created_at",
                    (account_id,),
                )
            ]

    def invite(self, account_id: str, *, username: str, display_name: str, actor: str) -> dict:
        login = username_key(username)
        user_id = str(uuid4())
        try:
            with self.connect(write=True) as db:
                row = db.execute("SELECT * FROM auth_accounts WHERE id=?", (account_id,)).fetchone()
                if not row or row["kind"] != "enterprise" or row["status"] != "active":
                    raise AccountError(409, "enterprise_required", "只有启用的企业账户能邀请成员")
                db.execute(
                    "INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        account_id,
                        login,
                        display_name,
                        "member",
                        None,
                        "pending",
                        time.time(),
                    ),
                )
                token = self._invitation(db, user_id, actor)
                self.audit(db, actor, "member_invited", account_id, user_id)
        except sqlite3.IntegrityError as exc:
            raise AccountError(
                409, "username_exists", "该手机号已被使用，企业成员必须使用独立手机号"
            ) from exc
        return {"id": user_id, "activation_token": token, "username": login}

    def remove_member(self, account_id: str, user_id: str, actor: str) -> None:
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM auth_users WHERE id=? AND account_id=?", (user_id, account_id)
            ).fetchone()
            if not row:
                raise AccountError(404, "member_missing", "成员不存在")
            if row["role"] == "owner":
                raise AccountError(409, "owner_required", "不能移除企业负责人")
            db.execute("UPDATE auth_users SET status='disabled' WHERE id=?", (user_id,))
            db.execute("DELETE FROM auth_sessions WHERE principal_id=?", (user_id,))
            db.execute("DELETE FROM project_edit_leases WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM auth_storage_tokens WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM auth_invitations WHERE user_id=?", (user_id,))
            self.audit(db, actor, "member_removed", account_id, user_id)

    def reset_link(self, account_id: str, user_id: str, actor: str) -> dict:
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM auth_users WHERE id=? AND account_id=?", (user_id, account_id)
            ).fetchone()
            if not row or row["status"] == "disabled":
                raise AccountError(404, "member_missing", "用户不存在或已停用")
            token = self._invitation(db, user_id, actor)
            self.audit(db, actor, "password_reset_issued", account_id, user_id)
            return {"activation_token": token, "username": row["username"]}

    def restore_member(self, account_id: str, user_id: str, actor: str) -> dict:
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT * FROM auth_users WHERE id=? AND account_id=?", (user_id, account_id)
            ).fetchone()
            if not row or row["role"] != "member" or row["status"] != "disabled":
                raise AccountError(409, "member_not_removed", "只能重新邀请已移除的企业成员")
            db.execute(
                "UPDATE auth_users SET status='pending',password_hash=NULL WHERE id=?", (user_id,)
            )
            token = self._invitation(db, user_id, actor)
            self.audit(db, actor, "member_reinvited", account_id, user_id)
            return {"activation_token": token, "username": row["username"]}

    def activate(self, token: str, password: str) -> None:
        encoded = password_hash(password)
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT i.*,u.account_id,u.status,a.status AS account_status "
                "FROM auth_invitations i JOIN auth_users u ON u.id=i.user_id "
                "JOIN auth_accounts a ON a.id=u.account_id WHERE i.token_hash=?",
                (token_hash(token),),
            ).fetchone()
            if (
                not row
                or row["used_at"]
                or row["expires_at"] <= time.time()
                or row["status"] == "disabled"
                or row["account_status"] != "active"
            ):
                raise AccountError(410, "invitation_expired", "链接已失效，请联系管理员重新邀请")
            db.execute(
                "UPDATE auth_users SET password_hash=?,status='active' WHERE id=?",
                (encoded, row["user_id"]),
            )
            db.execute(
                "UPDATE auth_invitations SET used_at=? WHERE token_hash=?",
                (time.time(), token_hash(token)),
            )
            db.execute("DELETE FROM auth_sessions WHERE principal_id=?", (row["user_id"],))
            db.execute("DELETE FROM auth_storage_tokens WHERE user_id=?", (row["user_id"],))
            db.execute("DELETE FROM project_edit_leases WHERE user_id=?", (row["user_id"],))
            self.audit(db, row["user_id"], "password_set", row["account_id"], row["user_id"])

    def login(self, username: str, password: str, *, admin: bool, remote: str) -> str:
        username = username.strip().casefold() if admin else username_key(username)
        validate_password_length(password)
        failed_message = (
            "登录名或密码不正确，或账户未启用" if admin else "手机号或密码不正确，或账户未启用"
        )
        # Persist both IP and IP+login counters; account names never enter logs.
        keys = [token_hash(f"ip:{remote}"), token_hash(f"{remote}:{admin}:{username.casefold()}")]
        now = time.time()
        with self.connect(write=True) as db:
            db.execute("DELETE FROM auth_login_attempts WHERE expires_at<=?", (now,))
            for key, limit in zip(keys, (30, 8), strict=True):
                row = db.execute(
                    "SELECT failures FROM auth_login_attempts WHERE attempt_key=?", (key,)
                ).fetchone()
                if row and row["failures"] >= limit:
                    raise AccountError(429, "login_throttled", "尝试次数过多，请 15 分钟后重试")
                db.execute(
                    "INSERT INTO auth_login_attempts VALUES(?,1,?) ON CONFLICT(attempt_key) "
                    "DO UPDATE SET failures=failures+1",
                    (key, now + 900),
                )
            table = "auth_admins" if admin else "auth_users"
            row = db.execute(
                f"SELECT * FROM {table} WHERE username=?", (username.strip().casefold(),)
            ).fetchone()
        # Equal-cost verification for unknown names, without persistent dummy credentials.
        dummy = "scrypt$32768$8$3$" + "00" * 16 + "$" + "00" * 32
        matches = password_matches(password, row["password_hash"] if row else dummy)
        if not row or not matches or (not admin and row["status"] != "active"):
            raise AccountError(401, "login_failed", failed_message)
        with self.connect(write=True) as db:
            current = db.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone()
            if not current or current["password_hash"] != row["password_hash"]:
                raise AccountError(401, "login_failed", "登录状态已改变，请重新登录")
            if not admin:
                account = db.execute(
                    "SELECT status FROM auth_accounts WHERE id=?", (current["account_id"],)
                ).fetchone()
                if current["status"] != "active" or not account or account["status"] != "active":
                    raise AccountError(401, "login_failed", failed_message)
            db.execute("DELETE FROM auth_login_attempts WHERE attempt_key=?", (keys[1],))
            token = secrets.token_urlsafe(32)
            duration = ADMIN_SESSION_SECONDS if admin else SESSION_SECONDS
            db.execute(
                "INSERT INTO auth_sessions VALUES(?,?,?,?,?)",
                (
                    token_hash(token),
                    row["id"],
                    "platform_admin" if admin else "user",
                    now + duration,
                    now,
                ),
            )
            self.audit(db, row["id"], "login")
            return token

    def session(self, token: str, *, admin: bool = False) -> dict:
        with self.connect() as db:
            session = db.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=? AND "
                "principal_type=? AND expires_at>?",
                (token_hash(token), "platform_admin" if admin else "user", time.time()),
            ).fetchone()
            if not session:
                raise AccountError(401, "login_required", "请先登录")
            if admin:
                row = db.execute(
                    "SELECT id FROM auth_admins WHERE id=?", (session["principal_id"],)
                ).fetchone()
                if not row:
                    raise AccountError(401, "login_required", "请先登录")
                return {
                    "admin_id": row["id"],
                    "display_name": "admin",
                    "principal_type": "platform_admin",
                    "auth_mode": "password",
                    "csrf_token": csrf_token(token),
                }
            user = db.execute(
                "SELECT * FROM auth_users WHERE id=?", (session["principal_id"],)
            ).fetchone()
            account = (
                db.execute(
                    "SELECT * FROM auth_accounts WHERE id=?", (user["account_id"],)
                ).fetchone()
                if user
                else None
            )
            if (
                not user
                or user["status"] != "active"
                or not account
                or account["status"] != "active"
            ):
                raise AccountError(401, "login_required", "账户已停用或成员资格已撤销")
            return {
                "access": self.access(account, user, token_hash(token)),
                "username": user["username"],
                "csrf_token": csrf_token(token),
            }

    def logout(self, token: str) -> None:
        digest = token_hash(token)
        with self.connect(write=True) as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest,))
            db.execute("DELETE FROM project_edit_leases WHERE session_hash=?", (digest,))

    def change_password(self, token: str, old: str, new: str, *, admin: bool) -> None:
        session = self.session(token, admin=admin)
        user_id = session["admin_id"] if admin else str(session["access"].user_id)
        table = "auth_admins" if admin else "auth_users"
        with self.connect() as db:
            row = db.execute(f"SELECT password_hash FROM {table} WHERE id=?", (user_id,)).fetchone()
        if not password_matches(old, row["password_hash"]):
            raise AccountError(422, "password_incorrect", "当前密码不正确")
        encoded = password_hash(new)
        with self.connect(write=True) as db:
            changed = db.execute(
                f"UPDATE {table} SET password_hash=? WHERE id=? AND password_hash=?",
                (encoded, user_id, row["password_hash"]),
            )
            if not changed.rowcount:
                raise AccountError(409, "password_changed", "密码已修改，请重新登录")
            db.execute("DELETE FROM auth_sessions WHERE principal_id=?", (user_id,))
            db.execute("DELETE FROM project_edit_leases WHERE user_id=?", (user_id,))
            self.audit(db, user_id, "password_changed")
            if not admin:
                db.execute("DELETE FROM auth_storage_tokens WHERE user_id=?", (user_id,))

    def lease(
        self,
        access: AccountAccess,
        project_id: str,
        *,
        editor_id: str = "",
        token: str = "",
        action: Literal["read", "acquire", "renew", "release"] = "read",
    ) -> dict:
        now = time.time()
        account_id, user_id = str(access.account_id), str(access.user_id)
        with self.connect(write=action != "read") as db:
            valid = db.execute(
                "SELECT 1 FROM auth_sessions s JOIN auth_users u ON u.id=s.principal_id "
                "JOIN auth_accounts a ON a.id=u.account_id WHERE s.token_hash=? "
                "AND s.principal_type='user' AND s.expires_at>? AND u.id=? "
                "AND a.id=? AND u.status='active' AND a.status='active'",
                (access.session_hash, now, user_id, account_id),
            ).fetchone()
            if not valid:
                raise AccountError(401, "login_required", "登录已失效，请重新登录")
            row = db.execute(
                "SELECT l.*,u.display_name FROM project_edit_leases l "
                "JOIN auth_users u ON u.id=l.user_id "
                "WHERE l.account_id=? AND l.project_id=?",
                (account_id, project_id),
            ).fetchone()
            active = row is not None and row["expires_at"] > now
            owns = bool(
                active
                and row["session_hash"] == access.session_hash
                and row["editor_id"] == editor_id
                and hmac.compare_digest(row["token_hash"], token_hash(token))
            )
            if action == "release":
                if owns:
                    db.execute(
                        "UPDATE project_edit_leases SET expires_at=0 "
                        "WHERE account_id=? AND project_id=?",
                        (account_id, project_id),
                    )
                return {"editable": False, "occupied": bool(active and not owns)}
            if action == "renew" and not owns:
                raise AccountError(423, "edit_lease_lost", "编辑权已失效，未提交修改已保留")
            if action == "acquire" and not active:
                generation = (row["generation"] + 1) if row else 1
                db.execute(
                    "INSERT INTO project_edit_leases VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(account_id,project_id) DO UPDATE SET "
                    "user_id=excluded.user_id,session_hash=excluded.session_hash,"
                    "editor_id=excluded.editor_id,token_hash=excluded.token_hash,"
                    "generation=excluded.generation,expires_at=excluded.expires_at",
                    (
                        account_id,
                        project_id,
                        user_id,
                        access.session_hash,
                        editor_id,
                        token_hash(token),
                        generation,
                        now + LEASE_SECONDS,
                    ),
                )
                self.audit(db, user_id, "project_edit_acquired", account_id, project_id)
                return {
                    "editable": True,
                    "occupied": True,
                    "display_name": access.display_name,
                    "expires_at": now + LEASE_SECONDS,
                    "generation": generation,
                }
            if action in {"acquire", "renew"} and owns:
                db.execute(
                    "UPDATE project_edit_leases SET expires_at=? WHERE account_id=? "
                    "AND project_id=?",
                    (now + LEASE_SECONDS, account_id, project_id),
                )
            return {
                "editable": owns,
                "occupied": active,
                "display_name": row["display_name"] if active else None,
                "expires_at": now + LEASE_SECONDS
                if owns and action != "read"
                else row["expires_at"]
                if active
                else None,
                "generation": row["generation"] if active else None,
            }

    def require_lease(self, access: AccountAccess, project_id: str, editor_id: str, token: str):
        state = self.lease(access, project_id, editor_id=editor_id, token=token)
        if not state["editable"]:
            raise AccountError(423, "project_read_only", "当前项目为只读，请先取得编辑权")

    def read_notifications(self, user_id: str) -> dict[str, str]:
        with self.connect() as db:
            return {
                row["notification_id"]: row["event_version"]
                for row in db.execute(
                    "SELECT notification_id,event_version FROM notification_user_reads "
                    "WHERE user_id=?",
                    (user_id,),
                )
            }

    def mark_notifications(self, user_id: str, items: list[tuple[str, str]]) -> None:
        with self.connect(write=True) as db:
            db.executemany(
                "INSERT INTO notification_user_reads VALUES(?,?,?,?) "
                "ON CONFLICT(user_id,notification_id) DO UPDATE SET "
                "event_version=excluded.event_version,read_at=excluded.read_at",
                [(user_id, item_id, version, time.time()) for item_id, version in items],
            )
