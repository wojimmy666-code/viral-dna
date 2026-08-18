from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.control_assets.engines import (
    DepthEngineCapability,
    DepthEngineRegistry,
    DepthEngineSelectionError,
    DepthEngineSelector,
    DepthGenerationProfile,
)
from viral_dna_api.control_assets.engines.selector import CPU_ENGINE_ID, GPU_ENGINE_ID
from viral_dna_api.control_assets.jobs.domain import (
    DepthControlPreset,
    DepthExecutionDevice,
    DepthExecutionPreference,
)
from viral_dna_api.control_assets.settings import DepthGenerationSettingsService


class FakeEngine:
    def __init__(self, engine_id: str, *, available: bool, cuda: bool = False) -> None:
        self.engine_id = engine_id
        self.available = available
        self.cuda = cuda

    def capability(self) -> DepthEngineCapability:
        return DepthEngineCapability(
            engine=self.engine_id,
            version="test-v1",
            model_variant="small",
            available=self.available,
            availability_note="" if self.available else "not installed",
            repository_url="https://example.invalid",
            checkpoint_path=Path("model") if self.available else None,
            runtime_path=Path("runtime") if self.available else None,
            license="Apache-2.0",
        )

    async def profile(self, requested: DepthControlPreset) -> DepthGenerationProfile:
        if not self.available:
            raise RuntimeError("not installed")
        if self.engine_id == GPU_ENGINE_ID and not self.cuda:
            raise RuntimeError("NVIDIA CUDA unavailable")
        device = (
            DepthExecutionDevice.CUDA
            if self.engine_id == GPU_ENGINE_ID
            else DepthExecutionDevice.CPU
        )
        return DepthGenerationProfile(
            preset=(
                DepthControlPreset.BALANCED
                if device == DepthExecutionDevice.CUDA
                else DepthControlPreset.CPU_FAST
            ),
            device=device,
            device_name="Test GPU" if self.cuda else "Test CPU",
            target_fps=30,
            input_size=518,
            max_resolution=1280,
            timeout_seconds=7200,
        )


def selector(*, cpu: bool, gpu: bool, cuda: bool) -> DepthEngineSelector:
    return DepthEngineSelector(
        DepthEngineRegistry(
            [
                FakeEngine(CPU_ENGINE_ID, available=cpu),
                FakeEngine(GPU_ENGINE_ID, available=gpu, cuda=cuda),
            ]
        )
    )


def test_auto_prefers_cuda_and_falls_back_to_cpu() -> None:
    async def scenario() -> None:
        gpu_profile = await selector(cpu=True, gpu=True, cuda=True).resolve(
            preference=DepthExecutionPreference.AUTO,
        )
        assert gpu_profile.engine_id == GPU_ENGINE_ID
        assert gpu_profile.device == DepthExecutionDevice.CUDA

        cpu_profile = await selector(cpu=True, gpu=True, cuda=False).resolve(
            preference=DepthExecutionPreference.AUTO,
        )
        assert cpu_profile.engine_id == CPU_ENGINE_ID
        assert cpu_profile.device == DepthExecutionDevice.CPU

    asyncio.run(scenario())


def test_forced_gpu_does_not_silently_fall_back() -> None:
    async def scenario() -> None:
        with pytest.raises(DepthEngineSelectionError) as captured:
            await selector(cpu=True, gpu=True, cuda=False).resolve(
                preference=DepthExecutionPreference.GPU,
            )
        assert captured.value.code == "depth_gpu_unavailable"

    asyncio.run(scenario())


def test_account_depth_setting_defaults_to_auto_and_persists(tmp_path: Path) -> None:
    account_id = uuid4()
    workspace = SimpleNamespace(
        paths=SimpleNamespace(metadata_dir=tmp_path / ".viraldna")
    )
    account_context = SimpleNamespace(
        current_account=lambda: None,
    )

    async def current_account():
        return SimpleNamespace(id=account_id)

    account_context.current_account = current_account
    service = DepthGenerationSettingsService(workspace, account_context)

    async def scenario() -> None:
        _, initial = await service.get_current()
        assert initial.execution_preference == DepthExecutionPreference.AUTO
        await service.update_current(DepthExecutionPreference.CPU)
        _, saved = await service.get_current()
        assert saved.execution_preference == DepthExecutionPreference.CPU

    asyncio.run(scenario())
