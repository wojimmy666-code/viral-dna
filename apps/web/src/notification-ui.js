export const NOTIFICATION_FILTERS = Object.freeze([
  { id: "all", label: "全部" },
  { id: "in_progress", label: "进行中" },
  { id: "failed", label: "失败" },
]);

export function filterNotifications(items, filter) {
  if (filter === "in_progress") {
    return items.filter((item) => item.status === "in_progress");
  }
  if (filter === "failed") {
    return items.filter((item) => item.status === "failed");
  }
  return items;
}

export function notificationToastPayload(notification) {
  return {
    type: notification.level || (notification.status === "failed" ? "error" : "success"),
    title: notification.title,
    message: notification.message,
  };
}
