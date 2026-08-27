import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  CheckCircle,
  CircleNotch,
  Copy,
  DotsSixVertical,
  FloppyDisk,
  ImageSquare,
  MagicWand,
  MagnifyingGlassPlus,
  Plus,
  Trash,
  VideoCamera,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  REFERENCE_ROLE_OPTIONS,
  duplicateVisualBeatSourceIds,
  estimateImageGenerationCostMicros,
  generationFailureGuidance,
  imageGenerationModeLabel,
  imageGenerationInputManifest,
  imageIdentityPolicy,
  imageGenerationRunLabel,
  imageQualityLabel,
  isAiImageGenerationRun,
  isImageEngineConfigured,
  isRecoverableImageGenerationRun,
  productionPreviewLayout,
  resolveImageExecutionMode,
  workflowStatusClass,
  workflowStatusLabel,
} from "./production-ui.js";
import { MediaLightbox } from "./MediaLightbox.jsx";
import { AddToAssetsButton } from "./generated-assets/AddToAssetsButton.jsx";
import { ImageGenerationCommandBar } from "./image-generation-controls/ImageGenerationCommandBar.jsx";
import { ShotNavigationThumbnail } from "./ShotNavigationThumbnail.jsx";
import { TextModelIndicator } from "./ui/text-model/TextModelIndicator.jsx";
import {
  assetDirectoryLabel,
  assetMentionLabel,
  assetMentionSearchText,
  assetMentionToken,
  isUserDeletedCandidate,
  isVisibleImageCandidate,
  mentionToken,
  normalizePromptMentionDraft,
  reconcilePromptReferenceRemoval,
  removeMentionFromPrompt,
} from "./shot-image-ui.js";

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

function formatCandidateBatchTime(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
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
            <textarea className="prompt-editor-textarea" onChange={(event) => setImagePrompt(event.target.value)} rows={3} value={imagePrompt} />
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
  selectedVisualBeatId,
  draft,
  setDraft,
  assets,
  gate,
  generationCandidateCount,
  generationEngine,
  generationInputMode,
  generationModelAlias,
  generationSettings,
  project,
  advanced,
  busy,
  error,
  resolveUrl,
  setGenerationCandidateCount,
  setGenerationEngine,
  setGenerationInputMode,
  setGenerationModelAlias,
  sourceVideoUrl,
  onSelectShot,
  onSave,
  onGenerate,
  onCancelRun,
  onRecoverRun,
  onSelectKeyframe,
  onApproveSource,
  onCreateShot,
  onCreateVisualBeat,
  onDeleteVisualBeat,
  onDiscardShot,
  onArchiveCandidate,
  onSelectCandidate,
  onApprove,
  onRevokeApproval,
  onReorderShots,
  onReorderVisualBeats,
  onRestoreShot,
  onSelectVisualBeat,
  onUpdateVisualBeat,
  onAdvance,
  onNotice,
  request,
  textModelLabel = "Qwen3.7 Plus",
}) {
  const [keyframePickerOpen, setKeyframePickerOpen] = useState(false);
  const [shotCreateOpen, setShotCreateOpen] = useState(false);
  const [showDiscarded, setShowDiscarded] = useState(false);
  const [draggedShotId, setDraggedShotId] = useState(null);
  const [displayedCandidateId, setDisplayedCandidateId] = useState(null);
  const [visualChoice, setVisualChoice] = useState("source");
  const [candidateHistoryExpanded, setCandidateHistoryExpanded] = useState(false);
  const [lightboxCandidateId, setLightboxCandidateId] = useState(null);
  const [mentionMenu, setMentionMenu] = useState(null);
  const promptRef = useRef(null);
  const shotPlan = shotDetail?.plan;
  const visualBeats = useMemo(
    () => [...(shotPlan?.visual_beats || [])].sort((left, right) => left.index - right.index),
    [shotPlan?.visual_beats],
  );
  const duplicateSourceBeatIds = useMemo(
    () => new Set(duplicateVisualBeatSourceIds(visualBeats)),
    [visualBeats],
  );
  const activeVisualBeat = (
    visualBeats.find((item) => item.id === selectedVisualBeatId)
    || visualBeats[0]
    || null
  );
  const plan = shotPlan && activeVisualBeat
    ? {
      ...shotPlan,
      source_keyframe_url: activeVisualBeat.source_frame_url,
      source_keyframe_relative_path: activeVisualBeat.source_frame_relative_path,
      source_keyframe_timestamp_seconds: activeVisualBeat.source_timestamp_seconds,
      source_keyframe_origin: activeVisualBeat.source_origin,
      image_prompt: activeVisualBeat.image_prompt,
      image_prompt_mentions: activeVisualBeat.image_prompt_mentions,
      image_negative_constraints: activeVisualBeat.image_negative_constraints,
      image_status: activeVisualBeat.image_status,
      approved_image_candidate_id: activeVisualBeat.approved_image_candidate_id,
      required: activeVisualBeat.required,
      source_kind: activeVisualBeat.source_frame_url ? shotPlan.source_kind : "blank",
    }
    : shotPlan;
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
  const assetsById = useMemo(
    () => new Map(assets.map((asset) => [asset.id, asset])),
    [assets],
  );
  const identityPolicy = useMemo(
    () => imageIdentityPolicy(draft.referenceBindings, assets),
    [assets, draft.referenceBindings],
  );
  const generationInputManifest = useMemo(
    () => imageGenerationInputManifest({
      inputMode: identityPolicy.enabled ? "keyframe_edit" : generationInputMode,
      sourceUrl: plan?.source_keyframe_url || "",
      referenceBindings: draft.referenceBindings,
      assets,
    }),
    [
      assets,
      draft.referenceBindings,
      generationInputMode,
      identityPolicy.enabled,
      plan?.source_keyframe_url,
    ],
  );
  const visualBeatPreviews = useMemo(() => {
    const previews = new Map();
    for (const beat of visualBeats) {
      const beatRuns = generationRuns.filter((run) => (
        run.kind === "image"
        && (
          run.visual_beat_id === beat.id
          || (!run.visual_beat_id && beat.id === visualBeats[0]?.id)
        )
      ));
      const candidatesForBeat = beatRuns.flatMap((run) => run.candidates || []);
      const approved = candidatesForBeat.find(
        (candidate) => candidate.id === beat.approved_image_candidate_id,
      );
      const recent = approved || candidatesForBeat.find(
        (candidate) => !["rejected", "archived"].includes(candidate.status),
      );
      previews.set(
        beat.id,
        recent?.thumbnail_url || recent?.content_url || beat.source_frame_url || "",
      );
    }
    return previews;
  }, [generationRuns, visualBeats]);
  const imageRuns = useMemo(
    () => generationRuns.filter((run) => (
      run.kind === "image"
      && (
        run.visual_beat_id === activeVisualBeat?.id
        || (!run.visual_beat_id && activeVisualBeat?.id === visualBeats[0]?.id)
      )
    )),
    [activeVisualBeat?.id, generationRuns, visualBeats],
  );
  const aiImageRuns = useMemo(
    () => imageRuns.filter((run) => isAiImageGenerationRun(run)),
    [imageRuns],
  );
  const latestRun = aiImageRuns[0] || null;
  const candidateGroups = useMemo(
    () => aiImageRuns
      .map((run) => ({
        run,
        candidates: (run.candidates || [])
          .filter(isVisibleImageCandidate)
          .sort((left, right) => left.ordinal - right.ordinal)
          .map((candidate) => ({ ...candidate, generationRun: run })),
      }))
      .filter((group) => group.candidates.length > 0),
    [aiImageRuns],
  );
  const candidates = useMemo(
    () => candidateGroups.flatMap((group) => group.candidates),
    [candidateGroups],
  );
  const lightboxItems = useMemo(
    () => candidates.map((candidate) => ({
      id: candidate.id,
      src: resolveUrl(candidate.content_url || candidate.thumbnail_url),
      title: `分镜 ${plan?.index || ""} · AI 生成图`,
      meta: `${candidate.generationRun?.model_display_name || candidate.generationRun?.model || "未记录模型"} · ${formatCandidateBatchTime(candidate.generationRun?.completed_at || candidate.generationRun?.created_at)}`,
      alt: `分镜 ${plan?.index || ""} 的 AI 图片候选`,
    })),
    [candidates, plan?.index, resolveUrl],
  );
  const allImageCandidateEntries = useMemo(
    () => imageRuns.flatMap((run) => (run.candidates || []).map((candidate) => ({
      candidate,
      run,
    }))),
    [imageRuns],
  );
  const approvedCandidateEntry = allImageCandidateEntries.find(
    (entry) => entry.candidate.id === plan?.approved_image_candidate_id,
  ) || null;
  const approvedIsSource = Boolean(
    plan?.image_status === "approved"
    && approvedCandidateEntry?.run?.execution_mode === "source_frame",
  );
  const latestCandidateGroup = candidateGroups[0] || null;
  const historicalCandidateGroups = candidateGroups.slice(1);
  const historicalCandidateCount = historicalCandidateGroups.reduce(
    (total, group) => total + group.candidates.length,
    0,
  );
  const candidateIdentity = candidates
    .map((candidate) => `${candidate.id}:${candidate.status}`)
    .join("|");
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
    remote_model_alias: generationModelAlias || generationSettings?.remote_model_alias,
  };
  const estimatedCostMicros = estimateImageGenerationCostMicros(
    effectiveGenerationSettings,
    candidateCount,
  );
  const modeLabel = imageGenerationModeLabel(effectiveGenerationSettings);
  const selectedModel = (generationSettings?.models || []).find(
    (item) => item.alias === effectiveGenerationSettings.remote_model_alias,
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
  const commandCostLabel = (
    generationSettings?.enabled
    && executionMode === "remote_api"
    && estimatedCostMicros != null
  )
    ? `预计 ${formatCostMicros(estimatedCostMicros)}`
    : "";
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
  const latestRunRecoverable = isRecoverableImageGenerationRun(latestRun);
  const latestRunTone = latestRunRecoverable
    ? "recoverable"
    : ["completed", "cached"].includes(latestRun?.status)
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
  const displayedCandidateIsApproved = Boolean(
    displayedCandidate
    && displayedCandidate.id === plan?.approved_image_candidate_id,
  );
  const displayedCandidateRun = displayedCandidate?.generationRun || null;
  const displayedCandidateModelLabel = (
    displayedCandidateRun?.model_display_name
    || displayedCandidateRun?.model
    || "未记录模型"
  );
  const displayedCandidateBatchTime = formatCandidateBatchTime(
    displayedCandidateRun?.completed_at || displayedCandidateRun?.created_at,
  );
  const displayedCandidateQualityLabel = displayedCandidate
    ? imageQualityLabel(displayedCandidate.quality_report)
    : "尚无候选";
  const displayedCandidateStateLabel = displayedCandidateIsApproved
    ? "已采用"
    : visualChoice === "candidate"
      ? "待采用"
      : "仅预览";
  const candidateReadyForApproval = displayedCandidate && (
    plan?.image_status === "approved"
      ? !displayedCandidateIsApproved
      : displayedCandidate.status === "selected"
  ) ? displayedCandidate : null;
  const selectedChoiceIsCurrentApproval = Boolean(
    plan?.image_status === "approved"
    && (
      visualChoice === "source"
        ? approvedIsSource
        : displayedCandidateIsApproved
    )
  );
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
  const identityGenerationBlocker = !identityPolicy.valid
    ? identityPolicy.blocker
    : identityPolicy.enabled && !plan?.source_keyframe_url
      ? "人物身份替换需要先选择原视频关键帧"
      : "";
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
      approvedIsSource
        ? "source"
        : preferred && (
          preferred.status === "selected"
          || preferred.id === plan?.approved_image_candidate_id
        )
          ? "candidate"
          : "source",
    );
    setMentionMenu(null);
  }, [
    plan?.id,
    plan?.approved_image_candidate_id,
    approvedIsSource,
    candidateIdentity,
  ]);

  useEffect(() => {
    setCandidateHistoryExpanded(false);
    setLightboxCandidateId(null);
  }, [activeVisualBeat?.id, plan?.id]);

  useEffect(() => {
    setDraft((state) => {
      const normalized = normalizePromptMentionDraft(
        state.imagePrompt,
        state.imagePromptMentions,
        assets,
        state.referenceBindings,
      );
      return normalized.changed
        ? {
            ...state,
            imagePrompt: normalized.imagePrompt,
            imagePromptMentions: normalized.imagePromptMentions,
          }
        : state;
    });
  }, [
    activeVisualBeat?.id,
    assets,
    draft.imagePrompt,
    draft.imagePromptMentions,
    draft.referenceBindings,
    plan?.id,
    setDraft,
  ]);

  useEffect(() => {
    if (identityPolicy.enabled) {
      setGenerationInputMode("keyframe_edit");
    } else if (plan?.source_kind === "blank") {
      setGenerationInputMode("text_to_image");
    }
  }, [
    identityPolicy.enabled,
    plan?.id,
    plan?.source_kind,
    setGenerationInputMode,
  ]);

  function toggleBinding(asset) {
    setDraft((state) => {
      const exists = state.referenceBindings.some(
        (item) => item.reference_asset_id === asset.id,
      );
      const mention = state.imagePromptMentions.find(
        (item) => item.reference_asset_id === asset.id,
      );
      const currentIdentity = state.referenceBindings.find(
        (item) => item.role === "identity" && item.reference_asset_id !== asset.id,
      );
      const defaultRole = DEFAULT_ROLE_BY_TYPE[asset.type] || "layout";
      const nextRole = defaultRole === "identity" && currentIdentity
        ? "layout"
        : defaultRole;
      const nextState = {
        ...state,
        referenceBindings: exists
          ? state.referenceBindings.filter(
            (item) => item.reference_asset_id !== asset.id,
          )
          : [
            ...state.referenceBindings,
            {
              reference_asset_id: asset.id,
              role: nextRole,
              weight: 1,
            },
          ],
        imagePromptMentions: exists
          ? state.imagePromptMentions.filter(
            (item) => item.reference_asset_id !== asset.id,
          )
          : mention
            ? state.imagePromptMentions
            : [
              ...state.imagePromptMentions,
              { reference_asset_id: asset.id, label: assetMentionLabel(asset) },
            ],
        imagePrompt: exists
          ? removeMentionFromPrompt(state.imagePrompt, mention || {}, asset)
          : state.imagePrompt,
      };
      if (exists) return nextState;
      const normalized = normalizePromptMentionDraft(
        nextState.imagePrompt,
        nextState.imagePromptMentions,
        assets,
        nextState.referenceBindings,
      );
      return {
        ...nextState,
        imagePrompt: normalized.imagePrompt,
        imagePromptMentions: normalized.imagePromptMentions,
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

  function chooseSource() {
    if (!plan?.source_keyframe_url) return;
    setVisualChoice("source");
  }

  function manifestRoleLabel(item) {
    if (item.kind === "source_keyframe") return "构图、姿态、动作和机位";
    if (item.identity_source) return "唯一人物身份来源";
    return {
      product: "产品外观与结构",
      wardrobe: "服装款式与材质",
      scene: "场景环境",
      style: "视觉风格",
      layout: "道具与布局",
    }[item.role] || "参考资产";
  }

  function moveVisualBeat(visualBeatId, offset) {
    const currentIndex = visualBeats.findIndex((item) => item.id === visualBeatId);
    const targetIndex = currentIndex + offset;
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= visualBeats.length) return;
    const next = visualBeats.map((item) => item.id);
    const [moved] = next.splice(currentIndex, 1);
    next.splice(targetIndex, 0, moved);
    onReorderVisualBeats(next);
  }

  function chooseCandidate(candidate) {
    if (!candidate) return;
    setDisplayedCandidateId(candidate.id);
    setVisualChoice("candidate");
    if (
      plan?.image_status !== "approved"
      && ["ready", "archived"].includes(candidate.status)
      && !isUserDeletedCandidate(candidate)
    ) {
      onSelectCandidate(candidate.id);
    }
  }

  function activateChoiceFromKeyboard(event, action) {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    action();
  }

  function renderCandidateGroup(group, title, historical = false) {
    if (!group) return null;
    const modelLabel = group.run.model_display_name || group.run.model || "未记录模型";
    const batchTime = formatCandidateBatchTime(
      group.run.completed_at || group.run.created_at,
    );
    return (
      <div
        aria-label={`${title}，${group.candidates.length} 张，${modelLabel}，${batchTime}`}
        className={`shot-candidate-strip-group${historical ? " historical" : ""}`}
        key={group.run.id}
        role="group"
      >
        <div className="shot-candidate-batch-label">
          <strong>{title}</strong>
          <small>{batchTime}</small>
        </div>
        <div className="shot-candidate-strip-items">
          {group.candidates.map((candidate, index) => {
            const isApproved = (
              plan?.image_status === "approved"
              && candidate.id === plan?.approved_image_candidate_id
            );
            const isPreviewing = candidate.id === displayedCandidate?.id;
            const isChosen = isPreviewing && visualChoice === "candidate";
            const qualityLabel = imageQualityLabel(candidate.quality_report);
            const stateLabel = isApproved
              ? "已采用"
              : isChosen
                ? "待采用"
                : historical || candidate.status === "archived"
                  ? "历史"
                  : "候选";
            return (
              <div className="shot-candidate-tile-shell" key={candidate.id}>
                <button
                  aria-label={`${title}，第 ${index + 1} 张，共 ${group.candidates.length} 张，${stateLabel}`}
                  aria-pressed={isChosen}
                  className={[
                    "shot-candidate-tile",
                    isPreviewing ? "previewing" : "",
                    isChosen ? "active" : "",
                    isApproved ? "approved" : "",
                  ].filter(Boolean).join(" ")}
                  disabled={busy}
                  onClick={() => chooseCandidate(candidate)}
                  title={`${modelLabel} · ${batchTime} · ${qualityLabel}`}
                  type="button"
                >
                  <span className="shot-candidate-thumb">
                    <MediaPreview
                      alt={`${title}第 ${index + 1} 张图片候选`}
                      emptyLabel="候选图不可用"
                      src={resolveUrl(candidate.thumbnail_url || candidate.content_url)}
                    />
                  </span>
                </button>
                <span className="shot-candidate-tile-actions">
                  <button
                    aria-label="放大查看图片候选"
                    disabled={busy}
                    onClick={() => setLightboxCandidateId(candidate.id)}
                    title="放大查看"
                    type="button"
                  >
                    <MagnifyingGlassPlus size={14} />
                  </button>
                  {!isApproved && (
                    <button
                      aria-label="删除图片候选"
                      className="danger"
                      disabled={busy}
                      onClick={() => onArchiveCandidate?.(candidate.id)}
                      title="删除候选（可撤销）"
                      type="button"
                    >
                      <Trash size={14} />
                    </button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  function updatePrompt(event) {
    const value = event.target.value;
    const cursor = event.target.selectionStart ?? value.length;
    const prefix = value.slice(0, cursor);
    const match = prefix.match(/@([^@\n,，。；;]*)$/);
    setDraft((state) => {
      const references = reconcilePromptReferenceRemoval(
        value,
        state.imagePromptMentions,
        state.referenceBindings,
        assets,
      );
      return {
        ...state,
        imagePrompt: value,
        imagePromptMentions: references.imagePromptMentions,
        referenceBindings: references.referenceBindings,
      };
    });
    setMentionMenu(match ? { start: cursor - match[1].length - 1, end: cursor, query: match[1] } : null);
  }

  function insertMention(asset) {
    if (!mentionMenu) return;
    setDraft((state) => {
      const token = assetMentionToken(asset);
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
      const hasOtherIdentity = state.referenceBindings.some(
        (item) => item.role === "identity" && item.reference_asset_id !== asset.id,
      );
      const defaultRole = DEFAULT_ROLE_BY_TYPE[asset.type] || "layout";
      const nextState = {
        ...state,
        imagePrompt: nextPrompt,
        imagePromptMentions: hasMention
          ? state.imagePromptMentions
          : [
              ...state.imagePromptMentions,
              { reference_asset_id: asset.id, label: assetMentionLabel(asset) },
            ],
        referenceBindings: hasBinding
          ? state.referenceBindings
          : [
            ...state.referenceBindings,
            {
              reference_asset_id: asset.id,
              role: defaultRole === "identity" && hasOtherIdentity
                ? "layout"
                : defaultRole,
              weight: 1,
            },
          ],
      };
      const normalized = normalizePromptMentionDraft(
        nextState.imagePrompt,
        nextState.imagePromptMentions,
        assets,
        nextState.referenceBindings,
      );
      return {
        ...nextState,
        imagePrompt: normalized.imagePrompt,
        imagePromptMentions: normalized.imagePromptMentions,
      };
    });
    setMentionMenu(null);
    requestAnimationFrame(() => promptRef.current?.focus());
  }

  const mentionAssets = mentionMenu
    ? assets.filter((asset) => (
      !mentionMenu.query
      || assetMentionSearchText(asset).includes(
        mentionMenu.query.trim().toLocaleLowerCase("zh-CN"),
      )
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
            : latestRunTone === "recoverable"
              ? <ArrowCounterClockwise size={18} weight="bold" />
            : latestRunTone === "failed"
              ? <WarningCircle size={18} weight="fill" />
              : latestRunTone === "completed"
                ? <CheckCircle size={18} weight="fill" />
                : <MagicWand size={18} weight="fill" />}
        </span>
        <div>
          <strong>
            {latestRun
              ? `${latestRunRecoverable ? "图片待恢复" : generationRunStatusLabel(latestRun.status)} · ${latestRun.model}`
              : `${modeLabel} · ${configuredEngine}`}
          </strong>
          <small>
           {latestRun
              ? `${imageGenerationRunLabel(latestRun)} · ${latestRun.input_mode === "text_to_image" ? "纯文生图" : "图生图"} · ${latestRunCostLabel}${latestRun.latency_ms == null ? "" : " · " + latestRun.latency_ms + " ms"}`
             : `默认生成 ${candidateCount} 张 · ${configuredCostLabel}`}
          </small>
          {ignoredSimulation && (
            <em>历史模拟占位候选已忽略，不会作为 AI 图片或通过工作流确认。</em>
          )}
          {latestRunRecoverable && (
            <em>已找到 {latestRun.recovery_candidate_count} 张本次任务生成的图片，恢复不会再次消耗额度。</em>
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
                  <strong>
                    {seconds(plan.start_seconds)}s — {seconds(plan.end_seconds)}s
                    {activeVisualBeat ? ` · 画面 ${activeVisualBeat.index}` : ""}
                  </strong>
                </div>
                <span className={"workflow-pill " + workflowStatusClass(plan.image_status)}>
                  {workflowStatusLabel(plan.image_status)}
                </span>
              </div>
              {activeVisualBeat && (
                <section className="visual-beat-editor" aria-label="分镜内画面顺序">
                  <header>
                    <div>
                      <strong>画面轨道</strong>
                      <small>{visualBeats.length} 张有序参考图 · 图号按此顺序传给视频模型</small>
                    </div>
                    <button
                      className="secondary-button compact"
                      disabled={busy || visualBeats.length >= 20}
                      onClick={onCreateVisualBeat}
                      type="button"
                    >
                      <Plus size={14} />新增画面
                    </button>
                  </header>
                  <div className="visual-beat-rail">
                    {visualBeats.map((beat, beatIndex) => {
                      const previewUrl = visualBeatPreviews.get(beat.id);
                      const active = beat.id === activeVisualBeat.id;
                      const duplicateSource = duplicateSourceBeatIds.has(beat.id);
                      return (
                        <article
                          className={`${active ? "active" : ""} ${duplicateSource ? "duplicate-source" : ""}`}
                          key={beat.id}
                        >
                          <button
                            className="visual-beat-select"
                            onClick={() => onSelectVisualBeat(beat.id)}
                            type="button"
                          >
                            <span className="visual-beat-index">图{beat.index}</span>
                            <span className="visual-beat-thumb">
                              {previewUrl
                                ? <img alt="" src={resolveUrl(previewUrl)} />
                                : <ImageSquare size={22} />}
                            </span>
                            <span className="visual-beat-copy">
                              <strong>{beat.title}</strong>
                              <small>
                                {Math.round(beat.start_ratio * 100)}%–{Math.round(beat.end_ratio * 100)}%
                                {Number.isFinite(Number(beat.source_timestamp_seconds))
                                  ? ` · 源 ${Number(beat.source_timestamp_seconds).toFixed(2)}s`
                                  : ""}
                              </small>
                            </span>
                            {duplicateSource ? (
                              <span
                                className="visual-beat-source-warning"
                                title="该画面与其他画面使用了相同源帧，请自动修复或从视频重选"
                              >
                                <WarningCircle size={13} weight="fill" />源帧重复
                              </span>
                            ) : (
                              <span className={"shot-status-badge " + workflowStatusClass(beat.image_status)}>
                                {workflowStatusLabel(beat.image_status)}
                              </span>
                            )}
                          </button>
                          <div className="visual-beat-actions">
                            <button
                              aria-label="前移画面"
                              disabled={busy || beatIndex === 0}
                              onClick={() => moveVisualBeat(beat.id, -1)}
                              type="button"
                            ><ArrowLeft size={13} /></button>
                            <button
                              aria-label="后移画面"
                              disabled={busy || beatIndex === visualBeats.length - 1}
                              onClick={() => moveVisualBeat(beat.id, 1)}
                              type="button"
                            ><ArrowRight size={13} /></button>
                            <button
                              aria-label="删除画面"
                              disabled={busy || visualBeats.length <= 1}
                              onClick={() => onDeleteVisualBeat(beat.id)}
                              type="button"
                            ><Trash size={13} /></button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}
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
                  onClick={chooseSource}
                  onKeyDown={(event) => activateChoiceFromKeyboard(event, chooseSource)}
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
                    <span>
                      {approvedIsSource
                        ? "已采用"
                        : visualChoice === "source"
                          ? "已选择"
                          : "选择此图"}
                    </span>
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
                  onKeyDown={(event) => activateChoiceFromKeyboard(
                    event,
                    () => chooseCandidate(displayedCandidate),
                  )}
                  role="button"
                  tabIndex={0}
                >
                  <figcaption>
                    <div>
                      <strong>AI 生成图</strong>
                      <small>
                        {displayedCandidate
                          ? `${displayedCandidate.generationRun === latestCandidateGroup?.run ? "最近批次" : "历史批次"} · 候选 ${displayedCandidate.ordinal}`
                          : "尚未生成"}
                      </small>
                    </div>
                    <span>
                      {displayedCandidateIsApproved
                        ? "已采用"
                        : visualChoice === "candidate"
                          ? "已选择"
                          : "选择此图"}
                    </span>
                  </figcaption>
                  <div className="shot-media-frame">
                    <MediaPreview
                      alt={"分镜 " + plan.index + " 当前候选"}
                      emptyLabel="点击下方按钮生成候选"
                      src={displayedCandidate ? resolveUrl(displayedCandidate.content_url) : ""}
                    />
                    {displayedCandidate && (
                      <button
                        aria-label="放大查看当前 AI 生成图"
                        className="shot-media-zoom-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setLightboxCandidateId(displayedCandidate.id);
                        }}
                        title="放大查看"
                        type="button"
                      >
                        <MagnifyingGlassPlus size={17} />
                      </button>
                    )}
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

              {latestCandidateGroup && (
                <section className="shot-candidate-library" aria-label="AI 图片候选历史">
                  <header className="shot-candidate-library-heading">
                    <div>
                      <strong>AI 图片候选</strong>
                      <small>共 {candidates.length} 张，点击缩略图切换当前采用目标</small>
                    </div>
                    {historicalCandidateCount > 0 && (
                      <button
                        aria-expanded={candidateHistoryExpanded}
                        className={candidateHistoryExpanded ? "expanded" : ""}
                        onClick={() => setCandidateHistoryExpanded((value) => !value)}
                        type="button"
                      >
                        历史 {historicalCandidateCount} 张
                        <ArrowDown size={14} />
                      </button>
                    )}
                  </header>
                  <div
                    aria-label="图片候选，可横向滚动"
                    className="shot-candidate-strip"
                    role="region"
                    tabIndex={0}
                  >
                    {renderCandidateGroup(latestCandidateGroup, "最新")}
                    {candidateHistoryExpanded && historicalCandidateGroups.map(
                      (group, index) => renderCandidateGroup(
                        group,
                        `历史 ${index + 1}`,
                        true,
                      ),
                    )}
                  </div>
                  {displayedCandidate && (
                    <div className="shot-candidate-current-detail">
                      <strong>当前预览</strong>
                      <span>
                        {displayedCandidateModelLabel} · {displayedCandidateBatchTime} · {displayedCandidateQualityLabel}
                      </span>
                      <em className={
                        displayedCandidateIsApproved
                          ? "approved"
                          : visualChoice === "candidate"
                            ? "selected"
                            : ""
                      }>
                        {displayedCandidateStateLabel}
                      </em>
                      <AddToAssetsButton
                        artifactKind="image_candidate"
                        assetType="other"
                        disabled={busy}
                        name={`分镜 ${plan.index} 生成图片`}
                        onNotice={onNotice}
                        request={request}
                        shotPlanId={plan.id}
                        sourceEntityId={displayedCandidate.id}
                      />
                    </div>
                  )}
                </section>
              )}

              {latestRunTone === "failed" && !displayedCandidate && (
                <div className="shot-candidate-empty failed">
                  <strong>本次生成失败{latestRun?.error_code ? ` · ${latestRun.error_code}` : ""}</strong>
                  <p>{latestRun?.error_message || "本机工具没有返回可用候选。"}</p>
                  <small>{generationFailureGuidance(latestRun)}</small>
                </div>
              )}

              {latestRunRecoverable && !displayedCandidate && (
                <div className="shot-candidate-empty recoverable">
                  <strong>图片待恢复 · {latestRun.recovery_candidate_count} 张</strong>
                  <p>ImageGen 已完成生成，但图片尚未导入当前分镜。</p>
                  <small>{generationFailureGuidance(latestRun)}</small>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => onRecoverRun?.(latestRun.id)}
                    type="button"
                  >
                    <ArrowCounterClockwise size={16} />
                    恢复图片
                  </button>
                </div>
              )}

              {generationInputManifest.length > 0 && (
                <section className={`shot-input-manifest compact${identityPolicy.enabled ? " identity-locked" : ""}`}>
                  <header>
                    <div>
                      <strong>本次参考 {generationInputManifest.length} 项</strong>
                      <small>生成时按编号顺序提交</small>
                    </div>
                    {identityPolicy.enabled && <span>人物身份已锁定</span>}
                  </header>
                  <ol>
                    {generationInputManifest.map((item) => (
                      <li className={item.identity_source ? "identity" : ""} key={`${item.input_index}-${item.asset_id || "source"}`}>
                        <span className="shot-input-manifest-thumb">
                          <MediaPreview
                            alt={`${item.label}输入缩略图`}
                            emptyLabel="无预览"
                            src={resolveUrl(item.thumbnail_url)}
                          />
                        </span>
                        <span>
                          <b>{item.input_index}</b>
                          <strong>{item.label}</strong>
                          <small>{manifestRoleLabel(item)}</small>
                        </span>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              <ImageGenerationCommandBar
                aspectRatio={project?.output_aspect_ratio}
                busy={busy}
                candidateCount={candidateCount}
                estimatedCostLabel={commandCostLabel}
                generationAvailable={generationAvailable}
                identityBlocker={identityGenerationBlocker}
                identityLocked={identityPolicy.enabled}
                inputCount={generationInputManifest.length}
                inputMode={generationInputMode}
                latestRun={latestRun}
                latestRunBusy={latestRunBusy}
                modelAlias={
                  executionMode === "local_tool"
                    ? "local_tool"
                    : effectiveGenerationSettings.remote_model_alias
                }
                onCancelRun={onCancelRun}
                onCandidateCountChange={setGenerationCandidateCount}
                onGenerate={onGenerate}
                onInputModeChange={setGenerationInputMode}
                onModelChange={(alias, nextExecutionMode) => {
                  setGenerationEngine(nextExecutionMode);
                  setGenerationModelAlias(alias);
                }}
                planApproved={plan.image_status === "approved"}
                settings={effectiveGenerationSettings}
              />

              <div className="shot-review-actions">
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
                  className="primary-button compact"
                  disabled={
                    busy
                    || latestRunBusy
                    || selectedChoiceIsCurrentApproval
                    || (visualChoice === "source" && !plan.source_keyframe_url)
                    || (visualChoice === "candidate" && !candidateReadyForApproval)
                  }
                  onClick={() => (
                    visualChoice === "source"
                      ? onApproveSource()
                      : onApprove(candidateReadyForApproval.id)
                  )}
                  type="button"
                >
                  <CheckCircle size={16} weight="fill" />
                  {selectedChoiceIsCurrentApproval
                    ? "当前画面已采用"
                    : plan.image_status === "approved"
                      ? visualChoice === "source"
                        ? "改用当前关键帧"
                        : "改用此候选"
                      : "采用所选画面"}
                </button>
              </div>
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
              <span className="shot-prompt-field-title">
                <span>图片提示词</span>
                <TextModelIndicator label={textModelLabel} />
              </span>
              <div className="shot-prompt-editor">
                <textarea
                  className="prompt-editor-textarea"
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
                        <span>
                          <strong>{assetMentionToken(asset)}</strong>
                          <small>{assetDirectoryLabel(asset)} · {asset.type}</small>
                        </span>
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
                        imagePrompt: removeMentionFromPrompt(
                          state.imagePrompt,
                          mention,
                          assetsById.get(mention.reference_asset_id),
                        ),
                        imagePromptMentions: state.imagePromptMentions.filter(
                          (item) => item.reference_asset_id !== mention.reference_asset_id,
                        ),
                        referenceBindings: state.referenceBindings.filter(
                          (item) => item.reference_asset_id !== mention.reference_asset_id,
                        ),
                      }))}
                      type="button"
                    >
                      {mentionToken(
                        mention,
                        assetsById.get(mention.reference_asset_id),
                      )}<X size={11} />
                    </button>
                  ))}
                </span>
              )}
            </label>
            <details
              className="production-field shot-image-negative-constraints"
              key={activeVisualBeat?.id || plan?.id}
            >
              <summary>负面约束（可选）</summary>
              <textarea
                aria-label="图片负面约束"
                className="prompt-editor-textarea"
                maxLength={4000}
                onChange={(event) => setDraft((state) => ({ ...state, negativeConstraints: event.target.value }))}
                placeholder="每行一条"
                rows={4}
                value={draft.negativeConstraints}
              />
            </details>
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
                              <option
                                disabled={
                                  option.id === "identity"
                                  && identityPolicy.primaryBinding
                                  && identityPolicy.primaryBinding.reference_asset_id !== asset.id
                                }
                                key={option.id}
                                value={option.id}
                              >
                                {option.label}
                              </option>
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
      <MediaLightbox
        activeId={lightboxCandidateId}
        items={lightboxItems}
        onActiveChange={setLightboxCandidateId}
        onClose={() => setLightboxCandidateId(null)}
      />
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
