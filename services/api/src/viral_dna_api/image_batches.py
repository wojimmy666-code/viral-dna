"""Durable, bounded fan-out over the existing per-picture production jobs.

Batch membership is persisted before dispatch. Unknown remote outcomes are never
resubmitted automatically; successful candidates and human approvals survive.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from .image_batches_models import ImageBatch, ImageBatchItem, ImageBatchRequest
from .image_generation.catalog import ImageModelCatalogError
from .image_generation.selection import (
    LOCAL_UNCERTAIN_IMAGE_ERRORS,
    permits_unknown_local_image_cost,
    resolve_skill_image_request,
)
from .models import ImageGenerationCreate, ProductionOriginType, utc_now
from .project_prompts import prompt_snapshot

ACTIVE = {"queued", "running", "cancellation_requested"}
SUCCESS = {"completed", "cached"}
UNSAFE = LOCAL_UNCERTAIN_IMAGE_ERRORS | {
    "generation_interrupted",
    "generation_cancelled",
    "generation_worker_failed",
    "remote_outcome_unknown",
    "remote_transport_error",
    "remote_no_response",
    "remote_response_invalid",
    "remote_candidates_invalid",
    "remote_image_download_failed",
    "remote_image_size",
    "remote_image_invalid",
    "remote_image_format",
    "remote_image_url_invalid",
    "remote_image_url_untrusted",
    "generated_image_invalid",
    "generated_image_dimensions",
    "local_tool_timeout",
    "local_tool_output_missing",
    "local_tool_result_missing",
    "local_tool_result_invalid",
}


def input_fingerprint(plan, beat, bindings) -> str:
    material = {
        "prompt": beat.image_prompt,
        "negative": beat.image_negative_constraints,
        "source": beat.source_frame_url,
        "source_path": beat.source_frame_relative_path,
        "mentions": [item.model_dump(mode="json") for item in beat.image_prompt_mentions],
        "bindings": sorted(
            [
                (str(item.reference_asset_id), str(item.role), item.weight, item.crop_hint)
                for item in bindings
            ],
            key=lambda item: item[0],
        ),
        "lifecycle": str(plan.lifecycle_status),
        "output_mode": str(plan.output_mode),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class ImageBatchService:
    def __init__(self, production):
        self.production = production
        self.repository = production.repository
        self.tasks = {}
        self.locks = {}
        self.slots = asyncio.Semaphore(3)

    def fail(self, code, message, status=409):
        from .production import ProductionServiceError

        return ProductionServiceError(status, code, message)

    async def recover_local_output(self, run):
        if run and run.execution_mode == "local_tool" and run.status in {"failed", "blocked"}:
            from .production import ProductionServiceError

            try:
                await self.production.recover_image_generation_output(run.id)
            except ProductionServiceError:
                return run
            return await self.repository.get_generation_run(run.id)
        return run

    async def latest(self, project_id):
        await self.production._require_project(project_id)
        batches = await self.repository.list_image_batches(project_id)
        return batches[-1] if batches else None

    async def require(self, project_id, batch_id):
        await self.production._require_project(project_id)
        batch = await self.repository.get_image_batch(batch_id)
        if batch is None or batch.project_id != project_id:
            raise self.fail("image_batch_not_found", "图片批次不存在", 404)
        return batch

    async def preview(
        self, project_id, payload: ImageBatchRequest, *, budget_beat_ids=None, resume_batch=None
    ):
        p = self.production
        project = await p._require_project(project_id)
        p._require_expected_revision(project, payload.expected_revision_id)
        if project.origin_type != ProductionOriginType.SKILL_RUN:
            raise self.fail("skill_project_required", "当前批量入口只用于 Skill 项目")
        contract = await p._skill_run_contract(project)
        # New batches always request one image. Only resuming an existing batch
        # may use its historical count, never mutate a submitted task snapshot.
        payload = payload.model_copy(
            update={"candidate_count": resume_batch.candidate_count if resume_batch else 1}
        )
        try:
            contract, option = await resolve_skill_image_request(
                contract, payload, getattr(p.image_gateway, "settings_service", None)
            )
        except ImageModelCatalogError as exc:
            raise self.fail("image_model_unavailable", str(exc)) from exc
        if option.unit_cost_micros is None and not permits_unknown_local_image_cost(contract):
            raise self.fail(
                "local_image_cost_unknown",
                "本机费用未知，请先确认费用；硬预算下不能执行未知费用任务",
            )
        count = contract.candidate_count_by_stage.get("shot_image", 1)
        plans = await self.repository.list_shot_plans(project.id)
        runs = await self.repository.list_generation_runs(project.id)
        candidates = await self.repository.list_generation_candidates_by_run_ids(
            {run.id for run in runs}
        )
        by_run = {}
        for candidate in candidates:
            if candidate.status not in {"archived", "rejected", "stale"}:
                by_run.setdefault(candidate.generation_run_id, []).append(candidate.id)
        assets = {asset.id: asset for asset in await p._list_reference_assets(project.id)}
        prompt_context = await p.get_prompt_context(project.id)
        items = []
        for plan in plans:
            if plan.lifecycle_status == "discarded" or plan.output_mode == "source_video":
                continue
            bindings = await self.repository.list_reference_bindings(plan.id)
            beats = sorted(plan.visual_beats, key=lambda item: item.index)
            if resume_batch is not None:
                saved_ids = {item.visual_beat_id for item in resume_batch.items}
                beats = [beat for beat in beats if beat.id in saved_ids]
            elif payload.mode == "all":
                # The explicit button produces one primary picture per shot.
                # Automatic missing-output recovery still covers required beats.
                beats = beats[:1]
            for beat in beats:
                picture_bindings = p._image_bindings_for_beat(plan, beat, bindings)
                fingerprint = input_fingerprint(plan, beat, picture_bindings)
                item = ImageBatchItem(
                    shot_plan_id=plan.id,
                    visual_beat_id=beat.id,
                    shot_index=plan.index,
                    beat_index=beat.index,
                    input_fingerprint=fingerprint,
                    prompt_snapshot=prompt_snapshot(beat.image_prompt, prompt_context, "image"),
                )
                picture_runs = [
                    run
                    for run in runs
                    if run.kind == "image"
                    and run.shot_plan_id == plan.id
                    and (
                        run.visual_beat_id == beat.id
                        or (run.visual_beat_id is None and beat.id == plan.visual_beats[0].id)
                    )
                ]
                live = next((run for run in picture_runs if run.status in ACTIVE), None)
                successful = next(
                    (
                        run
                        for run in reversed(picture_runs)
                        if run.status in SUCCESS and by_run.get(run.id)
                    ),
                    None,
                )
                if live:
                    item.status, item.run_id = "running", live.id
                elif picture_runs and picture_runs[-1].error_code in UNSAFE:
                    item.status, item.run_id = "unknown", picture_runs[-1].id
                    item.error_message = "已有任务的上游结果未确认，请先核对，避免重复计费。"
                elif payload.mode == "missing" and (
                    beat.image_status == "approved"
                    or (successful and beat.image_status == "review_required")
                ):
                    item.status = "skipped"
                else:
                    message = ""
                    if not beat.image_prompt.strip():
                        message = "请先填写图片提示词"
                    elif count > option.capabilities.max_candidates:
                        message = "单画面候选数超过当前模型上限"
                    elif picture_bindings and not option.capabilities.image_to_image:
                        message = "当前模型不支持参考图片，请调整本画面的模型或参考素材"
                    elif len(picture_bindings) > option.capabilities.max_reference_images:
                        message = (
                            f"本画面绑定 {len(picture_bindings)} 项参考，"
                            f"模型最多支持 {option.capabilities.max_reference_images} 项"
                        )
                    elif any(
                        binding.reference_asset_id not in assets
                        or not assets[binding.reference_asset_id].rights_confirmed
                        for binding in picture_bindings
                    ):
                        message = "本画面存在失效或未确认权利的参考素材"
                    if message:
                        item.status, item.error_message, item.retryable = "failed", message, True
                items.append(item)
        if not items:
            raise self.fail("image_batch_empty", "没有可生成图片的有效分镜")
        estimated = (
            (
                sum(
                    item.status == "pending"
                    and (budget_beat_ids is None or item.visual_beat_id in budget_beat_ids)
                    for item in items
                )
                * count
                * option.unit_cost_micros
            )
            if option.unit_cost_micros is not None
            else None
        )
        if (
            project.budget_limit_micros is not None
            and estimated is not None
            and project.actual_cost_micros + estimated > project.budget_limit_micros
        ):
            raise self.fail(
                "production_budget_exceeded", "本批次预计费用超过方案剩余预算，请先调整预算"
            )
        now = utc_now()
        return ImageBatch(
            id=payload.request_id,
            project_id=project_id,
            revision_id=project.current_revision_id,
            mode=payload.mode,
            model_alias=contract.image_model_id,
            model_label=option.label,
            execution_mode="local_tool" if option.provider == "local_tool" else "remote_api",
            concurrency_limit=(
                min(3, p.image_gateway.settings_service.get().local_concurrency)
                if option.provider == "local_tool"
                else 3
            ),
            allow_unknown_cost=permits_unknown_local_image_cost(contract),
            image_tool_snapshot=option.tool_snapshot,
            width=contract.image_width,
            height=contract.image_height,
            candidate_count=count,
            estimated_cost_micros=estimated,
            items=items,
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )

    async def create(self, project_id, payload):
        lock = self.locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            existing = await self.repository.get_image_batch(payload.request_id)
            if existing:
                return await self.require(project_id, existing.id)
            latest = await self.latest(project_id)
            if latest and latest.status in {"running", "stopping"}:
                raise self.fail("image_batch_running", "当前已有批量图片任务，请等待完成或停止排队")
            batch = await self.preview(project_id, payload)
            if any(item.status in {"failed", "unknown", "running"} for item in batch.items):
                first = next(
                    item for item in batch.items if item.status in {"failed", "unknown", "running"}
                )
                raise self.fail(
                    "image_batch_preflight_failed",
                    f"分镜 {first.shot_index} · 画面 {first.beat_index}："
                    f"{first.error_message or '已有生成任务，请先等待完成'}",
                )
            await self.repository.save_image_batch(batch)
            self.schedule(batch.id)
            return batch

    def schedule(self, batch_id):
        if batch_id in self.tasks and not self.tasks[batch_id].done():
            return
        self.tasks[batch_id] = asyncio.create_task(
            self.run(batch_id), name=f"image-batch-{batch_id}"
        )

    async def update_item(self, batch_id, beat_id, **updates):
        lock = self.locks.setdefault(batch_id, asyncio.Lock())
        async with lock:
            batch = await self.repository.get_image_batch(batch_id)
            batch.items = [
                item.model_copy(update=updates) if item.visual_beat_id == beat_id else item
                for item in batch.items
            ]
            batch.updated_at = batch.last_heartbeat_at = utc_now()
            await self.repository.save_image_batch(batch)

    async def dispatch(self, batch_id, beat_id):
        # Stop and dispatch serialize only the short enqueue transaction, never
        # provider latency. Recheck after waiting so a cancelled item cannot start.
        async with self.locks.setdefault(batch_id, asyncio.Lock()):
            batch = await self.repository.get_image_batch(batch_id)
            item = next(item for item in batch.items if item.visual_beat_id == beat_id)
            if batch.status != "running" or item.status != "pending":
                return None
            p = self.production
            lock = await p._project_lock(batch.project_id)
            async with lock:
                project = await p._require_project(batch.project_id)
                plan = await p._require_shot(item.shot_plan_id)
                beat = next((beat for beat in plan.visual_beats if beat.id == beat_id), None)
                bindings = await self.repository.list_reference_bindings(plan.id)
                if (
                    beat is None
                    or input_fingerprint(
                        plan, beat, p._image_bindings_for_beat(plan, beat, bindings)
                    )
                    != item.input_fingerprint
                ):
                    raise self.fail(
                        "image_batch_input_changed",
                        "排队期间提示词、画面或参考素材发生修改，请检查后重试",
                    )
                run = await p._enqueue_image_run(
                    plan.id,
                    ImageGenerationCreate(
                        expected_revision_id=project.current_revision_id,
                        expected_shot_revision_id=plan.revision_id,
                        visual_beat_id=beat_id,
                        candidate_count=batch.candidate_count,
                        input_mode="text_to_image",
                        execution_mode=batch.execution_mode,
                        model_alias=batch.model_alias,
                        width=batch.width,
                        height=batch.height,
                        allow_unknown_cost=batch.allow_unknown_cost,
                        image_tool_snapshot=batch.image_tool_snapshot,
                        image_batch_id=batch.id,
                        preserve_approval=True,
                        generation_intent="new_variation" if batch.mode == "all" else "standard",
                    ),
                    frozen_prompt=item.prompt_snapshot,
                )
            item.status, item.run_id, item.retryable = "running", run.id, False
            batch.updated_at = batch.last_heartbeat_at = utc_now()
            await self.repository.save_image_batch(batch)
            return run.id

    async def execute_item(self, batch_id, beat_id):
        async with self.slots:
            batch = await self.repository.get_image_batch(batch_id)
            item = next(item for item in batch.items if item.visual_beat_id == beat_id)
            if batch.status != "running" and item.status == "pending":
                await self.update_item(batch_id, beat_id, status="cancelled", retryable=True)
                return
            if item.status not in {"pending", "running"}:
                return
            try:
                if not item.run_id:
                    item.run_id = await self.dispatch(batch_id, beat_id)
                    if item.run_id is None:
                        return
                    self.production._schedule_image_run(item.run_id)
                else:
                    existing = await self.repository.get_generation_run(item.run_id)
                    if existing and existing.status == "queued":
                        self.production._schedule_image_run(existing.id)
                while True:
                    run = await self.repository.get_generation_run(item.run_id)
                    if run is None:
                        raise self.fail(
                            "image_batch_run_missing", "子任务记录不存在，请检查任务记录"
                        )
                    if run.status not in ACTIVE:
                        break
                    await asyncio.sleep(0.5)
                run = await self.recover_local_output(run)
                candidates = await self.repository.list_generation_candidates(run.id)
                if run.status in SUCCESS and candidates:
                    await self.update_item(
                        batch_id,
                        beat_id,
                        status="completed",
                        candidate_ids=[c.id for c in candidates],
                        error_message="",
                        retryable=False,
                    )
                else:
                    unknown = run.error_code in UNSAFE
                    await self.update_item(
                        batch_id,
                        beat_id,
                        status="unknown" if unknown else "failed",
                        error_message=(
                            "上游结果未确认，请先核对或恢复现有任务，系统不会自动重复提交。"
                            if unknown
                            else run.error_message or "未生成有效图片"
                        ),
                        retryable=not unknown,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # An enqueue may have succeeded before a persistence/read failure.
                # Retain that task instead of silently creating a second paid run.
                linked = next(
                    (
                        run
                        for run in await self.repository.list_generation_runs(batch.project_id)
                        if str(run.request_payload.get("image_batch_id")) == str(batch_id)
                        and run.visual_beat_id == beat_id
                        and run.status in ACTIVE
                    ),
                    None,
                )
                await self.update_item(
                    batch_id,
                    beat_id,
                    status="unknown" if linked else "failed",
                    run_id=linked.id if linked else item.run_id,
                    error_message=str(exc)[:1000],
                    retryable=not bool(linked),
                )

    async def run(self, batch_id):
        batch = await self.repository.get_image_batch(batch_id)
        local_slots = asyncio.Semaphore(batch.concurrency_limit)

        async def execute(beat_id):
            async with local_slots:
                await self.execute_item(batch_id, beat_id)

        children = [
            asyncio.create_task(execute(item.visual_beat_id))
            for item in batch.items
            if item.status in {"pending", "running"}
        ]
        try:
            while any(not task.done() for task in children):
                await asyncio.sleep(1)
                async with self.locks.setdefault(batch_id, asyncio.Lock()):
                    current = await self.repository.get_image_batch(batch_id)
                    current.last_heartbeat_at = utc_now()
                    await self.repository.save_image_batch(current)
            await asyncio.gather(*children)
            async with self.locks.setdefault(batch_id, asyncio.Lock()):
                current = await self.repository.get_image_batch(batch_id)
                statuses = {item.status for item in current.items}
                current.status = (
                    "partial"
                    if statuses & {"failed", "unknown"}
                    else "cancelled"
                    if "cancelled" in statuses
                    else "completed"
                )
                current.completed_at = current.updated_at = current.last_heartbeat_at = utc_now()
                runs = [
                    await self.repository.get_generation_run(item.run_id)
                    for item in current.items
                    if item.run_id
                ]
                current.actual_cost_micros = sum(run.actual_cost_micros for run in runs if run)
                await self.repository.save_image_batch(current)
        except asyncio.CancelledError:
            for task in children:
                task.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            async with self.locks.setdefault(batch_id, asyncio.Lock()):
                current = await self.repository.get_image_batch(batch_id)
                current.status, current.updated_at = "interrupted", utc_now()
                await self.repository.save_image_batch(current)
        except Exception as exc:
            for task in children:
                task.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            async with self.locks.setdefault(batch_id, asyncio.Lock()):
                current = await self.repository.get_image_batch(batch_id)
                current.status, current.updated_at = "interrupted", utc_now()
                for item in current.items:
                    if item.status in {"running", "pending"}:
                        item.status = "unknown" if item.run_id else "failed"
                        item.retryable = not bool(item.run_id)
                        item.error_message = f"批次执行中断：{str(exc)[:500]}"
                await self.repository.save_image_batch(current)
        finally:
            self.tasks.pop(batch_id, None)

    async def stop(self, project_id, batch_id):
        async with self.locks.setdefault(batch_id, asyncio.Lock()):
            batch = await self.require(project_id, batch_id)
            if batch.status == "running":
                batch.status = "stopping"
                batch.items = [
                    item.model_copy(update={"status": "cancelled", "retryable": True})
                    if item.status == "pending"
                    else item
                    for item in batch.items
                ]
                batch.updated_at = utc_now()
                await self.repository.save_image_batch(batch)
            return batch

    async def resume(self, project_id, batch_id):
        async with self.locks.setdefault(project_id, asyncio.Lock()):
            batch = await self.require(project_id, batch_id)
            if batch.status in {"running", "stopping"}:
                return batch
            latest = await self.latest(project_id)
            if latest.id != batch.id and latest.status in {"running", "stopping"}:
                raise self.fail("image_batch_running", "已有其他批次正在执行")
            preview = await self.preview(
                project_id,
                ImageBatchRequest(
                    expected_revision_id=(
                        await self.production._require_project(project_id)
                    ).current_revision_id,
                    mode=batch.mode,
                    model_alias=batch.model_alias,
                    execution_mode=batch.execution_mode,
                    width=batch.width,
                    height=batch.height,
                    candidate_count=batch.candidate_count,
                    allow_unknown_cost=batch.allow_unknown_cost,
                    image_tool_snapshot=batch.image_tool_snapshot,
                ),
                budget_beat_ids={
                    item.visual_beat_id
                    for item in batch.items
                    if item.status not in {"completed", "skipped", "unknown"}
                },
                resume_batch=batch,
            )
            fresh = {item.visual_beat_id: item for item in preview.items}
            for index, item in enumerate(batch.items):
                if item.status in {"completed", "skipped"}:
                    continue
                if item.run_id:
                    run = await self.recover_local_output(
                        await self.repository.get_generation_run(item.run_id)
                    )
                    candidates = await self.repository.list_generation_candidates(item.run_id)
                    if run and run.status in SUCCESS and candidates:
                        batch.items[index] = item.model_copy(
                            update={
                                "status": "completed",
                                "candidate_ids": [c.id for c in candidates],
                                "error_message": "",
                                "retryable": False,
                            }
                        )
                        continue
                    if run and run.status in ACTIVE:
                        batch.items[index] = item.model_copy(update={"status": "running"})
                        continue
                    if item.status == "unknown" or (run and run.error_code in UNSAFE):
                        batch.items[index] = item.model_copy(
                            update={
                                "status": "unknown",
                                "retryable": False,
                                "error_message": (
                                    "上游结果未确认，请先核对或恢复现有任务，系统不会自动重复提交。"
                                ),
                            }
                        )
                        continue
                if item.visual_beat_id in fresh:
                    batch.items[index] = fresh[item.visual_beat_id].model_copy(
                        update={
                            "prompt_snapshot": item.prompt_snapshot,
                            "input_fingerprint": item.input_fingerprint,
                        }
                    )
                else:
                    batch.items[index] = item.model_copy(
                        update={
                            "status": "skipped",
                            "error_message": "该画面已删除或舍弃",
                            "retryable": False,
                        }
                    )
            batch.status, batch.completed_at = "running", None
            batch.updated_at = batch.last_heartbeat_at = utc_now()
            await self.repository.save_image_batch(batch)
            self.schedule(batch.id)
            return batch

    async def recover(self):
        for project in await self.repository.list_production_projects():
            for batch in await self.repository.list_image_batches(project.id):
                if batch.status not in {"running", "stopping", "interrupted"}:
                    continue
                # Reconcile the narrow crash window between enqueue and membership save.
                runs = await self.repository.list_generation_runs(project.id)
                for item in batch.items:
                    linked = next(
                        (
                            run
                            for run in runs
                            if str(run.request_payload.get("image_batch_id")) == str(batch.id)
                            and run.visual_beat_id == item.visual_beat_id
                        ),
                        None,
                    )
                    if item.run_id is None and linked:
                        item.run_id = linked.id
                    if item.run_id and item.status not in {"completed", "skipped"}:
                        item.status = "unknown"
                        item.retryable = False
                        item.error_message = "服务中断，需核对子任务结果后继续；不会自动重新计费。"
                batch.status = "interrupted"
                batch.updated_at = utc_now()
                await self.repository.save_image_batch(batch)

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def pause_project(self, project_id):
        tasks = [
            self.tasks[batch.id]
            for batch in await self.repository.list_image_batches(project_id)
            if batch.id in self.tasks
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
