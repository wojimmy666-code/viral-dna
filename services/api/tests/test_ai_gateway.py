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
from viral_dna_api.ai.shot_facts import ShotFactsService, _normalize_shot_facts
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
    ShotMotionPhaseFact,
    ShotTimelineEvidence,
    ShotTransitionFact,
    ShotVisualBeatFact,
    ShotVisualFacts,
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
            visual_beats=[
                ShotVisualBeatFact(
                    index=1,
                    title="画面 1",
                    start_seconds=0.2,
                    end_seconds=1.8,
                    source_timestamp_seconds=1,
                    image_prompt="竖屏写实中近景，人物在室内桌前拿起产品朝镜头展示。",
                )
            ],
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
        content_start_seconds=0.2,
        content_end_seconds=1.8,
        representative_timestamp=1,
        keyframe_url=urls[1],
        evidence_frame_urls=urls,
        evidence_timestamps=[0.4, 1, 1.6],
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
    assert plan.catalog_version == "phase2-model-catalog-2026-08-27-r10"
    assert plan.targets_for(ModelTask.SHOT_FACTS)[0].prompt_version == "shot-facts-v3"
    assert plan.targets_for(ModelTask.VIDEO_INTENT)[0].prompt_version == (
        "video-generation-intent-v2"
    )
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


def test_shot_facts_normalize_clip_relative_motion_and_transition_conflicts() -> None:
    shot = ShotEvidence(
        shot_id="shot_002",
        index=2,
        start_seconds=3.2,
        end_seconds=9.2,
        duration_seconds=6,
        content_start_seconds=3.2,
        content_end_seconds=8.9,
        outgoing_transition_start_seconds=8.9,
        outgoing_transition_end_seconds=9.6,
        analysis_clip_url="/api/v1/analyses/test/artifacts/shots/shot_002_analysis.mp4",
        analysis_clip_start_seconds=3.2,
        analysis_clip_end_seconds=9.6,
        representative_timestamp=6,
        keyframe_url="/api/v1/analyses/test/artifacts/shots/shot_002.jpg",
        detection_method="test",
    )
    facts = ShotVisualFacts(
        title="连续推近丝带",
        subjects=["黑色长发女性", "浅绿色丝带"],
        action="手整理丝带，丝带逐渐靠近镜头",
        scene="室内",
        camera="镜头持续推近",
        composition="丝带由局部逐渐占据画面",
        lighting="柔和明亮",
        color="暖木色与浅绿色",
        transition="硬切",
        narrative_role="遮挡转场",
        replication_prompt="人物整理丝带，随后画面切换为丝带特写，硬切结束。",
        confidence=0.9,
        continuous_take=True,
        motion_confidence=0.86,
        visual_beats=[
            ShotVisualBeatFact(
                index=1,
                title="丝带运动",
                start_seconds=0,
                end_seconds=5.7,
                source_timestamp_seconds=2.85,
                image_prompt="人物背对镜头，浅绿色丝带垂落",
            )
        ],
        motion_phases=[
            ShotMotionPhaseFact(
                index=1,
                start_seconds=0,
                end_seconds=4,
                description="中景缓慢推近，手整理丝带",
                camera_motion="缓慢推近",
                subject_motion="手整理丝带",
                foreground_motion="丝带向镜头靠近",
                foreground_occupancy_start_percent=15,
                foreground_occupancy_end_percent=65,
                confidence=0.88,
            ),
            ShotMotionPhaseFact(
                index=2,
                start_seconds=4,
                end_seconds=5.7,
                description="继续推至极近特写，丝带大面积遮挡画面",
                camera_motion="快速推近",
                foreground_motion="丝带覆盖镜头",
                foreground_occupancy_start_percent=65,
                foreground_occupancy_end_percent=100,
                confidence=0.91,
            ),
        ],
        outgoing_transition=ShotTransitionFact(),
    )

    normalized = _normalize_shot_facts(shot, facts)

    assert normalized.visual_beats[0].start_seconds == pytest.approx(3.2)
    assert normalized.visual_beats[0].end_seconds == pytest.approx(8.9)
    assert normalized.visual_beats[0].source_timestamp_seconds == pytest.approx(6.05)
    assert [(phase.start_seconds, phase.end_seconds) for phase in normalized.motion_phases] == [
        (3.2, 7.2),
        (7.2, 8.9),
    ]
    assert normalized.outgoing_transition.kind == "uncertain"
    assert normalized.outgoing_transition.start_seconds == pytest.approx(8.9)
    assert normalized.outgoing_transition.end_seconds == pytest.approx(9.6)
    assert normalized.outgoing_transition.description != "无出场转场"
    assert "【主体与服装】" in normalized.replication_prompt
    assert "【场景】" in normalized.replication_prompt
    assert "【时间轴】" not in normalized.replication_prompt
    assert "【出场转场】" not in normalized.replication_prompt
    assert "检测到出场转场窗口" not in normalized.replication_prompt
    assert "硬切" not in normalized.replication_prompt
    assert "画面切换为" not in normalized.replication_prompt


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
async def test_english_shot_facts_are_retried_with_a_chinese_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video, analysis, evidence, timeline = _build_media_inputs(tmp_path, monkeypatch)
    repository = InMemoryStore()
    await repository.add_video(video)
    await repository.add_analysis(analysis)
    successful_provider = FakeVisionProvider()

    class EnglishOnceProvider:
        provider_id = "dashscope"

        def __init__(self) -> None:
            self.calls = 0
            self.retry_prompt = ""

        async def generate(self, request, response_schema):
            self.calls += 1
            if self.calls > 1:
                self.retry_prompt = request.user_prompt
                return await successful_provider.generate(request, response_schema)
            facts = response_schema(
                title="Girl standing on a rooftop",
                subjects=["A girl with long black hair"],
                action="Standing still, hair and skirt blowing in wind",
                scene="Rooftop terrace overlooking a city",
                camera="Static / Locked-off",
                composition="Cinematic wide shot",
                lighting="Twilight light",
                color="Deep blue and warm yellow",
                transition="None",
                narrative_role="Quiet ending",
                replication_prompt="A girl stands on a rooftop at twilight.",
                confidence=0.8,
                visual_beats=[
                    ShotVisualBeatFact(
                        index=1,
                        title="Rooftop girl",
                        start_seconds=0.2,
                        end_seconds=1.8,
                        source_timestamp_seconds=1,
                        image_prompt="A girl stands on a rooftop at twilight.",
                    )
                ],
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
                provider_request_id="english-response",
                latency_ms=80,
                raw_content=facts.model_dump_json(),
            )

    provider = EnglishOnceProvider()
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
    assert "上一次输出未通过中文校验" in provider.retry_prompt
    runs = await repository.list_model_runs(analysis.id)
    assert [run.status for run in runs] == [ModelRunStatus.FAILED, ModelRunStatus.COMPLETED]
    assert runs[0].error_code == "model_language_invalid"


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
