"""Actionable messages without exposing model output or credential details."""

from ..models import ModelResponseDiagnostics

FORMAT_ERROR_CODES = {"model_schema_invalid", "schema_validation_failed", "invalid_json"}
REQUEST_ERROR_CODES = {"model_timeout", "model_transport_error"}


def request_error_message(code: str, diagnostics: ModelResponseDiagnostics | None = None) -> str:
    reason = "模型连接异常，未取得完整响应"
    if code == "model_timeout":
        reason = "模型请求超时，未取得完整响应"
        phases = {
            "connect": ("连接模型服务", "连接"),
            "read": ("等待模型响应", "读取"),
            "write": ("发送模型请求", "写入"),
            "pool": ("等待可用连接", "连接池"),
        }
        if diagnostics and diagnostics.timeout_phase in phases:
            description, limit_label = phases[diagnostics.timeout_phase]
            reason = f"模型请求超时：{description}"
            if diagnostics.timeout_seconds is not None:
                reason += f"（{limit_label}等待上限 {diagnostics.timeout_seconds:g} 秒）"
    return reason + "；本地任务已停止，不会自动重试，可稍后手动重试。费用未回报不代表免费"


def format_error_message(diagnostics: ModelResponseDiagnostics | None = None) -> str:
    reason = "模型已返回内容，但创意结果格式校验失败"
    if diagnostics:
        if diagnostics.finish_reason == "length":
            reason = "模型输出被截断，创意结果不完整"
        elif diagnostics.stage == "json_parse":
            reason = "模型返回的内容不是有效 JSON"
        elif diagnostics.stage == "response_envelope":
            reason = "模型响应缺少可读取的正文"
        elif diagnostics.issues:
            descriptions = {
                "missing": "缺少必填字段",
                "string_type": "应为文本",
                "string_too_short": "文本为空或过短",
                "string_too_long": "文本过长",
                "list_type": "应为数组",
                "too_short": "条目不足",
                "too_long": "条目过多",
                "literal_error": "取值不符合要求",
                "enum": "取值不符合要求",
            }
            parts = []
            for issue in diagnostics.issues[:3]:
                detail = descriptions.get(issue.code, "格式不符合要求")
                if issue.limit is not None and issue.code in {"string_too_long", "too_long"}:
                    detail += f"，最多 {issue.limit}"
                parts.append(f"{issue.path}（{detail}）")
            reason += "：" + "、".join(parts)
    return reason[:350] + "。任务已停止，不会自动重试；已回报用量仍计入费用"


def present_batch_error(item):
    # Correct the known misleading legacy message at read time; do not rewrite history.
    if (
        item.status == "failed"
        and item.error_code in FORMAT_ERROR_CODES | REQUEST_ERROR_CODES
        and item.error_message == "创意模型请求失败；请检查模型配置、额度或网络"
    ):
        reason = (
            request_error_message(item.error_code)
            if item.error_code in REQUEST_ERROR_CODES
            else format_error_message()
        )
        return item.model_copy(update={"error_message": reason})
    return item
