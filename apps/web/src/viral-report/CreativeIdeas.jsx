import { Button } from "../ui/system/Button.jsx";
import { useEffect, useRef, useState } from "react";
import { registerAccountFlusher } from "../accounts/account-client.js";

export function CreativeIdeas({ ideas, selectedId, onSelect, busy, onRegenerate, onRevisionOpenChange, revisionSupported }) {
  const [confirmId, setConfirmId] = useState("");
  const [drafts, setDrafts] = useState({});
  const textarea = useRef(null);
  const triggers = useRef({});
  useEffect(() => {
    if (!confirmId) return undefined;
    onRevisionOpenChange(true);
    textarea.current?.focus({ preventScroll: true });
    textarea.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
    const unregister = registerAccountFlusher(() => { throw new Error("请先提交或取消本条修改，意见仍保留在当前页面"); });
    const warn = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => {
      onRevisionOpenChange(false);
      unregister();
      window.removeEventListener("beforeunload", warn);
    };
  }, [confirmId, onRevisionOpenChange]);
  function cancel() {
    const trigger = triggers.current[confirmId];
    setConfirmId("");
    trigger?.focus();
  }
  return <section className="creative-ideas" aria-label="三个创意方向">
    {ideas.map((idea) => {
      const notes = drafts[idea.id] || "";
      return <article className={"creative-idea " + (selectedId === idea.id ? "is-selected" : "")} key={idea.id}>
        <label className="creative-idea-choice"><input type="radio" name="creative-idea" checked={selectedId === idea.id} disabled={busy || Boolean(confirmId)} onChange={() => onSelect(idea.id)} /><span>{idea.name}</span></label>
        <p className="creative-idea-summary">{idea.summary}</p>
        {idea.scene_plan?.length > 0 && <details><summary>{idea.scene_plan.length} 个成片分镜 · 约 {Number(idea.scene_plan.reduce((sum, scene) => sum + scene.duration_seconds, 0).toFixed(2))} 秒</summary><p>{idea.rhythm}</p><ol>{idea.scene_plan.map(scene => <li key={scene.index}>{scene.description}（{scene.duration_seconds} 秒）</li>)}</ol></details>}
        {idea.common_rules?.length > 0 && <details><summary>贯穿全片的公共设定</summary><ul>{idea.common_rules.map(rule => <li key={rule.requirement_index}>{[rule.image_rule, rule.video_rule].filter(Boolean).join("；")}</li>)}</ul></details>}
        <div className="creative-idea-actions">
          <Button type="button" className="text-button" ref={node => { triggers.current[idea.id] = node; }} disabled={busy || Boolean(confirmId && confirmId !== idea.id)} aria-expanded={confirmId === idea.id} aria-controls={"creative-revision-" + idea.id} onClick={() => setConfirmId(idea.id)} aria-label={"AI 修订本条：" + idea.name}>AI 修订本条</Button>
        </div>
        {confirmId === idea.id && <form id={"creative-revision-" + idea.id} className="creative-rewrite-confirm" aria-label={"修订《" + idea.name + "》"} onSubmit={event => {
          event.preventDefault();
          if (!busy && revisionSupported && notes.trim()) onRegenerate(idea, notes.trim());
        }}>
          <label className="creative-revision-notes"><span>修改意见</span><textarea ref={textarea} required maxLength={2000} rows={4} value={notes} disabled={busy} onChange={event => setDrafts(values => ({ ...values, [idea.id]: event.target.value }))} placeholder="例如：保留人物居中，把场景改为雨夜地标，加强裙摆与灯光的呼应。" /></label>
          <p className="creative-revision-cost">将调用文案模型并计费，仅修改本条。</p>
          {!revisionSupported && <p className="creative-failure" role="alert">服务版本尚未更新，请更新并重启服务后刷新页面。</p>}
          <div className="creative-idea-actions"><Button type="submit" className="primary-button" disabled={busy || !revisionSupported || !notes.trim()}>确认并 AI 修订</Button><Button type="button" className="text-button" disabled={busy} onClick={cancel}>取消</Button></div>
        </form>}
      </article>;
    })}
  </section>;
}
