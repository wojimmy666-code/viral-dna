import { useMemo, useState } from "react";
import { CaretDown, Check, Copy } from "@phosphor-icons/react";
import {
  buildVideoReferenceSystemConstraints,
  compileVideoPromptWithReferences,
  videoReferenceConflictPriority,
} from "./video-prompt-references.js";
import "./video-prompt-reference-policy.css";

export function VideoPromptReferencePolicy({ onNotice, prompt, references }) {
  const [copied, setCopied] = useState("");
  const constraints = useMemo(
    () => buildVideoReferenceSystemConstraints(references),
    [references],
  );
  const priority = useMemo(
    () => videoReferenceConflictPriority(references),
    [references],
  );

  if (constraints.length === 0) return null;

  async function copyPrompt(kind) {
    const text = kind === "compiled"
      ? compileVideoPromptWithReferences(prompt, references)
      : String(prompt || "");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      window.setTimeout(() => setCopied(""), 1600);
      onNotice?.(kind === "compiled" ? "已复制含系统约束的模型输入" : "已复制可编辑提示词");
    } catch (error) {
      onNotice?.({
        type: "error",
        title: "复制失败",
        message: error?.message || "浏览器未开放剪贴板权限",
      });
    }
  }

  return (
    <section className="video-reference-policy" aria-label="系统引用约束">
      <details>
        <summary>
          <span>
            <strong>系统引用约束</strong>
            <small>生成时自动附加，不占用可编辑提示词</small>
          </span>
          <span className="video-reference-policy-count">{constraints.length} 项</span>
          <CaretDown aria-hidden="true" size={16} />
        </summary>
        <div className="video-reference-policy-content">
          {constraints.map((constraint) => (
            <article key={constraint.key}>
              <header>
                <span>{constraint.roleLabel}</span>
                <code>{constraint.token}</code>
              </header>
              <strong>{constraint.summary}</strong>
              <p>{constraint.text}</p>
            </article>
          ))}
          {priority && <p className="video-reference-policy-priority">{priority}</p>}
        </div>
      </details>
      <div className="video-reference-policy-actions">
        <button onClick={() => copyPrompt("editable")} type="button">
          {copied === "editable" ? <Check size={16} /> : <Copy size={16} />}
          复制可编辑提示词
        </button>
        <button className="primary" onClick={() => copyPrompt("compiled")} type="button">
          {copied === "compiled" ? <Check size={16} /> : <Copy size={16} />}
          复制模型输入
        </button>
      </div>
    </section>
  );
}
