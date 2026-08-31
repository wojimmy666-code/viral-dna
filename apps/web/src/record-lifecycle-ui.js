export const RECORD_LIFECYCLES = Object.freeze(["active", "archived", "trashed"]);

export const RECORD_LIFECYCLE_META = Object.freeze({
  active: {
    label: "当前项目",
    title: "当前项目",
    description: "",
    emptyTitle: "当前没有项目",
    emptyDescription: "新建项目后，项目会显示在这里。",
  },
  archived: {
    label: "已归档",
    title: "已归档",
    description: "收起暂时不用、但仍需保留的项目。",
    emptyTitle: "还没有归档项目",
    emptyDescription: "归档不会删除视频、报告或创作方案，可随时恢复。",
  },
  trashed: {
    label: "回收站",
    title: "回收站",
    description: "恢复误删项目，或永久移除不再需要的项目。",
    emptyTitle: "回收站为空",
    emptyDescription: "移入回收站的项目会显示在这里。",
  },
});

export function normalizeRecordLifecycle(value) {
  return RECORD_LIFECYCLES.includes(value) ? value : "active";
}

export function recordBatchActions(lifecycle) {
  if (lifecycle === "archived") {
    return [
      { action: "activate", label: "恢复到当前项目", tone: "neutral" },
      { action: "trash", label: "移入回收站", tone: "danger" },
    ];
  }
  if (lifecycle === "trashed") {
    return [
      { action: "restore", label: "恢复", tone: "neutral" },
      { action: "purge", label: "永久删除", tone: "danger" },
    ];
  }
  return [
    { action: "archive", label: "归档", tone: "neutral" },
    { action: "trash", label: "移入回收站", tone: "danger" },
  ];
}

export function recordActionSuccessMessage(action, count) {
  const amount = `${count} 个项目`;
  if (action === "archive") return `${amount}已归档`;
  if (action === "activate") return `${amount}已恢复到当前项目`;
  if (action === "trash") return `${amount}已移入回收站`;
  if (action === "restore") return `${amount}已恢复`;
  if (action === "purge") return `${amount}已永久删除`;
  return `${amount}已更新`;
}

export function buildRecordListParams({
  query = "",
  folder = "",
  status = "",
  sort = "updated_desc",
  lifecycle = "active",
  page = 1,
  pageSize = 20,
} = {}) {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (folder) params.set("folder_id", folder);
  if (status) params.set("status", status);
  params.set("lifecycle", normalizeRecordLifecycle(lifecycle));
  params.set("sort", sort);
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  return params;
}
