from __future__ import annotations

import asyncio
import secrets
from uuid import UUID

from fastapi import Request

from ..access_context import EditFence, account_access, request_edit_fence
from .repository import AccountError, token_hash
from .runtime import account_repository, password_auth_enabled

# The outer, user-facing Project is the lock boundary, including every production.
COLLECTION_GETTERS = {
    "production-shots": ("get_shot_plan",),
    "generation-candidates": ("get_generation_candidate",),
    "generation-runs": ("get_generation_run",),
    "skill-runs": ("get_skill_run",),
    "analyses": ("get_analysis",),
    "videos": ("get_video",),
    "references": ("get_reference_asset",),
    "project-assets": ("get_project_asset_link",),
    "exports": ("get_export",),
    "depth-control-jobs": ("get_depth_control_job",),
    "video-enhancement-jobs": ("get_video_enhancement_job",),
    "viral-concept-sets": ("get_viral_concept_set",),
}


async def owner_project(repository, item_id: str, *, collection="projects", depth=0) -> str:
    if depth > 5:
        raise AccountError(404, "project_missing", "项目不存在")
    try:
        identifier = UUID(str(item_id))
    except ValueError:
        raise AccountError(404, "project_missing", "项目不存在") from None
    if collection in {"projects", "records", "productions"}:
        if collection != "productions":
            project = await repository.get_project(identifier)
            record = await repository.get_record(identifier) if project is None else None
            if project is not None or record is not None:
                return str(identifier)
        production = await repository.get_production_project(identifier)
        if production:
            return await owner_project(
                repository,
                str(production.owner_project_id or production.record_id),
                depth=depth + 1,
            )
    else:
        for getter in COLLECTION_GETTERS.get(collection, ()):
            item = await getattr(repository, getter)(identifier)
            if item is None:
                continue
            project_id = getattr(item, "owner_project_id", None) or getattr(item, "record_id", None)
            if project_id:
                return await owner_project(repository, str(project_id), depth=depth + 1)
            project_id = getattr(item, "project_id", None)
            if project_id:
                return await owner_project(repository, str(project_id), depth=depth + 1)
            shot_id = getattr(item, "shot_plan_id", None)
            if shot_id:
                return await owner_project(
                    repository, str(shot_id), collection="production-shots", depth=depth + 1
                )
            video_id = getattr(item, "video_id", None)
            if video_id:
                return await owner_project(
                    repository, str(video_id), collection="videos", depth=depth + 1
                )
            run_id = getattr(item, "generation_run_id", None)
            if run_id:
                return await owner_project(
                    repository, str(run_id), collection="generation-runs", depth=depth + 1
                )
    raise AccountError(404, "project_missing", "项目不存在或不属于当前账户")


def create_project_authorizer(repository):
    async def check(request: Request, temporary: list):
        if not password_auth_enabled() or not request.url.path.startswith("/api/v1/"):
            return
        path = request.url.path.removeprefix("/api/v1/")
        parts = path.split("/")
        if parts[0] in {"auth", "admin", "account", "public-media"}:
            return
        access = account_access.get()
        if access is None:
            raise AccountError(401, "login_required", "请先登录")
        if "workspace_id" in request.path_params and str(
            request.path_params["workspace_id"]
        ) != str(access.workspace_id):
            raise AccountError(404, "workspace_missing", "工作区不存在")
        write = request.method not in {"GET", "HEAD", "OPTIONS"}
        if path in {
            "context/active-workspace",
            "workspace/validate",
            "workspaces/register-local",
            "workspaces/validate-local",
        } or (path == "workspace" and write):
            raise AccountError(403, "workspace_fixed", "账户独立，数据位置由服务端管理")
        if write and (
            path.startswith("settings/model")
            or path.startswith("settings/image-generation")
            or path.startswith("settings/video-generation")
        ):
            raise AccountError(403, "admin_required", "平台配置请在管理后台修改")
        if write and ("/engine" in path and "installations" in path):
            from ..identity import require_platform_admin

            await require_platform_admin(request)
        if len(parts) > 2 and parts[0] == "projects" and parts[2] in {"edit-lease", "readonly"}:
            return
        # Pure media retrieval is account-scoped but never needs edit ownership.
        if not write and (
            parts[-1]
            in {
                "content",
                "thumbnail",
                "download",
                "media",
                "cover",
                "source-frame",
                "source-keyframe",
                "source-video",
                "subtitles",
                "events",
            }
            or (parts[0] == "analyses" and "artifacts" in parts)
        ):
            return
        ids: set[str] = set()
        collection = parts[0]
        # Routers such as depth-controls and video-enhancements nest resource IDs.
        for field, owner_collection in {
            "project_id": "projects",
            "record_id": "records",
            "shot_plan_id": "production-shots",
            "candidate_id": "generation-candidates",
            "analysis_id": "analyses",
            "run_id": "skill-runs" if collection == "skill-runs" else "generation-runs",
            "video_id": "videos",
        }.items():
            if field in request.path_params:
                ids.add(
                    await owner_project(
                        repository, request.path_params[field], collection=owner_collection
                    )
                )
        if not ids and "job_id" in request.path_params:
            job_collection = {
                "depth-controls": "depth-control-jobs",
                "video-enhancements": "video-enhancement-jobs",
            }.get(collection)
            if job_collection:
                ids.add(
                    await owner_project(
                        repository, request.path_params["job_id"], collection=job_collection
                    )
                )
        if collection in {"projects", "records", "productions", *COLLECTION_GETTERS}:
            if len(parts) >= 2:
                try:
                    UUID(parts[1])
                except ValueError:
                    pass
                else:
                    ids.add(await owner_project(repository, parts[1], collection=collection))
        # Body-only batch endpoints must not evade the same project boundary.
        if write and request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
            except ValueError:
                raise AccountError(422, "invalid_json", "请求内容不是有效 JSON") from None
            if isinstance(body, dict):
                mappings = {
                    "project_ids": "projects",
                    "record_ids": "records",
                    "shot_plan_ids": "production-shots",
                    "candidate_ids": "generation-candidates",
                }
                for field, owner_collection in mappings.items():
                    for identifier in body.get(field, []) or []:
                        ids.add(
                            await owner_project(
                                repository, str(identifier), collection=owner_collection
                            )
                        )
                # Several legacy bulk updates carry their production in the body.
                if not ids and collection in {"production-shots", "generation-candidates"}:
                    for field in ("project_id", "production_project_id"):
                        if body.get(field):
                            ids.add(await owner_project(repository, str(body[field])))
                    for update in body.get("updates", []) or []:
                        if isinstance(update, dict) and update.get("shot_plan_id"):
                            ids.add(
                                await owner_project(
                                    repository,
                                    str(update["shot_plan_id"]),
                                    collection="production-shots",
                                )
                            )
        if not ids:
            if write and collection in {
                "production-shots",
                "generation-candidates",
                "generation-runs",
            }:
                raise AccountError(423, "project_required", "请从项目编辑页面执行此操作")
            return
        # Read-only snapshots bypass editors' implicit initialize/update GETs.
        editor = request.headers.get("x-editor-id", "")
        token = request.headers.get("x-edit-token", "")
        repo = account_repository()
        # Explicit project-list operations and a newly uploaded video's first analysis
        # may take a short lease. An existing editor always wins; batch acquisition
        # completes for every target before the handler can write anything.
        transient = write and (
            collection in {"projects", "records"}
            and (len(parts) == 2 or parts[1] == "batch" or parts[-1] == "lifecycle")
            or collection == "videos"
            and parts[-1] == "analyses"
        )
        if transient:
            states = [
                await asyncio.to_thread(
                    repo.lease, access, project_id, editor_id=editor, token=token
                )
                for project_id in sorted(ids)
            ]
            if not all(state["editable"] for state in states):
                editor, token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
                for project_id in sorted(ids):
                    state = await asyncio.to_thread(
                        repo.lease,
                        access,
                        project_id,
                        editor_id=editor,
                        token=token,
                        action="acquire",
                    )
                    if not state["editable"]:
                        raise AccountError(423, "project_busy", "项目正在编辑，暂时不能执行此操作")
                    temporary.append((access, project_id, editor, token))
        for project_id in ids:
            await asyncio.to_thread(repo.require_lease, access, project_id, editor, token)
        request_edit_fence.set(
            EditFence(
                account_id=str(access.account_id),
                project_ids=tuple(sorted(ids)),
                session_hash=access.session_hash,
                editor_id=editor,
                token_hash=token_hash(token),
                auth_database=repo.path,
                request_task_id=id(asyncio.current_task()),
            )
        )

    async def authorize(request: Request):
        temporary = []
        context_token = request_edit_fence.set(None)
        try:
            await check(request, temporary)
            yield
        finally:
            request_edit_fence.reset(context_token)
            for access, project_id, editor, token in temporary:
                try:
                    await asyncio.to_thread(
                        account_repository().lease,
                        access,
                        project_id,
                        editor_id=editor,
                        token=token,
                        action="release",
                    )
                except AccountError:
                    pass  # Revocation already removed the lease.

    return authorize
