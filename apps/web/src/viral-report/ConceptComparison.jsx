import {
  CaretDown,
  Check,
  CircleNotch,
  MagicWand,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { findConceptDuplicateFields, STRATEGY_META } from "./viral-report-ui.js";

const LEVEL_LABELS = { low: "较低", medium: "中等", high: "较高" };

export function ConceptComparison({ conceptSet, publishingId, onPublish }) {
  const [selectedId, setSelectedId] = useStateSafe(conceptSet?.concepts?.[0]?.id || "");
  const selected = conceptSet?.concepts?.find((item) => item.id === selectedId) || conceptSet?.concepts?.[0];
  if (!conceptSet || !selected) return null;
  const duplicateFields = findConceptDuplicateFields(conceptSet.concepts);
  const isStale = conceptSet.status === "stale";

  return (
    <section className="concept-comparison">
      <header className="viral-section-header">
        <div><h2>比较并选择新视频方案</h2><p>选择后只创建可编辑方案，不会立即生成图片或视频。</p></div>
      </header>

      {duplicateFields.length > 0 && (
        <div className="concept-diversity-warning" role="status">
          <WarningCircle size={18} />
          <div><strong>检测到旧方案内容重复</strong><p>重复字段：{duplicateFields.join("、")}。建议重新生成后再创建创作方案。</p></div>
        </div>
      )}

      <div className="concept-summary-grid" role="radiogroup" aria-label="复刻方案">
        {conceptSet.concepts.map((concept) => {
          const meta = STRATEGY_META[concept.strategy] || { label: concept.strategy, tone: "faithful" };
          const active = concept.id === selected.id;
          return (
            <button className={`concept-summary-card ${meta.tone} ${active ? "active" : ""}`} type="button" role="radio" aria-checked={active} key={concept.id} onClick={() => setSelectedId(concept.id)}>
              <span className="concept-radio">{active && <Check size={13} weight="bold" />}</span>
              <h3>{concept.name}</h3>
              <p>{concept.one_liner}</p>
              <span className="concept-strategy-goal">{meta.goal}</span>
              <dl><div><dt>制作难度</dt><dd>{LEVEL_LABELS[concept.difficulty]}</dd></div><div><dt>成本等级</dt><dd>{LEVEL_LABELS[concept.estimated_cost_level]}</dd></div><div><dt>改动幅度</dt><dd>{meta.changeLevel}</dd></div></dl>
            </button>
          );
        })}
      </div>

      <article className="concept-detail">
        <div className="concept-detail-heading">
          <div><span>{STRATEGY_META[selected.strategy]?.label}</span><h3>{selected.name}</h3><p>{selected.why_it_can_work}</p></div>
          <button className="primary-button" type="button" onClick={() => onPublish(selected)} disabled={Boolean(publishingId) || isStale}>
            {publishingId === selected.id ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}
            {isStale ? "重新生成后可创建" : "创建创作方案"}
          </button>
        </div>
        <p className="concept-retained-summary">本策略锁定 {selected.retained_dna.length} 项内容 DNA，并以不同方式重写逐镜头指令。</p>
        <div className="concept-detail-columns">
          <div><strong>本方案重点改进</strong><ul>{selected.improvements.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><strong>本方案制作风险</strong><ul>{selected.risks.map((item) => <li key={item}><WarningCircle size={15} />{item}</li>)}</ul></div>
        </div>
        <details className="concept-shot-disclosure">
          <summary>查看逐镜头创作指令 <span>{selected.shots.length} 个分镜</span><CaretDown size={16} /></summary>
          <div className="concept-shot-list">
            {selected.shots.map((shot) => (
              <article key={shot.source_shot_id}>
                <span className="concept-shot-number">{String(shot.index).padStart(2, "0")}</span>
                <div className="concept-shot-content">
                  <span className="concept-shot-meta">{shot.traffic_role} · {shot.duration_seconds.toFixed(1)} 秒</span>
                  <h4>{shot.title}</h4>
                  <p className="concept-shot-video-prompt">{shot.video_prompt}</p>
                  <details className="concept-shot-image-prompt">
                    <summary>图片提示词</summary>
                    <p>{shot.image_prompt}</p>
                  </details>
                </div>
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
