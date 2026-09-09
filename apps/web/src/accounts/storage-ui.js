export const STORAGE_GB = 1_000_000_000;
export function formatStorage(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value >= STORAGE_GB) return `${Number((value / STORAGE_GB).toFixed(2))} GB`;
  if (value >= 1_000_000) return `${Number((value / 1_000_000).toFixed(1))} MB`;
  if (value >= 1_000) return `${Number((value / 1_000).toFixed(1))} KB`;
  return `${value} B`;
}
export function quotaBytes(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0 || numeric > 100_000) throw new Error("请填写大于 0、不超过 100000 GB 的容量");
  const bytes = Math.round(numeric * STORAGE_GB);
  if (!Number.isSafeInteger(bytes) || bytes < 1) throw new Error("容量数值无效");
  return bytes;
}
export function storageRatio(usage) {
  return usage?.limit_bytes > 0 ? Math.min(100, Math.max(0, 100 * (usage.used_bytes + usage.reserved_bytes) / usage.limit_bytes)) : 0;
}
export function historyOffset(total, offset, pageSize = 30) {
  return Math.max(0, Math.min(offset, Math.floor(Math.max(0, total - 1) / pageSize) * pageSize));
}
export const syncStatus = { queued: "等待同步", uploading: "正在同步", failed: "同步未完成", completed: "已同步", cancelled: "已停止" };
