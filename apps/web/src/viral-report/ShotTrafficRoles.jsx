import { CaretRight, CheckCircle, CircleNotch, ShieldWarning } from "@phosphor-icons/react";
import { formatInsightTime, ROLE_LABELS, useViralInsight } from "./viral-report-ui.js";

export function ShotTrafficRoles({ analysisId, request, resolveUrl, onSeek }) {
  const { insight, loading, error } = useViralInsight({ analysisId, request });
  if (loading && !insight) return <div className="viral-loading-state compact"><CircleNotch className="spin" size={19} />正在整理分镜贡献…</div>;
  if (error && !insight) return <div className="viral-error-state compact"><ShieldWarning size={19} />{error}</div>;
  if (!insight) return null;
  return (
    <section className="viral-report-page shot-traffic-section">
      <header className="viral-section-header"><div><span>SHOT CONTRIBUTION</span><h2>逐镜头流量角色</h2><p>判断每个分镜为何存在，以及复刻时哪些信息不能丢。</p></div></header>
      <div className="shot-traffic-list">
        {insight.shot_roles.map((shot) => (
          <button type="button" key={shot.shot_id} onClick={() => onSeek?.(shot.start_seconds)} aria-label={`查看${shot.title}对应时间点`}>
            {shot.keyframe_url ? <img src={resolveUrl(shot.keyframe_url)} alt={shot.title} /> : <span className="shot-traffic-index">{String(shot.shot_index).padStart(2, "0")}</span>}
            <span className="shot-traffic-copy">
              <span className="shot-traffic-heading">
                <strong>{shot.title}</strong>
                <span className="shot-traffic-meta">
                  <small>{formatInsightTime(shot.start_seconds)} — {formatInsightTime(shot.end_seconds)}</small>
                  <em>{ROLE_LABELS[shot.role] || shot.role}</em>
                  <span className="shot-traffic-score"><strong>{shot.contribution_score}</strong><small>贡献分</small></span>
                  <CaretRight size={17} />
                </span>
              </span>
              <p>{shot.contribution}</p>
              {shot.must_keep.length > 0 && (
                <span className="shot-traffic-preserve">
                  <strong>复刻时保留</strong>
                  <span className="shot-traffic-preserve-list">
                    {shot.must_keep.slice(0, 2).map((item) => <span key={item}><CheckCircle size={15} weight="fill" /><span>{item}</span></span>)}
                  </span>
                </span>
              )}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
