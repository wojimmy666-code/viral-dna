import { AutosaveStatus } from "../ui/system/index.js";
import "./prompt-context.css";

export function PromptSectionHeader({ as: Tag = "div", title, titleId, hint, state, onRetry, quiet = false }) {
  return <Tag className={`prompt-section-header${quiet ? " is-quiet" : ""}`} title={quiet ? hint : undefined} aria-label={quiet && hint ? `${title}，${hint}` : undefined}>
    <span className="prompt-section-heading"><strong id={titleId}>{title}</strong>{hint && !quiet && <small>{hint}</small>}</span>
    {["dirty", "saving", "error"].includes(state) && <AutosaveStatus state={state} onRetry={onRetry} />}
  </Tag>;
}
