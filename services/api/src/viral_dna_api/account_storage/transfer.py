from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from ..access_context import account_access
from ..accounts.repository import AccountError
from .catalog import CHUNK_BYTES, file_hash


class FileManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=100_000_000_000)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=120)


class EntryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=180)
    kind: Literal["asset", "image", "video", "source", "audio", "export"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    thumbnail_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metadata: dict
    updated_at: float = Field(ge=0)


class BatchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    source_workspace_id: UUID
    entries: list[EntryManifest] = Field(min_length=1, max_length=1000)
    files: list[FileManifest] = Field(min_length=1, max_length=2000)


class TransferReceiver:
    def __init__(self, service):
        self.service = service

    @property
    def catalog(self):
        return self.service.catalog

    def remote_key(self, manifest, entry):
        return "remote:" + str(
            uuid5(UUID(self.catalog.account_id), f"{manifest.source_workspace_id}:{entry.key}")
        )

    def retained(self, manifest, entry):
        key = self.remote_key(manifest, entry)
        current = self.catalog.entry(key)
        return self.catalog.removed(key) or (current and current["deleted_at"] is not None)

    def cleanup_incomplete(self):
        """Expire only abandoned transfer parts/holds, never durable originals."""
        catalog = self.catalog
        now = time.time()
        with catalog.connect(write=True) as db:
            rows = db.execute(
                "SELECT id FROM jobs WHERE id LIKE 'receive:%' "
                "AND status!='completed' AND updated_at<?",
                (now - 7 * 86400,),
            ).fetchall()
            for row in rows:
                for upload in db.execute("SELECT id FROM uploads WHERE batch_id=?", (row[0],)):
                    catalog.resolve(f"temp/storage-sync/{UUID(upload[0])}.part").unlink(
                        missing_ok=True
                    )
                db.execute("DELETE FROM uploads WHERE batch_id=?", (row[0],))
                db.execute("DELETE FROM reservations WHERE id=?", (row[0],))
                db.execute("DELETE FROM jobs WHERE id=?", (row[0],))
            db.execute(
                "DELETE FROM reservations WHERE id LIKE 'remote-generation:%' AND created_at<?",
                (now - 30 * 86400,),
            )

    def begin(self, manifest: BatchManifest, device_id: str | None = None):
        self.cleanup_incomplete()
        if device_id is not None and device_id != str(manifest.source_workspace_id):
            raise AccountError(403, "sync_device_mismatch", "同步清单不属于已授权的本地工作区")
        payload = manifest.model_dump(mode="json")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
            raise AccountError(413, "sync_manifest_too_large", "同步清单过大，请分批同步")
        catalog = self.catalog
        content = {e.sha256 for e in manifest.entries}
        thumbnails = {e.thumbnail_sha256 for e in manifest.entries if e.thumbnail_sha256}
        files = {f.sha256: f for f in manifest.files}
        if len(files) != len(manifest.files) or set(files) != content | thumbnails:
            raise AccountError(422, "sync_manifest_invalid", "同步文件清单不完整或重复")
        if any(files[h].size_bytes > 1_000_000 for h in thumbnails - content):
            raise AccountError(413, "sync_thumbnail_too_large", "同步缩略图不能超过 1 MB")
        active = [e for e in manifest.entries if not self.retained(manifest, e)]
        needed = {digest for e in active for digest in (e.sha256, e.thumbnail_sha256) if digest}
        # Validate asset data before accepting any bytes. IDs are always remapped
        # into the authenticated target account; source account IDs are not trusted.
        from ..asset_library import Asset, AssetFolder

        for entry in active:
            if entry.kind == "asset":
                asset = Asset.model_validate(entry.metadata.get("asset"))
                folders = [
                    AssetFolder.model_validate(item) for item in entry.metadata.get("folders", [])
                ]
                if (
                    len(folders) > 1000
                    or asset.workspace_id != manifest.source_workspace_id
                    or any(f.workspace_id != manifest.source_workspace_id for f in folders)
                ):
                    raise AccountError(
                        422, "sync_asset_scope_invalid", "资产或目录不属于来源工作区"
                    )
        job_id = f"receive:{manifest.id}"
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with catalog.connect(write=True) as db:
            old = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if old:
                if json.loads(old[0])["fingerprint"] != fingerprint:
                    raise AccountError(
                        409, "sync_batch_conflict", "本次同步清单已变化，请新建同步任务"
                    )
            else:
                missing = []
                required = 0
                promotions = []
                for digest, item in files.items():
                    if digest not in needed:
                        continue
                    blob = db.execute("SELECT * FROM blobs WHERE sha256=?", (digest,)).fetchone()
                    if blob and blob["size_bytes"] != item.size_bytes:
                        raise AccountError(
                            409, "sync_checksum_conflict", "同步文件大小与校验和不一致"
                        )
                    valid = blob and catalog.valid_blob(digest)
                    if not valid:
                        missing.append(item)
                    if digest in content and (blob is None or not blob["chargeable"]):
                        required += item.size_bytes
                        if valid:
                            promotions.append(item)
                holds = []
                for entry in manifest.entries:
                    run_id = entry.metadata.get("generation_run_id")
                    if run_id and entry.kind in {"image", "video"}:
                        try:
                            hold_id = (
                                f"remote-generation:{manifest.source_workspace_id}:{UUID(run_id)}"
                            )
                        except (ValueError, TypeError, AttributeError):
                            raise AccountError(
                                422, "sync_run_invalid", "生成任务标识无效"
                            ) from None
                        hold = db.execute(
                            "SELECT id,bytes FROM reservations WHERE id=?", (hold_id,)
                        ).fetchone()
                        if hold and hold["id"] not in {h["id"] for h in holds}:
                            holds.append(dict(hold))
                prepaid = sum(hold["bytes"] for hold in holds)
                available = catalog._usage(db)["available_bytes"]
                # Only previously admitted generation tasks have a bounded safety
                # margin; ordinary uploads can never assert a quota bypass flag.
                grace = (
                    min(prepaid * 4, 100_000_000)
                    if all(e.kind in {"image", "video"} for e in manifest.entries)
                    else 0
                )
                preserve = required > available + prepaid
                if required > available + prepaid + grace:
                    raise AccountError(
                        409,
                        "storage_quota_exceeded",
                        f"服务器空间不足，本次还需 {required:,} 字节，请先扩容",
                    )
                remaining = required
                for hold in holds:
                    consumed = min(remaining, hold["bytes"])
                    db.execute(
                        "UPDATE reservations SET bytes=bytes-? WHERE id=?", (consumed, hold["id"])
                    )
                    remaining -= consumed
                now = time.time()
                db.execute(
                    "INSERT INTO reservations VALUES(?,?,?,?)", (job_id, required, "sync", now)
                )
                for item in promotions:
                    db.execute("UPDATE blobs SET chargeable=1 WHERE sha256=?", (item.sha256,))
                    db.execute(
                        "UPDATE reservations SET bytes=bytes-? WHERE id=?",
                        (item.size_bytes, job_id),
                    )
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,0,?,NULL,?,?)",
                    (
                        job_id,
                        "uploading",
                        json.dumps(
                            {"fingerprint": fingerprint, "manifest": payload, "preserve": preserve}
                        ),
                        len(missing),
                        now,
                        now,
                    ),
                )
                for item in missing:
                    db.execute(
                        "INSERT INTO uploads VALUES(?,?,?,?,0,?,?,?)",
                        (
                            str(uuid4()),
                            job_id,
                            item.sha256,
                            item.size_bytes,
                            int(item.sha256 in content),
                            item.filename,
                            item.mime_type,
                        ),
                    )
            rows = db.execute("SELECT * FROM uploads WHERE batch_id=?", (job_id,)).fetchall()
        return {
            "id": str(manifest.id),
            "uploads": [dict(row) for row in rows],
            "usage": catalog.usage(),
        }

    def upload(self, upload_id: str):
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            if row is None:
                raise AccountError(404, "sync_upload_missing", "上传任务不存在")
            return dict(row)

    def chunk(self, upload_id: str, offset: int, payload: bytes):
        if not payload or len(payload) > CHUNK_BYTES:
            raise AccountError(413, "sync_chunk_invalid", "上传分块大小无效")
        catalog = self.catalog
        with catalog.connect(write=True) as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            if row is None:
                raise AccountError(404, "sync_upload_missing", "上传任务不存在")
            if offset != row["received"]:
                raise AccountError(409, "sync_offset_conflict", "上传进度已变化，请重新读取断点")
            if offset + len(payload) > row["size_bytes"]:
                raise AccountError(413, "sync_size_exceeded", "上传内容超过清单中的文件大小")
            path = catalog.resolve(f"temp/storage-sync/{UUID(upload_id)}.part")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("r+b" if path.exists() else "w+b") as handle:
                handle.seek(offset)
                handle.write(payload)
                handle.truncate()
                handle.flush()
                import os

                os.fsync(handle.fileno())
            db.execute(
                "UPDATE uploads SET received=? WHERE id=?", (offset + len(payload), upload_id)
            )
            db.execute("UPDATE jobs SET updated_at=? WHERE id=?", (time.time(), row["batch_id"]))
        return {"received": offset + len(payload)}

    def finish(self, upload_id: str):
        row = self.upload(upload_id)
        catalog = self.catalog
        existing = catalog.valid_blob(row["sha256"])
        if existing and (existing["chargeable"] or not row["chargeable"]):
            return {"complete": True}
        if row["received"] != row["size_bytes"]:
            raise AccountError(409, "sync_upload_incomplete", "文件尚未上传完成")
        path = catalog.resolve(f"temp/storage-sync/{UUID(upload_id)}.part")
        if file_hash(path) != (row["sha256"], row["size_bytes"]):
            with catalog.connect(write=True) as db:
                db.execute("UPDATE uploads SET received=0 WHERE id=?", (upload_id,))
            raise AccountError(409, "storage_checksum_mismatch", "上传文件校验失败，请重试此文件")
        if not row["chargeable"]:
            from PIL import Image

            try:
                with Image.open(path) as picture:
                    if picture.format not in {"PNG", "JPEG", "WEBP"} or max(picture.size) > 2048:
                        raise ValueError("invalid thumbnail")
                    picture.verify()
            except (OSError, ValueError):
                raise AccountError(422, "sync_thumbnail_invalid", "缩略图格式或尺寸无效") from None
        with catalog.connect() as db:
            admission = json.loads(
                db.execute("SELECT payload FROM jobs WHERE id=?", (row["batch_id"],)).fetchone()[0]
            )
        catalog.keep_file(
            path,
            chargeable=bool(row["chargeable"]),
            expected_sha256=row["sha256"],
            reservation_id=row["batch_id"],
            preserve=admission.get("preserve", False),
        )
        # Only our verified per-upload temporary chunk file is removed.
        path.unlink(missing_ok=True)
        return {"complete": True}

    async def commit(self, batch_id: UUID):
        catalog = self.catalog
        job_id = f"receive:{batch_id}"
        with catalog.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise AccountError(404, "sync_batch_missing", "同步任务不存在")
        saved = json.loads(row["payload"])
        if row["status"] == "completed":
            return {
                "complete": True,
                "retained_on_server": saved.get("retained_on_server", []),
                "usage": catalog.usage(),
            }
        manifest = BatchManifest.model_validate(saved["manifest"])
        needed = {
            digest
            for e in manifest.entries
            if not self.retained(manifest, e)
            for digest in (e.sha256, e.thumbnail_sha256)
            if digest
        }
        for item in manifest.files:
            if item.sha256 not in needed:
                continue
            if not await asyncio.to_thread(catalog.valid_blob, item.sha256):
                raise AccountError(
                    409, "sync_upload_incomplete", "仍有文件未完成上传，不能标记同步成功"
                )
        retained = []
        for entry in manifest.entries:
            remote_key = self.remote_key(manifest, entry)
            old = catalog.entry(remote_key)
            if catalog.removed(remote_key) or (old and old["deleted_at"] is not None):
                retained.append(entry.key)
                continue
            if old and old["sha256"] != entry.sha256:
                raise AccountError(
                    409, "sync_content_conflict", "同一记录的原文件发生变化，请核对后重新同步"
                )
            metadata = {
                **entry.metadata,
                "origin_workspace_id": str(manifest.source_workspace_id),
                "origin_key": entry.key,
            }
            if entry.kind == "asset":
                async with self.service.asset_lock:
                    original_id = entry.metadata.get("asset", {}).get("id")
                    namespace = uuid5(UUID(catalog.account_id), str(manifest.source_workspace_id))
                    catalog.set_setting(
                        f"imported_asset:{uuid5(namespace, str(original_id))}", remote_key
                    )
                    imported, kept = await self.import_asset(
                        manifest.source_workspace_id, entry, old
                    )
                metadata.update(imported)
                if kept:
                    retained.append(entry.key)
            await asyncio.to_thread(
                catalog.put_entry,
                remote_key,
                entry.kind,
                entry.sha256,
                metadata,
                entry.thumbnail_sha256,
            )
        saved["retained_on_server"] = retained
        await asyncio.to_thread(catalog.release, job_id)
        await asyncio.to_thread(
            catalog.save_job,
            job_id,
            "completed",
            saved,
            completed=len(manifest.files),
            total=len(manifest.files),
        )
        return {"complete": True, "retained_on_server": retained, "usage": catalog.usage()}

    async def import_asset(self, source_workspace: UUID, entry: EntryManifest, old=None):
        from ..asset_library import Asset, AssetFolder, AssetScope
        from ..storage_objects import StorageObjectType

        access = account_access.get()
        catalog = self.catalog
        namespace = uuid5(access.account_id, str(source_workspace))
        original = Asset.model_validate(entry.metadata.get("asset"))
        target_id = uuid5(namespace, str(original.id))
        current = await self.service.repository.get_asset(target_id)
        baseline = (old or {}).get("metadata", {}).get("imported_asset_version")
        if current and (current.version != baseline or current.deleted_at or current.archived_at):
            return {
                "target_asset_id": str(target_id),
                "imported_asset_version": baseline,
                "asset": current.model_dump(mode="json"),
            }, True
        folders = [
            AssetFolder.model_validate(item) for item in entry.metadata.get("folders", [])[:1000]
        ]
        source_folder_ids = {f.id for f in folders}
        folder_versions = catalog.setting(f"folder_versions:{source_workspace}", {})
        for folder in folders:
            target = folder.model_copy(
                update={
                    "id": uuid5(namespace, str(folder.id)),
                    "account_id": access.account_id,
                    "workspace_id": access.workspace_id,
                    "scope": AssetScope.ACCOUNT,
                    "parent_id": uuid5(namespace, str(folder.parent_id))
                    if folder.parent_id in source_folder_ids
                    else None,
                    "cover_asset_id": None,
                }
            )
            current_folder = await self.service.repository.get_asset_folder(target.id)
            baseline_folder = folder_versions.get(str(target.id))
            if current_folder is None or (
                current_folder.version == baseline_folder and not current_folder.deleted_at
            ):
                if current_folder and all(
                    getattr(current_folder, key) == getattr(target, key)
                    for key in ("name", "parent_id", "sort_order")
                ):
                    continue
                target = target.model_copy(
                    update={"version": current_folder.version + 1 if current_folder else 1}
                )
                repository = getattr(self.service.repository, "backend", self.service.repository)
                await repository.save_asset_folder(target)
                folder_versions[str(target.id)] = target.version
        catalog.set_setting(f"folder_versions:{source_workspace}", folder_versions)
        if current:
            target_folder = (
                uuid5(namespace, str(original.folder_id))
                if original.folder_id in source_folder_ids
                else None
            )
            target = current.model_copy(
                update={
                    **{
                        key: getattr(original, key)
                        for key in (
                            "name",
                            "description",
                            "tags",
                            "type",
                            "rights_confirmed",
                            "rights_note",
                        )
                    },
                    "folder_id": target_folder,
                    "version": current.version + 1,
                }
            )
            await self.service.repository.save_asset(target)
            return {
                "target_asset_id": str(target_id),
                "imported_asset_version": target.version,
                "asset": target.model_dump(mode="json"),
            }, False
        self.service.storage.bind_local_location(access.storage_location_id)
        objects = []
        for digest, role in [
            (entry.sha256, "content"),
            (entry.thumbnail_sha256 or entry.sha256, "thumbnail"),
        ]:
            blob = catalog.blob(digest)
            item = await self.service.storage.register_existing_local_object(
                account_id=access.account_id,
                workspace_id=access.workspace_id,
                storage_location_id=access.storage_location_id,
                object_type=StorageObjectType.THUMBNAIL
                if role == "thumbnail"
                else StorageObjectType.ASSET_IMAGE,
                original_filename=entry.metadata.get("filename", "asset.bin"),
                mime_type=entry.metadata.get("mime_type", "application/octet-stream"),
                object_key=blob["relative_path"],
                expected_sha256=digest,
            )
            objects.append(item.id)
        target = original.model_copy(
            update={
                "id": target_id,
                "account_id": access.account_id,
                "workspace_id": access.workspace_id,
                "scope": AssetScope.ACCOUNT,
                "folder_id": uuid5(namespace, str(original.folder_id))
                if original.folder_id in source_folder_ids
                else None,
                "content_object_id": objects[0],
                "thumbnail_object_id": objects[1],
                "origin_artifact_id": None,
            }
        )
        await self.service.repository.save_asset(target)
        return {
            "target_asset_id": str(target_id),
            "imported_asset_version": target.version,
            "asset": target.model_dump(mode="json"),
        }, False
