import {
  CheckCircle,
  CircleNotch,
  Copy,
  DownloadSimple,
  FileText,
  LockSimple,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  promptPackageToPlainText,
} from "./prompt-document.js";
import { PromptShotEditor } from "./PromptShotEditor.jsx";
import {
  hasReportableGlobalPrompt,
  mergePendingDrafts,
  PROMPT_AUTOSAVE_DELAY_MS,
  promptSaveLabel,
  replaceShotDraft,
} from "./prompt-editor-ui.js";
import "./prompt-editor.css";

function SaveState({ promptPackage, status }) {
  const Icon = status === "saving" || status === "loading"
    ? CircleNotch
    : status === "error"
      ? WarningCircle
      : CheckCircle;
  return (
    <span className={"prompt-save-state " + status} role="status" aria-live="polite">
      <Icon className={status === "saving" || status === "loading" ? "spin" : ""} size={16} />
      {promptSaveLabel(status, promptPackage?.revision_number)}
    </span>
  );
}

export function PromptEditor({
  analysisId,
  onCopy,
  onDownload,
  onNotice,
  onPromptPackageChange,
  promptPackage,
  readOnly = false,
  request,
}) {
  const [workingPackage, setWorkingPackage] = useState(promptPackage);
  const [saveStatus, setSaveStatus] = useState("loading");
  const [loadError, setLoadError] = useState("");
  const packageRef = useRef(promptPackage);
  const pendingDraftsRef = useRef(new Map());
  const saveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const mountedRef = useRef(true);

  const applyPackage = useCallback((nextPackage) => {
    packageRef.current = nextPackage;
    if (mountedRef.current) setWorkingPackage(nextPackage);
    onPromptPackageChange?.(nextPackage);
  }, [onPromptPackageChange]);

  const flushPending = useCallback(async () => {
    if (readOnly || pendingDraftsRef.current.size === 0) return;
    const snapshot = new Map(pendingDraftsRef.current);
    for (const shotId of snapshot.keys()) pendingDraftsRef.current.delete(shotId);
    const basePackage = packageRef.current;
    if (!basePackage?.revision_id) {
      for (const [shotId, draft] of snapshot) pendingDraftsRef.current.set(shotId, draft);
      return;
    }
    if (mountedRef.current) setSaveStatus("saving");
    try {
      const saved = await request("/analyses/" + analysisId + "/prompt-draft", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: basePackage.revision_id,
          shots: [...snapshot].map(([shotId, draft]) => ({ shot_id: shotId, draft })),
        }),
      });
      const merged = mergePendingDrafts(saved, pendingDraftsRef.current);
      applyPackage(merged);
      if (mountedRef.current) {
        setSaveStatus(pendingDraftsRef.current.size > 0 ? "dirty" : "saved");
      }
    } catch (error) {
      if (error.status === 409) {
        try {
          const latest = await request("/analyses/" + analysisId + "/prompt-draft");
          const local = new Map([...snapshot, ...pendingDraftsRef.current]);
          for (const [shotId, draft] of local) pendingDraftsRef.current.set(shotId, draft);
          applyPackage(mergePendingDrafts(latest, local));
          if (mountedRef.current) setSaveStatus("dirty");
          return;
        } catch {
          // The original conflict message is more actionable than a refresh failure.
        }
      }
      for (const [shotId, draft] of snapshot) {
        if (!pendingDraftsRef.current.has(shotId)) pendingDraftsRef.current.set(shotId, draft);
      }
      if (mountedRef.current) setSaveStatus("error");
      onNotice?.({ type: "error", message: error.message || "提示词保存失败" });
    }
  }, [analysisId, applyPackage, onNotice, readOnly, request]);

  const scheduleSave = useCallback(() => {
    if (readOnly) return;
    window.clearTimeout(saveTimerRef.current);
    setSaveStatus("dirty");
    saveTimerRef.current = window.setTimeout(() => {
      saveChainRef.current = saveChainRef.current.then(flushPending, flushPending);
    }, PROMPT_AUTOSAVE_DELAY_MS);
  }, [flushPending, readOnly]);

  useEffect(() => {
    mountedRef.current = true;
    setWorkingPackage(promptPackage);
    packageRef.current = promptPackage;
    pendingDraftsRef.current.clear();
    setLoadError("");
    setSaveStatus(readOnly ? "saved" : "loading");
    let cancelled = false;
    if (readOnly) {
      return () => {
        cancelled = true;
        mountedRef.current = false;
        window.clearTimeout(saveTimerRef.current);
      };
    }
    request("/analyses/" + analysisId + "/prompt-draft")
      .then((nextPackage) => {
        if (cancelled) return;
        applyPackage(nextPackage);
        setSaveStatus("saved");
      })
      .catch((error) => {
        if (cancelled) return;
        setLoadError(error.message || "结构化提示词读取失败");
        setSaveStatus("error");
      });
    return () => {
      cancelled = true;
      mountedRef.current = false;
      window.clearTimeout(saveTimerRef.current);
    };
  }, [
    analysisId,
    applyPackage,
    promptPackage?.id,
    promptPackage?.version,
    readOnly,
    request,
  ]);

  function changeShotDraft(shotId, draft) {
    const nextPackage = replaceShotDraft(packageRef.current, shotId, draft);
    packageRef.current = nextPackage;
    setWorkingPackage(nextPackage);
    pendingDraftsRef.current.set(shotId, draft);
    scheduleSave();
  }

  function retrySave() {
    window.clearTimeout(saveTimerRef.current);
    saveChainRef.current = saveChainRef.current.then(flushPending, flushPending);
  }

  async function downloadAfterSave() {
    window.clearTimeout(saveTimerRef.current);
    saveChainRef.current = saveChainRef.current.then(flushPending, flushPending);
    await saveChainRef.current;
    if (pendingDraftsRef.current.size > 0) {
      onNotice?.({ type: "error", message: "提示词尚未保存，暂时不能下载" });
      return;
    }
    onDownload?.(packageRef.current);
  }

  function saveWhenLeavingEditor(event) {
    if (readOnly || event.currentTarget.contains(event.relatedTarget)) return;
    window.clearTimeout(saveTimerRef.current);
    saveChainRef.current = saveChainRef.current.then(flushPending, flushPending);
  }

  if (!workingPackage) return null;
  const showGlobalPrompt = hasReportableGlobalPrompt(workingPackage.global_prompt);
  const showGlobalRules = workingPackage.continuity_locks?.length > 0
    || workingPackage.negative_constraints?.length > 0;

  return (
    <div className="prompt-editor" onBlurCapture={saveWhenLeavingEditor}>
      <header className="prompt-document-toolbar">
        <div className="prompt-document-title">
          <span className="prompt-document-title-icon"><FileText size={18} /></span>
          <span>
            <h2>提示词文档</h2>
            <small>
              {workingPackage.target_model} · Prompt V{workingPackage.version}
              {workingPackage.aspect_ratio ? " · " + workingPackage.aspect_ratio : ""}
            </small>
          </span>
        </div>
        <div className="prompt-document-toolbar-actions">
          <SaveState promptPackage={workingPackage} status={saveStatus} />
          {saveStatus === "error" && pendingDraftsRef.current.size > 0 && (
            <button
              className="secondary-button compact"
              type="button"
              onClick={retrySave}
            >
              重试保存
            </button>
          )}
          <button
            className="secondary-button compact"
            type="button"
            disabled={saveStatus === "loading"}
            onClick={() => onCopy(
              promptPackageToPlainText(workingPackage),
              "全部提示词已复制",
            )}
          >
            <Copy size={16} />
            复制全文
          </button>
          <button
            className="primary-button compact"
            type="button"
            disabled={saveStatus === "loading"}
            onClick={downloadAfterSave}
          >
            <DownloadSimple size={16} />
            下载 TXT
          </button>
        </div>
      </header>

      {loadError && (
        <div className="prompt-document-error" role="alert">
          <WarningCircle size={18} />
          {loadError}
        </div>
      )}
      {readOnly && (
        <div className="prompt-document-readonly">
          当前查看的是替换版提示词。切换到原始分析版本后可编辑结构化草稿。
        </div>
      )}

      <main className="prompt-document-surface" aria-label="提示词文档">
        {(showGlobalPrompt || showGlobalRules) && (
          <section className="prompt-document-global">
            <header>
              <h2>全局视觉路径</h2>
              <span>应用于全部分镜</span>
            </header>
            {showGlobalPrompt && <p className="prompt-document-global-copy">{workingPackage.global_prompt}</p>}
            {showGlobalRules && (
              <div className="prompt-document-global-rules">
                {workingPackage.continuity_locks?.length > 0 && (
                  <section>
                    <h3><LockSimple size={16} />连续性锁定</h3>
                    <ul>
                      {workingPackage.continuity_locks.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </section>
                )}
                {workingPackage.negative_constraints?.length > 0 && (
                  <section>
                    <h3><ShieldCheck size={16} />全局负面约束</h3>
                    <ul>
                      {workingPackage.negative_constraints.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </section>
                )}
              </div>
            )}
          </section>
        )}

        <div className="prompt-document-shot-list">
          {(workingPackage.shots || []).map((shot, index) => (
            <PromptShotEditor
              disabled={readOnly || saveStatus === "loading"}
              index={index}
              key={`${analysisId}:${shot.shot_id}`}
              shot={shot}
              onCopy={onCopy}
              onChange={(draft) => changeShotDraft(shot.shot_id, draft)}
              onRestore={() => changeShotDraft(shot.shot_id, shot.source_draft)}
            />
          ))}
        </div>
      </main>
    </div>
  );
}
