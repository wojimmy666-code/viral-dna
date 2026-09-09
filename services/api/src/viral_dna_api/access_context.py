"""Verified request context, inherited by background tasks but never globally switched."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class AccountAccess:
    account_id: UUID
    account_name: str
    account_kind: str
    workspace_id: UUID
    storage_location_id: UUID
    workspace_root: Path
    user_id: UUID | None = None
    display_name: str = ""
    role: str = "member"
    session_hash: str = ""
    device_id: UUID | None = None


account_access: ContextVar[AccountAccess | None] = ContextVar("account_access", default=None)


@dataclass(frozen=True)
class EditFence:
    account_id: str
    project_ids: tuple[str, ...]
    session_hash: str
    editor_id: str
    token_hash: str
    auth_database: Path
    request_task_id: int


request_edit_fence: ContextVar[EditFence | None] = ContextVar("request_edit_fence", default=None)
database_edit_fence: ContextVar[EditFence | None] = ContextVar("database_edit_fence", default=None)
