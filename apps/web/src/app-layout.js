export function isRecordDetailView(activeNav, report) {
  return activeNav === "workspace" && Boolean(report);
}

export function isProductionDetailView(activeNav, report, workspaceMode) {
  return isRecordDetailView(activeNav, report) && workspaceMode === "production";
}

export function shouldShowTopbarCreate(activeNav, report) {
  return !["assets", "history", "platform-connections"].includes(activeNav)
    && !isRecordDetailView(activeNav, report);
}

export function buildRecordBreadcrumb(workspaceMode, projectName = "") {
  const items = [
    { id: "workspace", label: "工作台", current: false },
    { id: "history", label: "分析记录", current: false },
  ];
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
