import {
  ArrowCounterClockwise,
  CaretRight,
  Copy,
  WarningCircle,
} from "@phosphor-icons/react";
import { useId, useState } from "react";
import {
  promptDocumentTextToDraft,
  promptShotCharacterCount,
  promptShotDocumentText,
  promptShotSummary,
  promptShotToPlainText,
} from "./prompt-document.js";
import { PromptRichTextEditor } from "./PromptRichTextEditor.jsx";
import { promptDraftContainsUnlabeledEnglish } from "./prompt-editor-ui.js";

function shotDuration(shot) {
  const duration = Number(shot?.duration_seconds);
  return Number.isFinite(duration) ? `${duration.toFixed(1)} 秒` : "时长未设置";
}

export function PromptShotEditor({
  disabled,
  index,
  onChange,
  onCopy,
  onRestore,
  shot,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const regionId = useId();
  const draft = shot.draft;
  const documentText = promptShotDocumentText(shot);
  const languageIssues = shot.language_issues || [];
  const hasLanguageIssue = Boolean(draft) && (
    languageIssues.length > 0 || promptDraftContainsUnlabeledEnglish(draft)
  );
  const title = `分镜 ${index + 1}`;

  return (
    <article
      className={`prompt-document-shot${isOpen ? " is-open" : ""}`}
      id={`prompt-shot-${shot.shot_id}`}
    >
      <div className="prompt-document-shot-row">
        <button
          aria-controls={regionId}
          aria-expanded={isOpen}
          className="prompt-document-shot-toggle"
          type="button"
          onClick={() => setIsOpen((current) => !current)}
        >
          <CaretRight className="prompt-document-shot-caret" size={17} weight="bold" />
          <span className="prompt-document-shot-identity">
            <strong>{title}</strong>
            <small>
              {shotDuration(shot)} · {promptShotCharacterCount(shot)} 字
            </small>
          </span>
          <span className="prompt-document-shot-summary">{promptShotSummary(shot)}</span>
          {hasLanguageIssue && (
            <WarningCircle
              aria-label="存在语言提示"
              className="prompt-document-shot-warning-marker"
              size={17}
            />
          )}
        </button>
        <button
          aria-label={`复制${title}提示词`}
          className="prompt-document-copy-action"
          title={`复制${title}提示词`}
          type="button"
          onClick={() => onCopy(
            promptShotToPlainText(shot, index),
            `${title}提示词已复制`,
          )}
        >
          <Copy size={17} />
        </button>
      </div>

      {isOpen && (
        <div
          aria-label={`${title}完整提示词`}
          className="prompt-document-shot-body"
          id={regionId}
          role="region"
        >
          <div className="prompt-document-shot-body-toolbar">
            <span>{draft ? "完整提示词 · 修改后自动保存" : "旧版提示词 · 仅支持阅读"}</span>
            {draft && (
              <button
                className="prompt-document-restore-action"
                disabled={disabled || !shot.source_draft}
                type="button"
                onClick={onRestore}
              >
                <ArrowCounterClockwise size={16} />
                恢复 AI 版本
              </button>
            )}
          </div>

          {hasLanguageIssue && (
            <div className="prompt-document-warning" role="alert">
              <WarningCircle size={18} />
              <span>
                <strong>检测到未转换的英文描述</strong>
                {languageIssues.length > 0
                  ? `请检查：${languageIssues.slice(0, 4).join("、")}。`
                  : "请改为简体中文；英文原文仅作为带标签的台词、字幕或画面标识保留。"}
              </span>
            </div>
          )}

          <PromptRichTextEditor
            ariaLabel={`${title}完整提示词`}
            disabled={disabled || !draft}
            value={documentText}
            onChange={(nextText) => {
              if (draft) onChange(promptDocumentTextToDraft(nextText, draft));
            }}
          />
        </div>
      )}
    </article>
  );
}
