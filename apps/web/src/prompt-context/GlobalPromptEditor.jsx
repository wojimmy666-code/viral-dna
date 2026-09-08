import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { PromptSectionHeader } from "./PromptSectionHeader.jsx";
import { combinePrompt, createGlobalPromptSession } from "./global-prompt-session.js";
import "./prompt-context.css";

export const GlobalPromptEditor = forwardRef(function GlobalPromptEditor({ path, part = "both", request, disabled = false, onChange }, ref) {
  const callbacks = useRef({ request, onChange });
  callbacks.current = { request, onChange };
  const session = useRef(null);
  const timer = useRef(null);
  const recoveryRef = useRef(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [recovery, setRecovery] = useState(null);
  const cacheKey = `viraldna:global-prompts:${path}`;
  useEffect(() => {
    let active = true;
    session.current = null;
    setState(null); setError("");
    callbacks.current.request(path).then(initial => {
      if (!active) return;
      const next = createGlobalPromptSession(initial, {
        save: payload => callbacks.current.request(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
        onChange: value => {
          if (!active) return;
          setState(value); callbacks.current.onChange?.(value.values);
          try {
            if (!recoveryRef.current) {
              if (value.dirty) localStorage.setItem(cacheKey, JSON.stringify({ expected_revision_id: value.revision.id, ...value.values }));
              else localStorage.removeItem(cacheKey);
            }
          } catch { /* Storage is optional; in-memory drafts remain. */ }
        },
      });
      session.current = next;
      setState(next.snapshot()); callbacks.current.onChange?.(next.snapshot().values);
      try {
        const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
        if (cached && typeof cached.common_image_prompt === "string" && typeof cached.common_video_prompt === "string") {
          // Never silently apply a recovered draft against a different revision.
          if (cached.expected_revision_id === initial.id) {
            next.edit("image", cached.common_image_prompt); next.edit("video", cached.common_video_prompt);
            timer.current = window.setTimeout(() => void next.flush(), 900);
          } else {
            recoveryRef.current = cached; setRecovery(cached);
            setError("发现旧版本的未保存全局草稿，请展开核对后选择保留哪个版本。");
          }
        }
      } catch { /* Keep the server version if local storage is unavailable. */ }
    }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; window.clearTimeout(timer.current); };
  }, [path, reload]);
  async function flush() {
    window.clearTimeout(timer.current);
    if (recoveryRef.current) return false;
    // Initial page hydration has no editable draft to save. Generation reads
    // the persisted context on the server even if this GET is still pending.
    return session.current ? session.current.flush() : !error;
  }
  useImperativeHandle(ref, () => ({ flush }), [error]);
  useEffect(() => {
    const beforeUnload = event => { if (session.current?.snapshot().dirty) { event.preventDefault(); event.returnValue = ""; } };
    const refresh = () => { if (!session.current?.snapshot().dirty && !recoveryRef.current) setReload(value => value + 1); };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("focus", refresh);
    return () => { window.removeEventListener("beforeunload", beforeUnload); window.removeEventListener("focus", refresh); };
  }, []);
  function resolveRecovery(useLocal) {
    const cached = recoveryRef.current;
    recoveryRef.current = null; setRecovery(null); setError("");
    if (useLocal && cached) {
      session.current.edit("image", cached.common_image_prompt);
      session.current.edit("video", cached.common_video_prompt);
      timer.current = window.setTimeout(() => void flush(), 900);
    } else {
      try { localStorage.removeItem(cacheKey); } catch { /* Optional cache. */ }
    }
  }
  function edit(type, value) {
    session.current?.edit(type, value);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), 900);
  }
  const parts = part === "both" ? ["image", "video"] : [part];
  return <div className="global-prompt-editor">
    <details onToggle={event => { if (!event.currentTarget.open) void flush(); }}>
      <PromptSectionHeader as="summary" quiet title={`全局${part === "both" ? "" : part === "image" ? "图片" : "视频"}提示词`} hint="适用于全部分镜" state={state?.status || "loading"} onRetry={() => void flush()} />
      <div className={`global-prompt-fields ${parts.length === 2 ? "is-paired" : ""}`}>
        {parts.map(type => <label key={type}>{parts.length === 2 && <span>{type === "image" ? "图片" : "视频"}提示词</span>}<textarea aria-label={`全局${type === "image" ? "图片" : "视频"}提示词`} rows={7} maxLength={8000} disabled={disabled || !state || Boolean(recovery)} value={state?.values[`common_${type}_prompt`] || ""} placeholder="可留空；只填写整片共同要求" onBlur={() => void flush()} onChange={event => edit(type, event.target.value)} /></label>)}
      </div>
    </details>
    {(error || state?.error) && <div className="prompt-context-error" role="alert"><span>{error || state.error}</span>{!recovery && <><button className="text-button" type="button" onClick={() => state ? void flush() : setReload(value => value + 1)}>重试保存</button><button className="text-button" type="button" onClick={() => setReload(value => value + 1)}>重新加载并核对</button></>}</div>}
    {recovery && <details className="prompt-recovery"><summary>核对未保存的全局草稿</summary>{["image", "video"].map(type => <label key={type}>本地全局{type === "image" ? "图片" : "视频"}草稿<textarea readOnly rows={5} value={recovery[`common_${type}_prompt`]} /></label>)}<button className="secondary-button" type="button" onClick={() => resolveRecovery(true)}>使用本地草稿</button><button className="text-button" type="button" onClick={() => resolveRecovery(false)}>保留服务器版本</button></details>}
  </div>;
});

export function PromptPreview({ common = "", local = "", label = "提示词" }) {
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  async function copy(value, kind) {
    try { await navigator.clipboard.writeText(value); setCopied(kind); setError(""); }
    catch { setError("复制失败，请选中文本后复制"); }
  }
  return <div className="prompt-preview">
    <button className="text-button" type="button" onClick={() => void copy(local, "local")}>{copied === "local" ? "已复制局部" : "复制局部"}</button>
    <details><summary>查看完整提示词</summary><textarea aria-label={`完整${label}`} readOnly rows={8} value={combinePrompt(common, local)} /><p>生成时还会附加本次参考素材与模型参数。</p><button className="text-button" type="button" onClick={() => void copy(combinePrompt(common, local), "full")}>{copied === "full" ? "已复制完整提示词" : "复制完整提示词"}</button></details>
    {error && <span role="alert">{error}</span>}
  </div>;
}
