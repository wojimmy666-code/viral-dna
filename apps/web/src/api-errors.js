const FIELD_LABELS = Object.freeze({
  project_id: "项目 ID",
  project_ids: "所选项目",
  record_id: "项目 ID",
  record_ids: "所选项目",
  action: "操作类型",
  name: "名称",
  folder_id: "目录",
});

function messageText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function validationMessage(issue) {
  if (!issue || typeof issue !== "object") return "";
  const location = Array.isArray(issue.loc) ? issue.loc : [];
  const field = [...location].reverse().find((part) => Object.hasOwn(FIELD_LABELS, part));
  const label = FIELD_LABELS[field] || "请求参数";
  const selection = ["project_ids", "record_ids"].includes(field);
  if (["uuid_parsing", "uuid_type", "uuid_version"].includes(issue.type)) {
    return selection || label === "项目 ID" ? "项目 ID 格式不正确" : `${label}格式不正确`;
  }
  if (issue.type === "missing") return selection ? "请选择要操作的项目" : `缺少${label}`;
  if (issue.type === "too_short" && selection) return "请至少选择一个项目";
  if (issue.type === "too_long" && selection) return "所选项目数量超过单次操作上限";
  if (["enum", "literal_error"].includes(issue.type)) return `${label}选项无效`;
  // Only expose the validation message, never input/ctx (which can include
  // credentials or an entire user-submitted document).
  const message = messageText(issue.msg);
  return message ? (field ? `${label}：${message}` : message) : "";
}

export function apiErrorMessage(payload, status) {
  const detail = payload?.detail;
  const businessMessage = messageText(detail) || messageText(detail?.message);
  if (businessMessage) return businessMessage;
  if (Array.isArray(detail)) {
    const messages = [...new Set(detail.map(validationMessage).filter(Boolean))].slice(0, 3);
    if (messages.length) return `请求参数有误：${messages.join("；")}`;
  }
  if (messageText(payload?.message)) return messageText(payload.message);
  if (status === 422) return "请求参数不正确，请检查后重试";
  return "请求失败，请稍后重试";
}
