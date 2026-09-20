"""Actionable messages without exposing model output or credential details."""

from ..models import ModelResponseDiagnostics

FORMAT_ERROR_CODES = {"model_schema_invalid", "schema_validation_failed", "invalid_json"}


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
        and item.error_code in FORMAT_ERROR_CODES
        and item.error_message == "创意模型请求失败；请检查模型配置、额度或网络"
    ):
        return item.model_copy(update={"error_message": format_error_message()})
    return item
