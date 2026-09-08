import { memo } from "react";
import { ArrowUp, ArrowDown, Trash } from "@phosphor-icons/react";
import { shotImageStatus } from "./image-batch-ui.js";
import { ShotNavigationThumbnail } from "../ShotNavigationThumbnail.jsx";

export const SkillShotNavigation = memo(function SkillShotNavigation({ shots, discarded, selectedId, busy, items, handlers, resolveUrl, shotDetail }) {
  return <aside className="shot-navigation-panel">
    <div className="shot-panel-title"><div><strong>分镜列表</strong><small>{shots.length} 个有效镜头</small></div><button className="shot-add-button" disabled={busy} onClick={() => handlers.current.add()} type="button">＋ 新增</button></div>
    <div className="skill-shot-list">{shots.map(({ plan, image_preview, visual_beat_count }, index) => <div key={plan.id} className={`skill-shot-row ${selectedId === plan.id ? "active" : ""}`} draggable={!busy} onDragStart={() => handlers.current.drag(plan.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => handlers.current.drop(plan.id)}>
      <button className="skill-shot-select" aria-current={selectedId === plan.id ? "true" : undefined} onClick={() => handlers.current.select(plan.id)} type="button">
        <ShotNavigationThumbnail className="compact" showIndex={false} index={plan.index} resolveUrl={resolveUrl} showImageStatus sources={image_preview ? [{ kind: image_preview.kind, url: image_preview.thumbnail_url }] : []} />
        <span className="skill-shot-copy"><strong>分镜 {String(plan.index).padStart(2, "0")}</strong><small>{shotImageStatus(shotDetail?.plan.id === plan.id ? shotDetail.plan : plan, items, {
          imagePreview: image_preview, visualBeatCount: visual_beat_count,
          generationRuns: shotDetail?.plan.id === plan.id ? shotDetail.generation_runs : undefined,
        })}</small></span>
      </button>
      {selectedId === plan.id && <div className="skill-shot-actions"><button aria-label="上移分镜" disabled={busy || index === 0} onClick={() => handlers.current.move(plan.id, -1)} type="button"><ArrowUp size={14} /></button><button aria-label="下移分镜" disabled={busy || index === shots.length - 1} onClick={() => handlers.current.move(plan.id, 1)} type="button"><ArrowDown size={14} /></button><button aria-label="舍弃分镜" disabled={busy || shots.length <= 1} onClick={() => handlers.current.discard(plan.id)} type="button"><Trash size={14} /></button></div>}
    </div>)}</div>
    {discarded.length > 0 && <details className="shot-discarded-section"><summary>已舍弃 {discarded.length}</summary>{discarded.map(({ plan }) => <div key={plan.id} className="shot-discarded-item"><span>分镜 {plan.index}</span><button disabled={busy} onClick={() => handlers.current.restore(plan.id)} type="button">恢复</button></div>)}</details>}
  </aside>;
});
