import { ArrowLeft, Check, LockSimple } from "@phosphor-icons/react";
import { PageShell } from "../ui/system/index.js";
import { mainCreationStep } from "./workspace-ui.js";
import "./creation-workspace.css";

export function CreationNavigation({ active, steps, onChange, busy = false }) {
  const selected = mainCreationStep(active);
  return (
    <nav className="creation-stepper" aria-label="创作工作流">
      {steps.map((step, index) => (
        <button aria-current={step.id === selected ? "step" : undefined} className={step.id === selected ? "is-active" : ""} disabled={busy || !step.enabled} key={step.id} onClick={() => onChange(step.id)} type="button">
          <span className="creation-step-number">{!step.enabled ? <LockSimple size={13} /> : step.complete ? <Check size={13} /> : index + 1}</span>
          <span><strong>{step.label}</strong><small>{step.status || (!step.enabled ? "待前序完成" : "")}</small></span>
        </button>
      ))}
    </nav>
  );
}

export function CreationWorkspace({ title, subtitle, source, metrics, actions, backLabel = "所有方案", onBack, navigation, children }) {
  return (
    <PageShell className="production-workspace creation-workspace">
      <header className="creation-workspace-header">
        <div className="creation-heading">
          {onBack && <button className="text-button creation-back" onClick={onBack} type="button"><ArrowLeft size={16} />{backLabel}</button>}
          <div><h1>{title}</h1><div className="creation-meta">{source && <span>{source}</span>}{subtitle && <span>{subtitle}</span>}{metrics}</div></div>
        </div>
        <div className="creation-header-actions">{actions}</div>
      </header>
      {navigation}
      {children}
    </PageShell>
  );
}
