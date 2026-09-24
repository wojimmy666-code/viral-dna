import { useId, useState } from "react";
import { CaretDown, MagicWand } from "@phosphor-icons/react";
import { Button, IconButton } from "../ui/system/Button.jsx";
import { PromptSectionView } from "../prompt-presentation/PromptSectionView.jsx";
import "./creative-plan-review.css";

export function CreativePlanReview({ conceptSet, selected, publishingId, publishDisabled = false, onPublish, onPromptPreview }) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const shots = selected.shots || [];
  const assets = selected.required_assets || [];
  const retained = selected.retained_dna || [];
  const hasDetails = Boolean(selected.narrative_structure || selected.payoff || selected.one_liner
    || selected.category_fit_summary || selected.target_audience || selected.changed_elements?.length || retained.length);
  const isStale = conceptSet.status === "stale";
  const published = Boolean(conceptSet.published_result);
  const blocked = publishDisabled || Boolean(publishingId) || isStale
    || (Boolean(conceptSet.language_issues?.length) && !published)
    || Boolean(conceptSet.input_snapshot?.prompt_language_project_id);

  return <section className="creative-plan-review" aria-label="完整方案审阅">
    <header className="creative-plan-header">
      <div><h2>{selected.name}</h2><p>完整方案 · {shots.length} 个分镜</p></div>
      {onPromptPreview && <Button variant="text" size="compact" onClick={onPromptPreview}>
        {conceptSet.language_issues?.length ? "查看方案提示词并转为中文" : "查看方案提示词"}
      </Button>}
    </header>

    <section className="creative-plan-overview" aria-label="创意概述">
      <div className="creative-plan-overview-heading">
        <h3>创意概述</h3>
        {hasDetails && <IconButton size="compact" label={detailsOpen ? "收起创意说明" : "展开创意说明"}
          aria-expanded={detailsOpen} aria-controls={detailsId} onClick={() => setDetailsOpen(open => !open)}>
          <CaretDown size={16} aria-hidden="true" />
        </IconButton>}
      </div>
      <p>{selected.thesis || selected.why_it_can_work}</p>
      {hasDetails && <div id={detailsId} className="creative-plan-details" hidden={!detailsOpen}>
        <dl>
          {selected.narrative_structure && <div><dt>叙事结构</dt><dd>{selected.narrative_structure}</dd></div>}
          {(selected.payoff || selected.one_liner) && <div><dt>结尾兑现</dt><dd>{selected.payoff || selected.one_liner}</dd></div>}
          {(selected.category_fit_summary || selected.target_audience) && <div><dt>品类适配</dt><dd>{selected.category_fit_summary || selected.target_audience}</dd></div>}
          {selected.changed_elements?.length > 0 && <div><dt>核心改动</dt><dd><ul>{selected.changed_elements.map((item, index) => <li key={index}>{item}</li>)}</ul></dd></div>}
          {retained.length > 0 && <div><dt>保留 {retained.length} 项 DNA</dt><dd><ul>{retained.map((item, index) => <li key={index}>{item}</li>)}</ul></dd></div>}
        </dl>
      </div>}
    </section>

    <section className="creative-plan-shots" aria-label="分镜方案">
      <h3>分镜方案 · {shots.length} 个</h3>
      <ol className="creative-plan-shot-list">
        {shots.map(shot => <li key={shot.index}>
          <details className="creative-plan-shot">
            <summary>
              <span className="creative-plan-shot-number">{String(shot.index).padStart(2, "0")}</span>
              <span className="creative-plan-shot-heading">
                <span className="creative-plan-shot-title">{shot.title}</span>
                <span className="creative-plan-shot-duration">{shot.duration_seconds.toFixed(1)} 秒</span>
              </span>
              <span className="creative-plan-shot-excerpt">{shot.description}</span>
              <span className="creative-plan-shot-toggle" aria-hidden="true"><CaretDown size={16} /></span>
            </summary>
            <div className="creative-plan-shot-body">
              {shot.traffic_role && <p className="creative-plan-shot-role">{shot.traffic_role}</p>}
              <div className="creative-plan-prompts">
                <section aria-label="图片提示词"><h4>图片提示词</h4><PromptSectionView prompt={shot.image_prompt} /></section>
                <section aria-label="视频提示词"><h4>视频提示词</h4><PromptSectionView prompt={shot.video_prompt} /></section>
              </div>
            </div>
          </details>
        </li>)}
      </ol>
    </section>

    {assets.length > 0 && <details className="creative-plan-assets">
      <summary><span>所需资产 · {assets.length} 项</span><CaretDown size={16} aria-hidden="true" /></summary>
      <ul>{assets.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </details>}

    <footer className="creative-plan-footer">
      <p>{published ? "方案已创建，可继续编辑与制作。" : "仅创建可编辑制作方案，不自动生成图片或视频。"}</p>
      <Button variant="primary" onClick={() => onPublish(selected)} disabled={blocked}
        icon={<MagicWand size={18} weight="fill" />} loading={publishingId === selected.id}
        loadingLabel={published ? "正在进入…" : "正在创建…"}>
        {isStale ? "重新生成后可创建" : published ? "进入已创建方案" : "确认分镜，进入制作"}
      </Button>
    </footer>
  </section>;
}
