"""Durable, explicitly requested two-stage ideation. No template fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from ..access_context import account_access
from ..ai.billing import (
    PriceCatalog,
    PriceCatalogError,
    calculate_cost_micros,
    committed_model_cost_micros,
    estimate_text_tokens,
)
from ..ai.catalog import ModelCatalogError, default_analysis_profile, load_model_plan
from ..ai.contracts import ModelProviderError, ModelRequest, ModelTimeouts
from ..ai.router import ModelRouter
from ..ai.text_model_routing import preferred_text_model_aliases
from ..category_profiles.service import CategoryProfileServiceError
from ..models import ModelResponseDiagnostics, ModelRun, ModelRunStatus, ModelTask, ModelUsage
from ..visual_styles import freeze_style
from .contracts import ViralConcept, ViralConceptSet, utc_now
from .creative_brief import (
    CreativeBriefError,
    freeze_brief,
    resolve_brief,
)
from .creative_errors import (
    FORMAT_ERROR_CODES,
    REQUEST_ERROR_CODES,
    format_error_message,
    present_batch_error,
    request_error_message,
)
from .creative_language import (
    CreativePromptLanguageError,
    present_language_state,
    require_chinese_prompts,
)
from .creative_prompts import (
    SYSTEM_PROMPT,
    IdeaResponse,
    PlanResponse,
    build_prompt,
    validate_ideas,
    validate_plan,
)
from .engine import report_fingerprint
from .creative_review import (
    assess, compile_common_rules, idea_can_expand, present_reviews, review_idea,
)
from .service import ViralInsightServiceError

ACTIVE = {"queued", "running"}
GENERATOR = "category-creative-model-v1"
CREATIVE_MODEL_TIMEOUTS = ModelTimeouts(
    connect_seconds=10, read_seconds=180, write_seconds=30, pool_seconds=10
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def scope():
    access = account_access.get()
    return str(access.account_id) if access else "local"


class CreativeConceptService:
    def __init__(
        self,
        repository,
        insights,
        preferences=None,
        *,
        router=None,
        price_catalog=None,
        timeout_seconds=240,
    ):
        self.repository = repository
        self.insights = insights
        self.preferences = preferences
        self.router = router or ModelRouter()
        self.prices = price_catalog or PriceCatalog()
        self.timeout_seconds = timeout_seconds
        self.tasks = {}
        self.locks = {}

    def lock(self, identifier):
        return self.locks.setdefault((scope(), str(identifier)), asyncio.Lock())

    async def targets(self):
        settings = (await self.preferences.get()).settings if self.preferences else None
        try:
            plan = load_model_plan(
                default_analysis_profile(),
                **(
                    {
                        "preferred_aliases": preferred_text_model_aliases(
                            settings.text_model_alias, settings.text_model_task_overrides
                        ),
                        "fallback_enabled": settings.text_model_fallback_enabled,
                    }
                    if settings
                    else {}
                ),
            )
            if not plan or not plan.targets_for(ModelTask.VIRAL_REASONING):
                raise ModelCatalogError("没有文案模型路由")
            if plan.pricing_version != self.prices.catalog_version:
                raise ModelCatalogError("模型价格目录版本不匹配")
        except ModelCatalogError as exc:
            raise ViralInsightServiceError(
                503,
                "creative_model_unavailable",
                "创意模型未配置或价格目录不匹配，请检查后台文案模型",
            ) from exc
        return plan.targets_for(ModelTask.VIRAL_REASONING)

    async def history(self, analysis_id, category_profile_id=None):
        await self.insights._source_report(analysis_id)
        items = await self.repository.list_viral_concept_sets(analysis_id)
        return sorted(
            (
                present_reviews(present_language_state(present_batch_error(item)))
                for item in items
                if category_profile_id is None
                or (item.category_profile and item.category_profile.id == category_profile_id)
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get(self, identifier):
        item = await self.repository.get_viral_concept_set(identifier)
        if item is None:
            raise ViralInsightServiceError(404, "concept_set_not_found", "创意批次不存在")
        return present_reviews(present_language_state(present_batch_error(item)))

    async def generate(self, analysis_id, payload):
        async with self.lock(analysis_id):
            previous = await self._deduplicate(analysis_id, payload, "generate")
            if previous:
                return previous
            source = await self.insights._source_report(analysis_id)
            insight = await self.insights.get_insight(analysis_id)
            try:
                profile = await self.insights.category_profiles.snapshot(
                    payload.category_profile_id
                )
            except CategoryProfileServiceError as exc:
                raise ViralInsightServiceError(exc.status_code, exc.code, str(exc)) from exc
            known = {item.entity_id for item in insight.replacement_opportunities}
            if any(item.entity_id not in known for item in payload.replacements):
                raise ViralInsightServiceError(
                    422, "replacement_entity_not_found", "替换元素不属于当前报告"
                )
            history = await self.history(analysis_id, profile.id)
            previous_brief = next((item for item in history if item.phase != "legacy"), None)
            feedback = resolve_brief(payload.feedback, previous_brief)
            visual_style = freeze_style(payload.visual_style or profile.default_visual_style)
            snapshot = {
                "visual_style_snapshot": visual_style,
                "category": profile.model_dump(mode="json"),
                "original_creative_brief": feedback,
                "source_grammar": {
                    "narrative_structure": (
                        source.viral_reasoning.narrative_structure
                        if source.viral_reasoning
                        else source.overview.narrative_structure
                    ),
                    "overview": source.overview.model_dump(mode="json"),
                    "dna": insight.dna.model_dump(mode="json"),
                    "mechanisms": [
                        item.model_dump(mode="json", exclude={"evidence"})
                        for item in insight.mechanisms
                    ],
                    "evidence_coverage": insight.evidence_coverage,
                },
                "source_shot_ids": [shot.id for shot in source.shots],
                "source_visual_facts": [
                    {
                        "id": shot.id,
                        "title": shot.title,
                        "scene": shot.scene,
                        "composition": shot.composition,
                        "color": shot.color,
                        "evidence_kind": shot.evidence_kind,
                    }
                    for shot in source.shots
                ],
                "replacements": [item.model_dump() for item in payload.replacements],
            }
            latest = next(
                (item for item in history if item.phase == "ideas" and item.status == "completed"),
                None,
            )
            job = ViralConceptSet(
                schema_version="viral-dna-concepts-v4",
                analysis_id=analysis_id,
                video_id=source.video_id,
                insight_report_id=insight.id,
                input_fingerprint=digest(snapshot),
                source_insight_fingerprint=report_fingerprint(source),
                status="queued",
                phase="ideas",
                generator_id=GENERATOR,
                strategy_contract_version="creative-two-stage-v2",
                category_profile=profile,
                visual_style_snapshot=visual_style,
                request_id=payload.request_id,
                feedback=feedback,
                request_signature=digest(
                    {"operation": "generate", **self._request_data(payload)}
                ),
                input_snapshot=snapshot,
            )
            await self.insights.category_profiles.mark_used(profile.id)
            return await self._start(job, previous=latest.ideas if latest else [])

    async def act(self, set_id, idea_id, payload, *, expand):
        if expand and payload.revision_notes is not None:
            raise ViralInsightServiceError(
                422, "revision_notes_not_supported", "修改意见只用于 AI 修订本条，请先修订后再展开"
            )
        parent = await self.get(set_id)
        async with self.lock(parent.analysis_id):
            operation = "expand" if expand else "regenerate"
            signature = {"operation": operation, "parent": str(set_id), "idea": str(idea_id)}
            previous = await self._deduplicate(parent.analysis_id, payload, **signature)
            if previous:
                return previous
            if parent.phase != "ideas" or not parent.ideas or parent.status not in {"completed", "failed"}:
                raise ViralInsightServiceError(409, "ideas_not_ready", "请先完成简短创意生成")
            selected = next((item for item in parent.ideas if item.id == idea_id), None)
            if selected is None:
                raise ViralInsightServiceError(404, "idea_not_found", "该创意不属于所选批次")
            if expand and not idea_can_expand(selected, resolve_brief(None, parent)):
                issue = next(
                    (item for item in selected.review_details if item.severity == "revision"),
                    next(iter(selected.review_details), None),
                )
                reason = issue.message if issue else "缺少完整、有效的场景规划或核对记录"
                raise ViralInsightServiceError(
                    409, "idea_review_required",
                    "这条创意需要修订后再展开：" + reason[:320] + "。请使用 AI 修订本条。",
                )
            job = parent.model_copy(
                deep=True,
                update={
                    "id": uuid4(),
                    "parent_set_id": parent.id,
                    "source_idea_id": idea_id,
                    "request_id": payload.request_id,
                    "request_signature": digest({**signature, **self._request_data(payload)}),
                    "phase": "expanded" if expand else "ideas",
                    "operation": operation,
                    "ideas": [],
                    "concepts": [],
                    "status": "queued",
                    "feedback": resolve_brief(payload.feedback, parent),
                    "revision_notes": payload.revision_notes,
                    "created_at": utc_now(),
                    "started_at": None,
                    "completed_at": None,
                    "requested_model": None,
                    "resolved_model": None,
                    "model_runs": [],
                    "model_cost_micros": 0,
                    "estimated_cost_micros": 0,
                    "cost_status": "not_started",
                    "model_elapsed_ms": 0,
                    "error_code": None,
                    "error_message": None,
                    "requirement_rules": [],
                    "review_source_fingerprint": None,
                },
            )
            original_order = [item if item.visual_style_snapshot is not None else item.model_copy(update={"visual_style_snapshot": parent.visual_style_snapshot}) for item in parent.ideas]
            existing = [] if expand else [item for item in original_order if item.id != idea_id]
            if payload.visual_style is not None:
                job.visual_style_snapshot = freeze_style(payload.visual_style)
            elif selected.visual_style_snapshot is not None:
                job.visual_style_snapshot = selected.visual_style_snapshot
            job.input_snapshot["visual_style_snapshot"] = job.visual_style_snapshot
            return await self._start(
                job, selected=selected, existing=existing, original_order=original_order
            )

    @staticmethod
    def _request_data(payload):
        data = payload.model_dump(mode="json")
        # Preserve signatures issued before per-idea notes were introduced.
        if data.get("revision_notes") is None:
            data.pop("revision_notes", None)
        if data.get("visual_style") is None:
            data.pop("visual_style", None)
        return data

    async def _deduplicate(self, analysis_id, payload, operation, **extra):
        items = await self.repository.list_viral_concept_sets(analysis_id)
        signature = digest({"operation": operation, **extra, **self._request_data(payload)})
        for item in items:
            if item.request_id == payload.request_id:
                if item.request_signature != signature:
                    raise ViralInsightServiceError(
                        409, "request_id_conflict", "请求标识已用于不同内容"
                    )
                return present_batch_error(item)
        if any(item.status in ACTIVE for item in items):
            raise ViralInsightServiceError(
                409, "creative_job_running", "当前分析已有创意任务，请等待完成或取消"
            )
        return None

    async def _start(self, job, *, selected=None, existing=(), previous=(), original_order=()):
        targets = await self.targets()
        job.input_snapshot["creative_brief"] = freeze_brief(job.feedback)
        # A later action must not silently inherit the previous action's notes.
        job.input_snapshot.pop("revision_notes", None)
        if job.revision_notes is not None:
            job.input_snapshot["revision_notes"] = job.revision_notes
        job.requested_model = targets[0].model
        job.input_snapshot["model_targets"] = [item.model_dump(mode="json") for item in targets]
        prompt_snapshot = {
            key: value for key, value in job.input_snapshot.items() if key != "model_targets"
        }
        prompt = build_prompt(
            prompt_snapshot,
            phase=job.phase,
            feedback=job.feedback,
            selected=selected,
            existing=existing,
            previous=previous,
        )
        job.input_fingerprint = digest(
            {"prompt": prompt, "targets": job.input_snapshot["model_targets"]}
        )
        await self.repository.save_viral_concept_set(job)
        key = (scope(), job.id)
        task = asyncio.create_task(self._execute(job, targets, prompt, existing, original_order))
        self.tasks[key] = task
        task.add_done_callback(lambda _: self.tasks.pop(key, None))
        return job.model_copy(deep=True)

    async def _execute(self, job, targets, prompt, existing, original_order):
        job.status = "running"
        job.started_at = utc_now()
        await self.repository.save_viral_concept_set(job)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self._generate(job, targets, prompt)
                job.requirement_rules = result.requirement_rules
                if job.phase == "ideas":
                    expected = 1 if existing else 3
                    if len(result.ideas) != expected:
                        raise ValueError(f"模型应返回 {expected} 个新创意")
                    fresh = [review_idea(item, job.input_snapshot["creative_brief"], result.requirement_rules)
                             for item in result.ideas]
                    fresh = [item.model_copy(update={"visual_style_snapshot": job.visual_style_snapshot}) for item in fresh]
                    if existing:
                        fresh = [
                            fresh[0] if item.id == job.source_idea_id else item
                            for item in original_order
                        ]
                    validate_ideas(fresh)
                    job.ideas = fresh
                else:
                    draft = compile_common_rules(result.concept)
                    issues, checks = assess(draft, job.input_snapshot["creative_brief"], result.requirement_rules, expanded=True)
                    concept = ViralConcept(
                        strategy="creative",
                        **draft.model_dump(exclude={"brief_checks"}),
                        brief_checks=checks,
                    )
                    validate_plan(concept, job.input_snapshot["source_shot_ids"])
                    job.concepts = [concept]
                    if issues:
                        raise CreativeBriefError("展开分镜需修订：" + "；".join(item.message for item in issues))
                    require_chinese_prompts(concept)
                job.status = "completed"
        except TimeoutError:
            await self.record_task_timeout(job)
        except asyncio.CancelledError:
            job.status, job.error_code = "cancelled", "creative_cancelled"
            job.error_message = "本地任务已停止；上游请求可能已计费，不会自动重试"
        except ViralInsightServiceError as exc:
            job.status, job.error_code, job.error_message = "failed", exc.code, str(exc)[:500]
        except CreativeBriefError as exc:
            job.status, job.error_code = "failed", exc.code
            job.error_message = str(exc)[:500]
        except CreativePromptLanguageError as exc:
            job.status, job.error_code = "failed", exc.code
            job.language_issues, job.error_message = exc.fields, str(exc)[:500]
        except (ValidationError, ValueError):
            job.status, job.error_code = "failed", "creative_output_invalid"
            job.error_message = (
                "模型结果未满足创意差异或分镜结构要求，请补充想法后重试；原结果已保留"
            )
        except Exception:
            job.status, job.error_code = "failed", "creative_failed"
            job.error_message = "创意任务处理失败，已停止且未使用模板替代；请重试或检查服务日志"
        finally:
            job.completed_at = utc_now()
            await self.repository.save_viral_concept_set(job)

    async def record_task_timeout(self, job, *, label="创意任务"):
        job.status, job.error_code = "failed", "creative_timeout"
        job.error_message = (
            f"{label}超过 {self.timeout_seconds:g} 秒总上限，已停止；"
            "不会自动重试，可稍后手动重试。上游请求可能已计费"
        )
        if not job.model_runs:
            return
        # The task deadline cancels the pending request. Distinguish it from user cancellation.
        for run in await self.repository.list_model_runs(job.analysis_id):
            if run.id == job.model_runs[-1] and run.error_code == "creative_interrupted":
                run.error_code, run.error_message = job.error_code, job.error_message
                run.response_diagnostics = ModelResponseDiagnostics(
                    stage="task_timeout",
                    timeout_phase="total",
                    timeout_seconds=self.timeout_seconds,
                    elapsed_ms=max(0, round((utc_now() - job.started_at).total_seconds() * 1000)),
                )
                await self.repository.save_model_run(run)
                break

    async def _generate(
        self, job, targets, prompt, *, schema=None, system_prompt=SYSTEM_PROMPT, prompt_version=None
    ):
        schema = schema or (PlanResponse if job.phase == "expanded" else IdeaResponse)
        for index, source_target in enumerate(targets):
            target = source_target.model_copy(
                update={
                    "prompt_version": prompt_version or (
                        "creative-ideas-revision-v1" if job.revision_notes
                        else f"creative-{job.phase}-v6"
                    ),
                    "schema_version": "prompt-chinese-v1"
                    if job.operation == "localize"
                    else "creative-content-v6",
                }
            )
            estimate = ModelUsage(
                input_tokens=estimate_text_tokens(system_prompt + prompt),
                output_tokens=(8000 if job.phase == "expanded" else 3000)
                + len(job.input_snapshot["creative_brief"]["requirements"])
                * (900 if job.operation == "generate" else 300),
            )
            try:
                price = self.prices.snapshot_for(
                    target.provider, target.model, estimate.input_tokens
                )
            except PriceCatalogError as exc:
                raise ViralInsightServiceError(
                    503, "creative_price_missing", "当前创意模型缺少价格配置"
                ) from exc
            estimated_cost = calculate_cost_micros(estimate, price)
            analysis = await self.repository.get_analysis(job.analysis_id)
            runs = await self.repository.list_model_runs(job.analysis_id)
            if (
                analysis
                and analysis.max_cost_micros
                and (committed_model_cost_micros(runs) + estimated_cost > analysis.max_cost_micros)
            ):
                raise ViralInsightServiceError(
                    409, "creative_budget_exceeded", "创意生成预计超过此分析的成本上限"
                )
            run = ModelRun(
                analysis_id=job.analysis_id,
                video_id=job.video_id,
                task=ModelTask.VIRAL_REASONING,
                attempt=index + 1,
                retry_of_run_id=job.model_runs[-1] if job.model_runs else None,
                provider=target.provider,
                requested_model=target.model,
                prompt_version=target.prompt_version,
                schema_version=target.schema_version,
                request_fingerprint=digest(
                    {"job": str(job.id), "prompt": prompt, "target": target.model_dump()}
                ),
                estimated_cost_micros=estimated_cost,
                price_snapshot_id=price.id,
            )
            await self.repository.save_price_snapshot(price)
            await self.repository.save_model_run(run)
            job.model_runs.append(run.id)
            job.estimated_cost_micros += estimated_cost
            job.cost_status = "unreported"
            await self.repository.save_viral_concept_set(job)
            begin = perf_counter()
            try:
                response = await self.router.provider_for(target).generate(
                    ModelRequest(
                        task=ModelTask.VIRAL_REASONING,
                        target=target,
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        timeouts=CREATIVE_MODEL_TIMEOUTS,
                        temperature=0.1
                        if job.operation == "localize"
                        else 0.65
                        if job.phase == "expanded"
                        else 0.85,
                    ),
                    schema,
                )
                await self._measure(job, run, response.usage, response.resolved_model)
                run.provider_request_id = response.provider_request_id
                run.result_payload = response.data.model_dump(mode="json")
                run.status = ModelRunStatus.COMPLETED
                return response.data
            except ModelProviderError as exc:
                run.status, run.error_code = ModelRunStatus.FAILED, exc.code
                run.response_diagnostics = exc.diagnostics
                reason = {
                    401: "模型凭据被拒绝，请在后台更新 API Key",
                    403: "模型访问被拒绝，请检查模型权限或账户状态",
                    429: "模型请求受限，请核对额度并稍后重试",
                }.get(exc.status_code) or {
                    "rate_limit": "模型请求受限，请核对额度并稍后重试",
                    "model_provider_unavailable": "创意模型不可用，请检查后台模型配置",
                }.get(exc.code, "创意模型请求失败；请检查模型配置、额度或网络")
                if exc.code in FORMAT_ERROR_CODES:
                    reason = format_error_message(exc.diagnostics)
                elif exc.code in REQUEST_ERROR_CODES:
                    reason = request_error_message(exc.code, exc.diagnostics)
                run.error_message = reason
                run.provider_request_id = exc.provider_request_id
                if exc.usage:
                    await self._measure(job, run, exc.usage, exc.resolved_model or target.model)
                if (
                    exc.code in FORMAT_ERROR_CODES | REQUEST_ERROR_CODES
                    or index + 1 >= len(targets)
                    or not exc.retryable
                ):
                    raise ViralInsightServiceError(502, exc.code, run.error_message) from exc
            except BaseException:
                run.status, run.error_code = ModelRunStatus.FAILED, "creative_interrupted"
                run.error_message = "请求中断或结果无法处理；未回报费用不等于免费"
                raise
            finally:
                run.latency_ms = round((perf_counter() - begin) * 1000)
                job.model_elapsed_ms += run.latency_ms
                run.completed_at = utc_now()
                await self.repository.save_model_run(run)
                analysis = await self.repository.get_analysis(job.analysis_id)
                if analysis is not None:
                    ledger = await self.repository.list_model_runs(job.analysis_id)
                    analysis.measured_cost_micros = sum(
                        item.measured_cost_micros for item in ledger
                    )
                    analysis.estimated_cost_micros = committed_model_cost_micros(ledger)
                    await self.repository.save_analysis(analysis)

    async def _measure(self, job, run, usage, resolved):
        try:
            price = self.prices.snapshot_for(run.provider, resolved, usage.input_tokens)
        except PriceCatalogError:
            price = self.prices.snapshot_for(run.provider, run.requested_model, usage.input_tokens)
        await self.repository.save_price_snapshot(price)
        run.resolved_model, run.usage, run.price_snapshot_id = resolved, usage, price.id
        run.measured_cost_micros = calculate_cost_micros(usage, price)
        job.model_cost_micros += run.measured_cost_micros
        job.resolved_model = resolved
        # A preceding failed attempt without usage remains unreported.
        other = [
            item
            for item in await self.repository.list_model_runs(job.analysis_id)
            if item.id in job.model_runs and item.id != run.id
        ]
        job.cost_status = (
            "unreported"
            if any(
                not item.usage.total_tokens
                and not item.usage.input_tokens
                and not item.usage.output_tokens
                for item in [*other, run]
            )
            else "measured"
        )

    async def cancel(self, identifier):
        item = await self.get(identifier)
        task = self.tasks.get((scope(), identifier))
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        item = await self.get(identifier)
        if item.status in ACTIVE:
            item.status, item.error_code = "failed", "creative_interrupted"
            item.error_message, item.completed_at = "任务已中断，请手动重试", utc_now()
            await self.repository.save_viral_concept_set(item)
        return await self.get(identifier)

    async def edit(self, identifier, payload):
        async with self.lock(identifier):
            parent = await self.get(identifier)
            if parent.phase != "expanded" or parent.status != "completed":
                raise ViralInsightServiceError(409, "plan_not_ready", "只能编辑已完成的展开方案")
            if parent.revision != payload.expected_revision or parent.published_result:
                raise ViralInsightServiceError(
                    409, "plan_changed", "方案已更新或发布，请重新读取后编辑"
                )
            validate_plan(payload.concept, parent.input_snapshot["source_shot_ids"])
            edited = parent.model_copy(
                deep=True,
                update={
                    "id": uuid4(),
                    "parent_set_id": parent.id,
                    "operation": "edit",
                    "request_id": None,
                    "request_signature": None,
                    "concepts": [
                        payload.concept.model_copy(update={"id": uuid4(), "brief_checks": []})
                    ],
                    "created_at": utc_now(),
                    "started_at": None,
                    "completed_at": utc_now(),
                    "model_runs": [],
                    "model_cost_micros": 0,
                    "estimated_cost_micros": 0,
                    "cost_status": "not_started",
                    "model_elapsed_ms": 0,
                    "requested_model": None,
                    "resolved_model": None,
                },
            )
            # Freeze the parent version too, so competing editors cannot overwrite it.
            parent.revision += 1
            await self.repository.save_viral_concept_set(parent)
            return await self.repository.save_viral_concept_set(edited)

    async def recover(self):
        for item in await self.repository.list_viral_concept_sets(None):
            if item.phase == "legacy" or item.status not in ACTIVE:
                continue
            item.status, item.error_code = "failed", "creative_interrupted"
            item.error_message = "服务重启导致任务中断；结果未自动重试，请核对费用后手动重试"
            item.completed_at = utc_now()
            for run in await self.repository.list_model_runs(item.analysis_id):
                if run.id in item.model_runs and run.status == ModelRunStatus.RUNNING:
                    run.status, run.error_code = ModelRunStatus.FAILED, "creative_interrupted"
                    run.completed_at = item.completed_at
                    await self.repository.save_model_run(run)
            await self.repository.save_viral_concept_set(item)

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
