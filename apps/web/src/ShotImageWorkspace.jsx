import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CheckCircle,
  CircleNotch,
  Copy,
  DotsSixVertical,
  FloppyDisk,
  ImageSquare,
  MagicWand,
  Plus,
  Trash,
  VideoCamera,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  REFERENCE_ROLE_OPTIONS,
  SHOT_LOCK_OPTIONS,
  estimateImageGenerationCostMicros,
  generationFailureGuidance,
  imageGenerationModeLabel,
  imageGenerationRunLabel,
  imageQualityLabel,
  isAiImageGenerationRun,
  isImageEngineConfigured,
  productionPreviewLayout,
  resolveImageExecutionMode,
  workflowStatusClass,
  workflowStatusLabel,
} from "./production-ui.js";
import { ShotNavigationThumbnail } from "./ShotNavigationThumbnail.jsx";

const DEFAULT_ROLE_BY_TYPE = Object.freeze({
  person: "identity",
  product: "product",
  wardrobe: "wardrobe",
  scene: "scene",
  style: "style",
  prop: "layout",
});

function seconds(value) {
  return Number(value || 0).toFixed(1);
}

function formatCostMicros(value) {
  const yuan = Math.max(0, Number(value || 0)) / 1_000_000;
  return `¥${yuan.toFixed(yuan > 0 ? 2 : 0)}`;
}

function generationRunStatusLabel(status) {
  return {
    queued: "排队中",
    running: "生成中",
    cancellation_requested: "取消中",
    cancelled: "已取消",
    completed: "已完成",
    cached: "缓存命中",
    failed: "生成失败",
    blocked: "已阻止",
  }[status] || "未开始";
}

function MediaPreview({ src, alt, emptyLabel }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return (
      <div className="shot-media-empty">
        <ImageSquare size={30} />
        <span>{emptyLabel}</span>
      </div>
    );
  }
  return <img alt={alt} onError={() => setFailed(true)} src={src} />;
}

function AssetThumbnail({ asset, resolveUrl }) {
  const [failed, setFailed] = useState(false);
  const source = resolveUrl(asset.thumbnail_url);

  useEffect(() => {
    setFailed(false);
  }, [source]);

  if (!source || failed) {
    return <span className="shot-reference-thumb fallback"><ImageSquare size={18} /></span>;
  }
  return (
    <span className="shot-reference-thumb">
      <img
        alt={asset.name + "缩略图"}
        loading="lazy"
        onError={() => setFailed(true)}
        src={source}
      />
    </span>
  );
}

function KeyframePicker({
  plan,
  sourceVideoUrl,
  busy,
  onClose,
  onConfirm,
}) {
  const videoRef = useRef(null);
  const start = Number(plan.start_seconds || 0);
  const end = Number(plan.end_seconds || start);
  const initial = Math.min(
    end,
    Math.max(start, Number(plan.source_keyframe_timestamp_seconds ?? (start + end) / 2)),
  );
  const [timestamp, setTimestamp] = useState(initial);

  useEffect(() => {
    setTimestamp(initial);
  }, [initial, plan.id]);

  function seek(nextValue) {
    const next = Math.min(end, Math.max(start, Number(nextValue) || start));
    setTimestamp(next);
    if (videoRef.current) videoRef.current.currentTime = next;
  }

  function keepInsideShot() {
    const video = videoRef.current;
    if (!video) return;
    if (video.currentTime < start) {
      video.currentTime = start;
      return;
    }
    if (video.currentTime > end) {
      video.pause();
      video.currentTime = end;
    }
    setTimestamp(Math.min(end, Math.max(start, video.currentTime)));
  }

  return (
    <div className="keyframe-picker-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <section
        aria-label="从源视频选择关键帧"
        aria-modal="true"
        className="keyframe-picker"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h4>从源视频选择关键帧</h4>
            <p>仅可选择当前分镜 {seconds(start)}s 到 {seconds(end)}s 的画面。</p>
          </div>
          <button aria-label="关闭" disabled={busy} onClick={onClose} type="button"><X size={17} /></button>
        </header>
        <div className="keyframe-picker-video">
          <video
            controls
            onLoadedMetadata={() => seek(timestamp)}
            onTimeUpdate={keepInsideShot}
            preload="metadata"
            ref={videoRef}
            src={sourceVideoUrl}
          />
        </div>
        <div className="keyframe-picker-timeline">
          <input
            aria-label="关键帧时间"
            max={end}
            min={start}
            onChange={(event) => seek(event.target.value)}
            step="0.01"
            type="range"
            value={timestamp}
          />
          <label>
            <span>时间点</span>
            <input
              max={end}
              min={start}
              onChange={(event) => seek(event.target.value)}
              step="0.01"
              type="number"
              value={timestamp.toFixed(2)}
            />
            <span>秒</span>
          </label>
        </div>
        <footer>
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button
            className="primary-button compact"
            disabled={busy}
            onClick={() => {
              onConfirm(timestamp);
              onClose();
            }}
            type="button"
          >
            <ImageSquare size={16} />
            使用这一帧
          </button>
        </footer>
      </section>
    </div>
  );
}

function ShotCreateDialog({ currentPlan, busy, onClose, onCreate }) {
  const [mode, setMode] = useState("duplicate");
  const start = Number(currentPlan?.end_seconds || 0);
  const [startSeconds, setStartSeconds] = useState(start.toFixed(2));
  const [endSeconds, setEndSeconds] = useState((start + 3).toFixed(2));
  const [keyframeSeconds, setKeyframeSeconds] = useState((start + 1.5).toFixed(2));
  const [imagePrompt, setImagePrompt] = useState("");

  function submit(event) {
    event.preventDefault();
    const payload = {
      mode,
      insert_after_shot_plan_id: currentPlan?.id || null,
      image_prompt: imagePrompt.trim(),
    };
    if (mode === "duplicate") {
      payload.source_shot_plan_id = currentPlan.id;
    }
    if (mode === "video_range") {
      payload.start_seconds = Number(startSeconds);
      payload.end_seconds = Number(endSeconds);
      payload.source_keyframe_timestamp_seconds = Number(keyframeSeconds);
    }
    onCreate(payload);
    onClose();
  }

  return (
    <div className="keyframe-picker-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <form
        aria-label="新增分镜"
        aria-modal="true"
        className="keyframe-picker shot-create-dialog"
        onSubmit={submit}
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div><h4>新增分镜</h4><p>新分镜将插入到当前分镜之后。</p></div>
          <button aria-label="关闭" disabled={busy} onClick={onClose} type="button"><X size={17} /></button>
        </header>
        <div className="shot-create-options">
          <label className={mode === "duplicate" ? "active" : ""}>
            <input checked={mode === "duplicate"} onChange={() => setMode("duplicate")} type="radio" />
            <Copy size={19} /><span><strong>复制当前分镜</strong><small>复制提示词、关键帧和资产绑定，不复制生成结果。</small></span>
          </label>
          <label className={mode === "video_range" ? "active" : ""}>
            <input checked={mode === "video_range"} onChange={() => setMode("video_range")} type="radio" />
            <VideoCamera size={19} /><span><strong>从源视频选段</strong><small>指定时间范围并提取新的关键帧。</small></span>
          </label>
          <label className={mode === "blank" ? "active" : ""}>
            <input checked={mode === "blank"} onChange={() => setMode("blank")} type="radio" />
            <Plus size={19} /><span><strong>空白分镜</strong><small>适合纯文生图，默认时长 3 秒。</small></span>
          </label>
        </div>
        {mode === "video_range" && (
          <div className="shot-create-timing">
            <label><span>开始（秒）</span><input min="0" onChange={(event) => setStartSeconds(event.target.value)} required step="0.01" type="number" value={startSeconds} /></label>
            <label><span>结束（秒）</span><input min="0.01" onChange={(event) => setEndSeconds(event.target.value)} required step="0.01" type="number" value={endSeconds} /></label>
            <label><span>关键帧（秒）</span><input min="0" onChange={(event) => setKeyframeSeconds(event.target.value)} required step="0.01" type="number" value={keyframeSeconds} /></label>
          </div>
        )}
        {mode !== "duplicate" && (
          <label className="production-field shot-create-prompt">
            <span>初始图片提示词（可稍后填写）</span>
            <textarea onChange={(event) => setImagePrompt(event.target.value)} rows={3} value={imagePrompt} />
          </label>
        )}
        <footer>
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button className="primary-button compact" disabled={busy} type="submit"><Plus size={16} />新增分镜</button>
        </footer>
      </form>
    </div>
  );
}

export function ShotImageWorkspace({
  shots,
  shotDetail,
  selectedShotId,
  draft,
  setDraft,
  assets,
  gate,
  generationCandidateCount,
  generationEngine,
  generationInputMode,
  generationSettings,
  project,
  advanced,
  busy,
  error,
  resolveUrl,
  rejectReason,
  setRejectReason,
  setGenerationCandidateCount,
  setGenerationEngine,
  setGenerationInputMode,
  sourceVideoUrl,
  onSelectShot,
  onSave,
  onGenerate,
  onCancelRun,
  onSelectKeyframe,
  onApproveSource,
  onCreateShot,
  onDiscardShot,
  onSelectCandidate,
  onApprove,
  onReject,
  onRevokeApproval,
  onReorderShots,
  onRetryRun,
  onRestoreShot,
  onAdvance,
}) {
  const [keyframePickerOpen, setKeyframePickerOpen] = useState(false);
  const [shotCreateOpen, setShotCreateOpen] = useState(false);
  const [showDiscarded, setShowDiscarded] = useState(false);
  const [draggedShotId, setDraggedShotId] = useState(null);
  const [displayedCandidateId, setDisplayedCandidateId] = useState(null);
  const [visualChoice, setVisualChoice] = useState("source");
  const [mentionMenu, setMentionMenu] = useState(null);
  const promptRef = useRef(null);
  const plan = shotDetail?.plan;
  const previewLayout = productionPreviewLayout(project);
  const previewCanvasStyle = {
    "--shot-preview-aspect-ratio": previewLayout.aspectRatio,
    "--shot-preview-max-width": previewLayout.maxWidth,
  };
  const activeShots = useMemo(
    () => shots.filter((item) => item.plan.lifecycle_status !== "discarded"),
    [shots],
  );
  const discardedShots = useMemo(
    () => shots.filter((item) => item.plan.lifecycle_status === "discarded"),
    [shots],
  );
  const generationRuns = shotDetail?.generation_runs || [];
  const latestRun = generationRuns.find((run) => run.kind === "image") || null;
  const candidates = useMemo(() => {
    if (!isAiImageGenerationRun(latestRun)) return [];
    return (latestRun?.candidates || []).filter(
      (candidate) => candidate.status !== "archived",
    );
  }, [latestRun]);
  const hasPriorAiCandidates = generationRuns.some(
    (run) => isAiImageGenerationRun(run) && (run.candidates || []).length > 0,
  );
  const candidateCount = Math.min(
    4,
    Math.max(1, Math.trunc(Number(generationCandidateCount) || 1)),
  );
  const executionMode = resolveImageExecutionMode(
    generationSettings,
    generationEngine,
  );
  const effectiveGenerationSettings = {
    ...generationSettings,
    execution_mode: executionMode || generationSettings?.execution_mode,
  };
  const estimatedCostMicros = estimateImageGenerationCostMicros(
    effectiveGenerationSettings,
    candidateCount,
  );
  const modeLabel = imageGenerationModeLabel(effectiveGenerationSettings);
  const selectedModel = (generationSettings?.models || []).find(
    (item) => item.alias === generationSettings?.remote_model_alias,
  );
  const configuredEngine = !generationSettings?.enabled
    ? "尚未配置"
    : executionMode === "local_tool"
      ? generationSettings.local_tool_id || "已配置 CLI"
      : selectedModel?.label || generationSettings.remote_model || "Qwen Image";
  const usesSubscriptionQuota = (
    generationSettings?.enabled
    && executionMode === "local_tool"
    && generationSettings.local_cost_source === "subscription_quota"
  );
  const configuredCostLabel = !generationSettings?.enabled
    ? "配置后显示成本"
    : usesSubscriptionQuota
      ? "使用订阅配额，金额不计入项目成本"
    : estimatedCostMicros == null
      ? "成本未知，生成前确认"
      : `预计 ${formatCostMicros(estimatedCostMicros)} / 次`;
  const latestRunCostLabel = latestRun?.cost_source === "subscription_quota"
    ? "使用订阅配额"
    : latestRun?.cost_source === "unknown"
      ? "成本未知"
      : latestRun
        ? `实际 ${formatCostMicros(latestRun.actual_cost_micros)}`
        : "";
  const latestRunBusy = ["queued", "running", "cancellation_requested"].includes(
    latestRun?.status,
  );
  const latestRunRetryable = ["failed", "blocked", "cancelled"].includes(
    latestRun?.status,
  );
  const latestRunTone = ["completed", "cached"].includes(latestRun?.status)
    ? "completed"
    : ["failed", "blocked"].includes(latestRun?.status)
      ? "failed"
      : latestRunBusy
        ? "running"
        : "idle";
  const displayedCandidate = (
    candidates.find((item) => item.id === displayedCandidateId)
    || candidates.find((item) => item.id === plan?.approved_image_candidate_id)
    || candidates.find((item) => item.status === "selected")
    || candidates[0]
    || null
  );
  const selectedForApproval = plan?.image_status === "approved"
    ? null
    : displayedCandidate?.status === "selected" ? displayedCandidate : null;
  const remoteConfigured = isImageEngineConfigured(
    generationSettings,
    "remote_api",
  );
  const localConfigured = isImageEngineConfigured(
    generationSettings,
    "local_tool",
  );
  const generationAvailable = Boolean(
    generationSettings?.enabled
    && executionMode
    && (
      executionMode === "local_tool"
        ? localConfigured
        : remoteConfigured
    ),
  );
  const ignoredSimulation = Boolean(
    latestRun
    && (
      latestRun.provider === "simulated"
      || latestRun.execution_mode === "simulated"
    ),
  );

  useEffect(() => {
    const preferred = (
      candidates.find((item) => item.id === plan?.approved_image_candidate_id)
      || candidates.find((item) => item.status === "selected")
      || candidates[0]
      || null
    );
    setDisplayedCandidateId(preferred?.id || null);
    setVisualChoice(
      plan?.image_status === "approved" && latestRun?.provider === "source_video"
        ? "source"
        : preferred && (
          preferred.status === "selected"
          || preferred.id === plan?.approved_image_candidate_id
        )
          ? "candidate"
          : "source",
    );
    setMentionMenu(null);
  }, [plan?.id, plan?.approved_image_candidate_id, latestRun?.id]);

  useEffect(() => {
    if (plan?.source_kind === "blank") setGenerationInputMode("text_to_image");
  }, [plan?.id, plan?.source_kind, setGenerationInputMode]);

  function toggleLock(lockId) {
    setDraft((state) => ({
      ...state,
      locks: state.locks.includes(lockId)
        ? state.locks.filter((item) => item !== lockId)
        : [...state.locks, lockId],
    }));
  }

  function toggleBinding(asset) {
    setDraft((state) => {
      const exists = state.referenceBindings.some(
        (item) => item.reference_asset_id === asset.id,
      );
      const mention = state.imagePromptMentions.find(
        (item) => item.reference_asset_id === asset.id,
      );
      return {
        ...state,
        referenceBindings: exists
          ? state.referenceBindings.filter(
            (item) => item.reference_asset_id !== asset.id,
          )
          : [
            ...state.referenceBindings,
            {
              reference_asset_id: asset.id,
              role: DEFAULT_ROLE_BY_TYPE[asset.type] || "layout",
              weight: 1,
            },
          ],
        imagePromptMentions: exists
          ? state.imagePromptMentions.filter(
            (item) => item.reference_asset_id !== asset.id,
          )
          : state.imagePromptMentions,
        imagePrompt: exists
          ? state.imagePrompt
            .replaceAll("@" + (mention?.label || asset.name), "")
            .replace(/\s{2,}/g, " ")
          : state.imagePrompt,
      };
    });
  }

  function changeBindingRole(assetId, role) {
    setDraft((state) => ({
      ...state,
      referenceBindings: state.referenceBindings.map((item) => (
        item.reference_asset_id === assetId ? { ...item, role } : item
      )),
    }));
  }

  function moveShot(shotId, offset) {
    const currentIndex = activeShots.findIndex((item) => item.plan.id === shotId);
    const targetIndex = currentIndex + offset;
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= activeShots.length) return;
    const next = activeShots.map((item) => item.plan.id);
    const [moved] = next.splice(currentIndex, 1);
    next.splice(targetIndex, 0, moved);
    onReorderShots(next);
  }

  function dropShot(targetShotId) {
    if (!draggedShotId || draggedShotId === targetShotId) return;
    const next = activeShots.map((item) => item.plan.id);
    const sourceIndex = next.indexOf(draggedShotId);
    const targetIndex = next.indexOf(targetShotId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const [moved] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, moved);
    setDraggedShotId(null);
    onReorderShots(next);
  }

  function chooseCandidate(candidate) {
    if (!candidate || plan?.image_status === "approved") return;
    setDisplayedCandidateId(candidate.id);
    setVisualChoice("candidate");
    if (candidate.status === "ready") onSelectCandidate(candidate.id);
  }

  function updatePrompt(event) {
    const value = event.target.value;
    const cursor = event.target.selectionStart ?? value.length;
    const prefix = value.slice(0, cursor);
    const match = prefix.match(/@([^@\s]*)$/);
    setDraft((state) => ({
      ...state,
      imagePrompt: value,
      imagePromptMentions: state.imagePromptMentions.filter(
        (item) => value.includes("@" + item.label),
      ),
    }));
    setMentionMenu(match ? { start: cursor - match[1].length - 1, end: cursor, query: match[1] } : null);
  }

  function insertMention(asset) {
    if (!mentionMenu) return;
    setDraft((state) => {
      const token = "@" + asset.name;
      const nextPrompt = (
        state.imagePrompt.slice(0, mentionMenu.start)
        + token
        + " "
        + state.imagePrompt.slice(mentionMenu.end)
      );
      const hasMention = state.imagePromptMentions.some(
        (item) => item.reference_asset_id === asset.id,
      );
      const hasBinding = state.referenceBindings.some(
        (item) => item.reference_asset_id === asset.id,
      );
      return {
        ...state,
        imagePrompt: nextPrompt,
        imagePromptMentions: hasMention
          ? state.imagePromptMentions
          : [...state.imagePromptMentions, { reference_asset_id: asset.id, label: asset.name }],
        referenceBindings: hasBinding
          ? state.referenceBindings
          : [
            ...state.referenceBindings,
            {
              reference_asset_id: asset.id,
              role: DEFAULT_ROLE_BY_TYPE[asset.type] || "layout",
              weight: 1,
            },
          ],
      };
    });
    setMentionMenu(null);
    requestAnimationFrame(() => promptRef.current?.focus());
  }

  const mentionAssets = mentionMenu
    ? assets.filter((asset) => (
      !mentionMenu.query
      || asset.name.toLowerCase().includes(mentionMenu.query.toLowerCase())
    ))
    : [];

  return (
    <section className="shot-image-workspace">
      <header className="shot-workspace-header">
        <div>
          <h3>分镜图片工作台</h3>
          <p>
            编辑静态画面指令，通过{modeLabel}生成候选，人工确认后再进入分段视频。
          </p>
        </div>
        <div className="shot-gate-summary">
          <span>{gate?.approved_shot_count || 0} / {gate?.required_shot_count || shots.length} 已确认</span>
          <button
            className="primary-button compact"
            disabled={busy || advanced || !gate?.allowed}
            onClick={onAdvance}
            type="button"
          >
            {advanced ? "已进入分段视频" : "进入分段视频"}
            <ArrowRight size={15} />
          </button>
        </div>
      </header>

      {error && (
        <div className="production-inline-error" role="alert">
          <WarningCircle size={17} />
          {error}
        </div>
      )}
      {gate?.blocker_messages?.length > 0 && (
        <div className="shot-gate-message">
          {gate.blocker_messages.join("；")}
        </div>
      )}

      <div className={"shot-generation-context " + latestRunTone}>
        <span className="shot-generation-context-icon">
          {latestRunBusy
            ? <CircleNotch className="spin" size={18} />
            : latestRunTone === "failed"
              ? <WarningCircle size={18} weight="fill" />
              : latestRunTone === "completed"
                ? <CheckCircle size={18} weight="fill" />
                : <MagicWand size={18} weight="fill" />}
        </span>
        <div>
          <strong>
            {latestRun
              ? `${generationRunStatusLabel(latestRun.status)} · ${latestRun.model}`
              : `${modeLabel} · ${configuredEngine}`}
          </strong>
          <small>
           {latestRun
              ? `${imageGenerationRunLabel(latestRun)} · ${latestRun.input_mode === "text_to_image" ? "纯文生图" : "关键帧编辑"} · ${latestRunCostLabel}${latestRun.latency_ms == null ? "" : " · " + latestRun.latency_ms + " ms"}`
             : `默认生成 ${candidateCount} 张 · ${configuredCostLabel}`}
          </small>
          {ignoredSimulation && (
            <em>历史模拟占位候选已忽略，不会作为 AI 图片或通过工作流确认。</em>
          )}
          {latestRunTone === "failed" && (
            <em>{latestRun.error_message || "生成未完成，请检查模型设置后重试。"}</em>
          )}
          {latestRun?.status === "cancelled" && (
            <em>任务已取消，可保留当前设置重试上次任务。</em>
          )}
        </div>
        <span className="shot-generation-mode">{modeLabel}</span>
      </div>

      <div className="shot-workspace-grid">
        <aside className="shot-navigation-panel">
          <div className="shot-panel-title">
            <div><strong>分镜列表</strong><small>{activeShots.length} 个有效镜头</small></div>
            <button
              className="shot-add-button"
              disabled={busy || !plan}
              onClick={() => setShotCreateOpen(true)}
              type="button"
            >
              <Plus size={15} />新增
            </button>
          </div>
          <div className="shot-navigation-list">
            {activeShots.map((item, itemIndex) => {
              const shot = item.plan;
              const active = shot.id === selectedShotId;
              return (
                <div
                  className={`shot-navigation-item ${active ? "active" : ""} ${draggedShotId === shot.id ? "dragging" : ""}`}
                  draggable={!busy}
                  key={shot.id}
                  onDragEnd={() => setDraggedShotId(null)}
                  onDragOver={(event) => event.preventDefault()}
                  onDragStart={() => setDraggedShotId(shot.id)}
                  onDrop={() => dropShot(shot.id)}
                >
                  <DotsSixVertical className="shot-drag-handle" size={17} />
                  <button className="shot-navigation-main" onClick={() => onSelectShot(shot.id)} type="button">
                    <ShotNavigationThumbnail
                      index={shot.index}
                      resolveUrl={resolveUrl}
                      sources={[
                        item.image_preview && {
                          kind: item.image_preview.kind,
                          url: item.image_preview.thumbnail_url,
                        },
                        { kind: "source_keyframe", url: shot.source_keyframe_url },
                      ]}
                    />
                    <span className="shot-navigation-copy">
                      <strong>分镜 {shot.index}</strong>
                      <small>{seconds(shot.start_seconds)}s — {seconds(shot.end_seconds)}s</small>
                    </span>
                    <span className={"shot-status-badge " + workflowStatusClass(shot.image_status)}>
                      {workflowStatusLabel(shot.image_status)}
                    </span>
                  </button>
                  <div className="shot-navigation-actions">
                    <button aria-label="上移分镜" disabled={busy || itemIndex === 0} onClick={() => moveShot(shot.id, -1)} title="上移" type="button"><ArrowUp size={13} /></button>
                    <button aria-label="下移分镜" disabled={busy || itemIndex === activeShots.length - 1} onClick={() => moveShot(shot.id, 1)} title="下移" type="button"><ArrowDown size={13} /></button>
                    <button aria-label="舍弃分镜" disabled={busy || activeShots.length <= 1} onClick={() => onDiscardShot(shot.id)} title="舍弃" type="button"><Trash size={13} /></button>
                  </div>
                </div>
              );
            })}
          </div>
          {discardedShots.length > 0 && (
            <div className="shot-discarded-section">
              <button onClick={() => setShowDiscarded((value) => !value)} type="button">
                <span>已舍弃 {discardedShots.length}</span>
                <small>{showDiscarded ? "收起" : "展开"}</small>
              </button>
              {showDiscarded && discardedShots.map((item) => (
                <div className="shot-discarded-item" key={item.plan.id}>
                  <ShotNavigationThumbnail
                    className="compact muted"
                    index={item.plan.index}
                    resolveUrl={resolveUrl}
                    sources={[
                      item.image_preview && {
                        kind: item.image_preview.kind,
                        url: item.image_preview.thumbnail_url,
                      },
                      { kind: "source_keyframe", url: item.plan.source_keyframe_url },
                    ]}
                  />
                  <span className="shot-discarded-copy">原分镜 · {seconds(item.plan.start_seconds)}s—{seconds(item.plan.end_seconds)}s</span>
                  <button disabled={busy} onClick={() => onRestoreShot(item.plan.id)} type="button"><ArrowCounterClockwise size={13} />恢复</button>
                </div>
              ))}
            </div>
          )}
        </aside>

        <main className="shot-canvas-panel">
          {!plan ? (
            <div className="shot-workspace-loading">
              <CircleNotch className="spin" size={24} />
              正在读取分镜
            </div>
          ) : (
            <>
              <div className="shot-canvas-heading">
                <div>
                  <small>分镜 {plan.index}</small>
                  <strong>{seconds(plan.start_seconds)}s — {seconds(plan.end_seconds)}s</strong>
                </div>
                <span className={"workflow-pill " + workflowStatusClass(plan.image_status)}>
                  {workflowStatusLabel(plan.image_status)}
                </span>
              </div>
              {plan.image_status === "stale" && (
                <div className="shot-stale-warning">
                  <WarningCircle size={17} weight="fill" />
                  上游输入已经修改，旧审批图仍保留，但必须重新生成并确认。
                </div>
              )}
              <div
                className={`shot-compare-grid shot-compare-${previewLayout.orientation}`}
                style={previewCanvasStyle}
              >
                <figure
                  className={visualChoice === "source" ? "selected" : ""}
                  onClick={() => {
                    if (plan.source_keyframe_url && plan.image_status !== "approved") {
                      setVisualChoice("source");
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <figcaption>
                    <div>
                      <strong>当前关键帧</strong>
                      <small>
                        {plan.source_keyframe_origin === "video_selection" ? "视频选帧" : "分析默认帧"}
                        {plan.source_keyframe_timestamp_seconds == null
                          ? ""
                          : " · " + seconds(plan.source_keyframe_timestamp_seconds) + "s"}
                      </small>
                    </div>
                    <span>{visualChoice === "source" ? "已选择" : "选择此图"}</span>
                  </figcaption>
                  <div className="shot-media-frame">
                    <MediaPreview
                      alt={"分镜 " + plan.index + " 原始关键帧"}
                      emptyLabel="原始关键帧不可用"
                      src={resolveUrl(plan.source_keyframe_url)}
                    />
                  </div>
                  <div className="shot-source-actions">
                    <button
                      disabled={busy || !sourceVideoUrl}
                      onClick={(event) => {
                        event.stopPropagation();
                        setKeyframePickerOpen(true);
                      }}
                      type="button"
                    >
                      <VideoCamera size={15} />
                      从视频重选
                    </button>
                  </div>
                </figure>
                <figure
                  className={visualChoice === "candidate" ? "selected" : ""}
                  onClick={() => chooseCandidate(displayedCandidate)}
                  role="button"
                  tabIndex={0}
                >
                  <figcaption>
                    <div>
                      <strong>AI 生成图</strong>
                      <small>{displayedCandidate ? "候选 " + displayedCandidate.ordinal : "尚未生成"}</small>
                    </div>
                    {candidates.length > 1 ? (
                      <select
                        aria-label="切换图片候选"
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => {
                          const candidate = candidates.find((item) => item.id === event.target.value);
                          chooseCandidate(candidate);
                        }}
                        value={displayedCandidate?.id || ""}
                      >
                        {candidates.map((candidate) => (
                          <option key={candidate.id} value={candidate.id}>候选 {candidate.ordinal}</option>
                        ))}
                      </select>
                    ) : (
                      <span>{visualChoice === "candidate" ? "已选择" : "选择此图"}</span>
                    )}
                  </figcaption>
                  <div className="shot-media-frame">
                    <MediaPreview
                      alt={"分镜 " + plan.index + " 当前候选"}
                      emptyLabel="点击下方按钮生成候选"
                      src={displayedCandidate ? resolveUrl(displayedCandidate.content_url) : ""}
                    />
                  </div>
                  {displayedCandidate && (
                    <small
                      className={
                        displayedCandidate.quality_report?.status === "warning"
                          ? "shot-candidate-quality warning"
                          : "shot-candidate-quality"
                      }
                      title={displayedCandidate.quality_report?.summary || "该候选没有自动质检报告"}
                    >
                      {imageQualityLabel(displayedCandidate.quality_report)}
                    </small>
                  )}
                </figure>
              </div>

              {latestRunTone === "failed" && !displayedCandidate && (
                <div className="shot-candidate-empty failed">
                  <strong>本次生成失败{latestRun?.error_code ? ` · ${latestRun.error_code}` : ""}</strong>
                  <p>{latestRun?.error_message || "本机工具没有返回可用候选。"}</p>
                  <small>{generationFailureGuidance(latestRun)}</small>
                </div>
              )}

              <section className="shot-generation-controls">
                <header>
                  <div>
                    <strong>AI 生图设置</strong>
                    <small>仅作用于本次生成，不修改全局模型设置</small>
                  </div>
                  <span>默认 1 张</span>
                </header>
                <div>
                  <label>
                    <span>生成方式</span>
                    <select
                      disabled={busy}
                      onChange={(event) => setGenerationInputMode(event.target.value)}
                      value={generationInputMode}
                    >
                      <option value="keyframe_edit">关键帧编辑（文字 + 图片）</option>
                      <option value="text_to_image">纯文生图（仅文字）</option>
                    </select>
                  </label>
                  <label>
                    <span>生图引擎</span>
                    <select
                      disabled={busy}
                      onChange={(event) => setGenerationEngine(event.target.value)}
                      value={generationEngine}
                    >
                      <option value="default">默认（{imageGenerationModeLabel(generationSettings)}）</option>
                      <option disabled={!remoteConfigured} value="remote_api">国内大模型 API{remoteConfigured ? "" : "（未配置）"}</option>
                      <option disabled={!localConfigured} value="local_tool">本机 ImageGen{localConfigured ? "" : "（未配置）"}</option>
                    </select>
                  </label>
                  <label>
                    <span>候选数量</span>
                    <select
                      disabled={busy}
                      onChange={(event) => setGenerationCandidateCount(Number(event.target.value))}
                      value={candidateCount}
                    >
                      {[1, 2, 3, 4].map((count) => (
                        <option key={count} value={count}>{count} 张</option>
                      ))}
                    </select>
                  </label>
                </div>
                <p>
                  {generationInputMode === "text_to_image"
                    ? "纯文生图不会发送当前关键帧或已绑定参考图。"
                    : "关键帧编辑会发送当前关键帧，并附带已绑定的人物、产品或场景参考图。"}
                  {" "}{configuredCostLabel}
                </p>
              </section>

              <div className="shot-review-actions">
                {latestRunBusy && (
                  <button
                    className="secondary-button compact danger-text"
                    disabled={busy || latestRun.status === "cancellation_requested"}
                    onClick={() => onCancelRun(latestRun.id)}
                    type="button"
                  >
                    {latestRun.status === "cancellation_requested"
                      ? <CircleNotch className="spin" size={16} />
                      : <X size={16} />}
                    {latestRun.status === "cancellation_requested" ? "正在取消" : "取消任务"}
                  </button>
                )}
                {plan.image_status === "approved" && (
                  <button
                    className="secondary-button compact"
                    disabled={busy || latestRunBusy}
                    onClick={onRevokeApproval}
                    type="button"
                  >
                    <ArrowCounterClockwise size={16} />
                    取消采用
                  </button>
                )}
                <button
                  className="secondary-button compact"
                  disabled={
                    busy
                    || latestRunBusy
                    || plan.image_status === "approved"
                    || !generationAvailable
                  }
                  onClick={() => (
                    latestRunRetryable
                      ? onRetryRun(latestRun.id)
                      : onGenerate()
                  )}
                  type="button"
                >
                  {busy || latestRunBusy
                    ? <CircleNotch className="spin" size={16} />
                    : <MagicWand size={16} />}
                  {!generationAvailable
                    ? "请先配置生图模型"
                    : latestRunBusy
                    ? "正在生成"
                    : plan.image_status === "approved"
                      ? "取消采用后可生成"
                    : latestRunRetryable
                      ? "重试上次任务"
                      : `生成 ${candidateCount} 个${hasPriorAiCandidates ? "新" : ""}候选`}
                </button>
                <button
                  className="primary-button compact"
                  disabled={
                    busy
                    || latestRunBusy
                    || plan.image_status === "approved"
                    || (visualChoice === "source" && !plan.source_keyframe_url)
                    || (visualChoice === "candidate" && !selectedForApproval)
                  }
                  onClick={() => (
                    visualChoice === "source"
                      ? onApproveSource()
                      : onApprove(selectedForApproval.id)
                  )}
                  type="button"
                >
                  <CheckCircle size={16} weight="fill" />
                  {plan.image_status === "approved" ? "当前画面已采用" : "采用所选画面"}
                </button>
              </div>
              {visualChoice === "candidate" && selectedForApproval && (
                <div className="shot-reject-row">
                  <input
                    maxLength={1000}
                    onChange={(event) => setRejectReason(event.target.value)}
                    placeholder="退回时填写原因"
                    value={rejectReason}
                  />
                  <button
                    className="danger-button compact"
                    disabled={busy || !rejectReason.trim()}
                    onClick={() => onReject(selectedForApproval.id)}
                    type="button"
                  >
                    <X size={15} />
                    退回修改
                  </button>
                </div>
              )}
            </>
          )}
        </main>

        <aside className="shot-inspector-panel">
          <form onSubmit={onSave}>
            <div className="shot-panel-title">
              <div>
                <strong>分镜配置</strong>
                <small>保存草稿不会自动生成</small>
              </div>
              <button className="primary-button compact" disabled={busy || !plan} type="submit">
                {busy ? <CircleNotch className="spin" size={15} /> : <FloppyDisk size={15} />}
                保存
              </button>
            </div>
            <label className="production-field">
              <span>图片提示词</span>
              <div className="shot-prompt-editor">
                <textarea
                  maxLength={8000}
                  onChange={updatePrompt}
                  placeholder="描述画面；输入 @ 可关联人物、产品或场景资产"
                  ref={promptRef}
                  rows={8}
                  value={draft.imagePrompt}
                />
                {mentionMenu && (
                  <div className="shot-mention-menu">
                    <small>关联参考资产</small>
                    {mentionAssets.length === 0 ? (
                      <p>没有匹配的资产</p>
                    ) : mentionAssets.map((asset) => (
                      <button
                        key={asset.id}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => insertMention(asset)}
                        type="button"
                      >
                        <AssetThumbnail asset={asset} resolveUrl={resolveUrl} />
                        <span><strong>@{asset.name}</strong><small>{asset.type}</small></span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <small className="shot-prompt-help">输入 @ 选择资产；系统会保存资产 ID，并自动加入本次图片生成参考。</small>
              {draft.imagePromptMentions.length > 0 && (
                <span className="shot-mention-chips">
                  {draft.imagePromptMentions.map((mention) => (
                    <button
                      key={mention.reference_asset_id}
                      onClick={() => setDraft((state) => ({
                        ...state,
                        imagePrompt: state.imagePrompt
                          .replaceAll("@" + mention.label, "")
                          .replace(/\s{2,}/g, " "),
                        imagePromptMentions: state.imagePromptMentions.filter(
                          (item) => item.reference_asset_id !== mention.reference_asset_id,
                        ),
                      }))}
                      type="button"
                    >
                      @{mention.label}<X size={11} />
                    </button>
                  ))}
                </span>
              )}
            </label>
            <label className="production-field">
              <span>负面约束</span>
              <textarea
                maxLength={4000}
                onChange={(event) => setDraft((state) => ({ ...state, negativeConstraints: event.target.value }))}
                placeholder="每行一条"
                rows={4}
                value={draft.negativeConstraints}
              />
            </label>
            <fieldset className="shot-lock-field">
              <legend>锁定原视频要素</legend>
              <div>
                {SHOT_LOCK_OPTIONS.map((item) => (
                  <label key={item.id}>
                    <input
                      checked={draft.locks.includes(item.id)}
                      onChange={() => toggleLock(item.id)}
                      type="checkbox"
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="shot-reference-field">
              <legend>参考资产绑定</legend>
              {assets.length === 0 ? (
                <p>还没有参考资产，可先在上一步上传。</p>
              ) : (
                <div className="shot-reference-list">
                  {assets.map((asset) => {
                    const binding = draft.referenceBindings.find(
                      (item) => item.reference_asset_id === asset.id,
                    );
                    return (
                      <div className={binding ? "selected" : ""} key={asset.id}>
                        <label>
                          <input
                            checked={Boolean(binding)}
                            onChange={() => toggleBinding(asset)}
                            type="checkbox"
                          />
                          <AssetThumbnail asset={asset} resolveUrl={resolveUrl} />
                          <span>
                            <strong>{asset.name}</strong>
                            <small>{asset.type}</small>
                          </span>
                        </label>
                        {binding && (
                          <select
                            aria-label={asset.name + "参考角色"}
                            onChange={(event) => changeBindingRole(asset.id, event.target.value)}
                            value={binding.role}
                          >
                            {REFERENCE_ROLE_OPTIONS.map((option) => (
                              <option key={option.id} value={option.id}>{option.label}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </fieldset>
            <label className="shot-required-check">
              <input
                checked={draft.required}
                onChange={(event) => setDraft((state) => ({ ...state, required: event.target.checked }))}
                type="checkbox"
              />
              <span>
                <strong>必需分镜</strong>
                <small>未确认时阻止进入分段视频</small>
              </span>
            </label>
          </form>
        </aside>
      </div>
      {keyframePickerOpen && plan && (
        <KeyframePicker
          busy={busy}
          onClose={() => setKeyframePickerOpen(false)}
          onConfirm={onSelectKeyframe}
          plan={plan}
          sourceVideoUrl={sourceVideoUrl}
        />
      )}
      {shotCreateOpen && plan && (
        <ShotCreateDialog
          busy={busy}
          currentPlan={plan}
          onClose={() => setShotCreateOpen(false)}
          onCreate={onCreateShot}
        />
      )}
    </section>
  );
}
