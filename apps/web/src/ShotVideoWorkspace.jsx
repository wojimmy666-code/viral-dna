import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  CircleNotch,
  DownloadSimple,
  FilmStrip,
  FloppyDisk,
  MagicWand,
  PlayCircle,
  Prohibit,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  formatVideoDuration,
  latestRunByKind,
  normalizeVideoDuration,
  videoDurationConstraintLabel,
  videoDurationOptions,
  videoGenerationRunLabel,
  workflowStatusClass,
  workflowStatusLabel,
} from "./production-ui.js";
import { ShotNavigationThumbnail } from "./ShotNavigationThumbnail.jsx";

const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "running",
  "cancellation_requested",
]);

function approvedImageCandidate(detail) {
  const candidateId = detail?.plan?.approved_image_candidate_id;
  if (!candidateId) return null;
  for (const run of detail.generation_runs || []) {
    if (run.kind !== "image") continue;
    const candidate = (run.candidates || []).find((item) => item.id === candidateId);
    if (candidate) return candidate;
  }
  return null;
}

function ShotVideoList({ shots, selectedShotId, onSelectShot, resolveUrl }) {
  const activeShots = shots.filter(
    (item) => item.plan.lifecycle_status !== "discarded",
  );
  return (
    <aside className="shot-video-list" aria-label="分镜视频列表">
      <header>
        <strong>有效分镜</strong>
        <span>{activeShots.length} 个</span>
      </header>
      <div>
        {activeShots.map((item) => {
          const plan = item.plan;
          return (
            <button
              className={selectedShotId === plan.id ? "active" : ""}
              key={plan.id}
              onClick={() => onSelectShot(plan.id)}
              type="button"
            >
              <ShotNavigationThumbnail
                index={plan.index}
                resolveUrl={resolveUrl}
                sources={[
                  item.video_preview && {
                    kind: item.video_preview.kind,
                    url: item.video_preview.thumbnail_url,
                  },
                  item.image_preview && {
                    kind: item.image_preview.kind,
                    url: item.image_preview.thumbnail_url,
                  },
                  { kind: "source_keyframe", url: plan.source_keyframe_url },
                ]}
              />
              <span className="shot-video-list-copy">
                <strong>分镜 {plan.index} · {plan.video_prompt || "尚未填写视频提示词"}</strong>
                <small>{plan.start_seconds.toFixed(1)}s–{plan.end_seconds.toFixed(1)}s · {plan.duration_seconds.toFixed(1)}s</small>
              </span>
              <span className={`production-status ${workflowStatusClass(plan.video_status)}`}>
                {workflowStatusLabel(plan.video_status)}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export function ShotVideoWorkspace({
  advanced,
  busy,
  error,
  gate,
  initialCandidateId = "",
  onAdvance,
  onApprove,
  onCancelRun,
  onGenerate,
  onReject,
  onRetryRun,
  onRevokeApproval,
  onSave,
  onSelectCandidate,
  onSelectShot,
  project,
  resolveUrl,
  selectedShotId,
  setVideoDraft,
  shotDetail,
  shots,
  videoDraft,
  videoGenerationSettings,
}) {
  const [displayedCandidateId, setDisplayedCandidateId] = useState(null);
  const [durationAdjustmentMessage, setDurationAdjustmentMessage] = useState("");
  const plan = shotDetail?.plan;
  const generationRuns = shotDetail?.generation_runs || [];
  const latestRun = latestRunByKind(generationRuns, "video");
  const candidates = useMemo(
    () => (latestRun?.candidates || []).filter(
      (candidate) => candidate.status !== "archived",
    ),
    [latestRun],
  );
  const imageCandidate = approvedImageCandidate(shotDetail);
  const displayedCandidate = (
    candidates.find((item) => item.id === displayedCandidateId)
    || candidates.find((item) => item.id === plan?.approved_video_candidate_id)
    || candidates.find((item) => item.status === "selected")
    || candidates[0]
    || null
  );
  const activeRun = latestRun && ACTIVE_RUN_STATUSES.has(latestRun.status)
    ? latestRun
    : null;
  const videoModels = videoGenerationSettings?.models || [];
  const selectedModel = videoModels.find(
    (item) => item.alias === videoDraft.modelAlias,
  );
  const providerSettings = (videoGenerationSettings?.providers || []).find(
    (item) => item.provider === selectedModel?.provider,
  );
  const supportedResolutions =
    selectedModel?.capabilities?.supported_resolutions || [];
  const durationOptions = useMemo(
    () => videoDurationOptions(selectedModel),
    [selectedModel],
  );
  const durationNumber = normalizeVideoDuration(
    videoDraft.durationSeconds || plan?.duration_seconds,
    selectedModel,
  );
  const durationIndex = Math.max(0, durationOptions.indexOf(durationNumber));
  const durationScaleValues = durationOptions.length <= 5
    ? durationOptions
    : [durationOptions[0], durationOptions.at(-1)];
  const durationHelpId = plan?.id
    ? `video-duration-help-${plan.id}`
    : "video-duration-help";
  const durationControlId = plan?.id
    ? `video-duration-control-${plan.id}`
    : "video-duration-control";
  const pricing = selectedModel?.pricing || {};
  let estimatedCostMicros = null;
  if (pricing.kind === "per_second_by_resolution") {
    const rate = Number(pricing.rates_micros?.[videoDraft.resolution]);
    if (Number.isFinite(rate)) {
      estimatedCostMicros = Math.round(
        rate * durationNumber * Number(videoDraft.candidateCount || 1),
      );
    }
  } else if (pricing.kind === "fixed_matrix") {
    const rate = Number(
      pricing.rates_micros?.[`${videoDraft.resolution}:${durationNumber}`],
    );
    if (Number.isFinite(rate)) {
      estimatedCostMicros = Math.round(
        rate * Number(videoDraft.candidateCount || 1),
      );
    }
  }
  const generationBlockedReason = !videoGenerationSettings?.enabled
    ? "视频生成尚未启用"
    : !selectedModel
      ? "请选择视频模型"
      : !selectedModel.available
        ? selectedModel.availability_note || "该模型暂不可调用"
        : !providerSettings?.api_key_configured
          ? `尚未配置 ${providerSettings?.label || selectedModel.provider} API Key`
          : null;
  const estimatedCostLabel = estimatedCostMicros == null
    ? "按实际用量结算"
    : `¥${(estimatedCostMicros / 1_000_000).toFixed(2)}`;
  const latestCostLabel = latestRun?.actual_cost_known
    ? `实际 ¥${(Number(latestRun.actual_cost_micros || 0) / 1_000_000).toFixed(2)}`
    : latestRun?.cost_estimate_known
      ? `预计 ¥${(Number(latestRun.estimated_cost_micros || 0) / 1_000_000).toFixed(2)}`
      : "费用待回传";

  useEffect(() => {
    setDisplayedCandidateId(
      initialCandidateId && candidates.some((item) => item.id === initialCandidateId)
        ? initialCandidateId
        : null,
    );
    setDurationAdjustmentMessage("");
  }, [initialCandidateId, latestRun?.id, plan?.id]);

  if (!plan) {
    return (
      <div className="production-empty-state shot-video-empty">
        <FilmStrip size={28} />
        <div><h4>请选择一个有效分镜</h4><p>每个分镜独立生成和审核，避免单个失败影响全部镜头。</p></div>
      </div>
    );
  }

  async function rejectDisplayedCandidate() {
    if (!displayedCandidate) return;
    const reason = window.prompt("请输入退回原因", "动作或画面稳定性需要调整");
    if (!reason?.trim()) return;
    await onReject(displayedCandidate.id, reason.trim());
  }

  function selectVideoModel(modelAlias) {
    const model = videoModels.find((item) => item.alias === modelAlias);
    const nextDuration = normalizeVideoDuration(
      videoDraft.durationSeconds || plan?.duration_seconds,
      model,
    );
    const previousDuration = Number(videoDraft.durationSeconds);
    const supported = model?.capabilities?.supported_resolutions || [];
    setVideoDraft((current) => ({
      ...current,
      modelAlias,
      durationSeconds: String(nextDuration),
      resolution: supported.includes(current.resolution)
        ? current.resolution
        : supported[0] || current.resolution,
    }));
    setDurationAdjustmentMessage(
      Number.isFinite(previousDuration)
      && Math.abs(previousDuration - nextDuration) > 0.001
        ? `${model?.label || "当前模型"} 不支持原时长，已调整为 ${formatVideoDuration(nextDuration)} 秒。`
        : "",
    );
  }

  function selectDuration(index) {
    const nextDuration = durationOptions[Number(index)];
    if (nextDuration == null) return;
    setVideoDraft((current) => ({
      ...current,
      durationSeconds: String(nextDuration),
    }));
    setDurationAdjustmentMessage("");
  }

  return (
    <section className="shot-video-workspace">
      <header className="shot-video-stage-header">
        <div>
          <h3>分段视频工作台</h3>
          <p>以已确认图片作为起始帧，逐镜头生成、播放和审核视频候选。</p>
        </div>
        <div className="shot-video-gate">
          <span>{gate?.approved_shot_count || 0} / {gate?.required_shot_count || 0} 已确认</span>
          <button
            className="primary-button compact"
            disabled={busy || advanced || !gate?.allowed}
            onClick={onAdvance}
            type="button"
          >
            {advanced ? "已进入剪辑合成" : "进入剪辑合成"}
            <ArrowRight size={16} />
          </button>
        </div>
      </header>

      <div className="shot-video-foundation-note">
        <MagicWand size={18} weight="fill" />
        <span><strong>国内视频模型 API</strong>：每个候选对应一个独立上游任务；结果会立即下载到本地工作区，仍需人工审核后采用。</span>
      </div>
      {error && <div className="production-inline-error" role="alert"><WarningCircle size={18} />{error}</div>}

      <div className="shot-video-layout">
        <ShotVideoList
          onSelectShot={onSelectShot}
          resolveUrl={resolveUrl}
          selectedShotId={selectedShotId}
          shots={shots}
        />

        <div className="shot-video-editor">
          <header className="shot-video-editor-title">
            <div>
              <span>分镜 {plan.index}</span>
              <strong>{plan.start_seconds.toFixed(1)}s–{plan.end_seconds.toFixed(1)}s</strong>
            </div>
            <span className={`production-status ${workflowStatusClass(plan.video_status)}`}>
              {workflowStatusLabel(plan.video_status)}
            </span>
          </header>

          <div className="shot-video-preview-grid">
            <article className="shot-video-preview-card">
              <header><span>已确认起始帧</span><small>图片阶段产物</small></header>
              <div className="shot-video-media-frame">
                {imageCandidate ? (
                  <img alt={`分镜 ${plan.index} 已确认图片`} src={resolveUrl(imageCandidate.content_url)} />
                ) : (
                  <div className="shot-video-media-placeholder"><WarningCircle size={26} /><span>缺少已确认图片</span></div>
                )}
              </div>
            </article>

            <article className="shot-video-preview-card">
              <header>
                <span>视频候选</span>
                <small>{videoGenerationRunLabel(latestRun)}</small>
              </header>
              <div className="shot-video-media-frame shot-video-candidate-frame">
                {displayedCandidate ? (
                  <>
                    <video
                      controls
                      key={displayedCandidate.id}
                      playsInline
                      poster={resolveUrl(displayedCandidate.thumbnail_url)}
                      preload="metadata"
                      src={resolveUrl(displayedCandidate.content_url)}
                    />
                    <a
                      aria-label={`下载视频候选 ${displayedCandidate.ordinal}`}
                      className="shot-video-download-button"
                      download={`shot-${plan.index}-candidate-${displayedCandidate.ordinal}.mp4`}
                      href={resolveUrl(displayedCandidate.content_url)}
                      title="下载视频候选"
                    >
                      <DownloadSimple size={16} />
                    </a>
                  </>
                ) : (
                  <div className="shot-video-media-placeholder"><PlayCircle size={30} /><span>生成后可在这里播放候选</span></div>
                )}
              </div>
            </article>
          </div>

          {candidates.length > 1 && (
            <div className="shot-video-candidate-tabs" aria-label="视频候选">
              {candidates.map((candidate) => (
                <button
                  className={displayedCandidate?.id === candidate.id ? "active" : ""}
                  key={candidate.id}
                  onClick={() => setDisplayedCandidateId(candidate.id)}
                  type="button"
                >
                  候选 {candidate.ordinal}
                  {candidate.status === "selected" && <CheckCircle size={14} weight="fill" />}
                </button>
              ))}
            </div>
          )}

          <div className="shot-video-prompt-panel">
            <label>
              <span>视频提示词</span>
              <textarea
                maxLength={8000}
                onChange={(event) => setVideoDraft((current) => ({
                  ...current,
                  videoPrompt: event.target.value,
                }))}
                rows={5}
                value={videoDraft.videoPrompt}
              />
            </label>
            <label>
              <span>视频负面约束</span>
              <textarea
                maxLength={3000}
                onChange={(event) => setVideoDraft((current) => ({
                  ...current,
                  negativeConstraints: event.target.value,
                }))}
                placeholder="每行一项，例如：人物身份漂移"
                rows={3}
                value={videoDraft.negativeConstraints}
              />
            </label>
            <div className="shot-video-generation-options">
              <label className="shot-video-generation-field">
                <span className="shot-video-field-heading">视频模型</span>
                <select
                  onChange={(event) => selectVideoModel(event.target.value)}
                  value={videoDraft.modelAlias}
                >
                  {videoModels.map((model) => (
                    <option disabled={!model.available} key={model.alias} value={model.alias}>
                      {model.label}{!model.available ? "（待开放）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="shot-video-generation-field">
                <span className="shot-video-field-heading">分辨率</span>
                <select
                  onChange={(event) => setVideoDraft((current) => ({
                    ...current,
                    resolution: event.target.value,
                  }))}
                  value={videoDraft.resolution}
                >
                  {supportedResolutions.map((resolution) => (
                    <option key={resolution} value={resolution}>{resolution}</option>
                  ))}
                </select>
              </label>
              <div className="shot-video-generation-field shot-video-duration-option">
                <div className="shot-video-field-heading shot-video-duration-heading">
                  <label htmlFor={durationControlId}>生成时长</label>
                  <output htmlFor={durationControlId}>{formatVideoDuration(durationNumber)} 秒</output>
                </div>
                <div className="shot-video-duration-control">
                  <input
                    aria-describedby={durationHelpId}
                    aria-label="生成时长"
                    aria-valuetext={`${formatVideoDuration(durationNumber)} 秒`}
                    disabled={!selectedModel || durationOptions.length <= 1}
                    id={durationControlId}
                    max={Math.max(0, durationOptions.length - 1)}
                    min={0}
                    onChange={(event) => selectDuration(event.target.value)}
                    step={1}
                    type="range"
                    value={durationIndex}
                  />
                  <span className="shot-video-duration-scale" aria-hidden="true">
                    {durationScaleValues.map((duration) => (
                      <small key={duration}>{formatVideoDuration(duration)} 秒</small>
                    ))}
                  </span>
                </div>
                <div className="shot-video-duration-meta">
                  <small className="shot-video-duration-help" id={durationHelpId}>
                    {selectedModel
                      ? `${selectedModel.label}：${videoDurationConstraintLabel(selectedModel)}`
                      : "选择模型后显示可用时长"}
                  </small>
                  {durationAdjustmentMessage && (
                    <small className="shot-video-duration-adjustment" role="status">
                      {durationAdjustmentMessage}
                    </small>
                  )}
                </div>
              </div>
              <label className="shot-video-generation-field">
                <span className="shot-video-field-heading">候选数量</span>
                <select
                  onChange={(event) => setVideoDraft((current) => ({
                    ...current,
                    candidateCount: Number(event.target.value),
                  }))}
                  value={videoDraft.candidateCount}
                >
                  {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count} 个</option>)}
                </select>
              </label>
            </div>
            <div className="shot-video-prompt-actions">
              <div className="shot-video-cost-summary">
                <span>预计 <strong>{estimatedCostLabel}</strong></span>
                <small>
                  {providerSettings?.label || selectedModel?.provider || "未选择 Provider"}
                  {providerSettings?.api_key_configured ? " · Key 已配置" : " · Key 未配置"}
                </small>
              </div>
              {activeRun && (
                <button className="text-button compact" disabled={busy} onClick={() => onCancelRun(activeRun.id)} type="button">
                  <Prohibit size={15} />取消任务
                </button>
              )}
              {!activeRun && ["failed", "cancelled", "blocked"].includes(latestRun?.status) && (
                <button className="secondary-button compact" disabled={busy} onClick={() => onRetryRun(latestRun.id)} type="button">
                  重试上次任务
                </button>
              )}
              <button className="secondary-button compact" disabled={busy} onClick={onSave} type="button">
                <FloppyDisk size={16} />保存提示词
              </button>
              <button
                className="primary-button compact"
                disabled={busy || Boolean(activeRun) || !imageCandidate || !videoDraft.videoPrompt.trim() || plan.video_status === "approved" || Boolean(generationBlockedReason)}
                onClick={onGenerate}
                title={generationBlockedReason || ""}
                type="button"
              >
                {activeRun ? <CircleNotch className="spin" size={16} /> : <MagicWand size={16} weight="fill" />}
                {activeRun ? "正在生成" : `生成 ${videoDraft.candidateCount} 个视频候选`}
              </button>
            </div>
            {generationBlockedReason && (
              <div className="production-inline-error" role="status">
                <WarningCircle size={17} />{generationBlockedReason}，请到“模型与设置”完成配置。
              </div>
            )}
          </div>

          {displayedCandidate && (
            <footer className="shot-video-review-actions">
              <div>
                <strong>
                  候选 {displayedCandidate.ordinal} · {latestRun?.model_display_name || latestRun?.model_alias || latestRun?.model || "视频模型"}
                </strong>
                <span>
                  {displayedCandidate.duration_seconds?.toFixed(1)} 秒 · {displayedCandidate.width} × {displayedCandidate.height} · {latestCostLabel}
                </span>
              </div>
              {plan.video_status === "approved" && plan.approved_video_candidate_id === displayedCandidate.id ? (
                <button className="secondary-button compact" disabled={busy} onClick={onRevokeApproval} type="button">取消采用</button>
              ) : (
                <>
                  <button className="secondary-button compact" disabled={busy || displayedCandidate.status === "rejected"} onClick={rejectDisplayedCandidate} type="button">退回</button>
                  {displayedCandidate.status === "selected" ? (
                    <button className="primary-button compact" disabled={busy} onClick={() => onApprove(displayedCandidate.id)} type="button"><CheckCircle size={16} weight="fill" />确认采用</button>
                  ) : (
                    <button className="primary-button compact" disabled={busy} onClick={() => onSelectCandidate(displayedCandidate.id)} type="button">选择此候选</button>
                  )}
                </>
              )}
            </footer>
          )}
        </div>
      </div>

      {!gate?.allowed && gate?.blocker_messages?.length > 0 && (
        <div className="shot-video-gate-blockers">
          <WarningCircle size={17} />{gate.blocker_messages.join("；")}
        </div>
      )}
      <span className="shot-video-project-meta">输出画幅 {project.output_aspect_ratio} · {project.output_width} × {project.output_height}</span>
    </section>
  );
}
