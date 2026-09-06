from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_generation_jobs import _workspace
from test_image_batches import environment, finish, until
from test_skill_look_test import ParallelImageGateway, seed_look_test

from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.image_generation.catalog import ImageModelCatalogError
from viral_dna_api.image_generation.gateway import ImageGenerationGatewayError
from viral_dna_api.image_generation.selection import resolve_skill_image_selection
from viral_dna_api.models import (
    ImageGenerationCapability,
    ImageGenerationCreate,
    ImageGenerationSettingsResponse,
)
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.skill_workflow.contracts import LookTestGenerationRequest
from viral_dna_api.skill_workflow.service import SkillWorkflowService


def local_settings(*, cost=None, concurrency=2):
    return ImageGenerationSettingsResponse(
        enabled=True,
        execution_mode="local_tool",
        remote_base_url="https://dashscope.aliyuncs.com/api/v1",
        catalog_version="test",
        pricing_version="test",
        models=[],
        local_executable_path="configured-tool",
        local_model="gpt-5.6-sol",
        local_tool_id="openai-codex-imagegen",
        local_tool_version="test-v1",
        local_adapter_id="codex_imagegen_v1",
        local_concurrency=concurrency,
        local_cost_source="unknown" if cost is None else "configured_rate",
        local_unit_cost_micros=cost,
        local_capabilities=ImageGenerationCapability(text_to_image=True, max_reference_images=5),
    )


async def local_environment(tmp_path, monkeypatch, count=5, cost=None):
    env = await environment(tmp_path, monkeypatch, count=count)
    env.gateway.settings_service = SimpleNamespace(get=lambda: local_settings(cost=cost))
    contract = env.service._skill_run_contract.return_value
    contract.image_model_id = contract.image_provider_connection_id = "local_tool"
    contract.allow_unknown_local_image_cost = True
    contract.image_width, contract.image_height = 1080, 1920
    return env


@pytest.mark.asyncio
async def test_local_batch_uses_existing_gateway_and_device_concurrency(tmp_path, monkeypatch):
    env = await local_environment(tmp_path, monkeypatch)
    batch = await env.batch.create(
        env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    )
    try:
        await until(lambda: len(env.gateway.calls) == 2)
        assert batch.execution_mode == "local_tool"
        assert batch.model_label == "image-2（本机 ImageGen）"
        assert batch.estimated_cost_micros is None
        assert batch.concurrency_limit == 2
    finally:
        result = await finish(env, batch)
    assert result.status == "completed"
    assert env.gateway.max_active == 2
    assert len(env.gateway.calls) == 5
    assert all(call[1]["execution_mode"] == "local_tool" for call in env.gateway.calls)
    assert all(call[1]["model_alias"] == "local_tool" for call in env.gateway.calls)
    assert all(call[1]["allow_unknown_cost"] for call in env.gateway.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("hard_budget,accepted", [(None, False), (1_000_000, True)])
async def test_local_unknown_cost_cannot_bypass_confirmation_or_hard_budget(
    tmp_path, monkeypatch, hard_budget, accepted
):
    env = await local_environment(tmp_path, monkeypatch, count=1)
    contract = env.service._skill_run_contract.return_value
    contract.budget_limit_micros, contract.allow_unknown_local_image_cost = hard_budget, accepted
    with pytest.raises(ProductionServiceError, match="费用未知"):
        await env.batch.preview(
            env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
        )
    assert not env.gateway.calls


@pytest.mark.asyncio
async def test_local_single_shot_rejects_remote_route_and_unsupported_resolution(
    tmp_path, monkeypatch
):
    env = await local_environment(tmp_path, monkeypatch, count=1, cost=100)
    payload = ImageGenerationCreate(
        expected_revision_id=env.project.current_revision_id,
        candidate_count=1,
        model_alias="local_tool",
        execution_mode="remote_api",
    )
    with pytest.raises(ProductionServiceError, match="执行方式"):
        await env.service._validate_skill_image_contract(env.project, payload)
    env.service._skill_run_contract.return_value.image_width = 3840
    with pytest.raises(ProductionServiceError, match="分辨率"):
        await env.service._validate_skill_image_contract(
            env.project, payload.model_copy(update={"execution_mode": "local_tool"})
        )


@pytest.mark.asyncio
async def test_tool_snapshot_does_not_confuse_orchestration_with_image_model(tmp_path, monkeypatch):
    env = await local_environment(tmp_path, monkeypatch)
    contract = env.service._skill_run_contract.return_value
    selection = await resolve_skill_image_selection(contract, env.gateway.settings_service)
    assert selection.tool_snapshot["orchestration_model"] == "gpt-5.6-sol"
    assert selection.tool_snapshot["tool_id"] == "openai-codex-imagegen"
    contract.image_tool_snapshot = {"tool_id": "changed-tool", "adapter_id": "codex_imagegen_v1"}
    with pytest.raises(ImageModelCatalogError, match="工具已改变"):
        await resolve_skill_image_selection(contract, env.gateway.settings_service)


@pytest.mark.asyncio
async def test_local_look_test_reuses_local_gateway_and_preserves_candidates(tmp_path, monkeypatch):
    gateway = ParallelImageGateway()
    gateway.settings_service = SimpleNamespace(get=lambda: local_settings())
    gateway.workspace = _workspace(tmp_path, monkeypatch)
    store, service, _, run, _ = await seed_look_test(gateway)
    contract = await store.get_run_contract_revision(run.run_contract_revision_id)
    await store.save_run_contract_revision(
        contract.model_copy(
            update={
                "image_model_id": "local_tool",
                "image_provider_connection_id": "local_tool",
                "allow_unknown_local_image_cost": True,
            }
        )
    )
    result = await service.generate_look_test(run.id)
    assert result.execution_status == "succeeded"
    assert len(result.candidate_ids) == 4
    assert gateway.execution_modes == ["local_tool", "local_tool"]
    assert gateway.model_aliases == ["local_tool", "local_tool"]
    await service.generate_look_test(run.id)
    assert len(gateway.execution_modes) == 2


@pytest.mark.asyncio
async def test_interrupted_local_look_test_closes_checkpoint_and_recovers_before_retry(
    tmp_path, monkeypatch
):
    gateway = ParallelImageGateway()
    gateway.settings_service = SimpleNamespace(get=lambda: local_settings())
    gateway.workspace = _workspace(tmp_path, monkeypatch)
    gateway.generate = AsyncMock(side_effect=RuntimeError("模拟本机调用中断"))
    gateway.recover_local_tool_output = AsyncMock(
        side_effect=ImageGenerationGatewayError(409, "local_tool_output_missing", "尚无匹配输出")
    )
    store, service, _, run, _ = await seed_look_test(gateway)
    contract = await store.get_run_contract_revision(run.run_contract_revision_id)
    await store.save_run_contract_revision(
        contract.model_copy(
            update={
                "image_model_id": "local_tool",
                "image_provider_connection_id": "local_tool",
                "allow_unknown_local_image_cost": True,
            }
        )
    )
    result = await service.generate_look_test(run.id)
    assert result.execution_status == "failed"
    assert len(store.generation_runs) == 2
    assert all(item.status == "failed" for item in store.generation_runs.values())
    assert all(
        item.error_code == "look_test_item_failed" for item in store.generation_runs.values()
    )
    recovered = await service.generate_look_test(run.id)
    assert recovered.execution_status == "blocked"
    assert gateway.recover_local_tool_output.await_count == 2
    assert gateway.generate.await_count == 2


@pytest.mark.asyncio
async def test_local_batch_recovery_never_starts_a_new_generation(tmp_path, monkeypatch):
    env = await local_environment(tmp_path, monkeypatch, count=1)
    run = SimpleNamespace(id=env.project.id, execution_mode="local_tool", status="failed")
    env.service.recover_image_generation_output = AsyncMock(
        side_effect=ProductionServiceError(
            409, "generation_output_recovery_unavailable", "没有匹配输出"
        )
    )
    assert await env.batch.recover_local_output(run) is run
    env.service.recover_image_generation_output.assert_awaited_once_with(run.id)
    assert not env.gateway.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("model_alias", ["local_tool", "qwen_image_2_pro"])
async def test_generation_overrides_default_without_changing_contract(
    tmp_path, monkeypatch, model_alias
):
    env = await local_environment(tmp_path, monkeypatch, count=1, cost=100)
    contract = env.service._skill_run_contract.return_value
    contract.image_model_id = "qwen_image_2_pro" if model_alias == "local_tool" else "local_tool"
    contract.image_provider_connection_id = (
        "dashscope" if model_alias == "local_tool" else "local_tool"
    )
    original = vars(contract).copy()
    request = ImageBatchRequest(
        expected_revision_id=env.project.current_revision_id,
        model_alias=model_alias,
        width=720,
        height=1280,
        candidate_count=2,
    )
    resolved = await env.service._validate_skill_image_contract(
        env.project,
        ImageGenerationCreate(
            expected_revision_id=env.project.current_revision_id,
            model_alias=model_alias,
            width=720,
            height=1280,
            candidate_count=2,
        ),
    )
    assert (resolved.width, resolved.height, resolved.candidate_count) == (720, 1280, 2)
    assert resolved.execution_mode == (
        "local_tool" if model_alias == "local_tool" else "remote_api"
    )
    batch = await env.batch.create(env.project.id, request)
    try:
        result = await finish(env, batch)
        assert result.status == "completed", result.model_dump()
        assert (result.model_alias, result.width, result.height, result.candidate_count) == (
            model_alias,
            720,
            1280,
            2,
        )
        assert env.gateway.calls[0][1]["model_alias"] == model_alias
        assert env.gateway.calls[0][1]["candidate_count"] == 2
        assert vars(contract) == original
    finally:
        await env.service.shutdown_generation_runs()


@pytest.mark.asyncio
async def test_look_test_override_preserves_history_and_is_idempotent(tmp_path, monkeypatch):
    gateway = ParallelImageGateway()
    gateway.settings_service = SimpleNamespace(get=lambda: local_settings(cost=100))
    gateway.workspace = _workspace(tmp_path, monkeypatch)
    store, service, _, run, _ = await seed_look_test(gateway)
    first = await service.generate_look_test(run.id)
    contract = await store.get_run_contract_revision(run.run_contract_revision_id)
    original = contract.model_dump()
    options = LookTestGenerationRequest(
        request_id=uuid4(), model_alias="local_tool", width=720, height=1280, candidate_count=1
    )
    started = await service.start_look_test_generation(run.id, options)
    task = service._look_test_tasks.get(run.id)
    second = await task if task else started
    assert second.execution_status == "succeeded"
    assert second.id != first.id
    assert set(first.candidate_ids) < set(second.candidate_ids)
    assert len(second.candidate_ids) == 6
    assert second.generation_parameters["model_alias"] == "local_tool"
    assert (second.output_width, second.output_height) == (720, 1280)
    assert gateway.execution_modes == ["remote_api", "remote_api", "local_tool", "local_tool"]
    repeated = await service.start_look_test_generation(run.id, options)
    assert repeated.id == second.id
    assert len(gateway.execution_modes) == 4
    assert (
        await store.get_run_contract_revision(run.run_contract_revision_id)
    ).model_dump() == original


@pytest.mark.asyncio
async def test_full_auto_reuses_the_same_local_batch_queue(tmp_path, monkeypatch):
    env = await local_environment(tmp_path, monkeypatch, count=4, cost=100)
    env.gateway.release.set()
    service = SimpleNamespace(
        production_service=env.service,
        _require_skill_project=AsyncMock(
            return_value=SimpleNamespace(
                source_binding=SimpleNamespace(production_project_id=env.project.id),
            )
        ),
    )
    await SkillWorkflowService._full_auto_generate_images(
        service,
        SimpleNamespace(project_id=env.project.id),
        env.service._skill_run_contract.return_value,
    )
    assert (await env.batch.latest(env.project.id)).status == "completed"
    assert len(env.gateway.calls) == 4
    assert all(call[1]["execution_mode"] == "local_tool" for call in env.gateway.calls)
