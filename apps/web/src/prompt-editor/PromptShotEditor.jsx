import {
  ArrowCounterClockwise,
  CaretDown,
  Copy,
  Translate,
  WarningCircle,
} from "@phosphor-icons/react";
import { PromptTimelineEditor } from "./PromptTimelineEditor.jsx";
import { promptDraftContainsUnlabeledEnglish } from "./prompt-editor-ui.js";

const VISUAL_FIELDS = [
  ["subjects", "主体与服装", "人物、产品、道具和服装，只描述需要出现在画面中的内容。"],
  ["scene", "场景", "地点、背景和环境信息。"],
  ["composition", "构图", "景别、主体位置和前中后景关系。"],
  ["lighting", "光线", "光向、软硬、色温和对比度。"],
  ["color", "色彩", "主色、辅色和整体色调。"],
];

function updateTransition(draft, field, value) {
  return { ...draft, transition: { ...draft.transition, [field]: value } };
}

export function PromptShotEditor({
  disabled,
  index,
  onChange,
  onCopy,
  onRestore,
  shot,
}) {
  const draft = shot.draft;
  if (!draft) {
    return (
      <details className="prompt-shot-editor prompt-shot-editor-legacy" defaultOpen={index === 0}>
        <summary>
          <span className="prompt-shot-index">{String(index + 1).padStart(2, "0")}</span>
          <div className="prompt-shot-summary-copy">
            <strong>{shot.shot_id}</strong>
            <small>{shot.duration_seconds.toFixed(1)} 秒</small>
          </div>
          <span className="prompt-shot-summary-intent">旧版提示词（只读）</span>
          <CaretDown className="prompt-shot-editor-caret" size={17} />
        </summary>
        <div className="prompt-shot-editor-body">
          <div className="prompt-legacy-preview">
            <pre>{shot.prompt}</pre>
            <button
              className="prompt-editor-secondary-action"
              type="button"
              onClick={() => onCopy(shot.prompt, `${shot.shot_id} 模型提示词已复制`)}
            ><Copy size={16} />复制提示词</button>
          </div>
        </div>
      </details>
    );
  }
  const transitionVisible = draft.transition?.kind !== "none"
    || Boolean(draft.transition?.instruction);
  const languageIssues = shot.language_issues || [];
  const hasLanguageIssue = languageIssues.length > 0
    || promptDraftContainsUnlabeledEnglish(draft);

  return (
    <details className="prompt-shot-editor" defaultOpen={index === 0}>
      <summary>
        <span className="prompt-shot-index">{String(index + 1).padStart(2, "0")}</span>
        <div className="prompt-shot-summary-copy">
          <strong>{shot.shot_id}</strong>
          <small>{shot.duration_seconds.toFixed(1)} 秒</small>
        </div>
        <span className="prompt-shot-summary-intent">
          {draft.visual.subjects || draft.visual.scene || "待补充核心画面"}
        </span>
        <CaretDown className="prompt-shot-editor-caret" size={17} />
      </summary>

      <div className="prompt-shot-editor-body">
        <div className="prompt-shot-editor-toolbar">
          <div>
            <strong>结构化创作指令</strong>
            <span>修改字段后自动保存，并重新编译当前模型提示词。</span>
          </div>
          <button
            className="prompt-editor-secondary-action"
            type="button"
            disabled={disabled || !shot.source_draft}
            onClick={onRestore}
          >
            <ArrowCounterClockwise size={16} />恢复 AI 版本
          </button>
        </div>

        <div className="prompt-language-policy">
          <Translate size={18} />
          <span>
            <strong>默认使用简体中文</strong>
            英文仅保留原文台词、字幕或画面标识，并写成“英文标识：“Customer Map””。
          </span>
        </div>

        {hasLanguageIssue && (
          <div className="prompt-language-warning" role="alert">
            <WarningCircle size={19} />
            <span>
              <strong>检测到未转换的英文描述</strong>
              {languageIssues.length > 0
                ? `请检查：${languageIssues.slice(0, 4).join("、")}。旧分析可重新分析，或在当前字段中改为中文。`
                : "请改为简体中文；英文原文只能作为带标签的台词、字幕或画面标识保留。"}
            </span>
          </div>
        )}

        <section className="prompt-editor-section">
          <div className="prompt-editor-section-heading">
            <div>
              <strong>基础画面</strong>
              <span>只写静态视觉事实，动作和运镜放在时间轴中。</span>
            </div>
          </div>
          <div className="prompt-visual-fields">
            {VISUAL_FIELDS.map(([field, label, hint]) => (
              <label className={field === "subjects" || field === "scene" ? "wide" : ""} key={field}>
                <span>{label}</span>
                <textarea
                  rows="2"
                  value={draft.visual[field] || ""}
                  disabled={disabled}
                  aria-describedby={`${shot.shot_id}-${field}-hint`}
                  onChange={(event) => onChange({
                    ...draft,
                    visual: { ...draft.visual, [field]: event.target.value },
                  })}
                />
                <small id={`${shot.shot_id}-${field}-hint`}>{hint}</small>
              </label>
            ))}
          </div>
        </section>

        <PromptTimelineEditor
          disabled={disabled}
          durationSeconds={shot.duration_seconds}
          phases={draft.phases}
          onChange={(phases) => onChange({ ...draft, phases })}
        />

        <details className="prompt-editor-disclosure" defaultOpen={transitionVisible}>
          <summary>
            <span>出场转场</span>
            <small>{transitionVisible ? "已配置" : "无转场"}</small>
            <CaretDown size={16} />
          </summary>
          <div className="prompt-transition-fields">
            <label>
              <span>类型</span>
              <select
                value={draft.transition?.kind || "none"}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(draft, "kind", event.target.value))}
              >
                <option value="none">无转场</option>
                <option value="hard_cut">硬切</option>
                <option value="crossfade">交叉淡化</option>
                <option value="foreground_occlusion">前景遮挡</option>
                <option value="wipe">擦除</option>
                <option value="whip_pan">甩镜</option>
                <option value="match_cut">匹配剪辑</option>
                <option value="other">其他</option>
                <option value="uncertain">待确认</option>
              </select>
            </label>
            <label>
              <span>开始时间</span>
              <input
                type="number"
                min="0"
                step="0.1"
                value={draft.transition?.start_seconds ?? ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(
                  draft,
                  "start_seconds",
                  event.target.value === "" ? null : Number(event.target.value),
                ))}
              />
            </label>
            <label>
              <span>结束时间</span>
              <input
                type="number"
                min="0"
                step="0.1"
                value={draft.transition?.end_seconds ?? ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(
                  draft,
                  "end_seconds",
                  event.target.value === "" ? null : Number(event.target.value),
                ))}
              />
            </label>
            <label className="wide">
              <span>转场指令</span>
              <textarea
                rows="2"
                value={draft.transition?.instruction || ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(draft, "instruction", event.target.value))}
              />
            </label>
            <label>
              <span>遮挡对象</span>
              <input
                value={draft.transition?.mask_object || ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(draft, "mask_object", event.target.value))}
              />
            </label>
            <label>
              <span>运动方向</span>
              <input
                value={draft.transition?.direction || ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(draft, "direction", event.target.value))}
              />
            </label>
            <label className="wide">
              <span>结束状态</span>
              <input
                value={draft.transition?.terminal_frame || ""}
                disabled={disabled}
                onChange={(event) => onChange(updateTransition(draft, "terminal_frame", event.target.value))}
              />
            </label>
          </div>
        </details>

        <details className="prompt-editor-disclosure">
          <summary>
            <span>约束与补充说明</span>
            <small>{draft.negative_constraints?.length || 0} 项约束</small>
            <CaretDown size={16} />
          </summary>
          <div className="prompt-notes-fields">
            <label>
              <span>负面约束</span>
              <textarea
                rows="3"
                value={(draft.negative_constraints || []).join("\n")}
                disabled={disabled}
                placeholder="每行一项"
                onChange={(event) => onChange({
                  ...draft,
                  negative_constraints: event.target.value
                    .split("\n")
                    .map((item) => item.trim())
                    .filter(Boolean),
                })}
              />
            </label>
            <label>
              <span>补充说明</span>
              <textarea
                rows="3"
                value={draft.custom_notes || ""}
                disabled={disabled}
                onChange={(event) => onChange({ ...draft, custom_notes: event.target.value })}
              />
            </label>
          </div>
        </details>

        <details className="prompt-compiled-preview">
          <summary>
            <span>查看模型输入</span>
            <small>{shot.prompt?.length || 0} 字</small>
            <CaretDown size={16} />
          </summary>
          <div>
            <pre>{shot.prompt}</pre>
            <button
              className="prompt-editor-secondary-action"
              type="button"
              onClick={() => onCopy(shot.prompt, `${shot.shot_id} 模型提示词已复制`)}
            ><Copy size={16} />复制模型输入</button>
          </div>
        </details>
      </div>
    </details>
  );
}
