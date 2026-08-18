import "./settings-primitives.css";

function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

export function SettingsShell({ children, className = "", ...props }) {
  return (
    <main className={joinClasses("settings-surface", className)} {...props}>
      {children}
    </main>
  );
}

export function SettingsPanel({ busy, children, className = "", ...props }) {
  return (
    <section
      aria-busy={busy || undefined}
      className={joinClasses("settings-panel", className)}
      {...props}
    >
      {children}
    </section>
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
