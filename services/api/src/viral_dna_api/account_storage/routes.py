from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.responses import FileResponse

from ..access_context import account_access
from ..accounts.http import PhoneNumber
from ..accounts.repository import AccountError
from ..accounts.runtime import account_repository
from ..runtime_config import persist_config_values
from .catalog import CHUNK_BYTES, StorageCatalog
from .sync import server_url
from .transfer import BatchManifest, TransferReceiver


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuotaInput(StrictInput):
    limit_bytes: int = Field(strict=True, ge=1, le=100_000_000_000_000)
    note: str = Field(default="", max_length=500)


class ConnectionInput(StrictInput):
    username: PhoneNumber
    password: SecretStr = Field(min_length=8, max_length=128)


class ConfirmationInput(StrictInput):
    account_id: UUID


class ServerInput(StrictInput):
    url: str = Field(max_length=500)


class DeviceInput(StrictInput):
    device_id: UUID


class ReservationInput(StrictInput):
    id: UUID
    bytes: int = Field(strict=True, ge=1, le=2_000_000_000)


def create_storage_router(service, sync):
    router = APIRouter(tags=["account-storage"])
    receiver = TransferReceiver(service)

    def owner():
        if account_access.get() is None or account_access.get().role != "owner":
            raise AccountError(403, "owner_required", "请由账户负责人操作")

    def admin_catalog(account_id: UUID):
        access = next(
            (a for a in account_repository().runtime_accounts() if a.account_id == account_id), None
        )
        if access is None:
            raise AccountError(404, "account_missing", "账户不存在")
        return StorageCatalog(access.workspace_root, str(access.account_id), access.account_kind)

    @router.get("/account/storage")
    async def summary():
        await asyncio.to_thread(receiver.cleanup_incomplete)
        usage = await asyncio.to_thread(service.catalog.usage)
        connection = sync.state()
        return {
            **usage,
            **connection,
            "inventory_state": service.catalog.setting("inventory_state", "ready"),
            "archive_failure_count": len(service.catalog.setting("archive_failures", [])),
            "retained_on_server_count": len(service.catalog.setting("retained_on_server", [])),
            "meter": "account_backend",
        }

    @router.get("/account/storage/remote-usage")
    async def remote_usage():
        return await sync.remote_usage()

    @router.get("/account/storage/history")
    async def history(
        kind: Literal["image", "video", "asset", "export", "source", "audio"] = "image",
        trash: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return await service.history(kind=kind, trash=trash, limit=limit, offset=offset)

    @router.get("/account/storage/entries/{entry_key}/{variant}")
    async def content(
        entry_key: str, variant: Literal["content", "thumbnail"], download: bool = False
    ):
        entry = service.catalog.entry(entry_key)
        if entry is None:
            raise AccountError(404, "storage_entry_missing", "文件不存在")
        digest = entry["thumbnail_sha256"] if variant == "thumbnail" else entry["sha256"]
        blob = service.catalog.blob(digest) if digest else None
        if blob is None or not service.catalog.resolve(blob["relative_path"]).is_file():
            raise AccountError(404, "storage_file_missing", "原文件尚未归档完成，请重试归档")
        mime = entry["metadata"].get("mime_type", "application/octet-stream")
        if variant == "thumbnail":
            with service.catalog.resolve(blob["relative_path"]).open("rb") as source:
                header = source.read(16)
            mime = (
                "image/png"
                if header.startswith(b"\x89PNG\r\n\x1a\n")
                else (
                    "image/jpeg"
                    if header.startswith(b"\xff\xd8\xff")
                    else (
                        "image/webp"
                        if header[:4] == b"RIFF" and header[8:12] == b"WEBP"
                        else "application/octet-stream"
                    )
                )
            )
        if mime not in {
            "image/png",
            "image/jpeg",
            "image/webp",
            "video/mp4",
            "video/webm",
            "audio/mpeg",
            "audio/wav",
        }:
            mime = "application/octet-stream"
        return FileResponse(
            service.catalog.resolve(blob["relative_path"]),
            media_type=mime,
            filename=entry["metadata"].get("filename", "media.bin"),
            content_disposition_type="attachment"
            if download or mime == "application/octet-stream"
            else "inline",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )

    @router.post("/account/storage/entries/{entry_key}/trash")
    async def trash(entry_key: str):
        entry = service.catalog.entry(entry_key)
        if entry is None:
            raise AccountError(404, "storage_entry_missing", "记录不存在")
        async with service.mutation():
            if await service.referenced(entry):
                raise AccountError(
                    409, "storage_entry_referenced", "此文件仍被项目或资产引用，请在原入口管理"
                )
            await service.set_trash(entry)
        return {"trashed": True}

    @router.post("/account/storage/entries/{entry_key}/restore")
    async def restore(entry_key: str):
        entry = service.catalog.entry(entry_key)
        if entry is None:
            raise AccountError(404, "storage_entry_missing", "记录不存在")
        async with service.mutation():
            await service.set_trash(entry, restore=True)
        return {"restored": True}

    @router.delete("/account/storage/entries/{entry_key}")
    async def purge(entry_key: str, confirm: bool = False):
        if not confirm:
            raise AccountError(422, "storage_delete_confirmation", "请确认永久删除")
        entry = service.catalog.entry(entry_key)
        if entry is None:
            raise AccountError(404, "storage_entry_missing", "记录不存在")
        return await service.purge(entry)

    @router.post("/account/storage/reconcile")
    async def reconcile():
        service.start_inventory()
        return await summary()

    @router.post("/account/storage/connection")
    async def prepare(payload: ConnectionInput):
        return await sync.prepare(payload.username, payload.password.get_secret_value())

    @router.post("/account/storage/connection/confirm")
    async def confirm(payload: ConfirmationInput):
        owner()
        return sync.confirm(str(payload.account_id))

    @router.delete("/account/storage/connection")
    async def disconnect():
        owner()
        await sync.disconnect()
        return {"disconnected": True}

    @router.post("/account/storage/sync")
    async def start():
        return await sync.start()

    @router.get("/admin/accounts/{account_id}/storage")
    async def admin_usage(account_id: UUID):
        catalog = await asyncio.to_thread(admin_catalog, account_id)
        return {**catalog.usage(), "audit": catalog.audit()}

    @router.patch("/admin/accounts/{account_id}/storage")
    async def quota(account_id: UUID, payload: QuotaInput, request: Request):
        catalog = await asyncio.to_thread(admin_catalog, account_id)
        usage = await asyncio.to_thread(
            catalog.set_limit,
            payload.limit_bytes,
            request.state.authenticated_session["admin_id"],
            payload.note,
        )
        return {**usage, "audit": catalog.audit()}

    @router.get("/admin/storage/server")
    async def target_server():
        return {"url": sync.configured_url()}

    @router.put("/admin/storage/server")
    async def configure_server(payload: ServerInput):
        url = server_url(payload.url) if payload.url.strip() else ""
        await asyncio.to_thread(persist_config_values, {"VIRAL_DNA_SYNC_SERVER_URL": url})
        return {"url": url}

    @router.post("/account/storage/devices")
    async def device(payload: DeviceInput):
        owner()
        if payload.device_id == account_access.get().workspace_id:
            raise AccountError(
                409, "sync_same_workspace", "当前已经在此服务器账户中，无需同步到自身"
            )
        return await asyncio.to_thread(
            account_repository().issue_storage_token, account_access.get(), str(payload.device_id)
        )

    @router.delete("/account/storage/transfer/device")
    async def revoke(request: Request):
        device_id = request.state.authenticated_session.get("storage_device_id")
        if device_id:
            await asyncio.to_thread(
                account_repository().revoke_storage_token, account_access.get(), device_id
            )
        return {"revoked": True}

    @router.get("/account/storage/transfer/usage")
    async def transfer_usage():
        await asyncio.to_thread(receiver.cleanup_incomplete)
        return await asyncio.to_thread(service.catalog.usage)

    @router.post("/account/storage/transfer/reservations")
    async def reserve(payload: ReservationInput, request: Request):
        device_id = request.state.authenticated_session.get("storage_device_id", "browser")
        await asyncio.to_thread(
            service.catalog.reserve,
            f"remote-generation:{device_id}:{payload.id}",
            payload.bytes,
            "generation",
        )
        return {"reserved": True}

    @router.post("/account/storage/transfer/batches")
    async def begin(payload: BatchManifest, request: Request):
        return await asyncio.to_thread(
            receiver.begin, payload, request.state.authenticated_session.get("storage_device_id")
        )

    @router.delete("/account/storage/transfer/reservations/{run_id}")
    async def release_generation(run_id: UUID, request: Request):
        device_id = request.state.authenticated_session.get("storage_device_id", "browser")
        await asyncio.to_thread(service.catalog.release, f"remote-generation:{device_id}:{run_id}")
        return {"released": True}

    @router.get("/account/storage/transfer/uploads/{upload_id}")
    async def upload_state(upload_id: UUID):
        return await asyncio.to_thread(receiver.upload, str(upload_id))

    @router.put("/account/storage/transfer/uploads/{upload_id}")
    async def upload_chunk(upload_id: UUID, request: Request, offset: int = Query(ge=0)):
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > CHUNK_BYTES:
                raise AccountError(413, "sync_chunk_invalid", "上传分块不能超过 4 MB")
        return await asyncio.to_thread(receiver.chunk, str(upload_id), offset, bytes(payload))

    @router.post("/account/storage/transfer/uploads/{upload_id}/complete")
    async def complete_upload(upload_id: UUID):
        return await asyncio.to_thread(receiver.finish, str(upload_id))

    @router.post("/account/storage/transfer/batches/{batch_id}/complete")
    async def complete_batch(batch_id: UUID):
        return await receiver.commit(batch_id)

    return router
