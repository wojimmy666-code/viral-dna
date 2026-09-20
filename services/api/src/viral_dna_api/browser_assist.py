"""Local-desktop-only browser collection, isolated by account, user and device."""

from __future__ import annotations

import asyncio
import importlib.util
import ipaddress
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .access_context import account_access
from .accounts.runtime import password_auth_enabled
from .link_ingestion import (
    WORKER_IMPORT_ROOT,
    LinkCredentialError,
    LinkIngestionError,
    _stop_download_process,
    configured_timeout,
)
from .models import SourceType
from .platform_connections.repository import default_platform_connection_path
from .runtime_config import get_config_value

local_browser_request: ContextVar[bool] = ContextVar("local_browser_request", default=False)
TERMINAL = {"completed", "failed", "cancelled"}


def local_request(request: Request) -> bool:
    try:
        if not request.client or not ipaddress.ip_address(request.client.host).is_loopback:
            return False
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return False
        if any(name.lower().startswith(("x-forwarded", "forwarded")) for name in request.headers):
            return False
        origin = request.headers.get("origin")
        return not origin or urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    except ValueError:
        return False


async def browser_request_context(request: Request):
    token = local_browser_request.set(local_request(request))
    try:
        yield
    finally:
        local_browser_request.reset(token)


def browser_channel() -> str | None:
    for channel, path in (
        (
            "msedge",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
        ),
        (
            "chrome",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe",
        ),
    ):
        if path.is_file():
            return channel
    return None


def desktop_available() -> bool:
    if os.name != "nt":
        return False
    import ctypes

    session = ctypes.c_ulong()
    return (
        bool(ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)))
        and session.value != 0
    )


@dataclass
class BrowserSession:
    owner: tuple[str, str, str]
    id: str = field(default_factory=lambda: str(uuid4()))
    mode: str = "download"
    state: str = "starting"
    message: str = "正在打开专用采集浏览器。"
    reason: str | None = None
    error_code: str | None = None
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None
    updated: float = field(default_factory=monotonic)

    @property
    def occupies_profile(self) -> bool:
        return self.state not in TERMINAL or (
            self.process is not None and self.process.returncode is None
        )

    def public(self) -> dict:
        return {
            key: getattr(self, key)
            for key in (
                "id",
                "mode",
                "state",
                "message",
                "reason",
                "error_code",
            )
        }


class BrowserAssistService:
    def __init__(self, account_context_service, credential_resolver):
        self.context = account_context_service
        self.credentials = credential_resolver
        self.sessions: dict[str, BrowserSession] = {}

    def available(self) -> bool:
        return (
            local_browser_request.get()
            and get_config_value("VIRAL_DNA_BROWSER_ASSIST_ENABLED", "0") == "1"
            and desktop_available()
            and importlib.util.find_spec("playwright") is not None
            and browser_channel() is not None
        )

    async def owner(self) -> tuple[str, str, str]:
        access = account_access.get()
        if password_auth_enabled() and (access is None or access.user_id is None):
            raise HTTPException(401, "请先登录当前账户。")
        context = await self.context.ensure_current()
        return (
            str(context.account.id),
            str(access.user_id) if access and access.user_id else "local",
            str(context.device.id),
        )

    def root(self) -> Path:
        configured = get_config_value("VIRAL_DNA_BROWSER_ASSIST_ROOT", "").strip()
        return (
            Path(configured).resolve()
            if configured
            else default_platform_connection_path().parent / "browser-assist"
        )

    async def status(self) -> dict:
        if not self.available():
            return {
                "available": False,
                "session": None,
                "message": "专用采集浏览器仅在本机桌面模式启用；正式服务器不弹出本机窗口。",
            }
        owner = await self.owner()
        current = next(
            (item for item in reversed(list(self.sessions.values())) if item.owner == owner), None
        )
        return {"available": True, "session": current.public() if current else None}

    async def _new(self, mode: str) -> BrowserSession:
        if not self.available():
            raise LinkIngestionError("link_browser_unavailable", "当前环境不支持本机交互采集。")
        owner = await self.owner()
        self.sessions = {
            key: value
            for key, value in self.sessions.items()
            if value.occupies_profile or monotonic() - value.updated < 600
        }
        if any(
            item.owner == owner and item.occupies_profile for item in self.sessions.values()
        ):
            raise LinkIngestionError(
                "link_browser_busy",
                "当前用户的采集浏览器正在使用，请先完成或取消该任务。",
                retryable=True,
            )
        session = BrowserSession(owner, mode=mode)
        self.sessions[session.id] = session
        return session

    async def connect(self) -> dict:
        session = await self._new("connect")

        async def background():
            try:
                async with AsyncExitStack() as stack:
                    try:
                        credentials = await stack.enter_async_context(
                            self.credentials.session_for(SourceType.DOUYIN),
                        )
                    except LinkCredentialError:
                        # A broken exported file must not block a fresh interactive login.
                        credentials = None
                    await self._run(
                        session, {"source_url": "https://www.douyin.com/"}, credentials, None
                    )
            except Exception:
                if session.state not in TERMINAL:
                    session.state, session.message = (
                        "failed",
                        "无法打开采集浏览器，请检查本机连接。",
                    )

        session.task = asyncio.create_task(background())
        return session.public()

    async def download(self, source_url, target_dir, credentials, seconds, maximum, progress):
        session = await self._new("download")
        return await self._run(
            session,
            {
                "source_url": source_url,
                "target_dir": str(target_dir),
                "timeout_seconds": seconds,
                "max_download_bytes": maximum,
            },
            credentials,
            progress,
        )

    async def probe(self, source_url, credentials, seconds, progress):
        session = await self._new("probe")
        return await self._run(
            session,
            {"source_url": source_url, "timeout_seconds": seconds},
            credentials,
            progress,
        )

    async def _run(self, session, request, credentials, progress):
        profile = self.root().joinpath(*session.owner, "douyin")
        request.update(
            {
                "mode": session.mode,
                "channel": browser_channel(),
                "profile_dir": str(profile),
                "cookie_file": str(credentials.cookie_file)
                if credentials and credentials.cookie_file
                else None,
                "human_timeout_seconds": configured_timeout(
                    "VIRAL_DNA_BROWSER_HUMAN_TIMEOUT_SECONDS", 300
                ),
            }
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (WORKER_IMPORT_ROOT, environment.get("PYTHONPATH")))
        )
        try:
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "viral_dna_api.douyin_browser_worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environment,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if os.name == "nt"
                        else {"start_new_session": True}
                    ),
                )
            )
            try:
                session.process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                session.process = await spawn
                raise
            process = session.process
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            await process.stdin.drain()
            # This independent watchdog also covers hung browser commands while the
            # analysis clock is paused. Workers never get unlimited human waits.
            limit = request.get("timeout_seconds", 120) + request["human_timeout_seconds"] + 35
            async with asyncio.timeout(limit):
                while line := await process.stdout.readline():
                    event = json.loads(line)
                    session.state = event["state"]
                    session.reason = event.get("reason")
                    session.message = event.get("message", session.message)
                    session.updated = monotonic()
                    if event.get("error"):
                        error = event["error"]
                        session.error_code, session.message = error["code"], error["message"]
                    if session.state == "completed":
                        session.message = {
                            "connect": "专用浏览器登录操作已结束；视频可用性以实际采集为准。",
                            "probe": "已读取目标视频信息；未下载视频、未启动分析。",
                            "download": "视频已下载并校验，继续分析。",
                        }[session.mode]
                    if progress:
                        await progress(session.public())
                    if session.state == "completed":
                        return event["info"]
                    if session.state == "failed":
                        raise LinkIngestionError(
                            error["code"], error["message"], retryable=error["retryable"]
                        )
                if session.state == "cancelled":
                    raise LinkIngestionError(
                        "link_browser_cancelled", "已取消浏览器采集。", retryable=True
                    )
                raise LinkIngestionError(
                    "link_browser_closed", "专用采集进程已关闭，任务已停止。", retryable=True
                )
        except BaseException as exc:
            cancelled = isinstance(exc, asyncio.CancelledError) or (
                isinstance(exc, LinkIngestionError) and exc.code == "link_browser_cancelled"
            )
            session.state = "cancelled" if cancelled else "failed"
            if isinstance(exc, LinkIngestionError):
                session.error_code, session.message = exc.code, str(exc)
            if not isinstance(exc, LinkIngestionError):
                session.message = "浏览器采集已停止，可重新连接后重试。"
                if isinstance(exc, Exception):
                    raise LinkIngestionError(
                        "link_browser_failed", session.message, retryable=True
                    ) from None
            raise
        finally:
            if session.process:
                with suppress(Exception):
                    session.process.stdin.close()
                    await asyncio.wait_for(session.process.wait(), 3)
                await _stop_download_process(session.process)
            if progress:
                await progress(session.public())

    async def control(self, identifier: str, action: str) -> dict:
        if not self.available():
            raise HTTPException(403, "只能从本机桌面控制采集浏览器。")
        session = self.sessions.get(identifier)
        if session is None or session.owner != await self.owner():
            raise HTTPException(404, "该浏览器任务不存在或不属于当前用户。")
        if (
            session.state in TERMINAL
            or not session.process
            or session.process.returncode is not None
        ):
            raise HTTPException(409, "采集任务已结束，请重新提交。")
        if action not in {"focus", "continue", "cancel"}:
            raise HTTPException(422, "不支持的采集操作。")
        if action == "cancel":
            session.state, session.message = "cancelled", "已取消浏览器采集。"
            await _stop_download_process(session.process)
            return session.public()
        try:
            session.process.stdin.write((json.dumps({"action": action}) + "\n").encode())
            await session.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise HTTPException(409, "采集窗口已关闭，请刷新任务状态。") from None
        return session.public()

    async def shutdown(self):
        for session in self.sessions.values():
            if session.task and not session.task.done():
                session.task.cancel()
            if session.process:
                await _stop_download_process(session.process)
        await asyncio.gather(
            *(s.task for s in self.sessions.values() if s.task), return_exceptions=True
        )


class BrowserAction(BaseModel):
    action: str


def browser_assist_router(service: BrowserAssistService):
    router = APIRouter(prefix="/settings/browser-assist")

    @router.get("")
    async def status():
        return await service.status()

    @router.post("/connect")
    async def connect():
        try:
            return await service.connect()
        except LinkIngestionError as exc:
            raise HTTPException(409, {"code": exc.code, "message": str(exc)}) from None

    @router.post("/{session_id}/control")
    async def control(session_id: str, payload: BrowserAction):
        return await service.control(session_id, payload.action)

    return router
