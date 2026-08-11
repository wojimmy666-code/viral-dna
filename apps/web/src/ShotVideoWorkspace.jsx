import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  CircleNotch,
  Copy,
  DownloadSimple,
  FilmStrip,
  FloppyDisk,
  Gear,
  MagicWand,
  PlayCircle,
  Prohibit,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  formatVideoDuration,
  latestRunByKind,
  normalizeVideoDuration,
  preferredVideoResolution,
  videoGenerationDiagnosticText,
  videoDurationConstraintLabel,
  videoDurationOptions,
  videoGenerationFailureDetails,
  videoGenerationRunLabel,
  workflowStatusClass,
  workflowStatusLabel,
} from "./production-ui.js";
import { ShotNavigationThumbnail } from "./ShotNavigationThumbnail.jsx";
import { VideoCandidateLibrary } from "./VideoCandidateLibrary.jsx";

const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "running",
  "cancellation_requested",
]);

function approvedVisualBeatFrames(detail) {
  const beats = [...(detail?.plan?.visual_beats || [])]
    .sort((left, right) => left.index - right.index);
  const requiredBeats = beats.filter((item) => item.required);
  const targets = requiredBeats.length > 0 ? requiredBeats : beats;
  const firstBeatId = beats[0]?.id;
  const imageRuns = (detail?.generation_runs || []).filter((run) => run.kind === "image");
  return targets.map((beat) => {
    const runs = imageRuns.filter((run) => (
      run.visual_beat_id === beat.id
      || (!run.visual_beat_id && beat.id === firstBeatId)
    ));
    const candidate = beat.approved_image_candidate_id
      ? runs
        .flatMap((run) => run.candidates || [])
        .find((item) => item.id === beat.approved_image_candidate_id) || null
      : null;
    return { beat, candidate };
  });
}

function supportsOrderedMultiImage(model) {
  const capability = model?.capabilities;
  return Boolean(
    model?.available
    && capability?.multi_image_reference
    && capability?.ordered_reference_images,
  );
}

function generationRunCostLabel(run) {
  if (!run) return "费用未知";
  if (run.actual_cost_known) {
    return `实际 ¥${(Number(run.actual_cost_micros || 0) / 1_000_000).toFixed(2)}`;
  }
  if (run.cost_estimate_known) {
    return `预计 ¥${(Number(run.estimated_cost_micros || 0) / 1_000_000).toFixed(2)}`;
  }
  return "费用待回传";
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
  onArchiveCandidates,
  onCancelRun,
  onGenerate,
  onOpenModelSettings,
  onReject,
  onRetryRun,
  onRestoreCandidates,
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
  const [diagnosticCopyState, setDiagnosticCopyState] = useState("");
  const modelSelectRef = useRef(null);
  const plan = shotDetail?.plan;
  const generationRuns = shotDetail?.generation_runs || [];
  const videoRuns = useMemo(
    () => generationRuns.filter((run) => run.kind === "video"),
    [generationRuns],
  );
  const latestRun = latestRunByKind(videoRuns, "video");
  const latestFailure = useMemo(
    () => videoGenerationFailureDetails(latestRun),
    [latestRun],
  );
  const candidateSequenceById = useMemo(() => {
    const sequence = new Map();
    let next = 1;
    [...videoRuns].reverse().forEach((run) => {
      [...(run.candidates || [])]
        .sort((left, right) => left.ordinal - right.ordinal)
        .forEach((candidate) => {
          sequence.set(candidate.id, next);
          next += 1;
        });
    });
    return sequence;
  }, [videoRuns]);
  const candidateGroups = useMemo(
    () => videoRuns
      .map((run) => ({
        run,
        candidates: (run.candidates || [])
          .filter((candidate) => !["rejected", "archived"].includes(candidate.status))
          .sort((left, right) => left.ordinal - right.ordinal)
          .map((candidate) => ({
            ...candidate,
            generationRun: run,
            sequence: candidateSequenceById.get(candidate.id),
          })),
      }))
      .filter((group) => group.candidates.length > 0),
    [candidateSequenceById, videoRuns],
  );
  const archivedCandidateGroups = useMemo(
    () => videoRuns
      .map((run) => ({
        run,
        candidates: (run.candidates || [])
          .filter((candidate) => (
            candidate.status === "archived"
            && (
              candidate.archive_reason === "user_deleted"
              || candidate.quality_report?.archive_reason === "user_deleted"
            )
          ))
          .sort((left, right) => left.ordinal - right.ordinal)
          .map((candidate) => ({
            ...candidate,
            generationRun: run,
            sequence: candidateSequenceById.get(candidate.id),
          })),
      }))
      .filter((group) => group.candidates.length > 0),
    [candidateSequenceById, videoRuns],
  );
  const candidates = useMemo(
    () => candidateGroups.flatMap((group) => group.candidates),
    [candidateGroups],
  );
  const referenceFrames = useMemo(
    () => approvedVisualBeatFrames(shotDetail),
    [shotDetail],
  );
  const approvedReferenceCount = referenceFrames.filter((item) => item.candidate).length;
  const allReferencesApproved = (
    referenceFrames.length > 0
    && approvedReferenceCount === referenceFrames.length
  );
  const displayedCandidate = (
    candidates.find((item) => item.id === displayedCandidateId)
    || candidates.find((item) => item.id === plan?.approved_video_candidate_id)
    || candidates.find((item) => item.status === "selected")
    || candidates[0]
    || null
  );
  const displayedCandidateRun = displayedCandidate?.generationRun || null;
  const displayedCandidateCostLabel = generationRunCostLabel(displayedCandidateRun);
  const activeRun = videoRuns.find((run) => ACTIVE_RUN_STATUSES.has(run.status)) || null;
  const videoModels = videoGenerationSettings?.models || [];
  const compatibleVideoModels = useMemo(
    () => videoModels.filter(supportsOrderedMultiImage),
    [videoModels],
  );
  const selectedModel = compatibleVideoModels.find(
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
  const referenceLimitExceeded = Boolean(
    selectedModel
    && referenceFrames.length > Number(
      selectedModel.capabilities?.maximum_reference_images || 0,
    ),
  );
  const generationBlockedReason = !videoGenerationSettings?.enabled
    ? "视频生成尚未启用"
    : compatibleVideoModels.length === 0
      ? "没有已开放且支持有序多图参考的视频模型"
    : !selectedModel
      ? "请选择支持有序多图参考的视频模型"
      : referenceFrames.length === 0
        ? "当前分镜还没有可用于视频生成的画面"
        : !allReferencesApproved
          ? `请先确认全部必需画面（${approvedReferenceCount}/${referenceFrames.length}）`
          : referenceLimitExceeded
            ? `${selectedModel.label} 最多接收 ${selectedModel.capabilities.maximum_reference_images} 张参考图`
            : !providerSettings?.api_key_configured
              ? `尚未配置 ${providerSettings?.label || selectedModel.provider} API Key`
              : null;
  const estimatedCostLabel = estimatedCostMicros == null
    ? "按实际用量结算"
    : `¥${(estimatedCostMicros / 1_000_000).toFixed(2)}`;
  useEffect(() => {
    setDisplayedCandidateId(
      initialCandidateId && candidates.some((item) => item.id === initialCandidateId)
        ? initialCandidateId
        : null,
    );
    setDurationAdjustmentMessage("");
    setDiagnosticCopyState("");
  }, [initialCandidateId, latestRun?.id, plan?.id]);

  useEffect(() => {
    if (compatibleVideoModels.length === 0 || selectedModel) return;
    const fallback = compatibleVideoModels[0];
    setVideoDraft((current) => ({
      ...current,
      modelAlias: fallback.alias,
      durationSeconds: String(normalizeVideoDuration(
        current.durationSeconds || plan?.duration_seconds,
        fallback,
      )),
      resolution: preferredVideoResolution(fallback, current.resolution),
    }));
  }, [compatibleVideoModels, plan?.duration_seconds, selectedModel, setVideoDraft]);

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
    const model = compatibleVideoModels.find((item) => item.alias === modelAlias);
    const nextDuration = normalizeVideoDuration(
      videoDraft.durationSeconds || plan?.duration_seconds,
      model,
    );
    const previousDuration = Number(videoDraft.durationSeconds);
    setVideoDraft((current) => ({
      ...current,
      modelAlias,
      durationSeconds: String(nextDuration),
      resolution: preferredVideoResolution(model, current.resolution),
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

  function focusModelSelector() {
    modelSelectRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => modelSelectRef.current?.focus(), 180);
  }

  async function copyFailureDiagnostics() {
    const diagnostic = videoGenerationDiagnosticText(latestFailure);
    if (!diagnostic) return;
    try {
      await navigator.clipboard.writeText(diagnostic);
      setDiagnosticCopyState("已复制");
    } catch {
      setDiagnosticCopyState("复制失败，请手动选择文本");
    }
  }

  return (
    <section className="shot-video-workspace">
      <header className="shot-video-stage-header">
        <div>
          <h3>分段视频工作台</h3>
          <p>按图号把已确认画面作为有序多图参考，逐分镜生成、播放和审核视频候选。</p>
        </div>
        <div className="shot-video-gate">
          <span>
            {gate?.approved_shot_count || 0} / {gate?.required_shot_count || 0} 已采用
          </span>
          <button
            className="primary-button compact"
            disabled={busy || advanced || !gate?.allowed}
            onClick={onAdvance}
            type="button"
          >
            {advanced ? "已进入视频剪辑" : "进入视频剪辑"}
            <ArrowRight size={16} />
          </button>
        </div>
      </header>

      <div className="shot-video-foundation-note">
        <MagicWand size={18} weight="fill" />
        <span><strong>有序多图视频模型 API</strong>：图1、图2……将按画面轨道顺序提交；不支持任意多图参考的模型不会出现在可选列表中。</span>
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

          <div className="shot-video-preview-stack">
            <article className="shot-video-preview-card shot-video-reference-card">
              <header>
                <span>有序参考画面</span>
                <small>{approvedReferenceCount}/{referenceFrames.length} 已确认 · 按图号提交</small>
              </header>
              <div className="shot-video-storyboard" aria-label="有序多图参考故事板">
                {referenceFrames.length > 0 ? referenceFrames.map(({ beat, candidate }, index) => (
                  <div className="shot-video-storyboard-step" key={beat.id}>
                    <figure className={candidate ? "ready" : "missing"}>
                      <div className="shot-video-storyboard-image">
                        {candidate ? (
                          <img
                            alt={`图${beat.index} ${beat.title}`}
                            src={resolveUrl(candidate.thumbnail_url || candidate.content_url)}
                          />
                        ) : (
                          <span><WarningCircle size={22} />待确认</span>
                        )}
                        <b>图{beat.index}</b>
                      </div>
                    </figure>
                    {index < referenceFrames.length - 1 && (
                      <span className="shot-video-storyboard-transition">
                        <ArrowRight size={15} />
                        <small>{beat.transition_to_next_type === "cut" ? "切换" : "连续转场"}</small>
                      </span>
                    )}
                  </div>
                )) : (
                  <div className="shot-video-media-placeholder">
                    <WarningCircle size={26} /><span>请先在分镜图片阶段创建画面</span>
                  </div>
                )}
              </div>
            </article>

            <article className="shot-video-preview-card">
              <header>
                <span>视频候选</span>
                <small>{videoGenerationRunLabel(displayedCandidateRun || latestRun)}</small>
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
                      aria-label={`下载视频 ${displayedCandidate.sequence || displayedCandidate.ordinal}`}
                      className="shot-video-download-button"
                      download={`shot-${plan.index}-video-${displayedCandidate.sequence || displayedCandidate.ordinal}.mp4`}
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

          <VideoCandidateLibrary
            archivedCandidateGroups={archivedCandidateGroups}
            busy={busy}
            candidateGroups={candidateGroups}
            displayedCandidate={displayedCandidate}
            onArchiveCandidates={onArchiveCandidates}
            onPreviewCandidate={setDisplayedCandidateId}
            onRestoreCandidates={onRestoreCandidates}
            plan={plan}
            resolveUrl={resolveUrl}
          />

          <div className="shot-video-prompt-panel">
            {latestFailure && !activeRun && (
              <section className="shot-video-generation-error" role="alert">
                <span className="shot-video-generation-error-icon" aria-hidden="true">
                  <WarningCircle size={20} weight="fill" />
                </span>
                <div className="shot-video-generation-error-copy">
                  <strong>{latestFailure.title}</strong>
                  <p>{latestFailure.message}</p>
                  <div className="shot-video-generation-error-actions">
                    {latestFailure.action === "open_model_settings" && onOpenModelSettings && (
                      <button className="secondary-button compact" onClick={onOpenModelSettings} type="button">
                        <Gear size={15} />打开模型设置
                      </button>
                    )}
                    {compatibleVideoModels.length > 1 && (
                      <button className="secondary-button compact" onClick={focusModelSelector} type="button">
                        切换模型
                      </button>
                    )}
                    {latestFailure.retryable && (
                      <button className="secondary-button compact" disabled={busy} onClick={() => onRetryRun(latestRun.id)} type="button">
                        重试生成
                      </button>
                    )}
                  </div>
                  <details className="shot-video-generation-error-details">
                    <summary>技术详情</summary>
                    <dl>
                      <div><dt>错误码</dt><dd>{latestFailure.code}</dd></div>
                      {latestFailure.providerCode && (
                        <div><dt>Provider 错误码</dt><dd>{latestFailure.providerCode}</dd></div>
                      )}
                      <div><dt>模型</dt><dd>{latestFailure.modelLabel}</dd></div>
                      {latestFailure.providerRequestId && (
                        <div><dt>任务编号</dt><dd>{latestFailure.providerRequestId}</dd></div>
                      )}
                      {latestFailure.technicalMessage && (
                        <div className="technical-message"><dt>技术信息</dt><dd>{latestFailure.technicalMessage}</dd></div>
                      )}
                    </dl>
                    <button className="text-button compact" onClick={copyFailureDiagnostics} type="button">
                      <Copy size={14} />{diagnosticCopyState || "复制诊断信息"}
                    </button>
                  </details>
                </div>
              </section>
            )}
            <label>
              <span>视频提示词</span>
              <textarea
                className="prompt-editor-textarea"
                maxLength={8000}
                onChange={(event) => setVideoDraft((current) => ({
                  ...current,
                  videoPrompt: event.target.value,
                }))}
                rows={5}
                value={videoDraft.videoPrompt}
              />
            </label>
            <details className="shot-video-negative-constraints">
              <summary>视频负面约束（可选）</summary>
              <textarea
                aria-label="视频负面约束"
                className="prompt-editor-textarea"
                maxLength={3000}
                onChange={(event) => setVideoDraft((current) => ({
                  ...current,
                  negativeConstraints: event.target.value,
                }))}
                placeholder="每行一项，例如：人物身份漂移"
                rows={3}
                value={videoDraft.negativeConstraints}
              />
            </details>
            <div className="shot-video-generation-options">
              <label className="shot-video-generation-field">
                <span className="shot-video-field-heading">视频模型</span>
                <select
                  ref={modelSelectRef}
                  onChange={(event) => selectVideoModel(event.target.value)}
                  value={videoDraft.modelAlias}
                >
                  {compatibleVideoModels.length === 0 ? (
                    <option value="">暂无兼容模型</option>
                  ) : compatibleVideoModels.map((model) => (
                    <option key={model.alias} value={model.alias}>
                      {model.label}
                      {latestFailure && latestRun?.model_alias === model.alias ? " · 需处理" : ""}
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
              {!activeRun && latestRun?.status === "cancelled" && (
                <button className="secondary-button compact" disabled={busy} onClick={() => onRetryRun(latestRun.id)} type="button">
                  重试上次任务
                </button>
              )}
              <button className="secondary-button compact" disabled={busy} onClick={onSave} type="button">
                <FloppyDisk size={16} />保存提示词
              </button>
              <button
                className="primary-button compact"
                disabled={busy || Boolean(activeRun) || !allReferencesApproved || !videoDraft.videoPrompt.trim() || Boolean(generationBlockedReason)}
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
                  视频 #{displayedCandidate.sequence || displayedCandidate.ordinal} · {displayedCandidateRun?.model_display_name || displayedCandidateRun?.model_alias || displayedCandidateRun?.model || "视频模型"}
                </strong>
                <span>
                  {displayedCandidate.duration_seconds?.toFixed(1)} 秒 · {displayedCandidate.width} × {displayedCandidate.height} · {displayedCandidateCostLabel}
                </span>
              </div>
              {plan.video_status === "approved" && plan.approved_video_candidate_id === displayedCandidate.id ? (
                <button className="secondary-button compact" disabled={busy} onClick={onRevokeApproval} type="button">取消采用</button>
              ) : (
                <>
                  <button className="secondary-button compact" disabled={busy || displayedCandidate.status === "rejected"} onClick={rejectDisplayedCandidate} type="button">退回</button>
                  {plan.video_status === "approved" ? (
                    <button className="primary-button compact" disabled={busy} onClick={() => onApprove(displayedCandidate.id)} type="button"><CheckCircle size={16} weight="fill" />改用此视频</button>
                  ) : displayedCandidate.status === "selected" ? (
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
