import { useState } from "react";
import { CreativeBriefChecks } from "./CreativeBriefChecks.jsx";
import { ideaReviewState } from "./creative-workflow.js";

export function CreativeIdeas({ ideas, brief = "", selectedId, onSelect, busy, onRegenerate, onEdit }) {
  const [confirmId, setConfirmId] = useState("");
  return <section className="creative-ideas" aria-label="三个创意方向">
    {ideas.map((idea) => {
      const state = ideaReviewState(idea, brief);
      const stale = idea.review_brief != null && idea.review_brief !== brief;
      return <article className={"creative-idea " + (selectedId === idea.id ? "is-selected" : "")} key={idea.id}>
        <label className="creative-idea-choice"><input type="radio" name="creative-idea" checked={selectedId === idea.id} disabled={state !== "ready" || busy} onChange={() => onSelect(idea.id)} /><span>{idea.name}</span></label>
        <p className={"creative-review-label " + (state === "ready" ? "" : "needs-attention")}>{state === "ready" ? (idea.human_review ? "人工核对 · 可展开" : "可展开") : state === "needs_revision" ? "待修订" : "待核对"}</p>
        <p className="creative-idea-summary">{idea.summary}</p>
        {idea.scene_plan?.length > 0 && <details><summary>{idea.scene_plan.length} 个成片分镜 · 约 {Number(idea.scene_plan.reduce((sum, scene) => sum + scene.duration_seconds, 0).toFixed(2))} 秒</summary><p>{idea.rhythm}</p><ol>{idea.scene_plan.map(scene => <li key={scene.index}>{scene.description}（{scene.duration_seconds} 秒）</li>)}</ol></details>}
        {stale && <p className="creative-review-note">补充要求已变化，此方向仍保留原版本；请按当前要求修订后展开。</p>}
        {idea.review_issues?.length > 0 && <details className="creative-review-note"><summary>查看 {idea.review_issues.length} 项具体问题</summary><ul>{idea.review_issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></details>}
        {idea.common_rules?.length > 0 && <details><summary>贯穿全片的公共设定</summary><ul>{idea.common_rules.map(rule => <li key={rule.requirement_index}>{[rule.image_rule, rule.video_rule].filter(Boolean).join("；")}</li>)}</ul></details>}
        <p className="creative-memory"><strong>记忆画面</strong>{idea.visual_memory}</p>
        <details><summary>关键画面与品类适配</summary><ul>{idea.key_scenes.map((scene, index) => <li key={index}>{scene}</li>)}</ul><dl><div><dt>品类适配</dt><dd>{idea.category_fit}</dd></div><div><dt>借鉴</dt><dd>{idea.borrowed}</dd></div><div><dt>改变</dt><dd>{idea.changed}</dd></div></dl><CreativeBriefChecks checks={idea.brief_checks} />{idea.assumptions.length > 0 && <p>待确认：{idea.assumptions.join("；")}</p>}</details>
        <div className="creative-idea-actions">
          <button type="button" className="text-button" disabled={busy} onClick={() => onEdit?.(idea)}>修改与核对</button>
          <button type="button" className="text-button" disabled={busy} onClick={() => setConfirmId(idea.id)} aria-label={"只重写" + idea.name}>{state === "ready" ? "只换这一条" : "AI 修订本条"}</button>
        </div>
        {confirmId === idea.id && <div className="creative-rewrite-confirm"><p>将再次调用文案模型并计费，只处理此方向，另外两条保留。</p><button type="button" className="secondary-button" disabled={busy} onClick={() => { setConfirmId(""); onRegenerate(idea); }}>确认调用模型</button><button type="button" className="text-button" disabled={busy} onClick={() => setConfirmId("")}>取消</button></div>}
      </article>;
    })}
  </section>;
}
