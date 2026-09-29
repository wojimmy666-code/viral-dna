from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import VideoGenerationError


@dataclass(frozen=True, slots=True)
class VideoProviderFailure:
    """Safe, provider-neutral failure details for persistence and user interfaces."""

    code: str
    category: str
    title: str
    message: str
    suggested_action: str
    retryable: bool = False
    provider_code: str | None = None
    technical_message: str | None = None


_PROVIDER_LABELS = {
    "bailian": "百炼",
    "volc_ark": "火山方舟",
    "minimax": "MiniMax",
    "gemini_omni": "Gemini Omni",
}

_LOCAL_CODES = {
    "provider_reference_limit", "checksum_mismatch", "media_source_missing",
    "media_source_outside_workspace", "production_budget_exceeded",
    "video_api_key_missing", "video_generation_not_configured",
    "video_remote_provider_not_configured", "video_adapter_not_configured",
    "video_resolution_unsupported", "video_duration_unsupported",
    "video_candidate_count_unsupported", "video_native_audio_unsupported",
    "video_text_to_video_unsupported", "video_unknown_cost_confirmation_required",
    "video_execution_mode_invalid", "video_local_tool_not_supported",
    "video_provider_task_input_changed",
}
_LOCAL_PREFIXES = (
    "video_managed_", "video_reference_", "video_auxiliary_", "video_identity_",
    "video_real_person_", "video_inherited_", "depth_control_", "spatial_reference_",
    "style_reference_", "approved_image_", "oss_", "media_staging_", "public_media_", "video_public_media_",
)


def is_local_video_failure(code: str | None) -> bool:
    value = str(code or "")
    return value in _LOCAL_CODES or value.startswith(_LOCAL_PREFIXES)


def video_failure_location(*, code, provider_code=None, provider_task_id=None, provider_tasks=()):
    """Derive provenance from evidence, including old runs, without rewriting history.

    A task row is created BEFORE HTTP submission. Its existence (or a missing
    remote ID) alone cannot prove that submission succeeded or never happened.
    """
    submitted = bool(provider_task_id or any(t.provider_task_id for t in provider_tasks))
    state = "submitted" if submitted else "unknown"
    if is_local_video_failure(code):
        return dict(error_origin="system", error_stage="input_validation",
                    provider_submission_state=state if submitted else "not_submitted")
    if str(code or "").startswith("generated_video_") or code in {
        "video_provider_download_failed", "video_candidate_count_mismatch", "video_provider_output_write_failed",
    }:
        return dict(error_origin="system", error_stage="result_handling", provider_submission_state=state)
    if code in {"video_provider_unavailable", "video_provider_submission_ambiguous", "video_provider_task_timeout"}:
        return dict(error_origin="provider" if provider_code else "transport",
                    error_stage="result_query" if submitted else "submission",
                    provider_submission_state=state)
    if submitted or provider_code or code in {
        "video_provider_auth_invalid", "video_provider_balance_insufficient",
        "video_provider_inference_limit", "video_provider_rate_limited", "video_provider_content_rejected",
    }:
        return dict(error_origin="provider", error_stage="generation" if submitted else "submission",
                    provider_submission_state="submitted" if submitted else "rejected")
    return dict(error_origin="unknown", error_stage="submission" if provider_tasks else "unknown", provider_submission_state="unknown")


def sanitize_provider_error_message(value: str | None) -> str | None:
    """Keep diagnostics useful while removing common credential/account disclosures."""

    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"(?i)account\s*\[[^\]]+\]", "account [已隐藏]", text)
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [已隐藏]", text)
    text = re.sub(r"(?i)\b(?:sk|ak)-[a-z0-9_-]{8,}\b", "[密钥已隐藏]", text)
    text = re.sub(r"(?i)(api[_-]?key|access[_-]?token|signature|secret[_-]?key)([=:\s]+)[^\s&;,]+", r"\1\2[已隐藏]", text)
    return text[:4000]


def classify_video_provider_failure(
    *,
    provider: str | None,
    code: str | None,
    message: str | None,
    retryable: bool = False,
    provider_code: str | None = None,
) -> VideoProviderFailure:
    """Translate provider-specific failures into stable product-facing semantics.

    Provider adapters should still recognize their own exact codes first. This
    fallback guarantees that legacy runs and generic transport failures receive
    consistent Chinese copy and recovery actions.
    """

    normalized_code = str(code or "video_provider_request_failed").strip()
    raw_message = str(message or "").strip()
    raw_code = str(provider_code or "").strip() or None
    lowered = f"{normalized_code} {raw_code or ''} {raw_message}".casefold()

    if is_local_video_failure(normalized_code) and not normalized_code.startswith((
        "oss_", "media_staging_", "public_media_",
    )):
        reason = sanitize_provider_error_message(raw_message) or "生成输入未通过校验，请核对模型参数与所选参考。"
        if normalized_code == "video_managed_identity_required":
            reason = (
                "此任务被本地旧托管演员规则拦截：未绑定当前 Provider 的托管演员。"
                "如果使用已采用分镜图，请刷新后从当前输入重新生成；"
                "只有明确使用托管演员路径时才需要绑定演员。"
            )
        configuration = normalized_code.endswith(("not_configured", "key_missing"))
        return VideoProviderFailure(
            code=normalized_code, category="configuration" if configuration else "validation",
            title="本地模型配置未完成" if configuration else "系统输入校验未通过",
            message=reason,
            suggested_action="open_model_settings" if configuration else "review_references",
            technical_message=sanitize_provider_error_message(raw_message),
        )

    if normalized_code in {
        "media_staging_not_configured",
        "oss_credentials_missing",
        "oss_ecs_role_unavailable",
    }:
        return VideoProviderFailure(
            code=normalized_code,
            category="media_staging",
            title="媒体暂存服务尚未配置",
            message=(
                "当前模型需要可访问的 HTTPS 媒体地址。"
                "请在平台设置中完成 OSS 媒体暂存配置并通过连接测试。"
            ),
            suggested_action="open_model_settings",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code in {
        "media_source_missing",
        "media_source_outside_workspace",
        "checksum_mismatch",
    }:
        return VideoProviderFailure(
            code=normalized_code,
            category="generation_input",
            title="生成输入不可用",
            message="深度视频或参考媒体已丢失、已变更或不属于当前工作区，请重新生成或重新选择。",
            suggested_action="review_references",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code.startswith(("oss_", "media_staging_", "public_media_")):
        return VideoProviderFailure(
            code=normalized_code,
            category="media_staging",
            title="媒体暂存未完成",
            message="上传媒体或签发临时访问地址失败，请检查 OSS 配置和网络后重试。",
            suggested_action="retry",
            retryable=True,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    provider_label = _PROVIDER_LABELS.get(str(provider or ""), "视频模型服务")

    if (
        normalized_code == "video_provider_inference_limit"
        or "setlimitexceeded" in lowered
        or "safe experience mode" in lowered
        or "安心体验模式" in lowered
        or "安全体验模式" in lowered
    ):
        return VideoProviderFailure(
            code="video_provider_inference_limit",
            category="inference_limit",
            title=f"{provider_label}模型已暂停生成",
            message=(
                "该模型已达到 Provider 设置的推理上限。"
                "请调整模型额度后再试，或切换其他视频模型。"
            ),
            suggested_action="open_model_settings",
            retryable=False,
            provider_code=raw_code
            or (
                normalized_code
                if normalized_code != "video_provider_inference_limit"
                else None
            ),
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code == "video_provider_auth_invalid" or any(
        token in lowered for token in ("invalid api key", "unauthorized", "authentication")
    ):
        return VideoProviderFailure(
            code="video_provider_auth_invalid",
            category="authentication",
            title=f"{provider_label}认证失败",
            message="当前 API Key 无效、已失效或与所选区域不匹配。请重新配置并校验。",
            suggested_action="open_model_settings",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code == "video_provider_balance_insufficient" or any(
        token in lowered
        for token in (
            "accountoverdue",
            "insufficient balance",
            "arrearage",
            "quotaexhausted",
            "quota exhausted",
        )
    ):
        return VideoProviderFailure(
            code="video_provider_balance_insufficient",
            category="balance",
            title=f"{provider_label}余额或配额不足",
            message="请充值对应 Provider 账户，或切换其他已配置的视频模型。",
            suggested_action="open_model_settings",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code == "video_provider_rate_limited" or any(
        token in lowered for token in ("rate limit", "ratelimit", "too many requests")
    ):
        return VideoProviderFailure(
            code="video_provider_rate_limited",
            category="rate_limit",
            title=f"{provider_label}请求过于频繁",
            message="Provider 暂时限制了请求频率。请稍后重试。",
            suggested_action="retry",
            retryable=True,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if (
        normalized_code == "video_provider_task_timeout"
        or "timeout" in lowered
        or "超时" in lowered
    ):
        return VideoProviderFailure(
            code="video_provider_task_timeout",
            category="timeout",
            title="等待视频生成结果超时",
            message="尚未确认 Provider 的最终状态。请先查询已有任务或核对 Provider 控制台；不要直接重新生成，以免重复提交。",
            suggested_action="inspect_details",
            retryable=True,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if provider == "volc_ark" and any(
        token in lowered
        for token in (
            "inputimagesensitivecontentdetected.privacyinformation",
            "privacyinformation",
            "may contain real person",
        )
    ):
        return VideoProviderFailure(
            code="video_provider_content_rejected",
            category="person_reference_policy",
            title="Provider 人像审核未通过",
            message=(
                "Seedance 将参考图判定为可能包含真人身份；AI 生成的人像也可能触发此审核。"
                "请使用 Provider 支持且已授权的人像素材或托管演员路径，或更换支持该输入的模型。"
                "仅绑定演员并继续提交被拒绝的原图不能解决审核问题。"
            ),
            suggested_action="review_person_references",
            retryable=False,
            provider_code=raw_code or normalized_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if any(
        token in lowered
        for token in ("content policy", "content moderation", "sensitive", "risk", "审核")
    ):
        return VideoProviderFailure(
            code="video_provider_content_rejected",
            category="content_policy",
            title="提示词或参考画面未通过审核",
            message="请调整可能涉及敏感内容的提示词或参考图片后重新生成。",
            suggested_action="edit_prompt",
            retryable=False,
            provider_code=raw_code or normalized_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code in {
        "video_resolution_unsupported",
        "video_candidate_count_unsupported",
        "video_duration_unsupported",
        "video_reference_count_unsupported",
    } or any(
        token in lowered
        for token in ("invalid parameter", "invalidargument", "parameter invalid")
    ):
        return VideoProviderFailure(
            code=normalized_code,
            category="validation",
            title="当前生成参数不受支持",
            message=sanitize_provider_error_message(raw_message) or "请调整模型、分辨率、时长或参考图数量后重试。",
            suggested_action="review_parameters",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if normalized_code in {
        "video_api_key_missing",
        "video_generation_not_configured",
        "video_remote_provider_not_configured",
    }:
        return VideoProviderFailure(
            code=normalized_code,
            category="configuration",
            title="视频生成模型尚未配置完成",
            message=sanitize_provider_error_message(raw_message) or "请到模型与设置中完成配置和校验。",
            suggested_action="open_model_settings",
            retryable=False,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    if (
        normalized_code in {"video_provider_unavailable", "video_provider_download_failed"}
        or retryable
    ):
        return VideoProviderFailure(
            code=normalized_code,
            category="provider_unavailable",
            title=f"暂时无法连接{provider_label}",
            message="通信未完成，请先核对已有任务状态及网络，再决定是否重新生成，避免重复提交。",
            suggested_action="inspect_details",
            retryable=True,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    return VideoProviderFailure(
        code=normalized_code,
        category="unknown",
        title="视频生成未完成",
        message=sanitize_provider_error_message(raw_message) or "未获得具体失败原因，请查看技术详情及任务编号；目前不能确认故障来源。",
        suggested_action="inspect_details",
        retryable=False,
        provider_code=raw_code,
        technical_message=sanitize_provider_error_message(raw_message),
    )


class VideoProviderError(VideoGenerationError):
    """Normalized error raised by a concrete remote video provider."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        raw_code: str | int | None = None,
        provider: str | None = None,
        failure: VideoProviderFailure | None = None,
    ) -> None:
        provider_code = str(raw_code) if raw_code is not None else None
        details = failure or classify_video_provider_failure(
            provider=provider,
            code=code,
            message=message,
            retryable=retryable,
            provider_code=provider_code,
        )
        super().__init__(
            status_code,
            details.code,
            details.message,
            retryable=details.retryable,
            provider_code=details.provider_code,
            error_category=details.category,
            user_title=details.title,
            suggested_action=details.suggested_action,
            technical_message=details.technical_message,
        )
        self.raw_code = details.provider_code


def http_error_status(status_code: int) -> tuple[int, str, bool]:
    if status_code in {401, 403}:
        return 401, "video_provider_auth_invalid", False
    if status_code == 402:
        return 402, "video_provider_balance_insufficient", False
    if status_code == 429:
        return 429, "video_provider_rate_limited", True
    if status_code >= 500:
        return 503, "video_provider_unavailable", True
    return 502, "video_provider_request_failed", False
