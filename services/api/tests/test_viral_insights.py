from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.ai.catalog import load_model_catalog
from viral_dna_api.ai.contracts import ModelRequest, ProviderResult
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.ai.viral_reasoning import ViralReasoningService, validate_viral_reasoning
from viral_dna_api.category_profiles.contracts import (
    CategoryProfile,
    CategoryProfileSnapshot,
)
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisProfile,
    AnalysisReport,
    Entity,
    ModelTask,
    ModelUsage,
    PromptPackage,
    PromptShot,
    Shot,
    VideoOverview,
    ViralFinding,
    ViralReasoningImprovement,
    ViralReasoningSynthesis,
)
from viral_dna_api.store import InMemoryStore
from viral_dna_api.viral_insights.concept_strategies import (
    CONCEPT_GENERATOR_ID,
    CONCEPT_SCHEMA_VERSION,
    STRATEGY_CONTRACT_VERSION,
    ConceptDiversityError,
    validate_concept_diversity,
)
from viral_dna_api.viral_insights.contracts import (
    ViralConceptGenerateRequest,
    ViralConceptPublishRequest,
    ViralConceptPublishResult,
    ViralReplacementSelection,
)
from viral_dna_api.viral_insights.engine import build_concept_set, build_viral_insight
from viral_dna_api.viral_insights.publisher import ProductionConceptPublisher
from viral_dna_api.viral_insights.routes import create_viral_insight_router
from viral_dna_api.viral_insights.service import ViralInsightService, ViralInsightServiceError


def sample_category_profile() -> CategoryProfile:
    return CategoryProfile(
        account_id=uuid4(),
        display_name="都市通勤女装",
        category_name="女装",
        brand_name="森屿",
        brief="为通勤女性提供利落、易搭配的轻职场女装",
        audiences=["25–35 岁通勤女性", "轻熟风用户"],
        selling_points=["显瘦但不紧绷", "面料抗皱"],
        scenes=["上班通勤", "客户会议"],
        forbidden_claims=["绝对显瘦"],
        visual_style="都市自然光与克制低饱和色",
    )


class FakeCategoryProfileService:
    def __init__(self, profile: CategoryProfile | None = None) -> None:
        self.profile = profile or sample_category_profile()
        self.used = 0

    async def snapshot(self, profile_id):
        assert profile_id == self.profile.id
        return CategoryProfileSnapshot.from_profile(self.profile)

    async def mark_used(self, profile_id):
        assert profile_id == self.profile.id
        self.used += 1


def sample_report() -> AnalysisReport:
    analysis_id = uuid4()
    video_id = uuid4()
    shots = [
        Shot(
            id="shot-001",
            index=1,
            start_seconds=0,
            end_seconds=2.8,
            title="丝带遮挡转场",
            subjects=["黑长直发女性", "浅绿色丝带"],
            action="手整理丝带，镜头持续推近直至丝带遮满画面",
            scene="室内木门与白墙前",
            camera="中景快速推至丝带极近特写",
            composition="人物背对镜头，丝带位于视觉中心",
            lighting="柔和自然光",
            color="浅绿色与暖木色",
            subtitle_text="春天会抵达",
            audio="音乐节拍上扬",
            transition="丝带前景遮挡转场",
            narrative_role="开场钩子",
            prompt="女性背对镜头整理浅绿色丝带，镜头推近直到丝带遮满画面",
            confidence=0.9,
            keyframe_url="/api/v1/analyses/test/artifacts/shot-001.webp",
            evidence_kind="model",
        ),
        Shot(
            id="shot-002",
            index=2,
            start_seconds=2.8,
            end_seconds=8.5,
            title="户外结果画面",
            subjects=["水手服少女", "稻田"],
            action="少女坐在木台眺望稻田，丝带随风飘动",
            scene="茅草屋顶下的木台与翠绿稻田",
            camera="中远景缓慢后拉",
            composition="人物居中偏右，稻田形成纵深",
            lighting="明亮夏日自然光",
            color="绿色与蓝色",
            audio="音乐进入副歌",
            transition="结束",
            narrative_role="结果兑现",
            prompt="少女坐在木台眺望稻田，浅绿色丝带随风飘动",
            confidence=0.88,
            keyframe_url="/api/v1/analyses/test/artifacts/shot-002.webp",
            evidence_kind="model",
        ),
    ]
    return AnalysisReport(
        video_id=video_id,
        analysis_id=analysis_id,
        analysis_mode="model",
        overview=VideoOverview(
            summary="用丝带遮挡完成室内到户外的情绪转场。",
            content_type="情绪短片",
            narrative_structure="室内钩子→遮挡转场→户外兑现",
            audience_inference="喜欢清新治愈画面的年轻女性用户",
            visual_style="清新、治愈",
            duration_seconds=8.5,
            aspect_ratio="9:16",
            viral_potential_score=84,
            confidence=0.86,
        ),
        shots=shots,
        entities=[
            Entity(
                id="entity-person",
                type="person",
                name="黑长直发女性",
                description="背对镜头、佩戴浅绿色丝带的女性",
                occurrence_shot_ids=["shot-001", "shot-002"],
                replaceable_fields=["人物身份", "发型"],
                confidence=0.88,
            )
        ],
        viral_findings=[
            ViralFinding(
                id="finding-hook",
                type="hook",
                title="前景遮挡制造转场期待",
                score=91,
                start_seconds=0,
                end_seconds=2.8,
                observation="镜头推近丝带并让丝带覆盖画面。",
                mechanism="遮挡制造未完成感，并为场景切换提供视觉理由。",
                expected_effect="可能提升早期留存和转场后的继续观看。",
                recommendation="保留推近方向、遮挡时点和下一镜头的色彩呼应。",
                confidence=0.9,
            )
        ],
        prompt_package=PromptPackage(
            target_model="seedance",
            global_prompt="清新治愈的短视频，保持丝带视觉连续性。",
            continuity_locks=["丝带颜色", "动作方向", "遮挡转场时点"],
            entities={"entity-person": "黑长直发女性"},
            shots=[
                PromptShot(
                    shot_id=shot.id,
                    duration_seconds=shot.end_seconds - shot.start_seconds,
                    prompt=shot.prompt,
                    negative_constraints=["人物身份漂移", "丝带颜色改变"],
                )
                for shot in shots
            ],
            negative_constraints=["闪烁", "画面跳变"],
        ),
        generated_at=datetime.now(UTC),
    )


def test_insight_preserves_evidence_and_separates_inference() -> None:
    insight = build_viral_insight(sample_report())
    assert insight.data_basis == "content_inference"
    assert insight.mechanisms[0].claim_kind == "inferred"
    assert insight.mechanisms[0].evidence[0].shot_id == "shot-001"
    assert insight.shot_roles[0].role == "hook"
    assert insight.shot_roles[-1].role == "payoff"
    assert insight.evidence_coverage == 1
    assert "前景遮挡" in insight.headline


def test_insight_does_not_invent_mechanisms_or_default_improvements() -> None:
    report = sample_report().model_copy(update={"viral_findings": []})
    insight = build_viral_insight(report)

    assert insight.mechanisms == []
    assert insight.improvements == []
    assert insight.dna.invariants == []
    assert "首尾信息闭环" not in insight.headline
    assert "核心视觉信号前置" not in insight.strongest_hook


def test_model_reasoning_drives_unique_summary_and_evidence_scoped_improvements() -> None:
    report = sample_report()
    synthesis = ViralReasoningSynthesis(
        headline="浅绿色丝带遮满镜头后切入稻田，视觉材质承担场景转换",
        content_value="用同一条浅绿色丝带连接室内整理动作与户外眺望画面。",
        narrative_structure="整理丝带 → 丝带遮挡 → 稻田场景显现",
        audience="可能吸引偏好清新氛围短片与服装造型内容的用户。",
        strongest_hook="0.00–2.80 秒的丝带推近遮挡建立了后续场景变化预期。",
        findings=report.viral_findings,
        improvements=[
            ViralReasoningImprovement(
                title="缩短丝带尚未进入前景的整理段",
                rationale="分镜 1 的动作信息集中在丝带靠近镜头之后。",
                expected_gain="可能减少遮挡发生前的等待。",
                priority="medium",
                affected_shot_ids=["shot-001"],
            )
        ],
        confidence=0.86,
    )
    insight = build_viral_insight(report.model_copy(update={"viral_reasoning": synthesis}))

    assert insight.headline == synthesis.headline
    assert insight.content_value == synthesis.content_value
    assert insight.audience == synthesis.audience
    assert insight.strongest_hook == synthesis.strongest_hook
    assert insight.improvements[0].affected_shot_ids == ["shot-001"]
    assert insight.generator_id == "model-evidence-validator-v2"


def test_model_reasoning_validator_rejects_unbound_claims_and_generic_advice() -> None:
    report = sample_report()
    valid_finding = report.viral_findings[0]
    outside_video = valid_finding.model_copy(
        update={"id": "outside", "start_seconds": 20, "end_seconds": 21}
    )
    synthesis = ViralReasoningSynthesis(
        headline="浅绿色丝带遮挡连接两个场景",
        content_value="丝带承担场景连接。",
        narrative_structure="整理丝带 → 遮挡 → 户外画面",
        audience="可能吸引清新氛围内容受众。",
        strongest_hook="丝带靠近镜头并完成遮挡。",
        findings=[outside_video, valid_finding],
        improvements=[
            ViralReasoningImprovement(
                title="强化结尾兑现与首尾呼应",
                rationale="通用建议不应通过校验。",
                expected_gain="可能改善表现。",
                priority="high",
                affected_shot_ids=["shot-002"],
            ),
            ViralReasoningImprovement(
                title="压缩丝带进入前景前的等待",
                rationale="建议绑定到真实分镜。",
                expected_gain="可能减少等待。",
                priority="medium",
                affected_shot_ids=["shot-001", "missing-shot"],
            ),
        ],
        confidence=0.85,
    )

    validated = validate_viral_reasoning(report, synthesis)

    assert len(validated.findings) == 1
    assert validated.findings[0].start_seconds == 0
    assert [item.title for item in validated.improvements] == ["压缩丝带进入前景前的等待"]
    assert validated.improvements[0].affected_shot_ids == ["shot-001"]


class FakeReasoningProvider:
    provider_id = "dashscope"

    def __init__(self, synthesis: ViralReasoningSynthesis) -> None:
        self.synthesis = synthesis
        self.calls = 0

    async def generate(self, request: ModelRequest, response_schema) -> ProviderResult:
        self.calls += 1
        assert request.task == ModelTask.VIRAL_REASONING
        assert response_schema is ViralReasoningSynthesis
        usage = ModelUsage(input_tokens=800, output_tokens=300, total_tokens=1100)
        return ProviderResult(
            data=self.synthesis,
            usage=usage,
            requested_model=request.target.model,
            resolved_model=request.target.model,
            provider_request_id="viral-reasoning-test",
            latency_ms=42,
            raw_content=self.synthesis.model_dump_json(),
        )


def test_reasoning_service_runs_the_model_and_reuses_validated_cache() -> None:
    async def scenario() -> None:
        report = sample_report()
        plan = load_model_catalog().resolve(
            AnalysisProfile.BALANCED,
            allowed_providers={"dashscope"},
        )
        analysis = AnalysisJob(
            id=report.analysis_id,
            video_id=report.video_id,
            analysis_mode="model",
            simulated=False,
            model_plan=plan,
        )
        synthesis = ViralReasoningSynthesis(
            headline="浅绿色丝带遮挡连接室内与稻田场景",
            content_value="同一条丝带连接两个空间。",
            narrative_structure="整理丝带 → 遮挡 → 稻田显现",
            audience="可能吸引偏好清新氛围短片的用户。",
            strongest_hook="丝带推近并遮满画面，建立场景变化预期。",
            findings=report.viral_findings,
            improvements=[],
            confidence=0.88,
        )
        provider = FakeReasoningProvider(synthesis)
        store = InMemoryStore()
        await store.save_analysis(analysis)
        service = ViralReasoningService(
            store,
            router=ModelRouter({"dashscope": provider}),
        )

        first = await service.enrich(analysis, report)
        second = await service.enrich(analysis, report)

        assert first.viral_reasoning is not None
        assert first.overview.summary == synthesis.content_value
        assert second.viral_reasoning is not None
        assert provider.calls == 1
        runs = await store.list_model_runs(analysis.id)
        assert [run.status for run in runs] == ["completed", "cached"]

    asyncio.run(scenario())


def test_replication_difficulty_uses_motion_complexity_not_only_shot_count() -> None:
    report = sample_report()
    baseline = build_viral_insight(report)
    complex_shot = report.shots[0].model_copy(
        update={"camera": "手持跟拍后环绕主体，并以甩镜结束"}
    )
    complex_report = report.model_copy(update={"shots": [complex_shot, report.shots[1]]})

    assert baseline.replication_difficulty == "low"
    assert build_viral_insight(complex_report).replication_difficulty == "medium"


def test_concept_generation_creates_three_distinct_routes_and_replacements() -> None:
    report = sample_report()
    report.prompt_package.shots[0].prompt = (
        "【基础画面】\n主体：黑长直发女性与浅绿色丝带\n场景：室内木门前\n\n"
        "【时间轴】\n0.00–2.80s\n主体动作：女子整理丝带\n镜头运动：快速推近\n\n"
        "【出场转场】\n丝带遮满画面"
    )
    insight = build_viral_insight(report)
    profile = sample_category_profile()
    request = ViralConceptGenerateRequest(category_profile_id=profile.id)
    concepts = build_concept_set(
        report,
        insight,
        list(request.strategies),
        [
            ViralReplacementSelection(
                entity_id="entity-person",
                replacement="短发男摄影师",
            )
        ],
        CategoryProfileSnapshot.from_profile(profile),
    )
    assert [item.strategy for item in concepts.concepts] == [
        "faithful",
        "scenario",
        "proof",
    ]
    assert all(len(item.shots) == 2 for item in concepts.concepts)
    assert all("短发男摄影师" in item.shots[0].video_prompt for item in concepts.concepts)
    assert concepts.schema_version == CONCEPT_SCHEMA_VERSION
    assert concepts.generator_id == CONCEPT_GENERATOR_ID
    assert concepts.strategy_contract_version == STRATEGY_CONTRACT_VERSION
    assert concepts.source_insight_fingerprint == insight.input_fingerprint
    assert concepts.category_profile is not None
    assert concepts.category_profile.id == profile.id
    assert concepts.category_profile.fingerprint
    assert len({item.thesis for item in concepts.concepts}) == 3
    assert len({item.hook for item in concepts.concepts}) == 3
    assert len({item.narrative_structure for item in concepts.concepts}) == 3
    assert len({item.visual_memory for item in concepts.concepts}) == 3
    assert len({item.why_it_can_work for item in concepts.concepts}) == 3
    assert len({tuple(item.retained_dna) for item in concepts.concepts}) == 3
    assert len({tuple(item.improvements) for item in concepts.concepts}) == 3
    assert len({tuple(item.risks) for item in concepts.concepts}) == 3
    assert len({item.shots[0].image_prompt for item in concepts.concepts}) == 3
    assert len({item.shots[0].video_prompt for item in concepts.concepts}) == 3
    assert all("时间轴" not in item.shots[0].image_prompt for item in concepts.concepts)
    assert all("出场转场" not in item.shots[0].image_prompt for item in concepts.concepts)
    assert all("主体动作" not in item.shots[0].image_prompt for item in concepts.concepts)


def test_concept_diversity_guard_rejects_duplicated_strategy_content() -> None:
    report = sample_report()
    insight = build_viral_insight(report)
    profile = sample_category_profile()
    request = ViralConceptGenerateRequest(category_profile_id=profile.id)
    concepts = build_concept_set(
        report,
        insight,
        list(request.strategies),
        [],
        CategoryProfileSnapshot.from_profile(profile),
    ).concepts
    duplicate = concepts[0].model_copy(
        update={"id": uuid4(), "strategy": "scenario"},
    )

    with pytest.raises(ConceptDiversityError) as caught:
        validate_concept_diversity([concepts[0], duplicate])

    assert "有效性说明" in caught.value.duplicate_fields
    assert "逐镜头视频提示词" in caught.value.duplicate_fields


def test_legacy_concept_batch_is_returned_as_stale_and_cannot_be_published() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        report = sample_report()
        await store.save_report(report)
        service = ViralInsightService(store, publisher=FakePublisher())
        insight = await service.get_insight(report.analysis_id)
        profile = sample_category_profile()
        request = ViralConceptGenerateRequest(category_profile_id=profile.id)
        generated = build_concept_set(
            report,
            insight,
            list(request.strategies),
            [],
            CategoryProfileSnapshot.from_profile(profile),
        )
        legacy = generated.model_copy(
            update={
                "schema_version": "viral-dna-concepts-v1",
                "generator_id": "replication-rules-v1",
                "strategy_contract_version": "strategy-contract-v1",
                "source_insight_fingerprint": None,
            }
        )
        await store.save_viral_concept_set(legacy)

        latest = await service.latest_concepts(report.analysis_id)
        assert latest is not None
        assert latest.status == "stale"
        assert latest.stale_reason is not None

        with pytest.raises(ViralInsightServiceError) as caught:
            await service.publish_concept(
                legacy.id,
                legacy.concepts[0].id,
                ViralConceptPublishRequest(record_id=uuid4()),
            )
        assert caught.value.status_code == 409
        assert caught.value.code == "concept_set_stale"

    asyncio.run(scenario())


class FakePublisher:
    def __init__(self) -> None:
        self.published = None

    async def publish(self, *, analysis_id, concept, payload):
        self.published = (analysis_id, concept.id, payload.record_id)
        return ViralConceptPublishResult(
            project_id=uuid4(),
            project_name=concept.name,
            concept_id=concept.id,
            shot_count=len(concept.shots),
        )


def test_service_persists_latest_concepts_and_publishes_selected_route() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        report = sample_report()
        await store.save_report(report)
        publisher = FakePublisher()
        categories = FakeCategoryProfileService()
        service = ViralInsightService(
            store,
            publisher=publisher,
            category_profiles=categories,
        )

        first = await service.get_insight(report.analysis_id)
        second = await service.get_insight(report.analysis_id)
        assert first.id == second.id

        updated_report = report.model_copy(
            update={
                "generated_at": datetime.now(UTC),
                "overview": report.overview.model_copy(
                    update={"summary": "重新分析后生成的新摘要。"}
                ),
            }
        )
        await store.save_report(updated_report)
        rebuilt = await service.get_insight(report.analysis_id)
        assert rebuilt.id != second.id
        assert rebuilt.input_fingerprint != second.input_fingerprint

        concepts = await service.generate_concepts(
            report.analysis_id,
            ViralConceptGenerateRequest(category_profile_id=categories.profile.id),
        )
        latest = await service.latest_concepts(report.analysis_id)
        assert latest is not None and latest.id == concepts.id
        assert categories.used == 1

        selected = concepts.concepts[1]
        record_id = uuid4()
        result = await service.publish_concept(
            concepts.id,
            selected.id,
            ViralConceptPublishRequest(record_id=record_id),
        )
        assert result.concept_id == selected.id
        assert publisher.published == (report.analysis_id, selected.id, record_id)

    asyncio.run(scenario())


def test_viral_insight_routes_cover_read_generate_and_publish() -> None:
    store = InMemoryStore()
    report = sample_report()
    asyncio.run(store.save_report(report))
    categories = FakeCategoryProfileService()
    service = ViralInsightService(
        store,
        publisher=FakePublisher(),
        category_profiles=categories,
    )
    app = FastAPI()
    app.include_router(create_viral_insight_router(service), prefix="/api/v1")

    with TestClient(app) as client:
        insight_response = client.get(f"/api/v1/analyses/{report.analysis_id}/viral-insight")
        assert insight_response.status_code == 200
        assert insight_response.json()["data_basis"] == "content_inference"

        refresh_response = client.post(
            f"/api/v1/analyses/{report.analysis_id}/viral-insight/refresh"
        )
        assert refresh_response.status_code == 404

        concepts_response = client.post(
            f"/api/v1/analyses/{report.analysis_id}/viral-concepts",
            json={
                "category_profile_id": str(categories.profile.id),
                "strategies": ["faithful", "scenario", "proof"],
                "replacements": [],
            },
        )
        assert concepts_response.status_code == 201
        payload = concepts_response.json()
        assert len(payload["concepts"]) == 3

        selected = payload["concepts"][2]
        publish_response = client.post(
            f"/api/v1/viral-concept-sets/{payload['id']}/concepts/{selected['id']}/publish",
            json={"record_id": str(uuid4())},
        )
        assert publish_response.status_code == 201
        assert publish_response.json()["concept_id"] == selected["id"]


def test_production_publisher_maps_concept_prompts_through_narrow_adapter() -> None:
    report = sample_report()
    insight = build_viral_insight(report)
    profile = sample_category_profile()
    request = ViralConceptGenerateRequest(category_profile_id=profile.id)
    concept = build_concept_set(
        report,
        insight,
        list(request.strategies),
        [],
        CategoryProfileSnapshot.from_profile(profile),
    ).concepts[0]

    class FakeProductionService:
        def __init__(self) -> None:
            self.created_payload = None
            self.bulk_payload = None
            self.project_id = uuid4()
            self.revision_id = uuid4()

        async def create_project(self, record_id, payload):
            self.created_payload = payload
            return SimpleNamespace(
                project=SimpleNamespace(id=self.project_id, name=payload.name),
                current_revision=SimpleNamespace(id=self.revision_id),
            )

        async def list_shots(self, project_id):
            return [
                SimpleNamespace(
                    plan=SimpleNamespace(
                        id=uuid4(),
                        source_shot_id=shot.source_shot_id,
                        index=shot.index,
                    )
                )
                for shot in concept.shots
            ]

        async def bulk_update_shots(self, project_id, payload):
            self.bulk_payload = payload
            return []

    async def scenario() -> None:
        production = FakeProductionService()
        publisher = ProductionConceptPublisher(production)
        result = await publisher.publish(
            analysis_id=report.analysis_id,
            concept=concept,
            payload=ViralConceptPublishRequest(record_id=uuid4()),
        )
        assert result.project_id == production.project_id
        assert result.shot_count == len(concept.shots)
        assert production.created_payload.base_analysis_id == report.analysis_id
        assert production.bulk_payload.expected_revision_id == production.revision_id
        assert production.bulk_payload.updates[0].video_prompt == concept.shots[0].video_prompt

    asyncio.run(scenario())
