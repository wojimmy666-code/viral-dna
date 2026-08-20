import "./system-primitives.css";

export function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

export function PageShell({ as: Tag = "main", children, className = "", ...props }) {
  return (
    <Tag className={joinClasses("ui-page-shell", className)} {...props}>
      {children}
    </Tag>
  );
}

export function PageHeader({
  actions,
  before,
  className = "",
  description,
  title,
  ...props
}) {
  return (
    <header className={joinClasses("ui-page-header", className)} {...props}>
      {before && <div className="ui-page-header-before">{before}</div>}
      <div className="ui-page-header-copy">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="ui-page-header-actions">{actions}</div>}
    </header>
  );
}

export function SurfacePanel({ as: Tag = "section", children, className = "", ...props }) {
  return (
    <Tag className={joinClasses("ui-surface-panel", className)} {...props}>
      {children}
    </Tag>
  );
}

export function SectionHeader({ actions, className = "", description, title, ...props }) {
  return (
    <header className={joinClasses("ui-section-header", className)} {...props}>
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="ui-section-header-actions">{actions}</div>}
    </header>
  );
}

export function StatusBadge({ children, className = "", tone = "neutral", ...props }) {
  return (
    <span className={joinClasses("ui-status-badge", `is-${tone}`, className)} {...props}>
      {children}
    </span>
  );
}

export function InlineMessage({
  as: Tag = "div",
  children,
  className = "",
  tone = "info",
  ...props
}) {
  const role = tone === "danger" ? "alert" : props.role;
  return (
    <Tag
      className={joinClasses("ui-inline-message", `is-${tone}`, className)}
      {...props}
      role={role}
    >
      {children}
    </Tag>
  );
}
