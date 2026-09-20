import {
  CaretDown,
  Check,
  CircleNotch,
  MagicWand,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { PromptSectionView } from "../prompt-presentation/PromptSectionView.jsx";
import { CreativeBriefChecks } from "./CreativeBriefChecks.jsx";
import { findConceptDuplicateFields, STRATEGY_META } from "./viral-report-ui.js";

const LEVEL_LABELS = { low: "较低", medium: "中等", high: "较高" };

export function ConceptComparison({ conceptSet, historical = false, publishingId, onPublish }) {
  const [selectedId, setSelectedId] = useStateSafe(conceptSet?.concepts?.[0]?.id || "");
  const selected = conceptSet?.concepts?.find((item) => item.id === selectedId) || conceptSet?.concepts?.[0];
  if (!conceptSet || !selected) return null;
  const duplicateFields = findConceptDuplicateFields(conceptSet.concepts);
  const isStale = conceptSet.status === "stale";
  const creative = conceptSet.phase === "expanded";

  return (
    <section className="concept-comparison">
      <header className="viral-section-header">
        <div>
          <h2>{creative ? selected.name : historical ? "历史完整方案" : "比较并选择新视频方案"}</h2>
          {!historical && (
            <p>
              {creative ? "确认后创建可编辑制作方案，不会自动生成图片或视频。" : conceptSet.category_profile
                ? `三套方案均基于“${conceptSet.category_profile.display_name}”生成；选择后只创建可编辑方案。`
                : "选择后只创建可编辑方案，不会立即生成图片或视频。"}
            </p>
          )}
        </div>
      </header>

      {duplicateFields.length > 0 && (
        <div className="concept-diversity-warning" role="status">
          <WarningCircle size={18} />
          <div><strong>检测到旧方案内容重复</strong><p>重复字段：{duplicateFields.join("、")}。建议重新生成后再创建创作方案。</p></div>
        </div>
      )}

      {!creative && <div className="concept-summary-grid" role="radiogroup" aria-label="复刻方案">
        {conceptSet.concepts.map((concept) => {
          const meta = STRATEGY_META[concept.strategy] || { label: concept.strategy, tone: "faithful" };
          const active = concept.id === selected.id;
          return (
            <button className={`concept-summary-card ${meta.tone} ${active ? "active" : ""}`} type="button" role="radio" aria-checked={active} key={concept.id} onClick={() => setSelectedId(concept.id)}>
              <span className="concept-radio">{active && <Check size={13} weight="bold" />}</span>
              <span className="concept-strategy-label">{meta.label}</span>
              <h3>{concept.name}</h3>
              <p>{concept.one_liner}</p>
              {concept.hook && <span className="concept-card-signal"><small>钩子</small>{concept.hook}</span>}
              {concept.visual_memory && <span className="concept-card-signal"><small>记忆点</small>{concept.visual_memory}</span>}
              <dl><div><dt>制作难度</dt><dd>{LEVEL_LABELS[concept.difficulty]}</dd></div><div><dt>成本等级</dt><dd>{LEVEL_LABELS[concept.estimated_cost_level]}</dd></div><div><dt>改动幅度</dt><dd>{meta.changeLevel}</dd></div></dl>
            </button>
          );
        })}
      </div>}

      <article className="concept-detail">
        <div className="concept-creative-brief">
          <div><small>创意主张</small><strong>{selected.thesis || selected.why_it_can_work}</strong></div>
          <div><small>叙事结构</small><span>{selected.narrative_structure || "沿原片结构推进"}</span></div>
          <div><small>结尾兑现</small><span>{selected.payoff || selected.one_liner}</span></div>
          <div><small>品类适配</small><span>{selected.category_fit_summary || selected.target_audience}</span></div>
          {selected.changed_elements?.length > 0 && (
            <div className="concept-change-list"><small>核心改动</small><span>{selected.changed_elements.map((item) => <em key={item}>{item}</em>)}</span></div>
          )}
        </div>
        <div className="concept-detail-actions">
          <button className="primary-button" type="button" onClick={() => onPublish(selected)} disabled={Boolean(publishingId) || isStale}>
            {publishingId === selected.id ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}
            {isStale ? "重新生成后可创建" : conceptSet.published_result ? "进入已创建方案" : creative ? "确认分镜，进入制作" : "创建创作方案"}
          </button>
        </div>
        {creative && selected.required_assets.length > 0 && <details className="concept-risk-disclosure"><summary>所需资产 · {selected.required_assets.length} 项</summary><ul>{selected.required_assets.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
        {creative && selected.brief_checks?.length > 0 && <details className="concept-risk-disclosure"><summary>补充想法落实说明</summary><CreativeBriefChecks checks={selected.brief_checks} /></details>}
        {selected.risks.length > 0 && (
          <details className="concept-risk-disclosure">
            <summary>
              <span className="concept-risk-title"><WarningCircle size={16} />制作提醒</span>
              <span className="concept-disclosure-meta">{selected.risks.length} 项</span>
              <CaretDown size={16} />
            </summary>
            <ul>{selected.risks.map((item) => <li key={item}><WarningCircle size={15} />{item}</li>)}</ul>
          </details>
        )}
        <details className="concept-shot-disclosure">
          <summary>
            <span className="concept-disclosure-title">查看逐镜头创作指令</span>
            <span className="concept-disclosure-meta">保留 {selected.retained_dna.length} 项 DNA · {selected.shots.length} 个分镜</span>
            <CaretDown size={16} />
          </summary>
          <div className="concept-shot-list">
            {selected.shots.map((shot) => (
              <article key={shot.index}>
                <span className="concept-shot-number">{String(shot.index).padStart(2, "0")}</span>
                <div className="concept-shot-content">
                  <span className="concept-shot-meta">{shot.traffic_role} · {shot.duration_seconds.toFixed(1)} 秒</span>
                  <h4>{shot.title}</h4>
                  {creative && <><p>{shot.description}</p><details><summary>图片提示词</summary><PromptSectionView prompt={shot.image_prompt} /></details><strong>视频提示词</strong></>}
                  <PromptSectionView prompt={shot.video_prompt} />
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
