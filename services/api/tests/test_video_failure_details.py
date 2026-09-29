"""Failures report evidence, not the assumption that every error is a provider error."""
from types import SimpleNamespace

import pytest
from test_generation_jobs import _run
from test_image_batches import environment

from viral_dna_api.models import GenerationKind, ProductionRunStatus
from viral_dna_api.video_generation.errors import classify_video_provider_failure, video_failure_location


@pytest.mark.parametrize("code,message", [
    ("video_managed_identity_required", "请先绑定当前 Provider 的托管虚拟演员"),
    ("provider_reference_limit", "最多 9 项参考，本次需要 10 项"),
    ("video_reference_selection_changed", "所选图片无法完整保留"),
    ("video_resolution_unsupported", "当前模型不支持 4K"),
    ("depth_control_not_ready", "深度视频未准备好"),
    ("media_staging_failed", "media upload timeout"),
])
def test_local_failures_keep_specific_reason_and_never_blame_provider(code, message):
    failure = classify_video_provider_failure(provider="volc_ark", code=code, message=message)
    assert failure.category != "unknown"
    assert failure.technical_message == message
    assert "Provider 没有完成" not in failure.message
    assert video_failure_location(code=failure.code) == dict(
        error_origin="system", error_stage="input_validation", provider_submission_state="not_submitted")


@pytest.mark.parametrize("code,provider_code,task_id,expected", [
    ("video_provider_content_rejected", "PrivacyInformation", None, ("provider", "submission", "rejected")),
    ("video_provider_content_rejected", "PrivacyInformation", "task1", ("provider", "generation", "submitted")),
    ("video_provider_unavailable", None, None, ("transport", "submission", "unknown")),
    ("video_provider_task_timeout", None, "task1", ("transport", "result_query", "submitted")),
    ("video_provider_submission_ambiguous", None, None, ("transport", "submission", "unknown")),
    ("generated_video_missing", None, "task1", ("system", "result_handling", "submitted")),
    ("video_provider_download_failed", None, "task1", ("system", "result_handling", "submitted")),
    ("unidentified_failure", None, None, ("unknown", "unknown", "unknown")),
])
def test_error_source_and_submission_state_require_evidence(code, provider_code, task_id, expected):
    location = video_failure_location(code=code, provider_code=provider_code, provider_task_id=task_id,
                                      provider_tasks=[SimpleNamespace(provider_task_id=task_id)] if task_id else [])
    assert tuple(location.values()) == expected


def test_partial_submission_never_claims_entire_run_was_not_sent():
    location = video_failure_location(code="video_reference_selection_changed",
        provider_tasks=[SimpleNamespace(provider_task_id="already-submitted")])
    assert location["provider_submission_state"] == "submitted"


@pytest.mark.asyncio
async def test_historical_local_error_projection_is_corrected_without_rewriting_database(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    run = _run(env.project, env.shots[0], ProductionRunStatus.FAILED).model_copy(update={
        "kind": GenerationKind.VIDEO, "provider": "volc_ark", "model_alias": "seedance_2_0",
        "error_code": "video_managed_identity_required", "error_category": "unknown",
        "error_title": "视频生成未完成", "error_action": "inspect_details",
        "error_message": "Provider 没有完成本次生成。请查看技术详情，调整设置后再试。",
        "error_technical_message": "请先绑定当前 Provider 的托管虚拟演员",
        "actual_cost_known": False,
    })
    await env.store.save_generation_run(run)
    response = await env.service._run_response(run)
    assert response.error_origin == "system"
    assert response.error_stage == "input_validation"
    assert response.provider_submission_state == "not_submitted"
    assert response.error_category == "validation"
    assert response.error_title == "系统输入校验未通过"
    assert "旧托管演员规则" in response.error_message
    assert response.error_action == "review_references"
    assert response.error_code == "video_managed_identity_required"
    assert not response.actual_cost_known  # presentation must not invent a bill
    assert (await env.store.get_generation_run(run.id)).model_dump() == run.model_dump()


def test_unknown_error_keeps_sanitized_original_reason():
    failure = classify_video_provider_failure(provider="volc_ark", code="unexpected_failure",
        message="Unexpected backend status; Bearer secret-token; account [123456]", provider_code=None)
    assert "Unexpected backend status" in failure.message
    assert "secret-token" not in failure.message and "123456" not in failure.message
    assert failure.provider_code is None
