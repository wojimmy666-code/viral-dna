import { useEffect, useRef, useState } from "react";
import { Button } from "../ui/system/Button.jsx";
import { VisualStyleControl } from "./VisualStyleControl.jsx";

export function ProductionStyleControl({ batchId, request, disabled, onPending, onAvailable }) {
  const [state, setState] = useState(null), [error, setError] = useState(""), [reload, setReload] = useState(0);
  const active = useRef(false), callbacks = useRef({ onPending, onAvailable });
  callbacks.current = { onPending, onAvailable };
  const path = `/viral-concept-sets/${batchId}/production-style`;
  useEffect(() => {
    let current = true; active.current = true;
    setState(null); setError(""); callbacks.current.onPending?.(true); callbacks.current.onAvailable?.(false);
    request(path, { signal: AbortSignal.timeout(15000) }).then(result => { if (current) { setState(result); callbacks.current.onAvailable?.(true); } })
      .catch(failure => { if (current) { setError(failure.message); callbacks.current.onAvailable?.(false); } })
      .finally(() => { if (current) callbacks.current.onPending?.(false); });
    return () => { current = false; active.current = false; callbacks.current.onPending?.(false); };
  }, [path, request, reload]);
  async function save(value) {
    try {
      const next = await request(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: state.revision, visual_style: value }), signal: AbortSignal.timeout(15000) });
      if (active.current) { setState(next); setError(""); }
    } catch (failure) {
      if (Number(failure.status || failure.status_code) !== 409 || !active.current) throw failure;
      let latest;
      try { latest = await request(path, { signal: AbortSignal.timeout(15000) }); }
      catch {
        if (active.current) setError("风格版本冲突，暂时无法读取最新版本。请关闭选择器后重新读取。");
        throw new Error("风格版本冲突，暂时无法读取最新版本。当前选择未保存，请关闭选择器后重新读取。");
      }
      if (active.current) setState(latest);
      // Keep the modal's pending choice. Never silently retry a conflicting write.
      throw new Error(`其他页面已更新风格，已读取最新版本（${latest.snapshot?.label || "不附加风格"}）。当前选择仍保留，请核对后再次应用。`);
    }
  }
  return <div className="production-style-picker">
    {state && <VisualStyleControl label="风格" value={state.selection} snapshot={state.snapshot} request={request} disabled={disabled} onChange={save} onPending={onPending} onAvailable={onAvailable} />}
    {!state && !error && <p className="visual-style-status" role="status">正在读取制作风格…</p>}
    {error && <p className="visual-style-error" role="alert">{error}<Button variant="text" size="compact" onClick={() => setReload(count => count + 1)}>重新读取</Button></p>}
  </div>;
}

export function ShotStyleControl({ context, shotKey, editorRef, request, disabled, part }) {
  return <VisualStyleControl key={shotKey} label="风格" part={part} allowInherit
    value={context?.shot_styles?.[shotKey] ?? null} snapshot={context?.shot_style_snapshots?.[shotKey]} inheritedSnapshot={context?.visual_style_snapshot}
    request={request} disabled={disabled || !Object.hasOwn(context || {}, "visual_style")}
    onChange={(value, compiled) => editorRef.current.applyStyle(value, compiled, shotKey)} />;
}
