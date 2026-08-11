export const ASSET_PAGE_SIZES = [20, 40, 80];

export const ASSET_TYPE_OPTIONS = [
  { value: "person", label: "人物" },
  { value: "product", label: "产品" },
  { value: "clothing", label: "服装" },
  { value: "scene", label: "场景" },
  { value: "logo", label: "Logo" },
  { value: "other", label: "其他" },
];

export const ASSET_TYPE_LABELS = Object.fromEntries(
  ASSET_TYPE_OPTIONS.map((item) => [item.value, item.label]),
);

export const STORAGE_STATE_LABELS = {
  local_only: "仅本地",
  cloud_only: "仅云端",
  syncing: "同步中",
  synced: "已同步",
  download_required: "需下载",
  upload_failed: "上传失败",
  unavailable: "不可用",
};

export function assetLibraryView({
  folderId = "",
  type = "",
  query = "",
  storageState = "",
  includeArchived = false,
} = {}) {
  if (folderId === "unfiled") return "unfiled";
  if (folderId) return "folder";
  if (query.trim() || type || storageState || includeArchived) return "search";
  return "home";
}

export function assetListFolderForView(filters = {}) {
  return assetLibraryView(filters) === "home" ? "unfiled" : filters.folderId || "";
}

export function buildAssetListQuery({
  page = 1,
  pageSize = 20,
  folderId = "",
  type = "",
  query = "",
  storageState = "",
  includeArchived = false,
} = {}) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (folderId) params.set("folder_id", folderId);
  if (type) params.set("type", type);
  if (query.trim()) params.set("query", query.trim());
  if (storageState) params.set("storage_state", storageState);
  if (includeArchived) params.set("include_archived", "true");
  return params.toString();
}

export function buildPostUploadView(asset = {}) {
  return {
    folderId: asset.folder_id || "unfiled",
    query: "",
    type: "",
    storageState: "",
    includeArchived: false,
    page: 1,
  };
}

export function buildAssetPaginationItems(currentPage, totalPages) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  const visiblePages = [...new Set([1, currentPage - 1, currentPage, currentPage + 1, totalPages])]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right);
  const items = [];
  visiblePages.forEach((page, index) => {
    const previous = visiblePages[index - 1];
    if (index > 0 && page - previous === 2) items.push(previous + 1);
    if (index > 0 && page - previous > 2) items.push(`ellipsis-${previous}-${page}`);
    items.push(page);
  });
  return items;
}

export function normalizeAssetTags(value) {
  return [...new Set(
    String(value || "")
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean),
  )].slice(0, 20);
}

export function formatAssetSize(bytes) {
  const numeric = Number(bytes);
  if (!Number.isFinite(numeric) || numeric < 0) return "—";
  if (numeric < 1024) return `${numeric} B`;
  if (numeric < 1024 * 1024) return `${(numeric / 1024).toFixed(1)} KB`;
  return `${(numeric / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatAssetDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
