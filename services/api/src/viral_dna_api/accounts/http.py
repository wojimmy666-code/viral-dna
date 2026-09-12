from __future__ import annotations

import asyncio
import base64
import hmac
import json
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from starlette.responses import JSONResponse

from ..access_context import account_access
from ..runtime_config import get_config_value
from .repository import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PHONE_PATTERN,
    AccountError,
    csrf_token,
)
from .runtime import account_repository, password_auth_enabled
from .workspace_layout import WorkspaceLayoutError

USER_COOKIE = "viraldna_user_session"
ADMIN_COOKIE = "viraldna_admin_session"
_password_workers = asyncio.Semaphore(3)
PUBLIC = {
    "/api/v1/auth/status",
    "/api/v1/auth/login",
    "/api/v1/admin/auth/login",
    "/api/v1/auth/activate",
    "/api/v1/auth/setup",
}


def error_response(exc: AccountError):
    return JSONResponse(
        status_code=exc.status, content={"detail": {"code": exc.code, "message": str(exc)}}
    )


def trusted_origin(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    configured = get_config_value(
        "VIRAL_DNA_CORS_ORIGINS",
        "http://127.0.0.1:4174,http://localhost:4174,http://localhost:5173",
    )
    allowed = {value.strip().rstrip("/") for value in configured.split(",") if value.strip()}
    allowed.add(f"{request.url.scheme}://{request.url.netloc}")
    return origin.rstrip("/") in allowed and origin not in {"", "null"}


def check_csrf(request: Request, token: str):
    if not trusted_origin(request) or not hmac.compare_digest(
        request.headers.get("x-csrf-token", ""), csrf_token(token)
    ):
        raise AccountError(403, "csrf_invalid", "会话校验失败，请刷新页面后重试")


def user_payload(session: dict) -> dict:
    access = session["access"]
    return {
        "principal_type": "user",
        "user_id": str(access.user_id),
        "display_name": access.display_name,
        "username": session["username"],
        "auth_mode": "password",
        "account_id": str(access.account_id),
        "account_name": access.account_name,
        "account_kind": access.account_kind,
        "role": access.role,
        "csrf_token": session["csrf_token"],
    }


class AccountAuthenticationMiddleware:
    """ASGI context remains bound while streaming and background work is scheduled."""

    def __init__(self, app, initialize=None):
        self.app = app
        self.initialize = initialize

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        path = scope["path"]
        if path == "/health" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        if not password_auth_enabled():
            mode = get_config_value("VIRAL_DNA_AUTH_MODE", "password")
            local = request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
            if mode == "local_bootstrap" and local:
                return await self.app(scope, receive, send)
            return await error_response(AccountError(401, "login_required", "请先登录"))(
                scope, receive, send
            )
        try:
            repo = account_repository()
            if path.startswith("/api/v1/admin/"):
                from ..identity import admin_console_enabled

                if not admin_console_enabled():
                    raise AccountError(404, "admin_disabled", "平台管理后台未启用")
            if path in PUBLIC:
                if scope["method"] not in {"GET", "HEAD"} and not trusted_origin(request):
                    raise AccountError(403, "origin_invalid", "请从应用页面提交请求")
                return await self.app(scope, receive, send)
            if path.startswith("/api/v1/public-media/") and scope["method"] in {"GET", "HEAD"}:
                # Account ID selects a signing key only. The media handler still verifies
                # the complete HMAC and expiry before returning any bytes.
                encoded = path.rsplit("/", 1)[-1].split(".", 1)[0]
                try:
                    payload = json.loads(
                        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    )
                    if not isinstance(payload, dict):
                        raise ValueError("invalid media payload")
                    account_id = payload.get("a")
                except (ValueError, TypeError):
                    raise AccountError(404, "media_missing", "媒体地址无效") from None
                access = next(
                    (a for a in repo.runtime_accounts() if str(a.account_id) == account_id), None
                )
                if account_id and access is None:
                    raise AccountError(404, "media_missing", "媒体地址无效")
                token = account_access.set(access)
                try:
                    return await self.app(scope, receive, send)
                finally:
                    account_access.reset(token)
            admin = path.startswith("/api/v1/admin/")
            cookie = request.cookies.get(ADMIN_COOKIE if admin else USER_COOKIE, "")
            transfer_token = request.headers.get("authorization", "")
            transfer = path.startswith(
                "/api/v1/account/storage/transfer/"
            ) and transfer_token.startswith("Bearer ")
            if transfer:
                if request.url.scheme != "https":
                    raise AccountError(403, "https_required", "服务器同步必须使用 HTTPS")
                session = await asyncio.to_thread(repo.storage_token_session, transfer_token[7:])
            else:
                session = await asyncio.to_thread(repo.session, cookie, admin=admin)
            if not transfer and scope["method"] not in {"GET", "HEAD"}:
                check_csrf(request, cookie)
            scope.setdefault("state", {})["authenticated_session"] = session
            scope["state"]["authenticated_admin"] = admin
            token = account_access.set(None if admin else session["access"])
            try:
                if not admin and self.initialize is not None:
                    await self.initialize()

                async def secured_send(message):
                    if message["type"] == "http.response.start":
                        headers = list(message.get("headers", []))
                        headers.extend(
                            [
                                (b"cache-control", b"private, no-store"),
                                (b"referrer-policy", b"no-referrer"),
                            ]
                        )
                        message = {**message, "headers": headers}
                    await send(message)

                return await self.app(scope, receive, secured_send)
            finally:
                account_access.reset(token)
        except AccountError as exc:
            return await error_response(exc)(scope, receive, send)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


PhoneNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=11, max_length=11, pattern=PHONE_PATTERN),
]
AccountPassword = Annotated[
    SecretStr, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
]


class LoginInput(StrictInput):
    username: str = Field(min_length=1, max_length=120)
    password: AccountPassword


class UserLoginInput(LoginInput):
    username: PhoneNumber


class ActivateInput(StrictInput):
    token: SecretStr = Field(min_length=20, max_length=200)
    password: AccountPassword


class PasswordInput(StrictInput):
    current_password: AccountPassword
    new_password: AccountPassword


class AccountInput(StrictInput):
    kind: str = Field(pattern="^(personal|enterprise)$")
    name: str = Field(min_length=1, max_length=120)
    username: PhoneNumber
    display_name: str = Field(min_length=1, max_length=120)


class SetupInput(AccountInput):
    admin_password: AccountPassword
    owner_password: AccountPassword
    confirm_legacy_ownership: bool


class AccountUpdateInput(StrictInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    managed_asset_project: str | None = Field(default=None, max_length=120)


class MemberInput(StrictInput):
    username: PhoneNumber
    display_name: str = Field(min_length=1, max_length=120)


class MemberPhoneInput(StrictInput):
    current_username: PhoneNumber
    username: PhoneNumber
    confirm_change: bool = Field(strict=True)


class LeaseInput(StrictInput):
    editor_id: str = Field(min_length=16, max_length=100)
    token: SecretStr = Field(min_length=32, max_length=200)


def local_setup_allowed(request: Request) -> bool:
    # No initialization code: only the deployment machine may claim the first
    # account. Normal logins remain available remotely over HTTPS after setup.
    return bool(
        request.client
        and request.client.host in {"127.0.0.1", "::1", "testclient"}
        and request.url.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}
    )


def account_validation_error(errors: list[dict], *, admin_login: bool = False) -> AccountError:
    """Return field-specific guidance without reflecting input values or secrets."""
    labels = {
        "username": "登录名" if admin_login else "手机号",
        "current_username": "当前手机号",
        "confirm_change": "修改确认",
        "password": "密码",
        "admin_password": "admin 密码",
        "owner_password": "前端登录密码",
        "current_password": "当前密码",
        "new_password": "新密码",
        "name": "账户名称",
        "display_name": "姓名",
        "kind": "账户类型",
        "token": "激活／重置链接",
        "confirm_legacy_ownership": "现有数据归属确认",
    }
    messages = []
    for error in errors:
        field = str(error.get("loc", ("",))[-1])
        label = labels.get(field)
        reason = error.get("type", "")
        if not label or reason == "extra_forbidden":
            message = "表单字段已更新，请刷新页面后重试"
        elif field == "username" and not admin_login:
            message = "手机号必须为 11 位中国大陆手机号"
        elif field.endswith("password"):
            message = f"{label}需要 8–128 个字符"
        elif field == "token":
            message = "激活／重置链接不完整，请使用管理员提供的完整链接"
        elif field == "kind":
            message = "请选择个人或企业账户"
        elif field == "confirm_legacy_ownership":
            message = "请确认现有数据的归属账户"
        elif reason in {"missing", "string_too_short", "too_short"}:
            message = f"请填写{label}"
        elif reason in {"string_too_long", "too_long"}:
            message = f"{label}最多 120 个字符"
        else:
            message = f"请检查{label}的格式"
        if message not in messages:
            messages.append(message)
    return AccountError(422, "invalid_auth_input", "；".join(messages) or "请检查账户表单")


def require_owner():
    access = account_access.get()
    if not access or access.account_kind != "enterprise" or access.role != "owner":
        raise AccountError(403, "owner_required", "只有企业负责人可以管理成员")
    return access


def create_account_router(account_context, repository) -> APIRouter:
    router = APIRouter(tags=["accounts"])
    setup_lock = asyncio.Lock()

    @router.get("/auth/status")
    async def status_info(request: Request):
        if not password_auth_enabled():
            return {"auth_mode": "local_bootstrap", "initialized": True}
        repo = account_repository()
        return {
            "auth_mode": "password",
            "initialized": await asyncio.to_thread(repo.initialized),
            "setup_allowed": local_setup_allowed(request),
        }

    @router.post("/auth/setup")
    async def setup(payload: SetupInput, request: Request):
        async with setup_lock:
            return await initialize_accounts(payload, request)

    async def initialize_accounts(payload: SetupInput, request: Request):
        if account_repository().initialized():
            raise AccountError(409, "already_initialized", "账户系统已经初始化")
        if not local_setup_allowed(request):
            raise AccountError(403, "local_setup_required", "请在部署本机打开应用完成首次账户设置")
        if not payload.confirm_legacy_ownership:
            raise AccountError(422, "ownership_confirmation_required", "请确认现有数据的归属账户")
        try:
            context = await account_context.prepare_account_setup(account_repository().tenant_root)
        except WorkspaceLayoutError as exc:
            raise AccountError(409, "workspace_layout_invalid", str(exc)) from exc
        async with _password_workers:
            await asyncio.to_thread(
                account_repository().bootstrap,
                admin_password=payload.admin_password.get_secret_value(),
                owner_password=payload.owner_password.get_secret_value(),
                kind=payload.kind,
                name=payload.name,
                username=payload.username,
                display_name=payload.display_name,
                legacy_root=Path(context.registration.local_root),
                account_id=context.account.id,
                workspace_id=context.active_workspace.id,
                location_id=context.storage_locations[0].id,
                device_id=context.device.id,
                catalog_path=getattr(account_context.repository, "path", None),
                managed_asset_project=get_config_value(
                    "VIRAL_DNA_VOLC_ARK_ASSET_PROJECT_NAME", "default"
                ),
            )
        return {"initialized": True}

    async def login_response(
        payload: LoginInput, request: Request, response: Response, admin: bool
    ):
        if request.url.scheme != "https" and urlsplit(str(request.url)).hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            raise AccountError(400, "https_required", "远程登录必须使用 HTTPS")
        async with _password_workers:
            token = await asyncio.to_thread(
                account_repository().login,
                payload.username,
                payload.password.get_secret_value(),
                admin=admin,
                remote=request.client.host if request.client else "unknown",
            )
        response.set_cookie(
            ADMIN_COOKIE if admin else USER_COOKIE,
            token,
            secure=request.url.scheme == "https",
            httponly=True,
            samesite="lax",
            path="/",
            max_age=7200 if admin else 43200,
        )
        session = await asyncio.to_thread(account_repository().session, token, admin=admin)
        return session if admin else user_payload(session)

    @router.post("/auth/login")
    async def login(payload: UserLoginInput, request: Request, response: Response):
        return await login_response(payload, request, response, False)

    @router.post("/admin/auth/login")
    async def admin_login(payload: LoginInput, request: Request, response: Response):
        return await login_response(payload, request, response, True)

    @router.post("/auth/activate")
    async def activate(payload: ActivateInput):
        async with _password_workers:
            await asyncio.to_thread(
                account_repository().activate,
                payload.token.get_secret_value(),
                payload.password.get_secret_value(),
            )
        return {"activated": True}

    @router.post("/auth/logout")
    @router.post("/admin/auth/logout")
    async def logout(request: Request, response: Response):
        admin = request.url.path.startswith("/api/v1/admin/")
        name = ADMIN_COOKIE if admin else USER_COOKIE
        await asyncio.to_thread(account_repository().logout, request.cookies.get(name, ""))
        response.delete_cookie(name, path="/")
        return {"logged_out": True}

    @router.post("/auth/password")
    @router.post("/admin/auth/password")
    async def change_password(payload: PasswordInput, request: Request, response: Response):
        admin = request.url.path.startswith("/api/v1/admin/")
        name = ADMIN_COOKIE if admin else USER_COOKIE
        async with _password_workers:
            await asyncio.to_thread(
                account_repository().change_password,
                request.cookies.get(name, ""),
                payload.current_password.get_secret_value(),
                payload.new_password.get_secret_value(),
                admin=admin,
            )
        response.delete_cookie(name, path="/")
        return {"changed": True}

    @router.get("/admin/accounts")
    async def list_accounts():
        def with_storage():
            from ..account_storage.catalog import StorageCatalog

            repository = account_repository()
            access = {str(item.account_id): item for item in repository.runtime_accounts()}
            items = repository.accounts()
            for item in items:
                owner = access[item["id"]]
                item["storage"] = StorageCatalog(
                    owner.workspace_root, item["id"], item["kind"]
                ).usage()
            return items

        return {"items": await asyncio.to_thread(with_storage)}

    @router.post("/admin/accounts")
    async def create_account(payload: AccountInput, request: Request):
        return await asyncio.to_thread(
            account_repository().create_account,
            **payload.model_dump(),
            actor=request.state.authenticated_session["admin_id"],
        )

    @router.patch("/admin/accounts/{account_id}")
    async def update_account(account_id: str, payload: AccountUpdateInput, request: Request):
        await asyncio.to_thread(
            account_repository().update_account,
            account_id,
            actor=request.state.authenticated_session["admin_id"],
            **payload.model_dump(exclude_none=True),
        )
        return {"updated": True}

    @router.get("/admin/accounts/{account_id}/members")
    async def admin_members(account_id: str):
        return {"items": await asyncio.to_thread(account_repository().members, account_id)}

    @router.patch("/admin/accounts/{account_id}/members/{user_id}/phone")
    async def change_member_phone(
        account_id: UUID, user_id: UUID, payload: MemberPhoneInput, request: Request
    ):
        if not payload.confirm_change:
            raise AccountError(422, "phone_confirmation_required", "请确认修改登录手机号")
        return await asyncio.to_thread(
            account_repository().change_member_phone,
            str(account_id),
            str(user_id),
            current_username=payload.current_username,
            username=payload.username,
            actor=request.state.authenticated_session["admin_id"],
        )

    @router.post("/admin/accounts/{account_id}/members/{user_id}/reset")
    async def reset_password(account_id: str, user_id: str, request: Request):
        return await asyncio.to_thread(
            account_repository().reset_link,
            account_id,
            user_id,
            request.state.authenticated_session["admin_id"],
        )

    @router.get("/account/members")
    async def members():
        access = require_owner()
        return {
            "items": await asyncio.to_thread(account_repository().members, str(access.account_id))
        }

    @router.post("/account/members")
    async def invite(payload: MemberInput):
        access = require_owner()
        return await asyncio.to_thread(
            account_repository().invite,
            str(access.account_id),
            **payload.model_dump(),
            actor=str(access.user_id),
        )

    @router.delete("/account/members/{user_id}")
    async def remove(user_id: str):
        access = require_owner()
        await asyncio.to_thread(
            account_repository().remove_member, str(access.account_id), user_id, str(access.user_id)
        )
        return {"removed": True}

    @router.post("/account/members/{user_id}/reset")
    async def resend(user_id: str):
        access = require_owner()
        return await asyncio.to_thread(
            account_repository().reset_link, str(access.account_id), user_id, str(access.user_id)
        )

    @router.post("/account/members/{user_id}/restore")
    async def restore(user_id: str):
        access = require_owner()
        return await asyncio.to_thread(
            account_repository().restore_member,
            str(access.account_id),
            user_id,
            str(access.user_id),
        )

    @router.patch("/account")
    async def rename(payload: AccountUpdateInput):
        access = require_owner()
        if payload.status is not None or payload.managed_asset_project is not None:
            raise AccountError(403, "admin_required", "账户停用由后台管理员处理")
        await asyncio.to_thread(
            account_repository().update_account,
            str(access.account_id),
            actor=str(access.user_id),
            name=payload.name,
        )
        return {"updated": True}

    async def require_project(project_id: str):
        from uuid import UUID

        try:
            identifier = UUID(project_id)
        except ValueError:
            raise HTTPException(404, "项目不存在") from None
        project = await repository.get_project(identifier)
        record = await repository.get_record(identifier) if project is None else None
        if project is None and record is None:
            raise HTTPException(404, "项目不存在")

    @router.get("/projects/{project_id}/edit-lease")
    async def lease_state(project_id: str):
        await require_project(project_id)
        return await asyncio.to_thread(account_repository().lease, account_access.get(), project_id)

    @router.get("/projects/{project_id}/readonly")
    async def readonly_project(project_id: str):
        from uuid import UUID

        await require_project(project_id)
        identifier = UUID(project_id)
        project = await repository.get_project(identifier)
        record = await repository.get_record(identifier)
        result = {
            "id": project_id,
            "name": project.name if project else record.name,
            "productions": [],
            "report": None,
        }
        for field, getter in {
            "brief": "list_creative_brief_revisions",
            "outline": "list_outline_revisions",
            "manifest": "list_shot_manifest_revisions",
            "prompts": "list_project_prompt_revisions",
        }.items():
            versions = await getattr(repository, getter)(identifier)
            latest = max(versions, key=lambda value: value.revision_number, default=None)
            result[field] = latest.model_dump(mode="json") if latest else None
        if record:
            report = await repository.get_report(record.video_id)
            if report:
                result["report"] = report.model_dump(mode="json")
        for production in await repository.list_production_projects():
            if str(production.owner_project_id or production.record_id) != project_id:
                continue
            runs = await repository.list_generation_runs(production.id)
            candidates = await repository.list_generation_candidates_by_run_ids(
                {r.id for r in runs}
            )
            candidates.sort(key=lambda c: c.created_at, reverse=True)
            candidate_runs = {r.id: r for r in runs}
            shots = []
            for shot in await repository.list_shot_plans(production.id):
                if shot.lifecycle_status.value != "active":
                    continue
                images = []
                for beat in shot.visual_beats:
                    candidate = next(
                        (c for c in candidates if c.id == beat.approved_image_candidate_id), None
                    )
                    if candidate is not None:
                        images.append(
                            {
                                "url": f"/api/v1/generation-candidates/{candidate.id}/content",
                                "label": f"画面{beat.index}",
                                "adopted": True,
                            }
                        )
                if not images:
                    candidate = next(
                        (
                            c
                            for c in candidates
                            if c.kind.value == "image"
                            and c.status.value != "archived"
                            and candidate_runs[c.generation_run_id].shot_plan_id == shot.id
                        ),
                        None,
                    )
                    if candidate:
                        images.append(
                            {
                                "url": f"/api/v1/generation-candidates/{candidate.id}/content",
                                "label": "最新图片",
                                "adopted": False,
                            }
                        )
                shots.append(
                    {
                        "id": str(shot.id),
                        "index": shot.index,
                        "image_prompt": shot.image_prompt,
                        "video_prompt": shot.video_prompt,
                        "images": images,
                        "video_url": (
                            f"/api/v1/generation-candidates/{shot.approved_video_candidate_id}/content"
                            if shot.approved_video_candidate_id
                            else None
                        ),
                    }
                )
            prompts = await repository.list_project_prompt_revisions(production.id)
            latest_prompts = max(prompts, key=lambda value: value.revision_number, default=None)
            result["productions"].append(
                {
                    "id": str(production.id),
                    "name": production.name,
                    "prompts": latest_prompts.model_dump(mode="json")
                    if latest_prompts
                    else result["prompts"],
                    "shots": sorted(shots, key=lambda s: s["index"]),
                }
            )
        return result

    @router.post("/projects/{project_id}/edit-lease/{action}")
    async def lease_action(project_id: str, action: str, payload: LeaseInput):
        if action not in {"acquire", "renew", "release"}:
            raise HTTPException(404, "操作不存在")
        await require_project(project_id)
        return await asyncio.to_thread(
            account_repository().lease,
            account_access.get(),
            project_id,
            editor_id=payload.editor_id,
            token=payload.token.get_secret_value(),
            action=action,
        )

    return router
