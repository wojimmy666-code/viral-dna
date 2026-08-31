import {
  ArrowClockwise,
  CaretRight,
  CheckCircle,
  CircleNotch,
  LockSimple,
  ShieldWarning,
  Sparkle,
  Target,
} from "@phosphor-icons/react";
import {
  formatInsightTime,
  useViralInsight,
} from "./viral-report-ui.js";

export function ViralExecutiveSummary({ analysisId, request, onOpenMechanisms, onOpenReplication }) {
  const { insight, loading, error, reload } = useViralInsight({ analysisId, request });

  if (loading && !insight) {
    return (
      <section className="viral-loading-state" aria-live="polite">
        <CircleNotch className="spin" size={22} />
        <span>正在整理爆款机制与证据…</span>
      </section>
    );
  }
  if (error && !insight) {
    return (
      <section className="viral-error-state" role="alert">
        <ShieldWarning size={22} />
        <div><strong>爆款洞察暂时不可用</strong><p>{error}</p></div>
        <button type="button" onClick={() => reload()}><ArrowClockwise size={17} />重试</button>
      </section>
    );
  }
  if (!insight) return null;
  const strongestMechanism = insight.mechanisms.reduce(
    (strongest, item) => (!strongest || item.score > strongest.score ? item : strongest),
    null,
  );
  const strongestEvidence = (strongestMechanism?.evidence || [])
    .filter((item, index, items) => items.findIndex((candidate) => candidate.id === item.id) === index)
    .slice(0, 3);
  const modelSynthesized = insight.generator_id === "model-evidence-validator-v2";

  return (
    <section className="viral-executive-summary">
      <div className="viral-summary-heading">
        <div>
          <span className="viral-basis-badge">
            <Sparkle size={15} weight="fill" />
            {modelSynthesized ? "大模型综合 · 证据校验" : "证据规则整理"}
          </span>
          <h2>{insight.headline}</h2>
        </div>
      </div>

      <div className="viral-hook-callout">
        <Target size={23} weight="fill" />
        <div>
          <span>{strongestMechanism ? "最强流量抓手" : "证据状态"}</span>
          <strong>{strongestMechanism?.title || insight.headline}</strong>
          <p>{strongestMechanism?.mechanism || insight.strongest_hook}</p>
          {strongestEvidence.length > 0 && (
            <ul className="viral-hook-evidence" aria-label="关键证据">
              {strongestEvidence.map((item) => (
                <li key={item.id}>
                  <time>{formatInsightTime(item.start_seconds)}–{formatInsightTime(item.end_seconds)}</time>
                  <span>{item.text || item.source_label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="viral-dna-grid">
        <article>
          <header><LockSimple size={19} /><strong>必须保留的内容 DNA</strong></header>
          <ul>
            {insight.dna.invariants.length > 0
              ? insight.dna.invariants.map((item) => <li key={item}><CheckCircle size={15} />{item}</li>)
              : <li>暂无足够证据确定必须保留的内容 DNA</li>}
          </ul>
        </article>
        <article>
          <header><Sparkle size={19} /><strong>可以替换与改进</strong></header>
          <ul>
            {insight.dna.variables.length > 0 || insight.improvements.length > 0
              ? <>
                {insight.dna.variables.slice(0, 4).map((item) => <li key={item}>{item}</li>)}
                {insight.improvements.slice(0, 2).map((item) => <li key={item.id}>{item.title}</li>)}
              </>
              : <li>暂无经过证据校验的替换或改进建议</li>}
          </ul>
        </article>
      </div>

      <div className="viral-inference-note">
        <span>当前未读取真实平台播放、完播或互动指标，结论用于创作决策。</span>
        <div className="viral-summary-actions">
          <button type="button" onClick={onOpenMechanisms}>查看机制与证据<CaretRight size={16} /></button>
          <button className="primary" type="button" onClick={onOpenReplication}>开始复刻<CaretRight size={16} /></button>
        </div>
      </div>
    </section>
  );
}
