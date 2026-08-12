import {
  CaretDown,
  Check,
  CircleNotch,
  MagicWand,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { STRATEGY_META } from "./viral-report-ui.js";

const LEVEL_LABELS = { low: "较低", medium: "中等", high: "较高" };

export function ConceptComparison({ conceptSet, publishingId, onPublish }) {
  const [selectedId, setSelectedId] = useStateSafe(conceptSet?.concepts?.[0]?.id || "");
  const selected = conceptSet?.concepts?.find((item) => item.id === selectedId) || conceptSet?.concepts?.[0];
  if (!conceptSet || !selected) return null;

  return (
    <section className="concept-comparison">
      <header className="viral-section-header">
        <div><span>3 CREATIVE ROUTES</span><h2>比较并选择新视频方案</h2><p>选择方案不会立即生成图片或视频；确认后才创建可继续编辑的创作方案。</p></div>
        <span className="viral-basis-badge">本批次额外模型成本 ¥0.00</span>
      </header>

      <div className="concept-summary-grid" role="radiogroup" aria-label="复刻方案">
        {conceptSet.concepts.map((concept) => {
          const meta = STRATEGY_META[concept.strategy] || { label: concept.strategy, tone: "faithful" };
          const active = concept.id === selected.id;
          return (
            <button className={`concept-summary-card ${meta.tone} ${active ? "active" : ""}`} type="button" role="radio" aria-checked={active} key={concept.id} onClick={() => setSelectedId(concept.id)}>
              <span className="concept-radio">{active && <Check size={13} weight="bold" />}</span>
              <span className="concept-strategy">{meta.label}</span>
              <h3>{concept.name}</h3>
              <p>{concept.one_liner}</p>
              <dl><div><dt>制作难度</dt><dd>{LEVEL_LABELS[concept.difficulty]}</dd></div><div><dt>成本等级</dt><dd>{LEVEL_LABELS[concept.estimated_cost_level]}</dd></div><div><dt>分镜</dt><dd>{concept.shots.length} 个</dd></div></dl>
            </button>
          );
        })}
      </div>

      <article className="concept-detail">
        <div className="concept-detail-heading">
          <div><span>{STRATEGY_META[selected.strategy]?.label}</span><h3>{selected.name}</h3><p>{selected.why_it_can_work}</p></div>
          <button className="primary-button" type="button" onClick={() => onPublish(selected)} disabled={Boolean(publishingId)}>
            {publishingId === selected.id ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}
            创建创作方案
          </button>
        </div>
        <div className="concept-detail-columns">
          <div><strong>保留 DNA</strong><ul>{selected.retained_dna.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><strong>重点改进</strong><ul>{selected.improvements.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><strong>制作风险</strong><ul>{selected.risks.map((item) => <li key={item}><WarningCircle size={15} />{item}</li>)}</ul></div>
        </div>
        <details className="concept-shot-disclosure">
          <summary>查看逐镜头创作指令 <span>{selected.shots.length} 个分镜</span><CaretDown size={16} /></summary>
          <div className="concept-shot-list">
            {selected.shots.map((shot) => (
              <article key={shot.source_shot_id}>
                <span className="concept-shot-number">{String(shot.index).padStart(2, "0")}</span>
                <div><span>{shot.traffic_role} · {shot.duration_seconds.toFixed(1)} 秒</span><h4>{shot.title}</h4><p>{shot.video_prompt}</p><details><summary>图片提示词</summary><p>{shot.image_prompt}</p></details></div>
              </article>
            ))}
          </div>
        </details>
      </article>
    </section>
  );
}

// Preserve the selected card across local renders while resetting for a new batch.
function useStateSafe(initialValue) {
  const [value, setValue] = useState(initialValue);
  useEffect(() => setValue(initialValue), [initialValue]);
  return [value, setValue];
}
