from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_viral_insights import FakeCategoryProfileService, sample_report

from viral_dna_api.ai.catalog import load_model_catalog
from viral_dna_api.ai.contracts import ModelProviderError, ProviderResult
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisProfile,
    AnalysisRecord,
    ModelTask,
    ModelUsage,
    Video,
)
from viral_dna_api.production import ProductionService
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.store import InMemoryStore
from viral_dna_api.viral_insights.contracts import (
    CreativeActionRequest,
    CreativeGenerateRequest,
    CreativeIdea,
    CreativePlanEdit,
    ViralConcept,
    ViralConceptPublishRequest,
    ViralConceptShot,
)
from viral_dna_api.viral_insights.creative_prompts import IdeaResponse, PlanResponse, validate_ideas
from viral_dna_api.viral_insights.creative_service import CreativeConceptService
from viral_dna_api.viral_insights.publisher import ProductionConceptPublisher
from viral_dna_api.viral_insights.routes import create_viral_insight_router
from viral_dna_api.viral_insights.service import ViralInsightService, ViralInsightServiceError
from viral_dna_api.workspace import WorkspaceManager


def ideas():
    axes = [
        ("冬日来信", "私密的生活片段", "书信日记与记忆切片", "衣服承载情绪", "衣角里的一束暖光"),
        (
            "建筑的褶皱",
            "找寻城市的几何关系",
            "形状匹配的非线性蒙太奇",
            "裙褶作为建筑尺度",
            "裙褶接到柱廊",
        ),
        (
            "只有风醒着",
            "超现实的时间感",
            "静止世界与局部动态对比",
            "面料是画面唯一的运动",
            "暂停街道中飘起的丝带",
        ),
    ]
    return [
        CreativeIdea(
            name=name,
            summary=f"{intent}。结合 JK 品类提出新的视觉构想。",
            creative_intent=intent,
            visual_organization=organization,
            product_role=role,
            visual_memory=memory,
            key_scenes=["新的场景", memory],
            category_fit="原创 JK 的穿搭表达",
            borrowed="冷光和硬切",
            changed="从建筑游览转为服装视角",
            assumptions=["配色待实物确认"],
        )
        for name, intent, organization, role, memory in axes
    ]


def plan(count=5):
    return ViralConcept(
        strategy="creative",
        name="城市的褶皱",
        one_liner="让城市回应裙褶",
        target_audience="年轻女性",
        why_it_can_work="形状关联成为记忆点",
        required_assets=["真实 JK 服装参考"],
        shots=[
            ViralConceptShot(
                index=i,
                duration_seconds=1 + i / 10,
                title=f"新画面 {i}",
                traffic_role="形状呼应",
                description="原创场景而非源画面",
                image_prompt="静态裙褶与柱廊",
                video_prompt="裙摆随风轻动",
            )
            for i in range(1, count + 1)
        ],
    )


class FakeProvider:
    provider_id = "dashscope"

    def __init__(self):
        self.requests = []
        self.fail = False
        self.wait = None
        self.invalid = False

    async def generate(self, request, response_schema):
        self.requests.append(request)
        if self.wait:
            await self.wait.wait()
        if self.fail:
            raise ModelProviderError(
                "rate_limit",
                "sensitive upstream body",
                retryable=False,
                usage=ModelUsage(input_tokens=100, output_tokens=10, total_tokens=110),
            )
        context = json.loads(
            request.user_prompt.split("创作资料：\n")[1].split("\nJSON Schema：")[0]
        )
        if response_schema is PlanResponse:
            content = plan().model_dump()
            content["brief_checks"] = fixture_brief_checks(
                context, [shot["description"] for shot in content["shots"]]
            )
            result = PlanResponse(concept=content)
        else:
            items = ideas()
            if context["count"] == 1:
                items = [items[0].model_copy(update={"name": "重写的来信"})]
            if self.invalid:
                items = [items[0]] * 3
            contents = [item.model_dump() for item in items]
            for content in contents:
                content["brief_checks"] = fixture_brief_checks(context, content["key_scenes"])
            result = IdeaResponse(
                ideas=contents,
                diversity_rationale="不同的情绪目标、商品角色与视觉组织",
            )
        return ProviderResult(
            data=result,
            usage=ModelUsage(input_tokens=1000, output_tokens=500, total_tokens=1500),
            requested_model=request.target.model,
            resolved_model=request.target.model,
            provider_request_id="fake-request",
            latency_ms=20,
            raw_content="",
        )


def fixture_brief_checks(context, scenes):
    return [
        {
            "requirement_index": item["index"],
            "satisfied": True,
            "explanation": "测试示意：用具体画面核对本条创作要求。",
            "scene_scope": "all",
            "evidence": [
                {"scene_index": index, "quote": scene} for index, scene in enumerate(scenes, 1)
            ],
        }
        for item in context.get("effective_creative_brief", {}).get("requirements", [])
    ]


async def setup(repo=None, **kwargs):
    repo = repo or InMemoryStore()
    report = sample_report()
    await repo.save_report(report)
    await repo.save_analysis(
        AnalysisJob(
            id=report.analysis_id, video_id=report.video_id, stage="completed", progress=100
        )
    )
    categories = FakeCategoryProfileService()
    categories.profile.display_name = "JK"
    categories.profile.brief = "原创 JK 女装"
    provider = FakeProvider()
    insight = ViralInsightService(repo, category_profiles=categories)
    service = CreativeConceptService(
        repo, insight, router=ModelRouter({"dashscope": provider}), **kwargs
    )
    target = (
        load_model_catalog()
        .resolve(AnalysisProfile.BALANCED)
        .targets_for(ModelTask.VIRAL_REASONING)[0]
    )

    async def targets():
        return [target]

    service.targets = targets
    return repo, report, categories, provider, service


async def finish(service, job):
    task = service.tasks.get(("local", job.id))
    if task:
        await task
    return await service.get(job.id)


def test_two_stage_generation_regeneration_snapshots_and_costs():
    async def scenario():
        repo, report, categories, provider, service = await setup()
        request = CreativeGenerateRequest(
            request_id=uuid4(), category_profile_id=categories.profile.id
        )
        first = await finish(service, await service.generate(report.analysis_id, request))
        assert first.status == "completed" and len(first.ideas) == 3 and not first.concepts
        assert first.model_cost_micros > 0 and first.cost_status == "measured"
        assert first.completed_at and first.model_runs
        prompt = provider.requests[0].user_prompt
        assert "原创 JK 女装" in prompt and "narrative_structure" in prompt
        assert "显瘦但不紧绷" in prompt and "面料抗皱" in prompt
        assert provider.requests[0].temperature == 0.85
        assert (await service.generate(report.analysis_id, request)).id == first.id
        assert len(provider.requests) == 1
        original = first.model_dump(mode="json")
        categories.profile.brief = "后来修改的品类"
        rewrite = await finish(
            service,
            await service.act(
                first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=False
            ),
        )
        assert rewrite.status == "completed"
        assert rewrite.ideas[1:] == first.ideas[1:]
        assert rewrite.ideas[0].id != first.ideas[0].id
        expanded = await finish(
            service,
            await service.act(
                rewrite.id,
                rewrite.ideas[1].id,
                CreativeActionRequest(request_id=uuid4(), feedback="减少推销感"),
                expand=True,
            ),
        )
        assert expanded.status == "completed" and expanded.phase == "expanded"
        assert len(expanded.concepts[0].shots) == 5 != len(report.shots)
        assert expanded.category_profile.brief == "原创 JK 女装"
        assert first.model_dump(mode="json") == original
        assert "减少推销感" in provider.requests[-1].user_prompt
        assert "建筑的褶皱" in provider.requests[-1].user_prompt
        assert provider.requests[-1].temperature == 0.65
        assert len(await service.history(report.analysis_id)) == 3
        with pytest.raises(ViralInsightServiceError, match="先选择创意"):
            await service.insights.publish_concept(
                first.id, first.ideas[0].id, ViralConceptPublishRequest(record_id=uuid4())
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["timeout", "cancel", "provider", "duplicate"])
def test_failure_paths_stop_without_template_fallback(mode):
    async def scenario():
        repo, report, categories, provider, service = await setup(timeout_seconds=0.08)
        provider.fail = mode == "provider"
        provider.invalid = mode == "duplicate"
        provider.wait = asyncio.Event() if mode in {"timeout", "cancel"} else None
        job = await service.generate(
            report.analysis_id,
            CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id),
        )
        if mode == "cancel":
            await asyncio.sleep(0.01)
            await service.cancel(job.id)
        result = await finish(service, job)
        assert result.status in {"failed", "cancelled"}
        assert (
            result.error_code and result.completed_at and not result.ideas and not result.concepts
        )
        assert "sensitive" not in result.error_message
        runs = await repo.list_model_runs(report.analysis_id)
        assert all(item.status != "running" for item in runs)
        if mode in {"provider", "duplicate"}:
            assert result.model_cost_micros > 0
        else:
            assert result.cost_status == "unreported"

    asyncio.run(scenario())


def test_duplicate_submission_conflict_recovery_and_read_without_model(tmp_path):
    async def scenario():
        repo, report, categories, provider, service = await setup(
            SQLiteStore(tmp_path / "db.sqlite")
        )
        provider.wait = asyncio.Event()
        payload = CreativeGenerateRequest(
            request_id=uuid4(), category_profile_id=categories.profile.id
        )
        first, second = await asyncio.gather(
            service.generate(report.analysis_id, payload),
            service.generate(report.analysis_id, payload),
        )
        assert first.id == second.id
        with pytest.raises(ViralInsightServiceError):
            await service.generate(
                report.analysis_id, payload.model_copy(update={"request_id": uuid4()})
            )
        with pytest.raises(ViralInsightServiceError):
            await service.generate(
                report.analysis_id, payload.model_copy(update={"feedback": "changed"})
            )
        await asyncio.sleep(0.01)
        await service.shutdown()
        row = await service.get(first.id)
        row.status = "running"
        await repo.save_viral_concept_set(row)
        restarted = CreativeConceptService(SQLiteStore(tmp_path / "db.sqlite"), service.insights)
        await restarted.recover()
        assert (await restarted.get(first.id)).error_code == "creative_interrupted"
        requests = len(provider.requests)
        await service.insights.get_insight(report.analysis_id)
        await service.history(report.analysis_id)
        assert len(provider.requests) == requests

    asyncio.run(scenario())


def test_shared_montage_grammar_is_allowed_but_reworded_duplicates_are_rejected():
    items = [item.model_copy(update={"visual_organization": "非线性蒙太奇"}) for item in ideas()]
    validate_ideas(items)
    with pytest.raises(ValueError):
        validate_ideas([items[0], items[0].model_copy(update={"name": "换个名"}), items[2]])


def test_manual_edit_creates_new_version_and_conflicting_edit_is_rejected():
    async def scenario():
        repo, report, categories, provider, service = await setup()
        first = await finish(
            service,
            await service.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        expanded = await finish(
            service,
            await service.act(
                first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=True
            ),
        )
        changed = expanded.concepts[0].model_copy(deep=True)
        changed.shots[0].video_prompt = "人工调整的运镜"
        edit = CreativePlanEdit(expected_revision=1, concept=changed)
        saved = await service.edit(expanded.id, edit)
        assert (
            saved.id != expanded.id and saved.concepts[0].shots[0].video_prompt == "人工调整的运镜"
        )
        assert (await service.get(expanded.id)).concepts[0].shots[
            0
        ].video_prompt != "人工调整的运镜"
        with pytest.raises(ViralInsightServiceError):
            await service.edit(expanded.id, edit)

    asyncio.run(scenario())


def test_publish_uses_authored_shots_not_original_frames_or_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))

    async def scenario():
        repo, report, categories, provider, service = await setup()
        record_id = uuid4()
        video = Video(
            id=report.video_id,
            record_id=record_id,
            source_type="upload",
            filename="test.mp4",
            title="source",
            width=1080,
            height=1920,
            duration_seconds=8.5,
            status="ready",
        )
        await repo.save_video(video)
        await repo.save_record(
            AnalysisRecord(
                id=record_id,
                video_id=video.id,
                name="source",
                source_type="upload",
                latest_analysis_id=report.analysis_id,
            )
        )
        production = ProductionService(repo, WorkspaceManager())
        publisher = ProductionConceptPublisher(production)
        result = await publisher.publish(
            analysis_id=report.analysis_id,
            concept=plan(),
            payload=ViralConceptPublishRequest(record_id=record_id),
        )
        shots = await repo.list_shot_plans(result.project_id)
        assert result.shot_count == len(shots) == 5
        assert [shot.index for shot in shots] == [1, 2, 3, 4, 5]
        assert [shot.duration_seconds for shot in shots] == [1.1, 1.2, 1.3, 1.4, 1.5]
        assert all(
            shot.source_kind == "blank"
            and not shot.source_keyframe_url
            and shot.source_start_frame is None
            for shot in shots
        )
        assert shots[0].visual_beats[0].title == "新画面 1"
        project = await repo.get_production_project(result.project_id)
        seed = await repo.get_production_seed(project.production_seed_id)
        assert seed.audio_intent.clip_audio_strategy == "muted"
        assert seed.source_analysis_id == report.analysis_id
        assert len(await production.list_shots(result.project_id)) == 5
        # Recovery must not recreate the two original shots.
        repo.shot_plans.clear()
        assert len(await production.list_shots(result.project_id)) == 5

    asyncio.run(scenario())


def test_current_model_preferences_are_used_and_budget_blocks_before_request(monkeypatch):
    async def scenario():
        import viral_dna_api.viral_insights.creative_service as module

        repo, report, categories, provider, service = await setup()
        captured = {}

        def resolve(profile, **kwargs):
            captured.update(kwargs)
            return load_model_catalog().resolve(profile, **kwargs)

        monkeypatch.setattr(module, "load_model_plan", resolve)
        preferences = SimpleNamespace(
            text_model_alias="qwen37",
            text_model_task_overrides={"replication_plan": "qwen36flash"},
            text_model_fallback_enabled=False,
        )

        class Preferences:
            async def get(self):
                return SimpleNamespace(settings=preferences)

        live = CreativeConceptService(
            repo,
            service.insights,
            preferences=Preferences(),
            router=ModelRouter({"dashscope": provider}),
        )
        targets = await live.targets()
        assert captured["preferred_aliases"][ModelTask.VIRAL_REASONING] == "qwen36flash"
        assert captured["fallback_enabled"] is False and len(targets) == 1
        analysis = await repo.get_analysis(report.analysis_id)
        analysis.max_cost_micros = 1
        await repo.save_analysis(analysis)
        result = await finish(
            live,
            await live.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        assert result.error_code == "creative_budget_exceeded"
        assert result.cost_status == "not_started" and not provider.requests

    asyncio.run(scenario())


def test_http_routes_are_read_only_until_explicit_generation_and_publish_is_idempotent():
    async def scenario():
        repo, report, categories, provider, service = await setup()

        class NoPaidGet:
            async def enrich(self, *args):
                raise AssertionError("GET invoked a paid model")

        service.insights.reasoning = NoPaidGet()
        analysis = await repo.get_analysis(report.analysis_id)
        analysis.model_plan = load_model_catalog().resolve(AnalysisProfile.BALANCED)
        await repo.save_analysis(analysis)
        api = FastAPI()
        api.include_router(create_viral_insight_router(service.insights, service))
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://isolated"
        ) as client:
            for suffix in ["viral-insight", "viral-concepts/latest", "viral-concepts/history"]:
                assert (
                    await client.get(f"/analyses/{report.analysis_id}/{suffix}")
                ).status_code == 200
            assert not provider.requests
            payload = {
                "request_id": str(uuid4()),
                "category_profile_id": str(categories.profile.id),
            }
            response = await client.post(
                f"/analyses/{report.analysis_id}/viral-concepts", json=payload
            )
            assert response.status_code == 202
            first = await finish(service, await service.get(UUID(response.json()["id"])))
            action = await client.post(
                f"/viral-concept-sets/{first.id}/ideas/{first.ideas[0].id}/expand",
                json={"request_id": str(uuid4())},
            )
            assert action.status_code == 202
            expanded = await finish(service, await service.get(UUID(action.json()["id"])))

            class Publisher:
                calls = 0

                async def publish(self, *, analysis_id, concept, payload):
                    from viral_dna_api.viral_insights.contracts import ViralConceptPublishResult

                    self.calls += 1
                    return ViralConceptPublishResult(
                        project_id=uuid4(),
                        project_name=concept.name,
                        concept_id=concept.id,
                        shot_count=5,
                    )

            publisher = Publisher()
            service.insights.publisher = publisher
            path = f"/viral-concept-sets/{expanded.id}/concepts/{expanded.concepts[0].id}/publish"
            body = {"record_id": str(uuid4())}
            one, two = await asyncio.gather(
                client.post(path, json=body), client.post(path, json=body)
            )
            assert one.status_code == two.status_code == 201
            assert one.json()["project_id"] == two.json()["project_id"] and publisher.calls == 1

    asyncio.run(scenario())
