"""Validate edit ownership in the same SQLite transaction as each business write."""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
import time

from ..access_context import database_edit_fence, request_edit_fence
from .repository import AccountError


class FencedRepository:
    def __init__(self, repository):
        self.repository = repository

    def __getattr__(self, name):
        target = getattr(self.repository, name)
        if not inspect.iscoroutinefunction(target):
            return target

        async def invoke(*args, **kwargs):
            fence = request_edit_fence.get()
            # Child tasks keep tenant/actor identity, but a submitted durable job
            # is not tied to the lifetime of its initiating browser's edit lease.
            if fence and fence.request_task_id != id(asyncio.current_task()):
                fence = None
            token = database_edit_fence.set(fence)
            try:
                return await target(*args, **kwargs)
            finally:
                database_edit_fence.reset(token)

        return invoke


class FencedConnection(sqlite3.Connection):
    edit_fence = None

    def _check(self, sql: str):
        fence = self.edit_fence
        keyword = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if not fence or keyword not in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            return
        if not self.in_transaction:
            super().execute("BEGIN IMMEDIATE")
        # ATTACH + BEGIN IMMEDIATE serializes against acquire/revoke in the
        # identity database, closing the check-then-write race between workers.
        for project_id in fence.project_ids:
            row = (
                super()
                .execute(
                    "SELECT 1 FROM authz.project_edit_leases l "
                    "JOIN authz.auth_sessions s ON s.token_hash=l.session_hash "
                    "JOIN authz.auth_users u ON u.id=l.user_id "
                    "JOIN authz.auth_accounts a ON a.id=l.account_id "
                    "WHERE l.account_id=? AND l.project_id=? AND l.session_hash=? "
                    "AND l.editor_id=? AND l.token_hash=? AND l.expires_at>? "
                    "AND s.expires_at>? AND u.status='active' AND a.status='active'",
                    (
                        fence.account_id,
                        project_id,
                        fence.session_hash,
                        fence.editor_id,
                        fence.token_hash,
                        time.time(),
                        time.time(),
                    ),
                )
                .fetchone()
            )
            if row is None:
                raise AccountError(423, "edit_lease_lost", "编辑权已失效，未提交修改已保留")

    def execute(self, sql, parameters=()):
        self._check(sql)
        return super().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        self._check(sql)
        return super().executemany(sql, seq_of_parameters)
