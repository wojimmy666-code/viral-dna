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
}


def sanitize_provider_error_message(value: str | None) -> str | None:
    """Keep diagnostics useful while removing common credential/account disclosures."""

    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"(?i)account\s*\[[^\]]+\]", "account [已隐藏]", text)
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [已隐藏]", text)
    text = re.sub(r"(?i)\b(?:sk|ak)-[a-z0-9_-]{8,}\b", "[密钥已隐藏]", text)
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
            message="上游任务可能仍在运行。稍后重试查询不会重新提交，也不会重复计费。",
            suggested_action="retry",
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
            title="检测到未托管真人参考",
            message=(
                "Seedance 仍检测到可能包含真人身份的输入。请确认已绑定 Provider 托管演员，"
                "为限制真人参考的模型绑定 Provider 托管演员，并仅提交全场景深度控制与"
                "已授权外观资产；不要重试提交原始真人素材。"
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
            message=raw_message or "请调整模型、分辨率、时长或参考图数量后重试。",
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
            message=raw_message or "请到模型与设置中完成配置和校验。",
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
            message="Provider 服务或网络暂时不可用，请稍后重试。",
            suggested_action="retry",
            retryable=True,
            provider_code=raw_code,
            technical_message=sanitize_provider_error_message(raw_message),
        )
    return VideoProviderFailure(
        code=normalized_code,
        category="unknown",
        title="视频生成未完成",
        message="Provider 没有完成本次生成。请查看技术详情，调整设置后再试。",
        suggested_action="inspect_details",
        retryable=False,
        provider_code=raw_code
        or (normalized_code if not normalized_code.startswith("video_") else None),
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
