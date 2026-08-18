from __future__ import annotations

from dataclasses import replace

from ..jobs.domain import (
    DepthControlPreset,
    DepthExecutionPreference,
)
from .contracts import DepthGenerationProfile
from .registry import DepthEngineRegistry

CPU_ENGINE_ID = "depth_anything_v2_onnx"
GPU_ENGINE_ID = "video_depth_anything_cuda"


class DepthEngineSelectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DepthEngineSelector:
    def __init__(self, registry: DepthEngineRegistry) -> None:
        self.registry = registry

    async def gpu_available(self) -> tuple[bool, str, DepthGenerationProfile | None]:
        engine = self.registry.get(GPU_ENGINE_ID)
        if engine is None:
            return False, "GPU 深度引擎未注册", None
        capability = engine.capability()
        if not capability.available:
            return False, capability.availability_note or "GPU 深度引擎尚未安装", None
        try:
            profile = await engine.profile(DepthControlPreset.BALANCED)
        except Exception as exc:
            return False, str(exc), None
        return True, "已检测到可用的 NVIDIA CUDA 深度环境", profile

    def cpu_available(self) -> tuple[bool, str]:
        engine = self.registry.get(CPU_ENGINE_ID)
        if engine is None:
            return False, "CPU 深度引擎未注册"
        capability = engine.capability()
        return capability.available, capability.availability_note

    async def resolve(
        self,
        *,
        preference: DepthExecutionPreference,
        legacy_preset: DepthControlPreset = DepthControlPreset.AUTO,
    ) -> DepthGenerationProfile:
        effective_preference = preference
        if legacy_preset == DepthControlPreset.CPU_FAST:
            effective_preference = DepthExecutionPreference.CPU
        elif legacy_preset in {DepthControlPreset.BALANCED, DepthControlPreset.QUALITY}:
            effective_preference = DepthExecutionPreference.GPU

        if effective_preference == DepthExecutionPreference.CPU:
            return await self._cpu_profile(
                effective_preference,
                reason="已按设置强制使用 CPU 深度引擎",
            )

        if effective_preference == DepthExecutionPreference.GPU:
            available, note, profile = await self.gpu_available()
            if not available or profile is None:
                raise DepthEngineSelectionError("depth_gpu_unavailable", note)
            requested = (
                DepthControlPreset.QUALITY
                if legacy_preset == DepthControlPreset.QUALITY
                else DepthControlPreset.BALANCED
            )
            engine = self.registry.require(GPU_ENGINE_ID)
            selected = await engine.profile(requested)
            return replace(
                selected,
                engine_id=GPU_ENGINE_ID,
                selection_reason="已按设置强制使用 NVIDIA CUDA 深度引擎",
                requested_execution_preference=effective_preference,
            )

        available, _, profile = await self.gpu_available()
        if available and profile is not None:
            return replace(
                profile,
                engine_id=GPU_ENGINE_ID,
                selection_reason="自动检测到可用的 NVIDIA CUDA，已选择 GPU 时序深度引擎",
                requested_execution_preference=DepthExecutionPreference.AUTO,
            )
        return await self._cpu_profile(
            DepthExecutionPreference.AUTO,
            reason="未检测到可用的 NVIDIA CUDA，已自动选择 CPU ONNX 深度引擎",
        )

    async def _cpu_profile(
        self,
        preference: DepthExecutionPreference,
        *,
        reason: str,
    ) -> DepthGenerationProfile:
        engine = self.registry.require(CPU_ENGINE_ID)
        capability = engine.capability()
        if not capability.available:
            raise DepthEngineSelectionError(
                "depth_cpu_engine_unavailable",
                capability.availability_note or "CPU 深度引擎尚未安装",
            )
        profile = await engine.profile(DepthControlPreset.CPU_FAST)
        return replace(
            profile,
            engine_id=CPU_ENGINE_ID,
            selection_reason=reason,
            requested_execution_preference=preference,
        )
