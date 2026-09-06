"""Resolve a Skill's explicit image choice through the existing image adapters."""

from copy import copy
from dataclasses import dataclass

from ..models import GenerationCostSource, ImageGenerationCapability
from .catalog import ImageModelCatalogError, load_image_model_catalog
from .codex_local import local_tool_proxy_environment_url
from .contracts import ImageGenerationError
from .local_tool import detect_local_tool
from .settings import ImageGenerationSettingsService

LOCAL_UNCERTAIN_IMAGE_ERRORS = {
    "local_tool_timeout",
    "local_tool_failed",
    "local_tool_invalid_json",
    "local_tool_output_missing",
    "local_tool_output_size",
    "local_tool_output_hash",
    "local_tool_output_image",
    "local_tool_output_format",
    "local_tool_output_type",
    "local_tool_output_dimensions",
    "local_tool_result_missing",
    "local_tool_result_invalid",
    "local_tool_result_failed",
    "local_tool_result_protocol",
    "local_tool_candidates_missing",
    "local_tool_candidates_excess",
    "local_tool_candidate_invalid",
    "local_tool_cost_invalid",
    "look_test_timeout",
    "look_test_cancelled",
    "look_test_item_failed",
    "look_test_in_progress",
}


@dataclass(frozen=True)
class SkillImageSelection:
    provider: str
    label: str
    capabilities: ImageGenerationCapability
    unit_cost_micros: int | None
    tool_snapshot: dict


async def resolve_skill_image_selection(contract, settings_service=None) -> SkillImageSelection:
    if contract.image_provider_connection_id != "local_tool":
        option = load_image_model_catalog().option(contract.image_model_id)
        if option.provider != contract.image_provider_connection_id:
            raise ImageModelCatalogError("图片模型与项目锁定的 Provider 不一致，请重新选择模型")
        return SkillImageSelection(
            option.provider, option.label, option.capabilities, option.unit_cost_micros, {}
        )
    if contract.image_model_id != "local_tool":
        raise ImageModelCatalogError("本机 ImageGen 必须使用已有本机工具入口")
    settings = (settings_service or ImageGenerationSettingsService()).get()
    if not settings.local_executable_path:
        raise ImageModelCatalogError("本机 ImageGen 尚未配置，请先在图片生成设置中配置本机工具")
    cap = settings.local_capabilities
    tool_id, tool_version = settings.local_tool_id, settings.local_tool_version
    if cap is None:
        try:
            detected = await detect_local_tool(
                settings.local_executable_path,
                settings.local_fixed_args,
                timeout_seconds=min(30, settings.local_timeout_seconds),
                expected_protocol=settings.local_protocol_version,
                proxy_url=local_tool_proxy_environment_url(
                    settings.local_adapter_id,
                    settings.local_proxy_mode,
                    settings.local_proxy_effective_url,
                    settings.local_proxy_source,
                ),
            )
        except ImageGenerationError as exc:
            raise ImageModelCatalogError(str(exc)) from exc
        cap, tool_id, tool_version = detected.capability, detected.tool_id, detected.tool_version
    frozen = getattr(contract, "image_tool_snapshot", {})
    if frozen and (
        frozen.get("tool_id") != tool_id or frozen.get("adapter_id") != settings.local_adapter_id
    ):
        raise ImageModelCatalogError("本机图片工具已改变，请重新确认项目图片生成契约")
    cost = (
        settings.local_unit_cost_micros
        if settings.local_cost_source == GenerationCostSource.CONFIGURED_RATE
        else None
    )
    if settings.local_cost_source == GenerationCostSource.UNMETERED:
        cost = 0
    return SkillImageSelection(
        "local_tool",
        "image-2（本机 ImageGen）",
        cap,
        cost,
        {
            "tool_id": tool_id,
            "tool_version": tool_version,
            "adapter_id": settings.local_adapter_id,
            "orchestration_model": settings.local_model,
            "capabilities": cap.model_dump(mode="json"),
        },
    )


def permits_unknown_local_image_cost(contract) -> bool:
    return bool(
        contract.image_provider_connection_id == "local_tool"
        and contract.allow_unknown_local_image_cost
        and contract.budget_limit_micros is None
        and contract.automation_mode == "guided"
    )


async def resolve_skill_image_request(
    defaults, payload, settings_service=None, *, stage="shot_image"
):
    """Resolve once when queuing; never mutate the project's immutable defaults."""
    alias = payload.model_alias or defaults.image_model_id
    provider = (
        "local_tool" if alias == "local_tool" else load_image_model_catalog().option(alias).provider
    )
    mode = "local_tool" if provider == "local_tool" else "remote_api"
    if payload.execution_mode is not None and payload.execution_mode != mode:
        raise ImageModelCatalogError("图片执行方式与本次选择的模型不一致")
    count = payload.candidate_count or defaults.candidate_count_by_stage.get(stage, 1)
    updates = {
        "image_model_id": alias,
        "image_provider_connection_id": provider,
        "image_width": payload.width if payload.width is not None else defaults.image_width,
        "image_height": payload.height if payload.height is not None else defaults.image_height,
        "image_tool_snapshot": payload.image_tool_snapshot,
        "candidate_count_by_stage": {**defaults.candidate_count_by_stage, stage: count},
        "allow_unknown_local_image_cost": bool(
            payload.allow_unknown_cost or getattr(defaults, "allow_unknown_local_image_cost", False)
        ),
    }
    if hasattr(defaults, "model_copy"):
        effective = defaults.model_copy(update=updates)
    else:
        effective = copy(defaults)
        for key, value in updates.items():
            setattr(effective, key, value)
    selection = await resolve_skill_image_selection(effective, settings_service)
    cap = selection.capabilities
    if (
        effective.image_width > cap.maximum_width
        or effective.image_height > cap.maximum_height
        or effective.image_width * effective.image_height > cap.maximum_pixels
    ):
        raise ImageModelCatalogError("所选模型不支持本次图片分辨率，请重新选择；不会自动降档")
    if count > cap.max_candidates:
        raise ImageModelCatalogError("本次图片数量超过所选模型上限")
    if selection.unit_cost_micros is None and not permits_unknown_local_image_cost(effective):
        raise ImageModelCatalogError(
            "本机图片费用未知，请先确认费用；硬预算或全自动模式下不能执行未知费用任务"
        )
    return effective, selection
