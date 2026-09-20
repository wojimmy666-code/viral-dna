import { CreativeBriefChecks } from "./CreativeBriefChecks.jsx";

export function CreativeIdeas({ ideas, selectedId, onSelect, busy, onRegenerate }) {
  return <section className="creative-ideas" aria-label="三个创意方向">
    {ideas.map((idea) => <article className={`creative-idea ${selectedId === idea.id ? "is-selected" : ""}`} key={idea.id}>
      <label className="creative-idea-choice"><input type="radio" name="creative-idea" checked={selectedId === idea.id} onChange={() => onSelect(idea.id)} /><span>{idea.name}</span></label>
      <p className="creative-idea-summary">{idea.summary}</p>
      <p className="creative-memory"><strong>记忆画面</strong>{idea.visual_memory}</p>
      <details><summary>关键画面与品类适配</summary><ul>{idea.key_scenes.map((scene, index) => <li key={index}>{scene}</li>)}</ul><dl><div><dt>品类适配</dt><dd>{idea.category_fit}</dd></div><div><dt>借鉴</dt><dd>{idea.borrowed}</dd></div><div><dt>改变</dt><dd>{idea.changed}</dd></div></dl><CreativeBriefChecks checks={idea.brief_checks} />{idea.assumptions.length > 0 && <p>待确认：{idea.assumptions.join("；")}</p>}</details>
      <button type="button" className="text-button" disabled={busy} onClick={() => onRegenerate(idea)} aria-label={`只重写${idea.name}`}>只换这一条</button>
    </article>)}
  </section>;
}
