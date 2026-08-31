import {
  CheckCircle,
  CircleNotch,
  WarningCircle,
} from "@phosphor-icons/react";
import { joinClasses } from "./SystemPrimitives.jsx";
import "./autosave-status.css";

const AUTOSAVE_LABELS = Object.freeze({
  dirty: "待保存",
  saving: "保存中…",
  saved: "已保存",
  error: "保存失败",
});

export function AutosaveStatus({
  className = "",
  onRetry,
  state = "saved",
}) {
  const effectiveState = AUTOSAVE_LABELS[state] ? state : "saved";
  const icon = effectiveState === "saving"
    ? <CircleNotch aria-hidden="true" className="spin" size={14} />
    : effectiveState === "error"
      ? <WarningCircle aria-hidden="true" size={14} weight="fill" />
      : effectiveState === "saved"
        ? <CheckCircle aria-hidden="true" size={14} weight="fill" />
        : null;
  const content = (
    <>
      {icon}
      <span>{AUTOSAVE_LABELS[effectiveState]}</span>
    </>
  );

  if (effectiveState === "error" && onRetry) {
    return (
      <button
        aria-label="自动保存失败，点击重试"
        className={joinClasses("ui-autosave-status", "is-error", className)}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onRetry();
        }}
        type="button"
      >
        {content}
      </button>
    );
  }

  return (
    <span
      aria-live="polite"
      className={joinClasses(
        "ui-autosave-status",
        `is-${effectiveState}`,
        className,
      )}
      role="status"
    >
      {content}
    </span>
  );
}
