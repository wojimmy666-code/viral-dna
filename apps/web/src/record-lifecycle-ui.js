export const RECORD_LIFECYCLES = Object.freeze(["active", "archived", "trashed"]);

export const RECORD_LIFECYCLE_META = Object.freeze({
  active: {
    label: "当前记录",
    title: "当前记录",
    description: "集中管理正在使用的视频分析记录。",
    emptyTitle: "当前没有分析记录",
    emptyDescription: "新建分析后，记录会显示在这里。",
  },
  archived: {
    label: "已归档",
    title: "已归档",
    description: "收起暂时不用、但仍需保留的分析记录。",
    emptyTitle: "还没有归档记录",
    emptyDescription: "归档不会删除视频、报告或创作方案，可随时恢复。",
  },
  trashed: {
    label: "回收站",
    title: "回收站",
    description: "恢复误删记录，或永久移除不再需要的记录。",
    emptyTitle: "回收站为空",
    emptyDescription: "移入回收站的记录会显示在这里。",
  },
});

export function normalizeRecordLifecycle(value) {
  return RECORD_LIFECYCLES.includes(value) ? value : "active";
}

export function recordBatchActions(lifecycle) {
  if (lifecycle === "archived") {
    return [
      { action: "activate", label: "恢复到当前记录", tone: "neutral" },
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
  const amount = `${count} 条记录`;
  if (action === "archive") return `${amount}已归档`;
  if (action === "activate") return `${amount}已恢复到当前记录`;
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
