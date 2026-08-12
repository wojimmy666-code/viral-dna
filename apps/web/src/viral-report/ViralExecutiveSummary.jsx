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
import { confidenceLabel, difficultyLabel, useViralInsight } from "./viral-report-ui.js";

export function ViralExecutiveSummary({ analysisId, request, onOpenMechanisms }) {
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

  return (
    <section className="viral-executive-summary">
      <div className="viral-summary-heading">
        <div>
          <span className="viral-basis-badge"><Sparkle size={15} weight="fill" />内容证据推断</span>
          <h2>{insight.headline}</h2>
          <p>{insight.content_value}</p>
        </div>
        <button className="viral-refresh-button" type="button" onClick={() => reload({ refresh: true })} disabled={loading}>
          {loading ? <CircleNotch className="spin" size={17} /> : <ArrowClockwise size={17} />}
          重新整理
        </button>
      </div>

      <div className="viral-summary-metrics" aria-label="洞察摘要">
        <div><span>证据覆盖</span><strong>{Math.round(insight.evidence_coverage * 100)}%</strong></div>
        <div><span>判断置信度</span><strong>{confidenceLabel(insight.confidence)}</strong></div>
        <div><span>复刻难度</span><strong>{difficultyLabel(insight.replication_difficulty)}</strong></div>
        <div><span>机制数量</span><strong>{insight.mechanisms.length} 项</strong></div>
      </div>

      <div className="viral-hook-callout">
        <Target size={23} weight="fill" />
        <div><span>最强流量抓手</span><p>{insight.strongest_hook}</p></div>
      </div>

      <div className="viral-dna-grid">
        <article>
          <header><LockSimple size={19} /><strong>必须保留的内容 DNA</strong></header>
          <ul>{insight.dna.invariants.map((item) => <li key={item}><CheckCircle size={15} />{item}</li>)}</ul>
        </article>
        <article>
          <header><Sparkle size={19} /><strong>可以替换与改进</strong></header>
          <ul>
            {insight.dna.variables.slice(0, 4).map((item) => <li key={item}>{item}</li>)}
            {insight.improvements.slice(0, 2).map((item) => <li key={item.id}>{item.title}</li>)}
          </ul>
        </article>
      </div>

      <div className="viral-inference-note">
        当前没有读取真实平台播放、完播或互动指标；以上结论用于创作决策，不代表已验证的流量结果。
        <button type="button" onClick={onOpenMechanisms}>查看机制与证据<CaretRight size={16} /></button>
      </div>
    </section>
  );
}
