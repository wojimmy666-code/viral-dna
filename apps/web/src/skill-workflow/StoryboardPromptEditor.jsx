import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ArrowCounterClockwise, ArrowRight, Plus, Trash } from "@phosphor-icons/react";
import { AutosaveStatus, InlineMessage } from "../ui/system/index.js";
import { createStoryboardDraftSession, newStoryboardShot, storyboardDraftIssues } from "./storyboard-draft.js";
import "./storyboard-prompt-editor.css";

export const StoryboardPromptEditor = forwardRef(function StoryboardPromptEditor({
  approved, busy, manifest, onComplete, onSaved, outline, projectId, request, targetDurationFrames,
}, ref) {
  const callbacks = useRef({ onSaved, request });
  callbacks.current = { onSaved, request };
  const [view, setView] = useState(null);
  const [deleted, setDeleted] = useState(null);
  const [issues, setIssues] = useState([]);
  const [confirming, setConfirming] = useState(false);
  const [recoveryConflict, setRecoveryConflict] = useState(null);
  const saveTimer = useRef(null);
  const fields = useRef(new Map());
  const cacheKey = `viraldna:storyboard-draft:${projectId}`;
  const [session] = useState(() => createStoryboardDraftSession(manifest, {
    save: (payload) => callbacks.current.request(`/projects/${projectId}/storyboard-draft`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    }),
    onChange: setView,
    onSaved: (next) => callbacks.current.onSaved?.(next),
  }));
  const state = view || session.snapshot();

  async function flush() {
    window.clearTimeout(saveTimer.current);
    return session.flush();
  }

  useImperativeHandle(ref, () => ({ flush }), [session]);
  useEffect(() => { session.hydrate(manifest); }, [manifest, session]);
  useEffect(() => {
    // A crash/reload can occur inside the debounce window. Restore only against
    // the same base revision; never overwrite another tab's newer revision.
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
      const valid = cached && Array.isArray(cached.shots)
        && cached.shots.every((shot) => /^shot_[a-z0-9]{8,64}$/.test(shot.stable_shot_key)
          && typeof shot.image_prompt_body === "string" && typeof shot.video_prompt_body === "string");
      if (valid && cached.expected_revision_id === manifest.id) {
        session.edit(cached.shots);
        saveTimer.current = window.setTimeout(() => void session.flush(), 900);
      } else if (valid) {
        setRecoveryConflict(cached.shots);
      }
    } catch { /* Storage can be disabled without preventing editing. */ }
    const beforeUnload = (event) => {
      if (!session.snapshot().dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      window.clearTimeout(saveTimer.current);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [cacheKey, session]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (recoveryConflict) return;
    try {
      if (state.dirty) localStorage.setItem(cacheKey, JSON.stringify({ expected_revision_id: state.manifest.id, shots: state.shots }));
      else if (view) localStorage.removeItem(cacheKey);
    } catch { /* Keep the in-memory draft if storage is full. */ }
  }, [cacheKey, recoveryConflict, state, view]);

  function edit(update) {
    session.edit(update);
    setIssues([]);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => { void session.flush(); }, 900);
  }

  function addShot(afterIndex = state.shots.length - 1) {
    const shot = newStoryboardShot();
    edit((shots) => [...shots.slice(0, afterIndex + 1), shot, ...shots.slice(afterIndex + 1)]);
    window.requestAnimationFrame(() => fields.current.get(shot.stable_shot_key)?.focus());
  }

  function removeShot(index) {
    setDeleted({ shot: state.shots[index], index, previousKey: state.shots[index - 1]?.stable_shot_key });
    edit((shots) => shots.filter((_, shotIndex) => shotIndex !== index));
  }

  function undoDelete() {
    if (!deleted) return;
    edit((shots) => {
      const previousIndex = shots.findIndex((shot) => shot.stable_shot_key === deleted.previousKey);
      const index = previousIndex >= 0 ? previousIndex + 1 : Math.min(deleted.index, shots.length);
      return [...shots.slice(0, index), deleted.shot, ...shots.slice(index)];
    });
    setDeleted(null);
  }

  async function complete() {
    setConfirming(true);
    try {
      if (!await flush()) return;
      const next = session.snapshot();
      const missing = storyboardDraftIssues(next.shots);
      setIssues(missing);
      if (missing.length) {
        const first = next.shots.find((shot) => !shot.image_prompt_body.trim() || !shot.video_prompt_body.trim());
        fields.current.get(first?.stable_shot_key)?.focus();
        return;
      }
      await onComplete(next.manifest);
    } finally { setConfirming(false); }
  }

  const approach = state.manifest.creative_approach || (outline?.beats || []).map((beat) => beat.message || beat.purpose).join("；").slice(0, 150);
  const disabled = busy || confirming || Boolean(recoveryConflict);
  const actualFrames = (state.manifest.shots || []).reduce((sum, shot) => sum + (shot.duration_frames || 0), 0);
  return <div className="storyboard-prompt-editor">
    <section className="storyboard-approach" aria-labelledby="storyboard-approach-title">
      <div className="storyboard-prompt-heading"><h3 id="storyboard-approach-title">创作思路</h3><AutosaveStatus state={state.status} onRetry={() => void flush()} /></div>
      <p>{approach || "围绕创作目标呈现产品，通过镜头的前后衔接完成叙事。"}</p>
    </section>
    {state.error && <InlineMessage tone="error"><span>{state.error}</span></InlineMessage>}
    {recoveryConflict && <InlineMessage tone="warning"><div>
      <p>服务器已有更新，同时检测到本地未保存草稿。当前显示服务器版本，请选择要继续编辑的内容。</p>
      <div className="storyboard-shot-actions">
        <button className="secondary-button compact" onClick={() => {
          const recovered = recoveryConflict;
          setRecoveryConflict(null);
          edit(recovered);
        }} type="button">恢复本地草稿</button>
        <button className="secondary-button compact" onClick={() => {
          try { localStorage.removeItem(cacheKey); } catch { /* Optional browser storage. */ }
          setRecoveryConflict(null);
        }} type="button">保留服务器版本</button>
      </div>
    </div></InlineMessage>}
    {issues.length > 0 && <InlineMessage tone="warning"><span>{issues.join("；")}</span></InlineMessage>}
    {!state.dirty && actualFrames > 0 && targetDurationFrames > 0 && actualFrames !== targetDurationFrames && <InlineMessage tone="warning"><span>当前分镜合计 {(actualFrames / state.manifest.fps).toFixed(1)} 秒，目标 {(targetDurationFrames / state.manifest.fps).toFixed(1)} 秒；可继续编辑或在剪辑阶段调整，不会自动增删镜头。</span></InlineMessage>}
    {deleted && <div className="storyboard-delete-undo" role="status"><span>已移除分镜 {deleted.index + 1}，历史产物保留</span><button className="secondary-button compact" disabled={disabled} onClick={undoDelete} type="button"><ArrowCounterClockwise size={14} />撤销</button></div>}
    <section className="storyboard-prompt-list" aria-label="分镜提示词">
      {state.shots.map((shot, index) => <article className="storyboard-prompt-shot" key={shot.stable_shot_key} aria-labelledby={`title-${shot.stable_shot_key}`}>
        <header className="storyboard-prompt-heading">
          <h3 id={`title-${shot.stable_shot_key}`}>分镜 {String(index + 1).padStart(2, "0")}</h3>
          <div className="storyboard-shot-actions">
            <button className="secondary-button compact" disabled={disabled} onClick={() => addShot(index)} type="button" aria-label={`在分镜 ${index + 1} 后插入`}><Plus size={14} /><span>插入</span></button>
            <button className="secondary-button compact" disabled={disabled} onClick={() => removeShot(index)} type="button" aria-label={`删除分镜 ${index + 1}`}><Trash size={14} /><span>删除</span></button>
          </div>
        </header>
        <div className="storyboard-prompt-columns">
          {[["image", "图片提示词", "描述这一张静态画面的主体、场景与构图…"], ["video", "视频提示词", "描述基于分镜图的动作、运镜与声音…"]].map(([part, label, placeholder]) => <label key={part}>
            <span>{label}</span>
            <textarea aria-label={`分镜 ${index + 1} ${label}`} disabled={disabled} maxLength={8000} placeholder={placeholder} rows={10}
              ref={part === "image" ? (node) => { if (node) fields.current.set(shot.stable_shot_key, node); else fields.current.delete(shot.stable_shot_key); } : undefined}
              onBlur={() => void flush()}
              onChange={(event) => edit((shots) => shots.map((item) => item.stable_shot_key === shot.stable_shot_key ? { ...item, [`${part}_prompt_body`]: event.target.value } : item))}
              value={shot[`${part}_prompt_body`]} />
          </label>)}
        </div>
      </article>)}
      <footer className="storyboard-prompt-footer">
        <button className="secondary-button compact" disabled={disabled} onClick={() => addShot()} type="button"><Plus size={16} />添加分镜</button>
        <button className="primary-button" disabled={disabled} onClick={() => void complete()} type="button">{confirming ? "正在确认…" : approved && !state.dirty ? "进入分镜图片" : "确认并进入分镜图片"}<ArrowRight size={16} /></button>
      </footer>
    </section>
  </div>;
});
