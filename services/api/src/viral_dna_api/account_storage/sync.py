from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ..access_context import account_access
from ..accounts.repository import AccountError
from ..media_staging.secrets import MediaStagingSecretStore
from ..runtime_config import get_config_value
from ..workspace_catalog import default_account_catalog_path
from .catalog import CHUNK_BYTES


def server_url(value: str):
    parsed = urlsplit(value.strip().rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise AccountError(
            422, "sync_server_invalid", "请填写 HTTPS 服务器域名，不包含路径、账号或参数"
        )
    return f"https://{parsed.netloc}"


class ServerSyncService:
    def __init__(self, service, *, secrets=None, client_factory=None):
        self.service = service
        self.secrets = secrets or MediaStagingSecretStore(
            default_account_catalog_path().parent / "server-sync-secrets"
        )
        self.client_factory = client_factory or httpx.AsyncClient
        self.tasks = {}

    def configured_url(self):
        value = get_config_value("VIRAL_DNA_SYNC_SERVER_URL", "").strip()
        return server_url(value) if value else ""

    def client(self, url, token=None):
        headers = {"Origin": url}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.client_factory(
            base_url=url,
            headers=headers,
            follow_redirects=False,
            timeout=httpx.Timeout(60, connect=10),
        )

    @staticmethod
    async def request(client, method, path, **kwargs):
        try:
            response = await client.request(method, "/api/v1" + path, **kwargs)
        except httpx.HTTPError:
            raise AccountError(
                503, "sync_server_unreachable", "暂时无法连接服务器，本地文件已保留，可稍后重试"
            ) from None
        if response.is_redirect:
            raise AccountError(
                409, "sync_server_redirect", "服务器地址发生跳转，请管理员核对连接地址"
            )
        if response.is_error:
            try:
                detail = response.json().get("detail", {})
                code = (
                    detail.get("code", "sync_server_error")
                    if isinstance(detail, dict)
                    else "sync_server_error"
                )
                message = (
                    detail.get("message", "服务器未接受本次同步")
                    if isinstance(detail, dict)
                    else "服务器未接受本次同步"
                )
            except ValueError:
                code, message = "sync_server_error", "服务器未接受本次同步"
            # A remote login/device failure is not expiration of the local session.
            raise AccountError(
                409 if response.status_code == 401 else response.status_code, code, message
            )
        return response.json()

    def state(self):
        connection = self.service.catalog.setting("connection", {})
        return {
            "server_url": self.configured_url(),
            "secret_store_available": self.secrets.available,
            "connection": connection,
            "jobs": [j for j in self.service.catalog.jobs() if not j["id"].startswith("receive:")][
                :10
            ],
        }

    async def prepare(self, username: str, password: str):
        self.service.require_inventory()
        access = account_access.get()
        if access.role != "owner":
            raise AccountError(403, "owner_required", "请由账户负责人连接服务器")
        if self.service.catalog.setting("connection", {}).get("confirmed"):
            raise AccountError(409, "sync_already_connected", "请先断开当前服务器，再连接其他账户")
        url = self.configured_url()
        if not url:
            raise AccountError(409, "sync_server_not_configured", "请先由管理员设置服务器地址")
        if not self.secrets.available:
            raise AccountError(
                409,
                "sync_secret_store_unavailable",
                "当前设备没有可用的安全凭据存储，无法连接服务器",
            )
        async with self.client(url) as client:
            session = await self.request(
                client, "POST", "/auth/login", json={"username": username, "password": password}
            )
            if session.get("workspace_id") == str(access.workspace_id):
                raise AccountError(
                    409, "sync_same_workspace", "当前已经在此服务器账户中，无需同步到自身"
                )
            if session.get("account_kind") != access.account_kind:
                raise AccountError(
                    409, "sync_account_kind_mismatch", "本地与服务器账户类型不一致，不能同步"
                )
            device = await self.request(
                client,
                "POST",
                "/account/storage/devices",
                headers={"x-csrf-token": session["csrf_token"]},
                json={"device_id": str(access.workspace_id)},
            )
            await self.request(
                client, "POST", "/auth/logout", headers={"x-csrf-token": session["csrf_token"]}
            )
        await self.secrets.save(access.account_id, url, device.pop("token"))
        connection = {
            **device,
            "server_url": url,
            "confirmed": False,
            "auto_sync": False,
            "connected_at": time.time(),
        }
        self.service.catalog.set_setting("connection", connection)
        return connection

    def confirm(self, account_id: str):
        state = self.service.catalog.setting("connection", {})
        if (
            state.get("account_id") != account_id
            or state.get("server_url") != self.configured_url()
        ):
            raise AccountError(409, "sync_connection_changed", "目标账户已变化，请重新连接并确认")
        state["confirmed"] = True
        self.service.catalog.select_sync_target(f"{state['server_url']}:{account_id}")
        self.service.catalog.set_setting("connection", state)
        self.ensure_worker()
        return state

    async def credentials(self):
        state = self.service.catalog.setting("connection", {})
        if not state.get("confirmed"):
            raise AccountError(409, "sync_not_connected", "请先连接并确认服务器账户")
        credentials = await self.secrets.read(account_access.get().account_id)
        if (
            credentials is None
            or credentials[0] != state.get("server_url")
            or credentials[0] != self.configured_url()
        ):
            raise AccountError(409, "sync_connection_changed", "服务器配置已变化，请重新连接")
        return credentials

    async def disconnect(self):
        key = str(account_access.get().account_id)
        task = self.tasks.pop(key, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            url, token = await self.credentials()
            async with self.client(url, token) as client:
                for run_id in self.service.catalog.setting("remote_generation_runs", []):
                    await self.request(
                        client, "DELETE", f"/account/storage/transfer/reservations/{run_id}"
                    )
                await self.request(client, "DELETE", "/account/storage/transfer/device")
        except AccountError:
            pass
        await self.secrets.delete(account_access.get().account_id)
        self.service.catalog.set_setting("connection", {})
        self.service.catalog.set_setting("remote_generation_runs", [])

    async def remote_usage(self):
        url, token = await self.credentials()
        async with self.client(url, token) as client:
            return await self.request(client, "GET", "/account/storage/transfer/usage")

    async def reserve_generation(self, run_id: str, estimate: int):
        state = self.service.catalog.setting("connection", {})
        if not state.get("confirmed"):
            return
        url, token = await self.credentials()
        async with self.client(url, token) as client:
            await self.request(
                client,
                "POST",
                "/account/storage/transfer/reservations",
                json={"id": run_id, "bytes": estimate},
            )
        pending = self.service.catalog.setting("remote_generation_runs", [])
        self.service.catalog.set_setting(
            "remote_generation_runs", list(dict.fromkeys([*pending, run_id]))
        )
        self.ensure_worker()

    def ensure_worker(self):
        access = account_access.get()
        if access is None:
            return
        state = self.service.catalog.setting("connection", {})
        key = str(access.account_id)
        if state.get("confirmed") and (key not in self.tasks or self.tasks[key].done()):
            self.tasks[key] = asyncio.create_task(self.worker())

    async def start(self):
        self.service.require_inventory()
        await self.credentials()
        state = self.service.catalog.setting("connection", {})
        state["auto_sync"] = True
        self.service.catalog.set_setting("connection", state)
        for job in self.service.catalog.jobs(internal=True):
            if job["id"].startswith("send:") and job["status"] == "failed":
                self.service.catalog.save_job(
                    job["id"], "queued", job["payload"], total=job["total"]
                )
        self.ensure_worker()
        return {"started": True}

    async def worker(self):
        while True:
            catalog = self.service.catalog
            jobs = [
                j
                for j in catalog.jobs(internal=True)
                if j["id"].startswith("send:") and j["status"] != "completed"
            ]
            ready = [
                j for j in jobs if j["status"] != "failed" or time.time() - j["updated_at"] >= 60
            ]
            job = ready[-1] if ready else None
            if job is None:
                state = catalog.setting("connection", {})
                excluded = {e["key"] for j in jobs for e in j["payload"]["entries"]}
                pending = catalog.pending_entries(
                    created_after=0
                    if state.get("auto_sync")
                    else state.get("connected_at", float("inf")),
                    excluded=excluded,
                )
                if pending:
                    try:
                        manifest = self.manifest(pending)
                        while (
                            len(pending) > 1
                            and len(json.dumps(manifest, ensure_ascii=False).encode())
                            > 7 * 1024 * 1024
                        ):
                            pending = pending[: max(1, len(pending) // 2)]
                            manifest = self.manifest(pending)
                    except (KeyError, TypeError, OSError):
                        for entry in pending:
                            self.service.failure(entry["key"])
                        await asyncio.sleep(15)
                        continue
                    job_id = f"send:{manifest['id']}"
                    catalog.save_job(job_id, "queued", manifest, total=len(manifest["files"]))
                    job = {"id": job_id, "payload": manifest}
            if job:
                try:
                    await self.send(job["payload"])
                except AccountError as exc:
                    catalog.save_job(
                        job["id"],
                        "failed",
                        job["payload"],
                        total=len(job["payload"]["files"]),
                        error=str(exc),
                    )
                except (OSError, ValueError, KeyError):
                    catalog.save_job(
                        job["id"],
                        "failed",
                        job["payload"],
                        error="同步未完成，本地文件保留，请重试",
                    )
            try:
                await self.release_finished()
            except AccountError:
                pass
            await asyncio.sleep(15)

    async def release_finished(self):
        from uuid import UUID

        from .service import TERMINAL

        catalog = self.service.catalog
        runs = catalog.setting("remote_generation_runs", [])
        if not runs:
            return
        url, token = await self.credentials()
        async with self.client(url, token) as client:
            for run_id in list(runs):
                run = await self.service.repository.get_generation_run(UUID(run_id))
                if run is not None and str(run.status) not in TERMINAL:
                    continue
                candidates = (
                    await self.service.repository.list_generation_candidates(run.id) if run else []
                )
                entries = [catalog.entry(f"candidate:{candidate.id}") for candidate in candidates]
                if any(e is None or e["updated_at"] > e["synced_version"] for e in entries):
                    continue
                await self.request(
                    client, "DELETE", f"/account/storage/transfer/reservations/{run_id}"
                )
                current = catalog.setting("remote_generation_runs", [])
                catalog.set_setting(
                    "remote_generation_runs", [value for value in current if value != run_id]
                )

    def manifest(self, entries):
        files = {}
        for entry in entries:
            for digest in (entry["sha256"], entry["thumbnail_sha256"]):
                if not digest or digest in files:
                    continue
                blob = self.service.catalog.blob(digest)
                files[digest] = {
                    "sha256": digest,
                    "size_bytes": blob["size_bytes"],
                    "filename": entry["metadata"].get("filename", "file.bin")
                    if digest == entry["sha256"]
                    else "thumbnail.webp",
                    "mime_type": entry["metadata"].get("mime_type", "application/octet-stream")
                    if digest == entry["sha256"]
                    else "image/webp",
                }
        return {
            "id": str(uuid4()),
            "source_workspace_id": str(account_access.get().workspace_id),
            "entries": [
                {
                    k: e[k]
                    for k in ("key", "kind", "sha256", "thumbnail_sha256", "metadata", "updated_at")
                }
                for e in entries
            ],
            "files": list(files.values()),
        }

    async def send(self, manifest):
        catalog = self.service.catalog
        job_id = f"send:{manifest['id']}"
        url, token = await self.credentials()
        async with self.client(url, token) as client:
            # Remove the corresponding generation holds before exact-byte batch admission.
            # The receiver performs this conversion atomically with batch reservation.
            response = await self.request(
                client, "POST", "/account/storage/transfer/batches", json=manifest
            )
            semaphore = asyncio.Semaphore(2)
            completed = 0

            async def upload(item):
                nonlocal completed
                async with semaphore:
                    blob = catalog.blob(item["sha256"])
                    path = catalog.resolve(blob["relative_path"])
                    progress = await self.request(
                        client, "GET", f"/account/storage/transfer/uploads/{item['id']}"
                    )
                    offset = progress["received"]
                    with path.open("rb") as source:
                        source.seek(offset)
                        while chunk := await asyncio.to_thread(source.read, CHUNK_BYTES):
                            await self.request(
                                client,
                                "PUT",
                                f"/account/storage/transfer/uploads/{item['id']}",
                                params={"offset": offset},
                                content=chunk,
                                headers={"Content-Type": "application/octet-stream"},
                            )
                            offset += len(chunk)
                    await self.request(
                        client, "POST", f"/account/storage/transfer/uploads/{item['id']}/complete"
                    )
                    completed += 1
                    catalog.save_job(
                        job_id,
                        "uploading",
                        manifest,
                        completed=completed,
                        total=len(response["uploads"]),
                    )

            await asyncio.gather(*(upload(item) for item in response["uploads"]))
            receipt = await self.request(
                client, "POST", f"/account/storage/transfer/batches/{manifest['id']}/complete"
            )
        for entry in manifest["entries"]:
            catalog.mark_synced(entry["key"], entry["updated_at"])
        catalog.save_job(
            job_id,
            "completed",
            manifest,
            completed=len(manifest["files"]),
            total=len(manifest["files"]),
        )
        catalog.set_setting("retained_on_server", receipt.get("retained_on_server", []))

    async def shutdown(self):
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
