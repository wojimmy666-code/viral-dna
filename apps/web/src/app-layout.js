export function buildRecordBreadcrumb(workspaceMode, projectName = "") {
  const items = [{ id: "history", label: "项目", current: false }];
  if (workspaceMode !== "production") {
    return [...items, { id: "analysis", label: "分析报告", current: true }];
  }

  const normalizedProjectName = String(projectName || "").trim();
  items.push({ id: "production", label: "创作方案", current: !normalizedProjectName });
  if (normalizedProjectName) {
    items.push({ id: "project", label: normalizedProjectName, current: true });
  }
  return items;
}
