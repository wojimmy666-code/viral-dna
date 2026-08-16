import {
  ArrowDown,
  ArrowUp,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { createTimelinePhase, moveItem } from "./prompt-editor-ui.js";

function updatePhase(phases, index, field, value) {
  return phases.map((phase, phaseIndex) => (
    phaseIndex === index ? { ...phase, [field]: value } : phase
  ));
}

export function PromptTimelineEditor({ disabled, durationSeconds, phases, onChange }) {
  const items = phases || [];
  return (
    <section className="prompt-editor-section prompt-timeline-editor">
      <div className="prompt-editor-section-heading">
        <div>
          <strong>时序运镜</strong>
          <span>按时间修改动作、镜头和焦点，不需要编辑整段提示词。</span>
        </div>
        <button
          className="prompt-editor-secondary-action"
          type="button"
          disabled={disabled}
          onClick={() => onChange([...items, createTimelinePhase(items, durationSeconds)])}
        >
          <Plus size={16} />新增阶段
        </button>
      </div>

      <div className="prompt-phase-list">
        {items.map((phase, index) => (
          <article className="prompt-phase-row" key={phase.id || `${index}-${phase.start_seconds}`}>
            <div className="prompt-phase-heading">
              <strong>阶段 {index + 1}</strong>
              <div className="prompt-phase-time-fields">
                <label>
                  <span>开始</span>
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={phase.start_seconds}
                    disabled={disabled}
                    onChange={(event) => onChange(updatePhase(
                      items,
                      index,
                      "start_seconds",
                      Number(event.target.value),
                    ))}
                  />
                </label>
                <span aria-hidden="true">—</span>
                <label>
                  <span>结束</span>
                  <input
                    type="number"
                    min="0.1"
                    step="0.1"
                    value={phase.end_seconds}
                    disabled={disabled}
                    onChange={(event) => onChange(updatePhase(
                      items,
                      index,
                      "end_seconds",
                      Number(event.target.value),
                    ))}
                  />
                </label>
                <span className="prompt-phase-seconds">秒</span>
              </div>
              <div className="prompt-phase-actions">
                <button
                  type="button"
                  title="上移阶段"
                  aria-label="上移阶段"
                  disabled={disabled || index === 0}
                  onClick={() => onChange(moveItem(items, index, -1))}
                ><ArrowUp size={15} /></button>
                <button
                  type="button"
                  title="下移阶段"
                  aria-label="下移阶段"
                  disabled={disabled || index === items.length - 1}
                  onClick={() => onChange(moveItem(items, index, 1))}
                ><ArrowDown size={15} /></button>
                <button
                  type="button"
                  title="删除阶段"
                  aria-label="删除阶段"
                  disabled={disabled || items.length === 1}
                  onClick={() => onChange(items.filter((_, phaseIndex) => phaseIndex !== index))}
                ><Trash size={15} /></button>
              </div>
            </div>

            <div className="prompt-phase-primary-fields">
              <label>
                <span>主体动作</span>
                <textarea
                  rows="2"
                  value={phase.subject_motion || ""}
                  disabled={disabled}
                  onChange={(event) => onChange(updatePhase(
                    items,
                    index,
                    "subject_motion",
                    event.target.value,
                  ))}
                />
              </label>
              <label>
                <span>镜头运动</span>
                <textarea
                  rows="2"
                  value={phase.camera_motion || ""}
                  disabled={disabled}
                  onChange={(event) => onChange(updatePhase(
                    items,
                    index,
                    "camera_motion",
                    event.target.value,
                  ))}
                />
              </label>
            </div>

            <details className="prompt-phase-more">
              <summary>前景与焦点</summary>
              <div className="prompt-phase-primary-fields">
                <label>
                  <span>前景运动</span>
                  <textarea
                    rows="2"
                    value={phase.foreground_motion || ""}
                    disabled={disabled}
                    onChange={(event) => onChange(updatePhase(
                      items,
                      index,
                      "foreground_motion",
                      event.target.value,
                    ))}
                  />
                </label>
                <label>
                  <span>焦点变化</span>
                  <textarea
                    rows="2"
                    value={phase.focus_change || ""}
                    disabled={disabled}
                    onChange={(event) => onChange(updatePhase(
                      items,
                      index,
                      "focus_change",
                      event.target.value,
                    ))}
                  />
                </label>
              </div>
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
