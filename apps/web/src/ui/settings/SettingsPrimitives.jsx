import "./settings-primitives.css";
import {
  joinClasses,
  PageShell,
  SurfacePanel,
} from "../system/SystemPrimitives.jsx";

export function SettingsShell({ children, className = "", ...props }) {
  return (
    <PageShell className={joinClasses("settings-surface", className)} {...props}>
      {children}
    </PageShell>
  );
}

export function SettingsPanel({ busy, children, className = "", ...props }) {
  return (
    <SurfacePanel
      aria-busy={busy || undefined}
      className={joinClasses("settings-panel", className)}
      {...props}
    >
      {children}
    </SurfacePanel>
  );
}

export function SettingsPanelHeader({ children, description, title }) {
  return (
    <header className="settings-panel-header">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {children}
    </header>
  );
}

export function SettingsActions({ children, className = "" }) {
  return (
    <footer className={joinClasses("settings-actions", className)}>
      {children}
    </footer>
  );
}

export function SettingsDefinitionList({ items }) {
  return (
    <dl className="settings-definition-list">
      {items.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
