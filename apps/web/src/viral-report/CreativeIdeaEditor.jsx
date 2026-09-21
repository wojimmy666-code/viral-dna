import { useEffect, useRef, useState } from "react";
import { registerAccountFlusher } from "../accounts/account-client.js";
import { creativeBriefText, creativeRequirements } from "./creative-workflow.js";

export function CreativeIdeaEditor({ context, busy, onSave, onCancel }) {
  const { idea, batch, feedback } = context;
  const requirements = creativeRequirements(feedback);
  const sameBrief = feedback === creativeBriefText(batch);
  const [draft, setDraft] = useState(() => ({
    ...structuredClone(idea),
    common_rules: sameBrief ? structuredClone(idea.common_rules || []) : [],
    scene_plan: idea.scene_plan?.length ? structuredClone(idea.scene_plan)
      : idea.key_scenes.map((description, i) => ({ index: i + 1, description, duration_seconds: 1, transition: "cut" })),
  }));
  const [rules, setRules] = useState(() => requirements.map(item =>
    (sameBrief && batch.requirement_rules?.find(rule => rule.requirement_index === item.index))
      || { requirement_index: item.index, kind: "per_scene", expected_scene_count: null }));
  const [confirmed, setConfirmed] = useState([]);
  const [error, setError] = useState("");
  const heading = useRef(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView({ behavior: "instant", block: "start" });
    const unregister = registerAccountFlusher(() => { throw new Error("请先保存或取消当前创意修订，草稿已保留"); });
    const warn = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => { unregister(); window.removeEventListener("beforeunload", warn); };
  }, []);
  function update(values) { setDraft(old => ({ ...old, ...values })); setConfirmed([]); }
  function updateScene(index, values) {
    update({ scene_plan: draft.scene_plan.map((scene, i) => i === index ? { ...scene, ...values } : scene) });
  }
  function updateRule(index, values) {
    setRules(old => old.map(rule => rule.requirement_index === index ? { ...rule, ...values } : rule));
    setConfirmed([]);
    if (values.kind && values.kind !== "shared") update({ common_rules: draft.common_rules.filter(rule => rule.requirement_index !== index) });
  }
  function updateCommon(index, field, value) {
    const current = draft.common_rules.find(rule => rule.requirement_index === index)
      || { requirement_index: index, image_rule: "", video_rule: "" };
    update({ common_rules: [...draft.common_rules.filter(rule => rule.requirement_index !== index), { ...current, [field]: value }] });
  }
  async function save(event) {
    event.preventDefault(); setError("");
    if (draft.scene_plan.some(scene => !scene.description.trim() || !Number.isFinite(Number(scene.duration_seconds)) || Number(scene.duration_seconds) <= 0)) {
      setError("请填写每个场景的内容与有效时长。"); return;
    }
    await onSave({
      expected_revision: batch.revision,
      source_fingerprint: batch.review_source_fingerprint,
      feedback,
      idea: { ...draft, scene_plan: draft.scene_plan.map((scene, i) => ({ ...scene, index: i + 1, duration_seconds: Number(scene.duration_seconds) })), requirement_checks: [] },
      requirement_rules: rules,
      confirmed_requirements: confirmed,
    });
  }
  return <form className="creative-idea-editor" onSubmit={save} aria-label="修订创意">
    <header><h3 ref={heading} tabIndex={-1}>修订《{idea.name}》</h3><p>保存为新版本，不调用模型。未确认的要求保留为待核对。</p></header>
    <fieldset disabled={busy}>
      <label>片名<input required maxLength={80} value={draft.name} onChange={event => update({ name: event.target.value })} /></label>
      <label>创意简述<textarea required maxLength={220} rows={3} value={draft.summary} onChange={event => update({ summary: event.target.value })} /></label>
      <details open><summary>公共设定与要求分类</summary>
        {requirements.map(item => {
          const rule = rules.find(rule => rule.requirement_index === item.index);
          const common = draft.common_rules.find(rule => rule.requirement_index === item.index);
          return <div className="creative-rule-editor" key={item.index}>
            <label>{item.text}<select aria-label={item.text + "的适用范围"} value={rule.kind} onChange={event => updateRule(item.index, { kind: event.target.value, expected_scene_count: null })}>
              <option value="structure">全片结构</option><option value="shared">贯穿全片</option><option value="per_scene">逐场景内容</option>
            </select></label>
            {rule.kind === "structure" && <label>精确场景数量（未指定则留空）<input type="number" min={1} max={200} value={rule.expected_scene_count ?? ""} onChange={event => updateRule(item.index, { expected_scene_count: event.target.value ? Number(event.target.value) : null })} /></label>}
            {rule.kind === "shared" && <div className="creative-common-fields">
              <label>静态画面设定<textarea rows={2} maxLength={500} value={common?.image_rule || ""} onChange={event => updateCommon(item.index, "image_rule", event.target.value)} /></label>
              <label>动作与运镜设定<textarea rows={2} maxLength={500} value={common?.video_rule || ""} onChange={event => updateCommon(item.index, "video_rule", event.target.value)} /></label>
            </div>}
          </div>;
        })}
      </details>
      <section className="creative-scenes-editor" aria-label="完整场景规划">
        <h4>完整场景规划 · {draft.scene_plan.length} 个</h4>
        {draft.scene_plan.map((scene, i) => <div className="creative-scene-editor" key={i}>
          <label>场景 {i + 1}<textarea required rows={4} maxLength={1200} value={scene.description} onChange={event => updateScene(i, { description: event.target.value })} /></label>
          <div className="creative-editor-row">
            <label>时长（秒）<input required type="number" step="0.1" min="0.1" max={60} value={scene.duration_seconds} onChange={event => updateScene(i, { duration_seconds: event.target.value })} /></label>
            <label>转场<select value={scene.transition} onChange={event => updateScene(i, { transition: event.target.value })}><option value="cut">硬切</option><option value="continuous">连续</option><option value="dissolve">叠化</option></select></label>
            <button type="button" className="text-button" disabled={draft.scene_plan.length < 2} onClick={() => update({ scene_plan: draft.scene_plan.filter((_, index) => index !== i) })}>删除场景 {i + 1}</button>
          </div>
        </div>)}
        <button type="button" className="secondary-button" disabled={draft.scene_plan.length >= 200} onClick={() => update({ scene_plan: [...draft.scene_plan, { index: draft.scene_plan.length + 1, description: "", duration_seconds: 1, transition: "cut" }] })}>添加场景</button>
      </section>
      {requirements.length > 0 && <section className="creative-human-checks" aria-label="人工核对">
        <h4>人工核对</h4><p>逐项对照上面的公共设定与全部场景；修改内容后需重新核对。</p>
        {requirements.map(item => <label key={item.index}><input type="checkbox" checked={confirmed.includes(item.index)} onChange={event => setConfirmed(old => event.target.checked ? [...old, item.index] : old.filter(index => index !== item.index))} /><span>我已核对：{item.text}</span></label>)}
      </section>}
      {error && <p role="alert" className="creative-failure">{error}</p>}
      <div className="creative-editor-actions"><button type="submit" className="primary-button">保存修订</button><button type="button" className="secondary-button" onClick={onCancel}>取消编辑</button></div>
    </fieldset>
  </form>;
}
