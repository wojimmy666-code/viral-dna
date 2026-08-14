import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle,
  CircleNotch,
  Info,
  Warning,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { NOTIFICATION_FILTERS, filterNotifications } from "./notification-ui.js";

function notificationIcon(item, size = 18) {
  if (item.status === "in_progress") return <CircleNotch className="spin" size={size} />;
  if (item.level === "error" || item.status === "failed") return <WarningCircle size={size} />;
  if (item.level === "warning" || item.status === "cancelled") return <Warning size={size} />;
  if (item.level === "success" || item.status === "succeeded") {
    return <CheckCircle size={size} weight="fill" />;
  }
  return <Info size={size} />;
}

function formatNotificationTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function ToastItem({ toast, onDismiss }) {
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    if (actionBusy) return undefined;
    const timer = window.setTimeout(() => onDismiss(toast.id), toast.duration || 4200);
    return () => window.clearTimeout(timer);
  }, [actionBusy, onDismiss, toast.duration, toast.id]);

  async function runAction() {
    if (!toast.onAction || actionBusy) return;
    setActionBusy(true);
    try {
      await toast.onAction();
      onDismiss(toast.id);
    } catch {
      setActionBusy(false);
    }
  }

  const role = toast.type === "error" ? "alert" : "status";
  return (
    <article className={`app-toast ${toast.type || "success"}`} role={role}>
      <span className="app-toast-icon">{notificationIcon({ level: toast.type }, 19)}</span>
      <div className="app-toast-copy">
        {toast.title && <strong>{toast.title}</strong>}
        <p>{toast.message}</p>
        {toast.actionLabel && toast.onAction && (
          <button
            className="app-toast-action"
            disabled={actionBusy}
            onClick={runAction}
            type="button"
          >
            {actionBusy ? <CircleNotch className="spin" size={14} /> : null}
            {actionBusy ? "正在恢复" : toast.actionLabel}
          </button>
        )}
      </div>
      <button aria-label="关闭提示" onClick={() => onDismiss(toast.id)} type="button">
        <X size={15} />
      </button>
    </article>
  );
}

export function ToastViewport({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="app-toast-viewport" aria-label="操作消息">
      {toasts.slice(-3).map((toast) => (
        <ToastItem key={toast.id} onDismiss={onDismiss} toast={toast} />
      ))}
    </div>
  );
}

export function NotificationDrawer({
  filter,
  items,
  loading,
  onAction,
  onClose,
  onFilterChange,
  onMarkAllRead,
  onMarkRead,
  open,
  unreadCount,
}) {
  if (!open) return null;
  const filteredItems = filterNotifications(items, filter);
  return (
    <>
      <button
        className="notification-drawer-scrim"
        aria-label="关闭消息中心"
        onClick={onClose}
        type="button"
      />
      <aside className="notification-drawer" aria-label="消息中心" role="dialog">
        <header className="notification-drawer-header">
          <div>
            <span>账户消息</span>
            <h2>消息中心</h2>
          </div>
          <button className="icon-button" aria-label="关闭消息中心" onClick={onClose} type="button">
            <X size={19} />
          </button>
        </header>

        <div className="notification-drawer-toolbar">
          <div className="notification-filter-tabs" role="tablist" aria-label="筛选消息">
            {NOTIFICATION_FILTERS.map((item) => (
              <button
                aria-selected={filter === item.id}
                className={filter === item.id ? "active" : ""}
                key={item.id}
                onClick={() => onFilterChange(item.id)}
                role="tab"
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            className="notification-read-all"
            disabled={!unreadCount}
            onClick={onMarkAllRead}
            type="button"
          >
            <Check size={14} />全部已读
          </button>
        </div>

        <div className="notification-feed">
          {loading && !items.length ? (
            <div className="notification-empty"><CircleNotch className="spin" size={23} /><span>正在读取消息</span></div>
          ) : filteredItems.length ? (
            filteredItems.map((item) => (
              <article
                className={`notification-item ${item.level} ${item.read_at ? "read" : "unread"}`}
                key={item.id}
              >
                <span className="notification-item-icon">{notificationIcon(item)}</span>
                <div className="notification-item-copy">
                  <header>
                    <strong>{item.title}</strong>
                    <time dateTime={item.updated_at}>{formatNotificationTime(item.updated_at)}</time>
                  </header>
                  {item.message && <p>{item.message}</p>}
                  <footer>
                    {item.action_kind && item.action_label ? (
                      <button onClick={() => onAction(item)} type="button">
                        {item.action_label}<ArrowRight size={14} />
                      </button>
                    ) : (
                      <span />
                    )}
                    {!item.read_at && (
                      <button className="notification-mark-read" onClick={() => onMarkRead(item.id)} type="button">
                        标为已读
                      </button>
                    )}
                  </footer>
                </div>
              </article>
            ))
          ) : (
            <div className="notification-empty">
              <CheckCircle size={25} />
              <strong>这里暂时没有消息</strong>
              <span>任务完成或失败后会显示在这里。</span>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
