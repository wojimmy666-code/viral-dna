from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from viral_dna_api.ai.billing import PriceCatalog, calculate_cost_micros, cny_to_micros
from viral_dna_api.ai.catalog import (
    ModelCatalogError,
    default_analysis_profile,
    load_model_plan,
)
from viral_dna_api.ai.contracts import ModelProviderError, ModelRequest, ProviderResult
from viral_dna_api.ai.router import ModelRouter
from viral_dna_api.ai.shot_facts import ShotFactsService
from viral_dna_api.models import (
    AnalysisJob,
    AnalysisMode,
    AnalysisProfile,
    EvidenceTimeline,
    MediaEvidence,
    MediaMetadata,
    ModelRunStatus,
    ModelTask,
    ModelUsage,
    ShotEvidence,
    ShotTimelineEvidence,
    SourceType,
    Video,
)
from viral_dna_api.store import InMemoryStore


class FakeVisionProvider:
    provider_id = "dashscope"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        request: ModelRequest,
        response_schema,
    ) -> ProviderResult:
        self.calls += 1
        assert request.task == ModelTask.SHOT_FACTS
        assert len(request.image_paths) == 3
        facts = response_schema(
            title="人物展示产品",
            subjects=["一名穿浅色上衣的人物", "桌面上的产品"],
            action="人物拿起产品并朝镜头展示",
            scene="室内桌面场景，背景简洁",
            camera="固定中近景，平视机位",
            composition="人物居中，产品位于画面中心",
            lighting="柔和正面光，阴影较弱",
            color="暖白和浅棕色为主",
            transition="由上一画面直接切入",
            narrative_role="展示核心产品和使用动作",
            replication_prompt="竖屏写实中近景，人物在室内桌前拿起产品朝镜头展示。",
            confidence=0.91,
        )
        usage = ModelUsage(
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            image_count=3,
        )
        return ProviderResult(
            data=facts,
            usage=usage,
            requested_model=request.target.model,
            resolved_model=request.target.model,
            provider_request_id="fake-request-1",
            latency_ms=80,
            raw_content=facts.model_dump_json(),
        )


def _build_media_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_cost_micros: int | None = None,
) -> tuple[Video, AnalysisJob, MediaEvidence, EvidenceTimeline]:
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("VIRAL_DNA_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    plan = load_model_plan(AnalysisProfile.BALANCED)
    assert plan is not None

    video = Video(
        source_type=SourceType.UPLOAD,
        title="VLM 测试",
        sha256="a" * 64,
    )
    analysis = AnalysisJob(
        video_id=video.id,
        analysis_mode=AnalysisMode.MODEL,
        simulated=False,
        model_plan=plan,
        max_cost_micros=max_cost_micros,
    )
    shots_dir = storage_root / "analyses" / str(analysis.id) / "shots"
    shots_dir.mkdir(parents=True)
    urls = []
    for suffix in ("start", "middle", "end"):
        filename = "shot_001.jpg" if suffix == "middle" else f"shot_001_{suffix}.jpg"
        (shots_dir / filename).write_bytes(f"jpeg-{suffix}".encode())
        urls.append(f"/api/v1/analyses/{analysis.id}/artifacts/shots/{filename}")

    shot = ShotEvidence(
        shot_id="shot_001",
        index=1,
        start_seconds=0,
        end_seconds=2,
        duration_seconds=2,
        representative_timestamp=1,
        keyframe_url=urls[1],
        evidence_frame_urls=urls,
        detection_method="test",
    )
    evidence = MediaEvidence(
        processor_version="test",
        metadata=MediaMetadata(
            duration_seconds=2,
            width=640,
            height=360,
            fps=25,
            format_name="mp4",
            video_codec="h264",
            has_audio=True,
            size_bytes=100,
            sha256="a" * 64,
            aspect_ratio="16:9",
        ),
        proxy_url=f"/api/v1/analyses/{analysis.id}/artifacts/proxy.mp4",
        manifest_url=f"/api/v1/analyses/{analysis.id}/artifacts/manifest.json",
        shots=[shot],
    )
    timeline = EvidenceTimeline(
        duration_seconds=2,
        provider_runs=[],
        shots=[
            ShotTimelineEvidence(
                shot_id="shot_001",
                start_seconds=0,
                end_seconds=2,
                transcript_text="现在展示产品",
                ocr_text="新品上市",
            )
        ],
        artifact_url=f"/api/v1/analyses/{analysis.id}/artifacts/timeline.json",
    )
    return video, analysis, evidence, timeline


def test_catalog_freezes_profile_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "dashscope")
    plan = load_model_plan(AnalysisProfile.ECONOMY)
    assert plan is not None
    assert plan.catalog_version == "phase2-model-catalog-2026-08-06-r6"
    assert PriceCatalog().catalog_version == plan.pricing_version
    targets = plan.targets_for(ModelTask.SHOT_FACTS)
    assert [target.model for target in targets] == [
        "qwen3.6-flash-2026-04-16",
        "qwen3.7-plus-2026-05-26",
    ]

    monkeypatch.setenv("VIRAL_DNA_VLM_PROVIDER", "disabled")
    assert load_model_plan(AnalysisProfile.BALANCED) is None


def test_default_analysis_profile_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIRAL_DNA_MODEL_PROFILE", "economy")
    assert default_analysis_profile() == AnalysisProfile.ECONOMY

    monkeypatch.setenv("VIRAL_DNA_MODEL_PROFILE", "unknown")
    with pytest.raises(ModelCatalogError, match="VIRAL_DNA_MODEL_PROFILE"):
        default_analysis_profile()

    monkeypatch.delenv("VIRAL_DNA_MODEL_PROFILE")
    assert default_analysis_profile() == AnalysisProfile.BALANCED


def test_price_catalog_calculates_cached_and_uncached_tokens() -> None:
    catalog = PriceCatalog()
    price = catalog.snapshot_for("dashscope", "qwen3.7-plus-2026-05-26", 1000)
    price = price.model_copy(update={"cached_input_cny_per_million": Decimal("0.5")})
    usage = ModelUsage(
        input_tokens=1000,
        cached_input_tokens=400,
        output_tokens=500,
        total_tokens=1500,
    )
    assert calculate_cost_micros(usage, price) == 5400
    assert cny_to_micros(Decimal("0.125")) == 125000


@pytest.mark.asyncio
async def test_shot_facts_are_metered_and_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence, timeline = _build_media_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    provider = FakeVisionProvider()
    service = ShotFactsService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )

    first = await service.analyze(
        analysis=analysis,
        video=video,
        evidence=evidence,
        timeline=timeline,
    )
    assert first.facts["shot_001"].confidence == 0.91
    assert first.cost_summary.measured_cost_micros == 6000
    assert provider.calls == 1
    first_runs = await repository.list_model_runs(analysis.id)
    assert first_runs[0].status == ModelRunStatus.COMPLETED
    assert first_runs[0].provider_request_id == "fake-request-1"
    assert first_runs[0].raw_response_ref is not None

    second = await service.analyze(
        analysis=analysis,
        video=video,
        evidence=evidence,
        timeline=timeline,
    )
    assert second.facts["shot_001"].title == "人物展示产品"
    assert provider.calls == 1
    runs = await repository.list_model_runs(analysis.id)
    assert [run.status for run in runs] == [
        ModelRunStatus.COMPLETED,
        ModelRunStatus.CACHED,
    ]
    assert second.cost_summary.measured_cost_micros == 6000


@pytest.mark.asyncio
async def test_retryable_failure_creates_linked_run_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence, timeline = _build_media_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    successful_provider = FakeVisionProvider()

    class RetryOnceProvider:
        provider_id = "dashscope"

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request, response_schema):
            self.calls += 1
            if self.calls == 1:
                raise ModelProviderError(
                    "model_timeout",
                    "首次调用超时",
                    retryable=True,
                    provider_request_id="retry-1",
                )
            return await successful_provider.generate(request, response_schema)

    provider = RetryOnceProvider()
    service = ShotFactsService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )
    outcome = await service.analyze(
        analysis=analysis,
        video=video,
        evidence=evidence,
        timeline=timeline,
    )
    assert outcome.facts["shot_001"].title == "人物展示产品"
    assert provider.calls == 2
    runs = await repository.list_model_runs(analysis.id)
    assert [run.status for run in runs] == [ModelRunStatus.FAILED, ModelRunStatus.COMPLETED]
    assert runs[1].retry_of_run_id == runs[0].id


@pytest.mark.asyncio
async def test_budget_blocks_provider_before_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence, timeline = _build_media_inputs(
        tmp_path,
        monkeypatch,
        max_cost_micros=1,
    )
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    provider = FakeVisionProvider()
    service = ShotFactsService(
        repository,
        router=ModelRouter({"dashscope": provider}),
    )

    outcome = await service.analyze(
        analysis=analysis,
        video=video,
        evidence=evidence,
        timeline=timeline,
    )
    assert outcome.facts == {}
    assert provider.calls == 0
    assert "成本上限" in outcome.warnings[0]
    runs = await repository.list_model_runs(analysis.id)
    assert len(runs) == 1
    assert runs[0].status == ModelRunStatus.BLOCKED


@pytest.mark.asyncio
async def test_failed_response_with_usage_is_charged_to_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence, timeline = _build_media_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)

    class ChargedFailureProvider:
        provider_id = "dashscope"

        async def generate(self, request, response_schema):
            raise ModelProviderError(
                "model_schema_invalid",
                "响应结构无效",
                retryable=False,
                provider_request_id="charged-failure-1",
                usage=ModelUsage(
                    input_tokens=1000,
                    output_tokens=500,
                    total_tokens=1500,
                    image_count=3,
                ),
                resolved_model=request.target.model,
                latency_ms=42,
                raw_content='{"title":"incomplete"}',
            )

    service = ShotFactsService(
        repository,
        router=ModelRouter({"dashscope": ChargedFailureProvider()}),
    )
    outcome = await service.analyze(
        analysis=analysis,
        video=video,
        evidence=evidence,
        timeline=timeline,
    )

    assert outcome.facts == {}
    assert outcome.cost_summary.measured_cost_micros == 6000
    runs = await repository.list_model_runs(analysis.id)
    assert len(runs) == 1
    assert runs[0].status == ModelRunStatus.FAILED
    assert runs[0].provider_request_id == "charged-failure-1"
    assert runs[0].latency_ms == 42
    assert runs[0].measured_cost_micros == 6000
    assert runs[0].raw_response_ref is not None
    assert analysis.measured_cost_micros == 6000
