from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from viral_dna_api.models import (
    VideoCostEstimateRequest,
    VideoGenerationCapability,
    VideoGenerationSettingsUpdate,
    VideoProviderCredentialUpdate,
    VideoProviderTask,
    VideoProviderTaskStatus,
    VideoProviderValidationRequest,
)
from viral_dna_api.store import InMemoryStore
from viral_dna_api.video_generation.catalog import (
    VideoModelCatalogError,
    load_video_model_catalog,
    video_duration_constraint_text,
    video_duration_is_supported,
)
from viral_dna_api.video_generation.contracts import (
    ProviderCredentialValidation,
    ProviderPollResult,
    ProviderSubmitResult,
    ProviderVideoRequest,
)
from viral_dna_api.video_generation.costing import estimate_video_cost
from viral_dna_api.video_generation.errors import VideoProviderError
from viral_dna_api.video_generation.orchestrator import RemoteVideoOrchestrator
from viral_dna_api.video_generation.providers.bailian.error_mapper import (
    raise_bailian_error,
)
from viral_dna_api.video_generation.providers.minimax.adapter import (
    MiniMaxVideoProvider,
)
from viral_dna_api.video_generation.providers.minimax.error_mapper import (
    raise_minimax_error,
)
from viral_dna_api.video_generation.providers.minimax.h3_request_mapper import (
    build_minimax_h3_request,
)
from viral_dna_api.video_generation.registry import VideoProviderRegistry
from viral_dna_api.video_generation.settings import (
    VideoGenerationSettingsService,
    VideoGenerationSettingsServiceError,
    normalize_provider_base_url,
)


class FakeProvider:
    provider_id = "bailian"
    adapter_version = "fake-v1"

    def __init__(self) -> None:
        self.validation_calls = 0
        self.submit_calls = 0
        self.poll_calls = 0

    async def validate_credentials(self, api_key: str, base_url: str):
        self.validation_calls += 1
        return ProviderCredentialValidation(api_key == "valid-key", "校验完成", 3)

    async def submit(self, request, *, api_key: str, base_url: str):
        self.submit_calls += 1
        return ProviderSubmitResult(
            task_id=f"task-{request.ordinal}",
            raw={"output": {"task_id": f"task-{request.ordinal}"}},
        )

    async def poll(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ):
        self.poll_calls += 1
        return ProviderPollResult(
            status=VideoProviderTaskStatus.SUCCEEDED,
            output_url=f"https://example.com/{task_id}.mp4",
            usage={"output_video_duration": 2},
            duration_seconds=2,
            raw={"output": {"task_status": "SUCCEEDED"}},
        )

    async def cancel(
        self,
        task_id: str,
        *,
        api_key: str,
        base_url: str,
        provider_model: str | None = None,
    ):
        return True


def test_catalog_keeps_stable_aliases_and_versioned_costs() -> None:
    catalog = load_video_model_catalog()
    bailian = catalog.option("bailian_wan_2_7_i2v")
    estimate = estimate_video_cost(
        bailian,
        duration_seconds=2,
        resolution="720P",
        candidate_count=2,
    )
    assert estimate.known is True
    assert estimate.micros == 2_400_000

    minimax = catalog.option("minimax_h3")
    assert minimax.capability.minimum_duration_seconds == 4
    assert minimax.capability.duration_step_seconds == 1
    assert minimax.capability.default_duration_seconds == 5
    minimax_estimate = estimate_video_cost(
        minimax,
        duration_seconds=6,
        resolution="768P",
        candidate_count=1,
    )
    assert minimax_estimate.micros == 3_000_000

    seedance = catalog.option("seedance_2_0", require_available=False)
    assert (
        estimate_video_cost(
            seedance,
            duration_seconds=5,
            resolution="720P",
            candidate_count=1,
        ).known
        is False
    )
    with pytest.raises(VideoModelCatalogError):
        catalog.option("seedance_2_0")
    with pytest.raises(VideoModelCatalogError):
        catalog.option("seedance_2_5")
    assert all(
        not item.available
        for item in catalog.options()
        if item.alias in {"seedance_2_0", "seedance_2_0_fast", "seedance_2_5"}
    )


def test_range_video_duration_capabilities_enforce_model_steps() -> None:
    capability = VideoGenerationCapability(
        minimum_duration_seconds=5,
        maximum_duration_seconds=15,
        duration_step_seconds=2,
        default_duration_seconds=9,
    )

    assert video_duration_is_supported(capability, 5) is True
    assert video_duration_is_supported(capability, 9) is True
    assert video_duration_is_supported(capability, 6) is False
    assert video_duration_is_supported(capability, 16) is False
    assert video_duration_constraint_text(capability) == "支持 5～15 秒，按 2 秒调整"


def test_video_requests_accept_minimax_2k_resolution() -> None:
    request = VideoCostEstimateRequest(
        model_alias="minimax_h3",
        resolution="2K",
        duration_seconds=4,
        candidate_count=1,
    )

    assert request.resolution == "2K"


def test_minimax_h3_uses_the_v2_multimodal_request(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    payload = build_minimax_h3_request(
        ProviderVideoRequest(
            request_id=uuid4(),
            ordinal=1,
            model_alias="minimax_h3",
            provider_model="MiniMax-H3",
            prompt="人物向镜头挥手",
            negative_prompt="身份漂移",
            first_frame_path=frame,
            duration_seconds=4,
            resolution="2K",
            aspect_ratio="9:16",
            width=1440,
            height=2560,
        )
    )

    assert payload["model"] == "MiniMax-H3"
    assert payload["duration"] == 4
    assert payload["resolution"] == "2K"
    assert payload["content"][1]["role"] == "first_frame"
    assert payload["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_minimax_credential_validation_uses_the_h3_task_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    class StubMiniMaxClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def list_h3_tasks(self, *, page_num: int, page_size: int) -> httpx.Response:
            calls.append((page_num, page_size))
            return httpx.Response(
                200,
                json={"items": [], "total": 0},
                request=httpx.Request(
                    "GET",
                    "https://api.minimaxi.com/v2/query/video_generation",
                ),
            )

    monkeypatch.setattr(
        "viral_dna_api.video_generation.providers.minimax.adapter.MiniMaxClient",
        StubMiniMaxClient,
    )

    result = asyncio.run(
        MiniMaxVideoProvider().validate_credentials(
            "valid-key",
            "https://api.minimaxi.com/v1",
        )
    )

    assert calls == [(1, 1)]
    assert result.valid is True
    assert result.error_code is None


@pytest.mark.parametrize(
    ("status_code", "payload", "valid", "error_code", "retryable"),
    [
        (
            401,
            {
                "type": "error",
                "error": {"type": "authorized_error", "message": "login fail (1004)"},
            },
            False,
            "video_provider_auth_invalid",
            False,
        ),
        (
            403,
            {"type": "error", "error": {"message": "permission denied"}},
            False,
            "video_provider_permission_denied",
            False,
        ),
        (
            429,
            {
                "type": "error",
                "error": {"type": "rate_limit_error", "message": "rate limit (1002)"},
            },
            False,
            "video_provider_rate_limited",
            True,
        ),
        (
            402,
            {
                "type": "error",
                "error": {
                    "type": "insufficient_balance_error",
                    "message": "insufficient balance (1008)",
                },
            },
            True,
            "video_provider_balance_insufficient",
            False,
        ),
    ],
)
def test_minimax_credential_validation_classifies_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    payload: dict[str, object],
    valid: bool,
    error_code: str,
    retryable: bool,
) -> None:
    class StubMiniMaxClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def list_h3_tasks(self, *, page_num: int, page_size: int) -> httpx.Response:
            return httpx.Response(
                status_code,
                json=payload,
                request=httpx.Request(
                    "GET",
                    "https://api.minimaxi.com/v2/query/video_generation",
                ),
            )

    monkeypatch.setattr(
        "viral_dna_api.video_generation.providers.minimax.adapter.MiniMaxClient",
        StubMiniMaxClient,
    )

    result = asyncio.run(
        MiniMaxVideoProvider().validate_credentials(
            "test-key",
            "https://api.minimaxi.com/v1",
        )
    )

    assert result.valid is valid
    assert result.error_code == error_code
    assert result.retryable is retryable
    if error_code == "video_provider_balance_insufficient":
        assert result.balance_known is True
        assert result.balance_micros == 0


def test_minimax_base_urls_accept_current_official_regions() -> None:
    assert (
        normalize_provider_base_url("minimax", "https://api.minimaxi.com/v1")
        == "https://api.minimaxi.com/v1"
    )
    assert (
        normalize_provider_base_url("minimax", "https://api.minimax.io/v1")
        == "https://api.minimax.io/v1"
    )


def test_video_settings_preserve_minimax_validation_failure_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenMiniMaxProvider(FakeProvider):
        provider_id = "minimax"

        async def validate_credentials(self, api_key: str, base_url: str):
            self.validation_calls += 1
            return ProviderCredentialValidation(
                False,
                "MiniMax API Key 已被识别，但当前账号没有 H3 视频接口权限",
                3,
                error_code="video_provider_permission_denied",
            )

    async def scenario() -> None:
        env_path = tmp_path / ".env.local"
        monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        provider = ForbiddenMiniMaxProvider()
        service = VideoGenerationSettingsService(VideoProviderRegistry([provider]))

        with pytest.raises(VideoGenerationSettingsServiceError) as caught:
            await service.update(
                VideoGenerationSettingsUpdate(
                    default_model_alias="bailian_wan_2_7_i2v",
                    default_resolution="720P",
                    providers=[
                        VideoProviderCredentialUpdate(
                            provider="minimax",
                            api_key="valid-but-forbidden-key",
                            base_url="https://api.minimaxi.com/v1",
                        )
                    ],
                )
            )

        assert caught.value.status_code == 403
        assert caught.value.code == "video_provider_permission_denied"
        assert not env_path.exists()

    asyncio.run(scenario())


def test_settings_allow_blank_provider_keys_and_validate_nonblank_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        env_path = tmp_path / ".env.local"
        monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
        for name in (
            "DASHSCOPE_API_KEY",
            "ARK_API_KEY",
            "MINIMAX_API_KEY",
            "VIRAL_DNA_VIDEO_DEFAULT_MODEL_ALIAS",
        ):
            monkeypatch.delenv(name, raising=False)
        provider = FakeProvider()
        service = VideoGenerationSettingsService(VideoProviderRegistry([provider]))
        saved = await service.update(
            VideoGenerationSettingsUpdate(
                default_model_alias="bailian_wan_2_7_i2v",
                default_resolution="720P",
                providers=[
                    VideoProviderCredentialUpdate(
                        provider="bailian",
                        base_url="https://dashscope.aliyuncs.com/api/v1",
                    )
                ],
            )
        )
        assert saved.providers[0].api_key_configured is False
        assert provider.validation_calls == 0

        saved = await service.update(
            VideoGenerationSettingsUpdate(
                default_model_alias="bailian_wan_2_7_i2v",
                default_resolution="720P",
                providers=[
                    VideoProviderCredentialUpdate(
                        provider="bailian",
                        api_key="valid-key",
                        base_url="https://dashscope.aliyuncs.com/api/v1",
                    )
                ],
            )
        )
        assert saved.providers[0].api_key_configured is True
        assert provider.validation_calls == 1

    asyncio.run(scenario())


def test_validating_a_saved_key_persists_its_validation_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        env_path = tmp_path / ".env.local"
        monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
        monkeypatch.setenv("DASHSCOPE_API_KEY", "valid-key")
        monkeypatch.delenv("VIRAL_DNA_VIDEO_BAILIAN_VALIDATED_AT", raising=False)
        provider = FakeProvider()
        service = VideoGenerationSettingsService(VideoProviderRegistry([provider]))

        result = await service.validate_provider(
            "bailian",
            VideoProviderValidationRequest(),
        )

        assert result.valid is True
        assert "VIRAL_DNA_VIDEO_BAILIAN_VALIDATED_AT=" in env_path.read_text(encoding="utf-8")

    asyncio.run(scenario())


def test_provider_error_mapping_exposes_balance_shortage() -> None:
    with pytest.raises(VideoProviderError) as bailian:
        raise_bailian_error(400, {"code": "Arrearage", "message": "balance insufficient"})
    assert bailian.value.code == "video_provider_balance_insufficient"
    assert bailian.value.status_code == 402

    with pytest.raises(VideoProviderError) as minimax:
        raise_minimax_error(
            200, {"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}}
        )
    assert minimax.value.code == "video_provider_balance_insufficient"
    assert minimax.value.status_code == 402

    with pytest.raises(VideoProviderError) as minimax_h3:
        raise_minimax_error(
            402,
            {
                "type": "error",
                "error": {
                    "type": "insufficient_balance_error",
                    "message": "insufficient balance (1008)",
                    "http_code": "402",
                },
            },
        )
    assert minimax_h3.value.code == "video_provider_balance_insufficient"


def test_remote_orchestrator_persists_one_upstream_task_per_candidate_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        env_path = tmp_path / ".env.local"
        monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_path))
        monkeypatch.setenv("DASHSCOPE_API_KEY", "valid-key")
        monkeypatch.setenv("VIRAL_DNA_VIDEO_POLL_INTERVAL_SECONDS", "0.2")
        provider = FakeProvider()
        registry = VideoProviderRegistry([provider])
        settings = VideoGenerationSettingsService(registry)
        repository = InMemoryStore()
        orchestrator = RemoteVideoOrchestrator(settings, repository, registry)
        execution = orchestrator.resolve(
            model_alias="bailian_wan_2_7_i2v",
            duration_seconds=2,
            resolution="720P",
            candidate_count=2,
            allow_unknown_cost=False,
        )

        async def fake_download(url: str, destination: Path, **_: object) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(  # noqa: ASYNC240 - deterministic test stub
                b"\x00\x00\x00\x18ftypmp42remote-video"
            )

        monkeypatch.setattr(
            "viral_dna_api.video_generation.orchestrator.download_provider_video",
            fake_download,
        )
        run_id = uuid4()
        run_root = tmp_path / "run"
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"frame")
        result = await orchestrator.generate(
            execution,
            run_id=run_id,
            project_id=uuid4(),
            shot_plan_id=uuid4(),
            run_root=run_root,
            first_frame_path=frame,
            candidate_count=2,
            duration_seconds=2,
            aspect_ratio="9:16",
            width=720,
            height=1280,
            positive_prompt="人物向前走",
            negative_prompt="身份漂移",
            seed=7,
            cancel_event=None,
        )
        assert len(result.videos) == 2
        assert result.actual_cost_micros == 2_400_000
        tasks = await repository.list_video_provider_tasks(run_id)
        assert [item.provider_task_id for item in tasks] == ["task-1", "task-2"]
        assert all(item.status == VideoProviderTaskStatus.SUCCEEDED for item in tasks)
        assert provider.submit_calls == 2

        resumed = await orchestrator.generate(
            execution,
            run_id=run_id,
            project_id=tasks[0].project_id,
            shot_plan_id=tasks[0].shot_plan_id,
            run_root=run_root,
            first_frame_path=frame,
            candidate_count=2,
            duration_seconds=2,
            aspect_ratio="9:16",
            width=720,
            height=1280,
            positive_prompt="人物向前走",
            negative_prompt="身份漂移",
            seed=7,
            cancel_event=None,
        )
        assert len(resumed.videos) == 2
        assert provider.submit_calls == 2

    asyncio.run(scenario())


def test_ambiguous_submission_is_not_repeated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "valid-key")
        provider = FakeProvider()
        registry = VideoProviderRegistry([provider])
        settings = VideoGenerationSettingsService(registry)
        repository = InMemoryStore()
        orchestrator = RemoteVideoOrchestrator(settings, repository, registry)
        execution = orchestrator.resolve(
            model_alias="bailian_wan_2_7_i2v",
            duration_seconds=2,
            resolution="720P",
            candidate_count=1,
            allow_unknown_cost=False,
        )
        run_id = uuid4()
        snapshot = {
            "model_alias": "bailian_wan_2_7_i2v",
            "provider_model": "wan2.7-i2v-2026-04-25",
            "ordinal": 1,
            "duration_seconds": 2,
            "resolution": "720P",
            "aspect_ratio": "9:16",
            "width": 720,
            "height": 1280,
            "prompt": "人物向前走",
            "negative_prompt": "身份漂移",
            "seed": 7,
        }
        import hashlib
        import json

        fingerprint = hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        await repository.save_video_provider_task(
            VideoProviderTask(
                generation_run_id=run_id,
                project_id=uuid4(),
                shot_plan_id=uuid4(),
                ordinal=1,
                provider="bailian",
                model_alias="bailian_wan_2_7_i2v",
                provider_model="wan2.7-i2v-2026-04-25",
                submission_fingerprint=fingerprint,
                request_snapshot=snapshot,
            )
        )
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"frame")
        with pytest.raises(VideoProviderError) as error:
            await orchestrator.generate(
                execution,
                run_id=run_id,
                project_id=uuid4(),
                shot_plan_id=uuid4(),
                run_root=tmp_path / "run",
                first_frame_path=frame,
                candidate_count=1,
                duration_seconds=2,
                aspect_ratio="9:16",
                width=720,
                height=1280,
                positive_prompt="人物向前走",
                negative_prompt="身份漂移",
                seed=7,
                cancel_event=None,
            )
        assert error.value.code == "video_provider_submission_ambiguous"
        assert provider.submit_calls == 0

    asyncio.run(scenario())
