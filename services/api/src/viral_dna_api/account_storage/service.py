from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager
from uuid import UUID

from ..access_context import account_access
from ..accounts.repository import AccountError
from .catalog import StorageCatalog

UNMETERED = {"thumbnail", "analysis_file", "subtitle"}
TERMINAL = {"completed", "cached", "failed", "cancelled", "blocked"}


class AccountStorageService:
    def __init__(self, repository, workspace, storage):
        self.repository = repository
        self.workspace = workspace
        self.storage = storage
        self.sync = None
        self.asset_lock = asyncio.Lock()
        self._catalogs = {}
        self._mutation_locks = {}
        self._mutation_owners = {}
        self._inventory_tasks = {}

    def require_inventory(self):
        if self.enabled and self.catalog.setting("inventory_state", "ready") != "ready":
            raise AccountError(
                409, "storage_inventory_pending", "正在核对现有存储，请完成归档清点后再上传或生成"
            )

    def start_inventory(self):
        if not self.enabled:
            return
        key = str(account_access.get().account_id)
        previous = self._inventory_tasks.get(key)
        if previous and not previous.done():
            return
        self.catalog.set_setting("inventory_state", "scanning")

        async def inventory():
            try:
                await self.bootstrap()
            except Exception:
                self.catalog.set_setting("inventory_state", "failed")
                self.failure("inventory")

        self._inventory_tasks[key] = asyncio.create_task(inventory())

    async def shutdown(self):
        tasks = list(self._inventory_tasks.values())
        self._inventory_tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @asynccontextmanager
    async def mutation(self):
        if not self.enabled:
            yield
            return
        key = str(account_access.get().account_id)
        task = asyncio.current_task()
        if self._mutation_owners.get(key) is task:
            yield
            return
        async with self._mutation_locks.setdefault(key, asyncio.Lock()):
            self._mutation_owners[key] = task
            try:
                yield
            finally:
                self._mutation_owners.pop(key, None)

    @property
    def enabled(self):
        return account_access.get() is not None

    @property
    def catalog(self):
        access = account_access.get()
        if access is None:
            raise AccountError(401, "login_required", "请先登录账户")
        key = (str(access.account_id), str(access.workspace_root))
        if key not in self._catalogs:
            self._catalogs[key] = StorageCatalog(
                access.workspace_root, str(access.account_id), access.account_kind
            )
        return self._catalogs[key]

    async def before_run(self, run):
        if not self.enabled or str(run.status) not in {"queued", "running"}:
            return
        existing = await self.repository.get_generation_run(run.id)
        if existing is not None:
            return
        self.require_inventory()
        request = run.request_payload or {}
        count = max(1, int(request.get("candidate_count") or 1))
        if str(run.kind) == "image":
            width, height = int(request.get("width") or 2048), int(request.get("height") or 2048)
            estimate = count * max(8_000_000, width * height * 4 + 1_000_000)
        else:
            estimate = count * max(
                64_000_000, int(float(request.get("duration_seconds") or 8) * 8_000_000)
            )
        remote = self.catalog.setting("connection", {}).get("confirmed", False)
        await asyncio.to_thread(
            self.catalog.reserve, f"generation:{run.id}", estimate, "generation", enforce=not remote
        )
        try:
            if self.sync:
                await self.sync.reserve_generation(str(run.id), estimate)
        except BaseException:
            await asyncio.to_thread(self.catalog.release, f"generation:{run.id}")
            raise
        return True

    async def rollback_run(self, run):
        if self.enabled:
            await asyncio.to_thread(self.catalog.release, f"generation:{run.id}")
            # The sync worker also releases the remote hold when no saved run exists.

    async def after_run(self, run):
        if self.enabled and str(run.status) in TERMINAL:
            for candidate in await self.repository.list_generation_candidates(run.id):
                await self.capture_candidate(candidate)
            await asyncio.to_thread(self.catalog.release, f"generation:{run.id}")

    def failure(self, source_key: str):
        # Error records contain stable identifiers only, never paths or credentials.
        failures = self.catalog.setting("archive_failures", [])
        if source_key not in failures:
            self.catalog.set_setting("archive_failures", [*failures, source_key][-1000:])

    async def capture_candidate(self, candidate):
        if not self.enabled:
            return
        key = f"candidate:{candidate.id}"
        if self.catalog.removed(key):
            return
        try:
            run = await self.repository.get_generation_run(candidate.generation_run_id)
            if run is None:
                return
            catalog = self.catalog
            source = self.workspace.resolve(candidate.relative_path)
            blob = await asyncio.to_thread(
                catalog.keep_file,
                source,
                expected_sha256=candidate.sha256,
                reservation_id=f"generation:{run.id}",
                preserve=True,
            )
            thumbnail = None
            if candidate.thumbnail_relative_path:
                thumbnail_path = self.workspace.resolve(candidate.thumbnail_relative_path)
                if thumbnail_path.is_file():
                    thumbnail = (
                        await asyncio.to_thread(
                            catalog.keep_file, thumbnail_path, chargeable=False, preserve=True
                        )
                    )["sha256"]
            project = await self.repository.get_production_project(run.project_id)
            metadata = {
                "source_id": str(candidate.id),
                "source_workspace_id": str(account_access.get().workspace_id),
                "project_id": str(run.project_id),
                "project_name": getattr(project, "name", "") or "",
                "shot_plan_id": str(run.shot_plan_id),
                "generation_run_id": str(run.id),
                "provider": run.provider,
                "model": run.model,
                "prompt_snapshot": (run.request_payload or {}).get("prompt_snapshot"),
                "parameters": {
                    k: v
                    for k, v in (run.request_payload or {}).items()
                    if k
                    in {
                        "width",
                        "height",
                        "candidate_count",
                        "seed",
                        "input_mode",
                        "duration_seconds",
                        "resolution",
                        "aspect_ratio",
                    }
                },
                "actual_cost_micros": run.actual_cost_micros,
                "revision_id": str(run.revision_id),
                "width": candidate.width,
                "height": candidate.height,
                "duration_seconds": candidate.duration_seconds,
                "ordinal": candidate.ordinal,
                "created_at": candidate.created_at.isoformat(),
                "candidate_status": str(candidate.status),
                "filename": source.name,
                "mime_type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            }
            await asyncio.to_thread(
                catalog.put_entry, key, str(candidate.kind), blob["sha256"], metadata, thumbnail
            )
        except (OSError, ValueError, AccountError):
            self.failure(key)

    async def capture_asset(self, asset):
        if not self.enabled or self.catalog.removed(f"asset:{asset.id}"):
            return
        if asset.deleted_at is not None:
            self.catalog.trash(f"asset:{asset.id}")
            return
        try:
            catalog = self.catalog
            key = catalog.setting(f"imported_asset:{asset.id}", f"asset:{asset.id}")
            previous = catalog.entry(key)
            path = await self.storage.materialize_local(asset.content_object_id)
            blob = await asyncio.to_thread(catalog.keep_file, path, preserve=True)
            thumb = await self.storage.materialize_local(asset.thumbnail_object_id)
            thumbnail = await asyncio.to_thread(
                catalog.keep_file, thumb, chargeable=False, preserve=True
            )
            folders = [
                f
                for f in await self.repository.list_asset_folders()
                if f.workspace_id == asset.workspace_id
            ]
            metadata = {
                **(previous or {}).get("metadata", {}),
                "asset": asset.model_dump(mode="json"),
                "folders": [f.model_dump(mode="json") for f in folders if f.deleted_at is None],
                "source_id": str(asset.id),
                "source_workspace_id": str(asset.workspace_id),
                "filename": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            }
            await asyncio.to_thread(
                catalog.put_entry, key, "asset", blob["sha256"], metadata, thumbnail["sha256"]
            )
        except (OSError, ValueError, AccountError, RuntimeError):
            self.failure(f"asset:{asset.id}")

    async def capture_file(self, key, kind, relative, metadata, *, thumbnail=None, sha256=None):
        if not self.enabled or not relative or self.catalog.removed(key):
            return
        try:
            path = self.workspace.resolve(relative)
            blob = await asyncio.to_thread(
                self.catalog.keep_file,
                path,
                expected_sha256=sha256,
                preserve=True,
                reservation_id=key,
            )
            thumb = None
            if thumbnail and self.workspace.resolve(thumbnail).is_file():
                thumb = (
                    await asyncio.to_thread(
                        self.catalog.keep_file,
                        self.workspace.resolve(thumbnail),
                        chargeable=False,
                        preserve=True,
                    )
                )["sha256"]
            snapshot = {
                "source_workspace_id": str(account_access.get().workspace_id),
                "filename": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                **metadata,
            }
            await asyncio.to_thread(
                self.catalog.put_entry, key, kind, blob["sha256"], snapshot, thumb
            )
        except (OSError, ValueError, AccountError):
            self.failure(key)

    async def capture_video_source(self, video):
        await self.capture_file(
            f"source:{video.id}",
            "source",
            video.stored_relative_path or video.stored_path,
            {"source_id": str(video.id), "project_name": video.title},
            sha256=video.sha256,
        )

    async def capture_enhancement(self, job):
        if job.result_relative_path:
            await self.capture_file(
                f"enhancement:{job.id}",
                "video",
                job.result_relative_path,
                {
                    "source_id": str(job.id),
                    "project_id": str(job.project_id),
                    "model": job.model,
                    "provider": job.engine,
                    "candidate_id": str(job.candidate_id),
                    "variant": "enhanced",
                },
                sha256=job.result_sha256,
            )

    async def capture_shot_media(self, shot):
        if not self.enabled:
            return
        for asset in shot.depth_control_assets:
            if asset.relative_path:
                await self.capture_file(
                    f"depth:{asset.id}",
                    "video",
                    asset.relative_path,
                    {
                        "source_id": str(asset.id),
                        "project_id": str(shot.project_id),
                        "shot_plan_id": str(shot.id),
                        "model": asset.model_variant,
                        "provider": asset.engine,
                        "variant": "depth",
                    },
                    thumbnail=asset.thumbnail_relative_path,
                    sha256=asset.sha256,
                )

    async def capture_export(self, project, job):
        if str(job.kind) == "final" and job.output_relative_path:
            await self.capture_file(
                f"export:{job.id}",
                "export",
                job.output_relative_path,
                {
                    "source_id": str(job.id),
                    "project_id": str(project.id),
                    "project_name": project.name,
                    "revision_id": str(job.timeline_revision_id),
                },
                thumbnail=job.cover_relative_path,
                sha256=job.sha256,
            )

    async def reserve_auxiliary(self, key, size):
        if not self.enabled:
            return
        self.require_inventory()
        remote = self.catalog.setting("connection", {}).get("confirmed", False)
        if remote and self.sync and size > (await self.sync.remote_usage())["available_bytes"]:
            raise AccountError(409, "storage_quota_exceeded", "服务器空间不足，请先清理或扩容")
        await asyncio.to_thread(self.catalog.reserve, key, size, "auxiliary", enforce=not remote)

    async def release_auxiliary(self, key):
        if self.enabled:
            await asyncio.to_thread(self.catalog.release, key)

    async def before_object(self, storage_object):
        if not self.enabled or str(storage_object.object_type) in UNMETERED:
            return
        self.require_inventory()
        existing = await asyncio.to_thread(self.catalog.blob, storage_object.sha256)
        size = 0 if existing and existing["chargeable"] else storage_object.size_bytes
        remote = self.catalog.setting("connection", {}).get("confirmed", False)
        if remote and size and self.sync:
            usage = await self.sync.remote_usage()
            if size > usage["available_bytes"]:
                raise AccountError(
                    409, "storage_quota_exceeded", "服务器空间不足，请清理文件或联系管理员扩容"
                )
        await asyncio.to_thread(
            self.catalog.reserve, f"object:{storage_object.id}", size, enforce=not remote
        )

    async def after_object(self, storage_object, replica):
        if not self.enabled:
            return
        try:
            await self._capture_object(storage_object, replica)
        except (OSError, ValueError, AccountError, RuntimeError):
            self.failure(f"object:{storage_object.id}")
        finally:
            await asyncio.to_thread(self.catalog.release, f"object:{storage_object.id}")

    async def _capture_object(self, storage_object, replica):
        catalog = self.catalog
        blob = await asyncio.to_thread(
            catalog.keep_file,
            self.workspace.resolve(replica.object_key),
            chargeable=str(storage_object.object_type) not in UNMETERED,
            expected_sha256=storage_object.sha256,
            reservation_id=f"object:{storage_object.id}",
            preserve=True,
        )
        # Objects protect shared files even before they have an asset/history entry.
        await asyncio.to_thread(
            catalog.put_entry,
            f"object:{storage_object.id}",
            "object",
            blob["sha256"],
            {
                "object_id": str(storage_object.id),
                "type": str(storage_object.object_type),
                "filename": storage_object.original_filename,
                "mime_type": storage_object.mime_type,
            },
        )

    async def bootstrap(self):
        if not self.enabled:
            return
        self.catalog.set_setting("inventory_state", "scanning")
        self.catalog.set_setting("archive_failures", [])
        try:
            access = account_access.get()
            self.storage.bind_local_location(access.storage_location_id)
            for asset in await self.repository.list_assets():
                if asset.workspace_id == access.workspace_id:
                    await self.capture_asset(asset)
            for video in await self.repository.list_videos():
                await self.capture_video_source(video)
            for job in await self.repository.list_video_enhancement_jobs():
                await self.capture_enhancement(job)
            for project in await self.repository.list_production_projects():
                for shot in await self.repository.list_shot_plans(project.id):
                    await self.capture_shot_media(shot)
                runs = await self.repository.list_generation_runs(project.id)
                for candidate in await self.repository.list_generation_candidates_by_run_ids(
                    {r.id for r in runs}
                ):
                    await self.capture_candidate(candidate)
                for run in runs:
                    await self.after_run(run)
                paths = self.workspace.production_paths(project.record_id, project.id)
                from ..models import TimelineRenderJob

                for path in (paths.exports / "jobs").glob("*.json"):
                    try:
                        job = TimelineRenderJob.model_validate_json(
                            await asyncio.to_thread(path.read_text, encoding="utf-8-sig")
                        )
                        await self.capture_export(project, job)
                        await self.release_auxiliary(f"export:{job.id}")
                    except (OSError, ValueError):
                        self.failure(f"export-inventory:{project.id}")
                for path in paths.timelines.glob("audio/*"):
                    if path.is_file():
                        await self.capture_file(
                            f"audio:{path.stem}",
                            "audio",
                            self.workspace.relative(path),
                            {"project_id": str(project.id), "project_name": project.name},
                        )
            self.catalog.set_setting("inventory_state", "ready")
        except BaseException:
            self.catalog.set_setting("inventory_state", "failed")
            raise

    async def referenced(self, entry):
        """Fail closed on live references before any permanent-file operation."""
        metadata = entry["metadata"]
        identifier = metadata.get("target_asset_id") or metadata.get("source_id")
        own_asset = identifier if entry["kind"] == "asset" else None
        if entry["kind"] == "source" and identifier:
            video = await self.repository.get_video(UUID(identifier))
            if video and video.record_id and await self.repository.get_record(video.record_id):
                return True
        identifiers = {identifier} - {None}
        digests = {entry["sha256"], entry["thumbnail_sha256"]} - {None}
        for asset in await self.repository.list_assets():
            if asset.deleted_at is not None or str(asset.id) == own_asset:
                continue
            obj = await self.repository.get_storage_object(asset.content_object_id)
            if obj and obj.sha256 in digests:
                return True
        for link in await self.repository.list_project_asset_links():
            if link.removed_at is None and str(link.asset_id) in identifiers:
                if await self.repository.get_production_project(link.project_id):
                    return True
        for obj in await self.repository.list_storage_objects():
            if obj.sha256 in digests:
                identifiers.add(str(obj.id))
        with self.catalog.connect() as db:
            paths = [
                row[0]
                for row in db.execute("SELECT relative_path,sha256 FROM sources")
                if row[1] in digests
            ]
        identifiers.update(paths)
        for project in await self.repository.list_production_projects():
            if entry["kind"] in {"source", "audio"} and metadata.get("project_id") == str(
                project.id
            ):
                return True
            if (
                entry["kind"] == "source"
                and str(getattr(project, "source_video_id", "")) == identifier
            ):
                return True
            for revision in await self.repository.list_production_revisions(project.id):
                if any(value in revision.model_dump_json() for value in identifiers):
                    return True
            for shot in await self.repository.list_shot_plans(project.id):
                if any(value in shot.model_dump_json() for value in identifiers):
                    return True
            # Timeline snapshots are immutable references outside the business DB.
            root = self.workspace.production_paths(project.record_id, project.id).root
            for path in root.glob("timelines/**/*.json"):
                content = await asyncio.to_thread(path.read_text, encoding="utf-8-sig")
                if any(value in content for value in identifiers):
                    return True
        for project in await self.repository.list_projects():
            for usage in await self.repository.list_asset_usages(project.id):
                if any(value in usage.model_dump_json() for value in identifiers):
                    return True
            for revision in await self.repository.list_timeline_v3_revisions(project.id):
                if any(value in revision.model_dump_json() for value in identifiers):
                    return True
        return False

    async def set_trash(self, entry, restore=False):
        if entry["kind"] == "asset":
            from ..asset_library import utc_now

            identity = entry["metadata"].get("target_asset_id") or entry["metadata"].get(
                "source_id"
            )
            asset = await self.repository.get_asset(UUID(identity)) if identity else None
            if asset:
                await self.repository.save_asset(
                    asset.model_copy(
                        update={
                            "deleted_at": None if restore else utc_now(),
                            "version": asset.version + 1,
                        }
                    )
                )
        self.catalog.trash(entry["key"], restore=restore)

    async def purge(self, entry):
        # All business writes and reference checks share this account's mutation gate.
        async with self.mutation():
            if entry["deleted_at"] is None:
                raise AccountError(409, "storage_trash_required", "请先将记录移入回收站")
            if await self.referenced(entry):
                raise AccountError(
                    409, "storage_entry_referenced", "文件仍被项目或资产引用，不能永久删除"
                )
            identifier = entry["metadata"].get("source_id")
            if entry["key"].startswith("candidate:") and identifier:
                from ..models import (
                    GenerationCandidateArchiveReason,
                    GenerationCandidateStatus,
                    utc_now,
                )

                candidate = await self.repository.get_generation_candidate(UUID(identifier))
                if candidate:
                    retired = candidate.model_copy(
                        update={
                            "status": GenerationCandidateStatus.ARCHIVED,
                            "archived_at": utc_now(),
                            "archived_by_account_id": account_access.get().account_id,
                            "archive_reason": GenerationCandidateArchiveReason.USER_DELETED,
                        }
                    )
                    await self.repository.backend.save_generation_candidate(retired)
            digests = {entry["sha256"], entry["thumbnail_sha256"]} - {None}
            self.catalog.forget_object_guards(digests)
            return await asyncio.to_thread(self.catalog.purge, entry["key"])

    async def history(self, *, kind=None, trash=False, limit=50, offset=0):
        data = await asyncio.to_thread(
            self.catalog.entries, kind=kind, trash=trash, limit=limit, offset=offset
        )
        for entry in data["items"]:
            from urllib.parse import quote

            escaped = quote(entry["key"], safe="")
            entry["content_url"] = f"/api/v1/account/storage/entries/{escaped}/content"
            entry["thumbnail_url"] = (
                f"/api/v1/account/storage/entries/{escaped}/thumbnail"
                if entry["thumbnail_sha256"]
                else None
            )
            blob = self.catalog.blob(entry["sha256"])
            entry["size_bytes"] = blob["size_bytes"] if blob else 0
        return data
