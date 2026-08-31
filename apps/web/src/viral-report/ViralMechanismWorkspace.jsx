import {
  ArrowClockwise,
  CaretDown,
  CircleNotch,
  Clock,
  ImageSquare,
  ShieldWarning,
} from "@phosphor-icons/react";
import { formatInsightTime, useViralInsight } from "./viral-report-ui.js";

const IMPACT_LABELS = {
  click: "点击承接",
  retention: "留存",
  like: "点赞",
  comment: "评论",
  share: "分享",
  conversion: "转化",
};

export function ViralMechanismWorkspace({ analysisId, request, resolveUrl, onSeek }) {
  const { insight, loading, error, reload } = useViralInsight({ analysisId, request });
  if (loading && !insight) return <div className="viral-loading-state"><CircleNotch className="spin" size={22} />正在提取机制证据…</div>;
  if (error && !insight) {
    return <div className="viral-error-state"><ShieldWarning size={22} /><div><strong>无法读取爆款机制</strong><p>{error}</p></div><button type="button" onClick={() => reload()}><ArrowClockwise size={17} />重试</button></div>;
  }
  if (!insight) return null;

  return (
    <div className="viral-report-page viral-mechanism-workspace">
      <header className="viral-section-header">
        <h2>爆款机制与证据链</h2>
      </header>

      <div className="viral-mechanism-list">
        {insight.mechanisms.map((mechanism, index) => {
          const firstEvidence = mechanism.evidence[0];
          return (
            <details className="viral-mechanism-row" key={mechanism.id} open={index === 0}>
              <summary>
                <span className="viral-mechanism-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="viral-mechanism-summary-copy">
                  <strong>{mechanism.title}</strong>
                  <span>{mechanism.mechanism}</span>
                </span>
                <span className="viral-mechanism-summary-meta">
                  <small><Clock size={14} />{formatInsightTime(firstEvidence?.start_seconds || 0)}</small>
                  <CaretDown className="viral-disclosure-caret" size={17} />
                </span>
              </summary>
              <div className="viral-mechanism-body">
                <div className="viral-mechanism-footer">
                  <div className="viral-impact-tags">{mechanism.impact_dimensions.map((item) => <span key={item}>{IMPACT_LABELS[item] || item}</span>)}</div>
                </div>
                <div className="viral-logic-chain">
                  <div><span>视频事实</span><p>{mechanism.observation}</p></div>
                  <div><span>复刻建议</span><p>{mechanism.recommendation}</p></div>
                </div>
                <details className="viral-evidence-disclosure">
                  <summary><ImageSquare size={17} />查看 {mechanism.evidence.length} 条原始证据<CaretDown size={15} /></summary>
                  <div className="viral-evidence-grid">
                    {mechanism.evidence.map((evidence) => (
                      <button type="button" key={evidence.id} onClick={() => onSeek?.(evidence.start_seconds)}>
                        {evidence.frame_url ? <img src={resolveUrl(evidence.frame_url)} alt={evidence.source_label} /> : <span className="viral-evidence-placeholder">{evidence.kind.toUpperCase()}</span>}
                        <span><strong>{evidence.source_label}</strong><small>{formatInsightTime(evidence.start_seconds)} — {formatInsightTime(evidence.end_seconds)}</small><p>{evidence.text}</p></span>
                      </button>
                    ))}
                  </div>
                </details>
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
