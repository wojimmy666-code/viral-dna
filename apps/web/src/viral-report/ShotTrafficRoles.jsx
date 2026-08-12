import { CaretRight, CheckCircle, CircleNotch, ShieldWarning } from "@phosphor-icons/react";
import { formatInsightTime, ROLE_LABELS, useViralInsight } from "./viral-report-ui.js";

export function ShotTrafficRoles({ analysisId, request, resolveUrl, onSeek }) {
  const { insight, loading, error } = useViralInsight({ analysisId, request });
  if (loading && !insight) return <div className="viral-loading-state compact"><CircleNotch className="spin" size={19} />正在整理分镜贡献…</div>;
  if (error && !insight) return <div className="viral-error-state compact"><ShieldWarning size={19} />{error}</div>;
  if (!insight) return null;
  return (
    <details className="viral-report-page shot-traffic-section">
      <summary>
        <span><strong>逐镜头流量角色</strong><small>按需查看每个分镜承担的流量功能</small></span>
        <span>{insight.shot_roles.length} 个分镜<CaretRight size={17} /></span>
      </summary>
      <div className="shot-traffic-list">
        {insight.shot_roles.map((shot) => (
          <article key={shot.shot_id}>
            <button type="button" onClick={() => onSeek?.(shot.start_seconds)} aria-label={`查看${shot.title}对应时间点`}>
              {shot.keyframe_url ? <img src={resolveUrl(shot.keyframe_url)} alt={shot.title} /> : <span className="shot-traffic-index">{String(shot.shot_index).padStart(2, "0")}</span>}
              <span className="shot-traffic-copy">
                <span className="shot-traffic-heading">
                  <strong>{shot.title}</strong>
                  <span className="shot-traffic-meta">
                    <small>{formatInsightTime(shot.start_seconds)} — {formatInsightTime(shot.end_seconds)}</small>
                    <em>{ROLE_LABELS[shot.role] || shot.role}</em>
                    <CaretRight size={17} />
                  </span>
                </span>
                <p>{shot.contribution}</p>
              </span>
            </button>
            {shot.must_keep.length > 0 && (
              <details className="shot-traffic-preserve-details">
                <summary>复刻时保留 {shot.must_keep.length} 项</summary>
                <span className="shot-traffic-preserve-list">
                  {shot.must_keep.slice(0, 2).map((item) => <span key={item}><CheckCircle size={15} weight="fill" /><span>{item}</span></span>)}
                </span>
              </details>
            )}
          </article>
        ))}
      </div>
    </details>
  );
}
