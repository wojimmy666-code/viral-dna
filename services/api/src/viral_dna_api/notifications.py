from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from .chinese import to_simplified
from .workspace_catalog import AccountContextService, default_account_catalog_path


def utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationLevel(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationCategory(StrEnum):
    ANALYSIS = "analysis"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    EXPORT = "export"
    ASSET = "asset"
    SYSTEM = "system"


class NotificationActionKind(StrEnum):
    PRODUCTION_SHOT = "production_shot"
    ANALYSIS_RECORD = "analysis_record"
    MODEL_SETTINGS = "model_settings"
    ASSET_LIBRARY = "asset_library"


SENSITIVE_ACTION_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
}


class AccountNotification(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    workspace_id: UUID | None = None
    category: NotificationCategory
    level: NotificationLevel
    status: NotificationStatus
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(default="", max_length=1000)
    event_key: str = Field(min_length=1, max_length=240)
    action_kind: NotificationActionKind | None = None
    action_label: str | None = Field(default=None, max_length=40)
    action_payload: dict[str, str] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("title", "message", "action_label")
    @classmethod
    def normalize_chinese(cls, value: str | None) -> str | None:
        return to_simplified(value) if value is not None else None

    @field_validator("action_payload")
    @classmethod
    def reject_sensitive_action_payload(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("通知跳转参数过多")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key or any(part in key.casefold() for part in SENSITIVE_ACTION_KEY_PARTS):
                raise ValueError("通知中不能保存密钥或认证信息")
            text = str(raw_value).strip()
            if len(key) > 80 or len(text) > 500:
                raise ValueError("通知跳转参数过长")
            normalized[key] = text
        return normalized


class NotificationListResponse(BaseModel):
    items: list[AccountNotification] = Field(default_factory=list)
    unread_count: int = Field(default=0, ge=0)


class NotificationReadAllResponse(BaseModel):
    updated_count: int = Field(default=0, ge=0)


class NotificationRepository(Protocol):
    async def initialize(self) -> None: ...

    async def upsert(self, notification: AccountNotification) -> AccountNotification: ...

    async def list_for_account(
        self,
        account_id: UUID,
        *,
        status: NotificationStatus | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[AccountNotification]: ...

    async def mark_read(
        self,
        account_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> AccountNotification | None: ...

    async def mark_all_read(self, account_id: UUID, read_at: datetime) -> int: ...


class InMemoryNotificationRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, AccountNotification] = {}
        self._event_ids: dict[tuple[UUID, str], UUID] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def upsert(self, notification: AccountNotification) -> AccountNotification:
        async with self._lock:
            key = (notification.account_id, notification.event_key)
            current_id = self._event_ids.get(key)
            if current_id is None:
                stored = notification.model_copy(deep=True)
                self._items[stored.id] = stored
                self._event_ids[key] = stored.id
                return stored.model_copy(deep=True)
            current = self._items[current_id]
            changed = any(
                getattr(current, name) != getattr(notification, name)
                for name in (
                    "workspace_id",
                    "category",
                    "level",
                    "status",
                    "title",
                    "message",
                    "action_kind",
                    "action_label",
                    "action_payload",
                )
            )
            stored = notification.model_copy(
                update={
                    "id": current.id,
                    "created_at": current.created_at,
                    "updated_at": notification.updated_at if changed else current.updated_at,
                    "read_at": None if changed else current.read_at,
                },
                deep=True,
            )
            self._items[current.id] = stored
            return stored.model_copy(deep=True)

    async def list_for_account(
        self,
        account_id: UUID,
        *,
        status: NotificationStatus | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[AccountNotification]:
        async with self._lock:
            items = [
                item
                for item in self._items.values()
                if item.account_id == account_id
                and (status is None or item.status == status)
                and (not unread_only or item.read_at is None)
            ]
            items.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
            return [item.model_copy(deep=True) for item in items[:limit]]

    async def mark_read(
        self,
        account_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> AccountNotification | None:
        async with self._lock:
            current = self._items.get(notification_id)
            if current is None or current.account_id != account_id:
                return None
            updated = current.model_copy(update={"read_at": read_at}, deep=True)
            self._items[current.id] = updated
            return updated.model_copy(deep=True)

    async def mark_all_read(self, account_id: UUID, read_at: datetime) -> int:
        async with self._lock:
            updated_count = 0
            for notification_id, current in list(self._items.items()):
                if current.account_id != account_id or current.read_at is not None:
                    continue
                self._items[notification_id] = current.model_copy(update={"read_at": read_at})
                updated_count += 1
            return updated_count


class SQLiteNotificationRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS account_notifications (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    workspace_id TEXT,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    action_kind TEXT,
                    action_label TEXT,
                    action_payload_json TEXT NOT NULL,
                    read_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(account_id, event_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_account_notifications_feed
                ON account_notifications(account_id, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_account_notifications_unread
                ON account_notifications(account_id, read_at, updated_at DESC)
                """
            )

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> AccountNotification:
        return AccountNotification.model_validate(
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "workspace_id": row["workspace_id"],
                "category": row["category"],
                "level": row["level"],
                "status": row["status"],
                "title": row["title"],
                "message": row["message"],
                "event_key": row["event_key"],
                "action_kind": row["action_kind"],
                "action_label": row["action_label"],
                "action_payload": json.loads(row["action_payload_json"] or "{}"),
                "read_at": row["read_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    async def upsert(self, notification: AccountNotification) -> AccountNotification:
        async with self._lock:
            return await asyncio.to_thread(self._upsert, notification)

    def _upsert(self, notification: AccountNotification) -> AccountNotification:
        self._initialize()
        serialized = notification.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_notifications (
                    id, account_id, workspace_id, category, level, status,
                    title, message, event_key, action_kind, action_label,
                    action_payload_json, read_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, event_key) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    category = excluded.category,
                    level = excluded.level,
                    status = excluded.status,
                    title = excluded.title,
                    message = excluded.message,
                    action_kind = excluded.action_kind,
                    action_label = excluded.action_label,
                    action_payload_json = excluded.action_payload_json,
                    read_at = CASE
                        WHEN account_notifications.status != excluded.status
                          OR account_notifications.level != excluded.level
                          OR account_notifications.title != excluded.title
                          OR account_notifications.message != excluded.message
                        THEN NULL
                        ELSE account_notifications.read_at
                    END,
                    updated_at = CASE
                        WHEN account_notifications.status != excluded.status
                          OR account_notifications.level != excluded.level
                          OR account_notifications.title != excluded.title
                          OR account_notifications.message != excluded.message
                        THEN excluded.updated_at
                        ELSE account_notifications.updated_at
                    END
                """,
                (
                    serialized["id"],
                    serialized["account_id"],
                    serialized["workspace_id"],
                    serialized["category"],
                    serialized["level"],
                    serialized["status"],
                    serialized["title"],
                    serialized["message"],
                    serialized["event_key"],
                    serialized["action_kind"],
                    serialized["action_label"],
                    json.dumps(serialized["action_payload"], ensure_ascii=False),
                    serialized["read_at"],
                    serialized["created_at"],
                    serialized["updated_at"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM account_notifications WHERE account_id = ? AND event_key = ?",
                (serialized["account_id"], serialized["event_key"]),
            ).fetchone()
        if row is None:
            raise RuntimeError("通知写入失败")
        return self._row_to_model(row)

    async def list_for_account(
        self,
        account_id: UUID,
        *,
        status: NotificationStatus | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[AccountNotification]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_for_account,
                account_id,
                status,
                unread_only,
                limit,
            )

    def _list_for_account(
        self,
        account_id: UUID,
        status: NotificationStatus | None,
        unread_only: bool,
        limit: int,
    ) -> list[AccountNotification]:
        self._initialize()
        clauses = ["account_id = ?"]
        parameters: list[object] = [str(account_id)]
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status.value)
        if unread_only:
            clauses.append("read_at IS NULL")
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM account_notifications
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._row_to_model(row) for row in rows]

    async def mark_read(
        self,
        account_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> AccountNotification | None:
        async with self._lock:
            return await asyncio.to_thread(
                self._mark_read,
                account_id,
                notification_id,
                read_at,
            )

    def _mark_read(
        self,
        account_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> AccountNotification | None:
        self._initialize()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE account_notifications
                SET read_at = COALESCE(read_at, ?)
                WHERE id = ? AND account_id = ?
                """,
                (read_at.isoformat(), str(notification_id), str(account_id)),
            )
            row = connection.execute(
                "SELECT * FROM account_notifications WHERE id = ? AND account_id = ?",
                (str(notification_id), str(account_id)),
            ).fetchone()
        return self._row_to_model(row) if row is not None else None

    async def mark_all_read(self, account_id: UUID, read_at: datetime) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._mark_all_read, account_id, read_at)

    def _mark_all_read(self, account_id: UUID, read_at: datetime) -> int:
        self._initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE account_notifications
                SET read_at = ?
                WHERE account_id = ? AND read_at IS NULL
                """,
                (read_at.isoformat(), str(account_id)),
            )
            return max(0, cursor.rowcount)


class NotificationServiceError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotificationPublisher(Protocol):
    async def publish(
        self,
        *,
        category: NotificationCategory | str,
        level: NotificationLevel | str,
        status: NotificationStatus | str,
        title: str,
        message: str,
        event_key: str,
        action_kind: NotificationActionKind | str | None = None,
        action_label: str | None = None,
        action_payload: dict[str, str] | None = None,
    ) -> AccountNotification: ...


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        account_context: AccountContextService,
    ) -> None:
        self.repository = repository
        self.account_context = account_context

    async def initialize(self) -> None:
        await self.repository.initialize()

    async def publish(
        self,
        *,
        category: NotificationCategory | str,
        level: NotificationLevel | str,
        status: NotificationStatus | str,
        title: str,
        message: str,
        event_key: str,
        action_kind: NotificationActionKind | str | None = None,
        action_label: str | None = None,
        action_payload: dict[str, str] | None = None,
    ) -> AccountNotification:
        context = await self.account_context.ensure_current()
        notification = AccountNotification(
            account_id=context.account.id,
            workspace_id=context.active_workspace.id,
            category=category,
            level=level,
            status=status,
            title=title,
            message=message,
            event_key=event_key,
            action_kind=action_kind,
            action_label=action_label,
            action_payload=action_payload or {},
        )
        return await self.repository.upsert(notification)

    async def list_notifications(
        self,
        *,
        status: NotificationStatus | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> NotificationListResponse:
        context = await self.account_context.ensure_current()
        items = await self.repository.list_for_account(
            context.account.id,
            status=status,
            unread_only=unread_only,
            limit=limit,
        )
        unread = await self.repository.list_for_account(
            context.account.id,
            unread_only=True,
            limit=1000,
        )
        return NotificationListResponse(items=items, unread_count=len(unread))

    async def mark_read(self, notification_id: UUID) -> AccountNotification:
        account = await self.account_context.current_account()
        updated = await self.repository.mark_read(account.id, notification_id, utc_now())
        if updated is None:
            raise NotificationServiceError(404, "通知不存在")
        return updated

    async def mark_all_read(self) -> NotificationReadAllResponse:
        account = await self.account_context.current_account()
        updated = await self.repository.mark_all_read(account.id, utc_now())
        return NotificationReadAllResponse(updated_count=updated)


def default_notification_database_path() -> Path:
    configured = os.getenv("VIRAL_DNA_NOTIFICATION_DB_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    return default_account_catalog_path().with_name("notifications.sqlite3")


def create_notification_repository() -> NotificationRepository:
    if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
        return InMemoryNotificationRepository()
    return SQLiteNotificationRepository(default_notification_database_path())


def create_notification_service(
    account_context: AccountContextService,
) -> NotificationService:
    return NotificationService(create_notification_repository(), account_context)
