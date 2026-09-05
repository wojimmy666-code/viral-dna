from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_storyboard_prompt_editor import payload, runtime

from viral_dna_api.ai.contracts import ModelProviderError, ProviderResult
from viral_dna_api.models import ModelUsage
from viral_dna_api.skill_workflow.contracts import (
    ExecutionStatus,
    PromptQualityReport,
    ShotManifestUpdate,
    StoryboardPromptDraftUpdate,
)
from viral_dna_api.skill_workflow.service import SkillWorkflowService, SkillWorkflowServiceError
from viral_dna_api.skill_workflow.storyboard_authoring import (
    AuthoredStoryboard,
    ModelStoryboardAuthor,
    ReferenceStyleStoryboardAuthor,
    StoryboardAuthoringContext,
    StoryboardAuthoringError,
    StoryboardAuthoringResult,
)


async def context_for(env):
    brief = (await env.store.list_creative_brief_revisions(env.project.id))[-1]
    return StoryboardAuthoringContext(
        manifest=(await env.store.get_skill_version_snapshot(env.project.id)).manifest,
        brand=await env.store.get_brand_snapshot(brief.brand_snapshot_id),
        brief=brief,
        style_bible=env.bible,
        run_contract=(await env.store.list_run_contract_revisions(env.project.id))[-1],
        asset_facts=[],
        approved_claims=[],
    )


async def source_for(env, count):
    result = await ReferenceStyleStoryboardAuthor().author(await context_for(env))
    shots = [
        result.storyboard.shots[index % len(result.storyboard.shots)] for index in range(count)
    ]
    return result.storyboard.model_copy(update={"shots": shots})


@pytest.mark.parametrize("count", [1, 13, 20, 101])
def test_model_accepts_any_nonempty_count_without_retry(count):
    async def scenario():
        env = await runtime()
        source = await source_for(env, count)
        calls, models = [], []

        class Provider:
            async def generate(self, request, schema):
                calls.append(request)
                return ProviderResult(
                    data=schema.model_validate(source.model_dump()),
                    usage=ModelUsage(),
                    requested_model="selected",
                    resolved_model="selected",
                    provider_request_id="request-1",
                    latency_ms=120,
                    raw_content=source.model_dump_json(),
                )

        author = ModelStoryboardAuthor(router=SimpleNamespace(provider_for=lambda _: Provider()))

        async def targets(_):
            return [
                SimpleNamespace(provider="fake", model="selected"),
                SimpleNamespace(provider="fake", model="must-not-be-called"),
            ]

        author._target = targets
        context = await context_for(env)
        from dataclasses import replace

        async def started(provider, model):
            models.append((provider, model))

        result = await author.author(replace(context, on_model_started=started))
        assert len(result.storyboard.shots) == count
        assert len(calls) == 1
        assert models == [("fake", "selected")]
        assert result.raw_content == source.model_dump_json()
        assert "suggested_shot_count" in calls[0].user_prompt
        assert "target_shot_count" not in calls[0].user_prompt
        assert "maxItems" not in AuthoredStoryboard.model_json_schema()["properties"]["shots"]

    asyncio.run(scenario())


def test_zero_shots_has_a_specific_error():
    async def scenario():
        env = await runtime()
        raw = (await source_for(env, 0)).model_dump_json()

        class Provider:
            async def generate(self, request, schema):
                try:
                    schema.model_validate_json(raw)
                except ValidationError as exc:
                    raise ModelProviderError(
                        "model_schema_invalid",
                        "invalid response",
                        retryable=True,
                        raw_content=raw,
                        provider_request_id="empty-request",
                    ) from exc

        author = ModelStoryboardAuthor(router=SimpleNamespace(provider_for=lambda _: Provider()))

        async def targets(_):
            return [SimpleNamespace(provider="fake", model="selected")]

        author._target = targets
        with pytest.raises(StoryboardAuthoringError) as error:
            await author.author(await context_for(env))
        assert error.value.code == "storyboard_empty"
        assert "未返回任何镜头" in str(error.value)
        assert error.value.provider_error.raw_content == raw

    asyncio.run(scenario())


class FixedAuthor:
    def __init__(self, source):
        self.source, self.calls = source, 0

    async def author(self, context):
        self.calls += 1
        if context.on_model_started:
            await context.on_model_started("fake", "selected-model")
        return StoryboardAuthoringResult(
            storyboard=self.source,
            provider="fake",
            model="selected-model",
            request_id="complete-response",
            provider_ms=120,
            actual_cost_micros=77,
            raw_content=self.source.model_dump_json(),
        )

    async def rewrite_shot(self, *args, **kwargs):
        raise AssertionError("No count-based repair or paid rewrite expected")


async def compile_and_wait(env):
    await env.service.compile_storyboard(env.run.id)
    task = env.service._storyboard_tasks.get(env.run.id)
    if task:
        await task
    steps = await env.store.list_skill_step_runs(env.run.id)
    return max(steps, key=lambda step: step.attempt)


def quality_pass(*args, **kwargs):
    return PromptQualityReport(passed=True, score=100)


@pytest.mark.parametrize("count", [1, 13, 101])
def test_compiler_uses_the_actual_list(count, monkeypatch):
    monkeypatch.setattr("viral_dna_api.skill_workflow.service.assess_prompts", quality_pass)

    async def scenario():
        env = await runtime()
        env.service.storyboard_author = FixedAuthor(await source_for(env, count))
        step = await compile_and_wait(env)
        assert step.execution_status == ExecutionStatus.SUCCEEDED, step.error_message
        manifest = (await env.store.list_shot_manifest_revisions(env.project.id))[-1]
        assert len(manifest.shots) == count
        assert manifest.edit_plan["shot_count"] == count
        assert step.total_shots == step.completed_shots == count
        assert env.service.storyboard_author.calls == 1

    asyncio.run(scenario())


async def fail_after_two(env, monkeypatch):
    from viral_dna_api.skill_workflow import service as module

    real = module.compile_image_prompt
    calls = 0

    def fail_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("测试编译中断")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "assess_prompts", quality_pass)
    monkeypatch.setattr(module, "compile_image_prompt", fail_third)
    author = FixedAuthor(await source_for(env, 3))
    env.service.storyboard_author = author
    step = await compile_and_wait(env)
    assert step.execution_status == ExecutionStatus.FAILED
    assert step.model == "selected-model"
    assert step.progress > 65
    assert step.completed_shots == 2 and step.total_shots == 3
    assert step.resumable
    return author, step


def test_resume_keeps_response_and_skips_completed_shots(monkeypatch):
    async def scenario():
        env = await runtime()
        author, failed = await fail_after_two(env, monkeypatch)
        checkpoint = await env.store.get_skill_artifact(failed.checkpoint_artifact_id)
        assert len(checkpoint.generation_parameters["authored"]["storyboard"]["shots"]) == 3
        assert json.loads(checkpoint.generation_parameters["authored"]["raw_content"])["shots"]
        partial = (await env.store.list_shot_manifest_revisions(env.project.id))[-1]
        assert len(partial.shots) == 2
        assert (
            await env.store.get_skill_run(env.run.id)
        ).execution_status == ExecutionStatus.FAILED
        # A new service instance must recover solely from persisted repository records.
        env.service = SkillWorkflowService(
            env.store, env.service.projects, env.service.account_context, storyboard_author=author
        )
        succeeded = await compile_and_wait(env)
        assert succeeded.execution_status == ExecutionStatus.SUCCEEDED, succeeded.error_message
        assert author.calls == 1
        assert succeeded.actual_cost_micros == 0
        final = (await env.store.list_shot_manifest_revisions(env.project.id))[-1]
        assert len(final.shots) == 3
        assert [shot.stable_shot_key for shot in final.shots[:2]] == [
            shot.stable_shot_key for shot in partial.shots
        ]
        assert not succeeded.resumable

    asyncio.run(scenario())


def test_resume_cannot_overwrite_manual_draft(monkeypatch):
    async def scenario():
        env = await runtime()
        author, _ = await fail_after_two(env, monkeypatch)
        partial = (await env.store.list_shot_manifest_revisions(env.project.id))[-1]
        edit = payload(partial)
        edit.shots[0].image_prompt_body += " 用户保留的文字"
        saved = await env.service.put_storyboard_prompt_draft(env.project.id, edit)
        with pytest.raises(SkillWorkflowServiceError) as error:
            await env.service.compile_storyboard(env.run.id)
        assert error.value.code == "storyboard_resume_conflict"
        assert (await env.store.list_shot_manifest_revisions(env.project.id))[-1] == saved
        assert author.calls == 1

    asyncio.run(scenario())


def test_editing_and_handoff_contracts_have_no_count_ceiling():
    from viral_dna_api.production_seeds.contracts import ProductionSeed
    from viral_dna_api.skill_workflow.contracts import (
        PictureLockRequest,
        ShotManifestRevision,
        TimelineV3Revision,
    )

    for model, field in [
        (StoryboardPromptDraftUpdate, "shots"),
        (ShotManifestUpdate, "shots"),
        (ShotManifestRevision, "shots"),
        (ProductionSeed, "shots"),
        (PictureLockRequest, "clips"),
    ]:
        assert "maxItems" not in model.model_json_schema()["properties"][field]
    assert "maxItems" not in TimelineV3Revision.model_json_schema()["properties"]["video_clips"]


def test_more_shots_than_target_frames_are_saved_without_dropping_any():
    async def scenario():
        env = await runtime()
        edits = [
            {
                "stable_shot_key": f"shot_manual{index:08d}",
                "image_prompt_body": "产品静态近景",
                "video_prompt_body": "镜头缓慢推进",
            }
            for index in range(501)
        ]
        saved = await env.service.put_storyboard_prompt_draft(
            env.project.id, payload(env.manifest, edits)
        )
        assert len(saved.shots) == 501
        assert all(shot.duration_frames >= 1 for shot in saved.shots)
        assert [shot.stable_shot_key for shot in saved.shots] == [
            shot["stable_shot_key"] for shot in edits
        ]

    asyncio.run(scenario())


def test_cancellation_preserves_model_and_latest_progress():
    async def scenario():
        env = await runtime()
        started = asyncio.Event()

        class WaitingAuthor:
            async def author(self, context):
                await context.on_model_started("fake", "user-selected-model")
                started.set()
                await asyncio.Event().wait()

        env.service.storyboard_author = WaitingAuthor()
        await env.service.compile_storyboard(env.run.id)
        await asyncio.wait_for(started.wait(), timeout=2)
        step = (await env.store.list_skill_step_runs(env.run.id))[-1]
        assert step.model == "user-selected-model"
        await env.service._update_storyboard_step(step, 41)
        detail = await env.service.cancel_storyboard(env.run.id)
        stopped = detail.steps[-1]
        assert stopped.execution_status == ExecutionStatus.CANCELLED
        assert stopped.progress == 41
        assert stopped.model == "user-selected-model"
        assert stopped.completed_at is not None

    asyncio.run(scenario())


def test_sqlite_restart_restores_checkpoint_and_draft(monkeypatch, tmp_path):
    from viral_dna_api.platform_skills import PlatformSkillCatalogService
    from viral_dna_api.projects import ProjectService
    from viral_dna_api.sqlite_store import SQLiteStore

    async def scenario():
        path = tmp_path / "checkpoint.db"
        env = await runtime(SQLiteStore(path))
        author, failed = await fail_after_two(env, monkeypatch)
        await env.store.save_skill_step_run(
            failed.model_copy(
                update={
                    "execution_status": ExecutionStatus.RUNNING,
                    "completed_at": None,
                }
            )
        )
        run = await env.store.get_skill_run(env.run.id)
        await env.store.save_skill_run(
            run.model_copy(update={"execution_status": ExecutionStatus.RUNNING})
        )
        account = env.service.account_context
        env.store = SQLiteStore(path)
        env.service = SkillWorkflowService(
            env.store,
            ProjectService(env.store, PlatformSkillCatalogService(None), account),
            account,
            storyboard_author=author,
        )
        await env.service.recover()
        workspace = await env.service.workspace(env.project.id)
        step = workspace.run.steps[-1]
        assert step.execution_status == ExecutionStatus.FAILED
        assert step.error_code == "storyboard_worker_interrupted"
        assert step.resumable
        assert len(workspace.shot_manifest.shots) == 2
        assert step.checkpoint_manifest_revision_id == workspace.shot_manifest.id
        succeeded = await compile_and_wait(env)
        assert succeeded.execution_status == ExecutionStatus.SUCCEEDED, succeeded.error_message
        assert author.calls == 1

    asyncio.run(scenario())
