import {
  ArrowClockwise,
  CaretDown,
  CircleNotch,
  Clock,
  ImageSquare,
  ShieldWarning,
} from "@phosphor-icons/react";
import { confidenceLabel, formatInsightTime, useViralInsight } from "./viral-report-ui.js";

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
        <div><span>WHY IT WORKS</span><h2>爆款机制与证据链</h2><p>先看视频中可观察的事实，再看系统对流量作用的推断。</p></div>
        <span className="viral-basis-badge">内容推断 · {Math.round(insight.evidence_coverage * 100)}% 有证据</span>
      </header>

      <div className="viral-mechanism-list">
        {insight.mechanisms.map((mechanism, index) => {
          const firstEvidence = mechanism.evidence[0];
          return (
            <article className="viral-mechanism-row" key={mechanism.id}>
              <div className="viral-mechanism-time">
                <span>{String(index + 1).padStart(2, "0")}</span>
                <button type="button" onClick={() => onSeek?.(firstEvidence?.start_seconds || 0)}>
                  <Clock size={15} />{formatInsightTime(firstEvidence?.start_seconds || 0)}
                </button>
              </div>
              <div className="viral-mechanism-body">
                <div className="viral-mechanism-title">
                  <div><span>{mechanism.claim_kind === "observed" ? "观察事实" : "机制推断"}</span><h3>{mechanism.title}</h3></div>
                  <div className="viral-mechanism-score"><span>机制强度</span><strong>{mechanism.score}</strong></div>
                </div>
                <div className="viral-logic-chain">
                  <div><span>视频事实</span><p>{mechanism.observation}</p></div>
                  <div><span>为何有效</span><p>{mechanism.mechanism}</p></div>
                  <div><span>可能作用</span><p>{mechanism.expected_effect}</p></div>
                </div>
                <div className="viral-mechanism-footer">
                  <div className="viral-impact-tags">{mechanism.impact_dimensions.map((item) => <span key={item}>{IMPACT_LABELS[item] || item}</span>)}</div>
                  <span>置信度 {confidenceLabel(mechanism.confidence)} · {Math.round(mechanism.confidence * 100)}%</span>
                </div>
                <div className="viral-recommendation"><strong>复刻建议</strong><p>{mechanism.recommendation}</p></div>
                <details className="viral-evidence-disclosure">
                  <summary><ImageSquare size={17} />查看 {mechanism.evidence.length} 条证据<CaretDown size={15} /></summary>
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
            </article>
          );
        })}
      </div>
    </div>
  );
}
