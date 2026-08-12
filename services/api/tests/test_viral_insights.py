from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.models import (
    AnalysisReport,
    Entity,
    PromptPackage,
    PromptShot,
    Shot,
    VideoOverview,
    ViralFinding,
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


def test_concept_generation_creates_three_distinct_routes_and_replacements() -> None:
    report = sample_report()
    insight = build_viral_insight(report)
    concepts = build_concept_set(
        report,
        insight,
        list(ViralConceptGenerateRequest().strategies),
        [
            ViralReplacementSelection(
                entity_id="entity-person",
                replacement="短发男摄影师",
            )
        ],
    )
    assert [item.strategy for item in concepts.concepts] == [
        "faithful",
        "differentiated",
        "enhanced",
    ]
    assert all(len(item.shots) == 2 for item in concepts.concepts)
    assert all("短发男摄影师" in item.shots[0].video_prompt for item in concepts.concepts)
    assert concepts.schema_version == CONCEPT_SCHEMA_VERSION
    assert concepts.generator_id == CONCEPT_GENERATOR_ID
    assert concepts.strategy_contract_version == STRATEGY_CONTRACT_VERSION
    assert concepts.source_insight_fingerprint == insight.input_fingerprint
    assert len({item.why_it_can_work for item in concepts.concepts}) == 3
    assert len({tuple(item.retained_dna) for item in concepts.concepts}) == 3
    assert len({tuple(item.improvements) for item in concepts.concepts}) == 3
    assert len({tuple(item.risks) for item in concepts.concepts}) == 3
    assert len({item.shots[0].image_prompt for item in concepts.concepts}) == 3
    assert len({item.shots[0].video_prompt for item in concepts.concepts}) == 3


def test_concept_diversity_guard_rejects_duplicated_strategy_content() -> None:
    report = sample_report()
    insight = build_viral_insight(report)
    concepts = build_concept_set(
        report,
        insight,
        list(ViralConceptGenerateRequest().strategies),
        [],
    ).concepts
    duplicate = concepts[0].model_copy(
        update={"id": uuid4(), "strategy": "differentiated"},
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
        generated = build_concept_set(
            report,
            insight,
            list(ViralConceptGenerateRequest().strategies),
            [],
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
        service = ViralInsightService(store, publisher=publisher)

        first = await service.get_insight(report.analysis_id)
        second = await service.get_insight(report.analysis_id)
        assert first.id == second.id

        concepts = await service.generate_concepts(
            report.analysis_id,
            ViralConceptGenerateRequest(),
        )
        latest = await service.latest_concepts(report.analysis_id)
        assert latest is not None and latest.id == concepts.id

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
    service = ViralInsightService(store, publisher=FakePublisher())
    app = FastAPI()
    app.include_router(create_viral_insight_router(service), prefix="/api/v1")

    with TestClient(app) as client:
        insight_response = client.get(f"/api/v1/analyses/{report.analysis_id}/viral-insight")
        assert insight_response.status_code == 200
        assert insight_response.json()["data_basis"] == "content_inference"

        concepts_response = client.post(
            f"/api/v1/analyses/{report.analysis_id}/viral-concepts",
            json={
                "strategies": ["faithful", "differentiated", "enhanced"],
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
    concept = build_concept_set(
        report,
        insight,
        list(ViralConceptGenerateRequest().strategies),
        [],
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
