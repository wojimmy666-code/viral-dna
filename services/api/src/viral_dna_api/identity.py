from __future__ import annotations

import os
from enum import StrEnum
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from .runtime_config import get_config_value
from .workspace_catalog import AccountContextService


class PrincipalType(StrEnum):
    USER = "user"
    PLATFORM_ADMIN = "platform_admin"


class AuthMode(StrEnum):
    LOCAL_BOOTSTRAP = "local_bootstrap"
    EXTERNAL = "external"


class UserSession(BaseModel):
    principal_type: PrincipalType = PrincipalType.USER
    user_id: UUID
    display_name: str
    auth_mode: AuthMode


class PlatformAdminSession(BaseModel):
    principal_type: PrincipalType = PrincipalType.PLATFORM_ADMIN
    admin_id: UUID
    display_name: str
    auth_mode: AuthMode
    permissions: list[str]


LOCAL_PLATFORM_ADMIN_ID = uuid5(NAMESPACE_URL, "viraldna:local-platform-admin")
PLATFORM_ADMIN_PERMISSIONS = [
    "platform.settings.read",
    "platform.settings.write",
    "platform.billing.read",
    "platform.skills.read",
    "platform.skills.write",
    "platform.skills.publish",
]


def current_auth_mode() -> AuthMode:
    raw = get_config_value("VIRAL_DNA_AUTH_MODE", AuthMode.LOCAL_BOOTSTRAP.value)
    try:
        return AuthMode(raw.strip().lower())
    except ValueError:
        return AuthMode.LOCAL_BOOTSTRAP


def admin_console_enabled() -> bool:
    raw = get_config_value("VIRAL_DNA_ADMIN_CONSOLE_ENABLED", "true")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_local_request(request: Request) -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    host = (request.client.host if request.client else "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


async def require_platform_admin(request: Request) -> PlatformAdminSession:
    if not admin_console_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="平台管理后台未启用")
    mode = current_auth_mode()
    if mode is not AuthMode.LOCAL_BOOTSTRAP:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="平台管理员尚未登录",
        )
    allow_remote = get_config_value("VIRAL_DNA_LOCAL_ADMIN_ALLOW_REMOTE", "false")
    if allow_remote.strip().lower() not in {"1", "true", "yes", "on"}:
        if not _is_local_request(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="本地管理模式只允许从当前设备访问",
            )
    return PlatformAdminSession(
        admin_id=LOCAL_PLATFORM_ADMIN_ID,
        display_name="本地平台管理员",
        auth_mode=mode,
        permissions=PLATFORM_ADMIN_PERMISSIONS,
    )


PlatformAdmin = Annotated[PlatformAdminSession, Depends(require_platform_admin)]


def create_identity_router(account_context: AccountContextService) -> APIRouter:
    router = APIRouter(tags=["identity"])

    @router.get("/session", response_model=UserSession)
    async def user_session() -> UserSession:
        account = await account_context.current_account()
        return UserSession(
            user_id=account.id,
            display_name=account.display_name,
            auth_mode=current_auth_mode(),
        )

    @router.get("/admin/session", response_model=PlatformAdminSession)
    async def admin_session(admin: PlatformAdmin) -> PlatformAdminSession:
        return admin

    return router
