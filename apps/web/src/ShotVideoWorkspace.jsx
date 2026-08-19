import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  DownloadSimple,
  FilmStrip,
  MagicWand,
  PlayCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  formatVideoDuration,
  latestRunByKind,
  normalizeVideoDuration,
  preferredVideoResolution,
  videoDurationOptions,
  videoGenerationRunLabel,
  workflowStatusClass,
  workflowStatusLabel,
} from "./production-ui.js";
import { ShotNavigationThumbnail } from "./ShotNavigationThumbnail.jsx";
import { VideoCandidateLibrary } from "./VideoCandidateLibrary.jsx";
import { ContinuityQualityPanel } from "./ContinuityQualityPanel.jsx";
import { ShotVideoGenerationControls } from "./ShotVideoGenerationControls.jsx";
import { ManagedAssetPicker } from "./managed-assets/ManagedAssetPicker.jsx";
import { DepthControlPanel } from "./video-controls/DepthControlPanel.jsx";
import { useDepthControlJob } from "./video-controls/depth/useDepthControlJob.js";
import { VideoInputComposer } from "./video-inputs/VideoInputComposer.jsx";
import { VideoPromptReferenceEditor } from "./video-inputs/VideoPromptReferenceEditor.jsx";
import {
  requiredSourceForVideoMention,
  videoMentionToken,
} from "./video-inputs/video-prompt-references.js";
import "./managed-assets/managed-assets.css";
import "./video-controls/depth-control.css";

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

function supportsReferenceRoute(model) {
  const capability = model?.capabilities;
  return Boolean(
    model?.available
    && (
      capability?.text_to_video
      || (
        capability?.image_to_video
        && capability?.reference_route?.enabled !== false
      )
    ),
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
  assets = [],
  busy,
  continuityReport,
  error,
  gate,
  initialCandidateId = "",
  onAdvance,
  onApprove,
  onArchiveCandidates,
  onCancelRun,
  onClearError,
  onCreateDepthControl,
  onDecideContinuity,
  onDeleteDepthControl,
  onToggleDepthControl,
  onGenerate,
  onManagedAssetChange,
  onNotice,
  onNotificationsChanged,
  onRunContinuity,
  onOpenModelSettings,
  onReject,
  onRetryRun,
  onRestoreCandidates,
  onRevokeApproval,
  onSelectCandidate,
  onSelectShot,
  project,
  request,
  resolveUrl,
  selectedShotId,
  setVideoDraft,
  shotDetail,
  shots,
  sourceVideoUrl,
  videoDraft,
  videoGenerationSettings,
  videoGenerationSettingsError = "",
  videoGenerationSettingsStatus = "ready",
  onReloadVideoGenerationSettings,
}) {
  const [displayedCandidateId, setDisplayedCandidateId] = useState(null);
  const [durationAdjustmentMessage, setDurationAdjustmentMessage] = useState("");
  const [managedAssetPickerOpen, setManagedAssetPickerOpen] = useState(false);
  const [depthEngineCapabilities, setDepthEngineCapabilities] = useState([]);
  const [depthEngineLoadBusy, setDepthEngineLoadBusy] = useState(false);
  const [depthEngineLoadError, setDepthEngineLoadError] = useState("");
  const [depthEngineInstallation, setDepthEngineInstallation] = useState(null);
  const [depthEngineInstallError, setDepthEngineInstallError] = useState("");
  const depthEnginePollTimer = useRef(null);
  const [referenceStrategy, setReferenceStrategy] = useState(null);
  const [referenceStrategyError, setReferenceStrategyError] = useState("");
  const plan = shotDetail?.plan;
  const depthGeneration = useDepthControlJob({
    expectedRevisionId: project?.current_revision_id,
    onTerminal: async (job) => {
      onNotificationsChanged?.();
      if (job.status === "succeeded") {
        await onCreateDepthControl?.(job);
      }
    },
    request,
    shotPlanId: plan?.id,
  });
  const generationRuns = shotDetail?.generation_runs || [];
  const videoRuns = useMemo(
    () => generationRuns.filter((run) => run.kind === "video"),
    [generationRuns],
  );
  const latestRun = latestRunByKind(videoRuns, "video");
  const latestFailedVideoRun = useMemo(
    () => videoRuns.find((run) => ["failed", "blocked"].includes(run.status)) || null,
    [videoRuns],
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
    () => videoModels.filter(supportsReferenceRoute),
    [videoModels],
  );
  const modelCatalogLoading = (
    ["idle", "loading"].includes(videoGenerationSettingsStatus)
    && compatibleVideoModels.length === 0
  );
  const modelCatalogFailed = (
    videoGenerationSettingsStatus === "error"
    && compatibleVideoModels.length === 0
  );
  const selectedModel = compatibleVideoModels.find(
    (item) => item.alias === videoDraft.modelAlias,
  );
  const managedAssetBinding = (plan?.managed_asset_bindings || []).find(
    (item) => item.role === "actor_identity",
  ) || null;
  const selectedManagedAssetCapability = selectedModel?.capabilities?.managed_assets;
  const personReferenceCapability = selectedModel?.capabilities?.person_references || {};
  const referenceRouteCapability = selectedModel?.capabilities?.reference_route || {};
  const routeUsesManagedIdentity = (
    referenceRouteCapability.identity_transport === "provider_managed_asset"
  );
  const managedIdentityRequired = personReferenceCapability.policy === "managed_required";
  const selectedDepthCount = (plan?.depth_control_assets || []).filter(
    (item) => item.enabled && item.status === "ready" && item.validation_status === "passed",
  ).length;
  const selectedInputSources = useMemo(
    () => new Set(videoDraft.inputSources || []),
    [videoDraft.inputSources],
  );
  const usesApprovedImages = selectedInputSources.has("approved_images");
  const usesProjectAssets = selectedInputSources.has("project_assets");
  const usesManagedAssets = selectedInputSources.has("provider_managed_assets");
  const usesReferenceVideo = selectedInputSources.has("reference_video");
  const usesDepthControl = selectedInputSources.has("depth_control");
  const explicitVideoMentions = videoDraft.videoPromptMentions || [];
  const explicitProjectAssetMentions = explicitVideoMentions.filter(
    (mention) => mention.reference_kind === "project_asset",
  );
  const projectAssetCount = useMemo(() => (
    explicitProjectAssetMentions.length > 0
      ? new Set(explicitProjectAssetMentions.map((mention) => mention.reference_id)).size
      : new Set(
          (plan?.visual_beats || []).flatMap((beat) => (
            beat.image_prompt_mentions || plan?.image_prompt_mentions || []
          )).map((mention) => mention.reference_asset_id),
        ).size
  ), [explicitProjectAssetMentions, plan?.image_prompt_mentions, plan?.visual_beats]);

  useEffect(() => () => {
    if (depthEnginePollTimer.current) {
      window.clearTimeout(depthEnginePollTimer.current);
    }
  }, []);

  async function pollDepthEngineInstallation(installationId) {
    try {
      const installation = await request(
        `/depth-controls/engines/installations/${installationId}`,
      );
      setDepthEngineInstallation(installation);
      if (["queued", "running"].includes(installation.status)) {
        depthEnginePollTimer.current = window.setTimeout(
          () => pollDepthEngineInstallation(installationId),
          750,
        );
        return;
      }
      if (installation.status === "succeeded") {
        if (installation.capability) {
          setDepthEngineCapabilities((current) => [
            installation.capability,
            ...current.filter((item) => item.engine !== installation.capability.engine),
          ]);
        }
        setDepthEngineInstallError("");
        onNotice?.({
          type: "success",
          title: "深度引擎安装完成",
          message: "Video Depth Anything Small 已可用于生成全场景深度视频。",
        });
      } else {
        const message = installation.error || "深度引擎安装失败";
        setDepthEngineInstallError(message);
        onNotice?.({
          type: "error",
          title: "深度引擎安装失败",
          message,
        });
      }
      await onNotificationsChanged?.();
    } catch (installError) {
      const message = installError?.message || "无法读取深度引擎安装进度";
      setDepthEngineInstallError(message);
      onNotice?.({ type: "error", title: "安装进度读取失败", message });
    }
  }

  async function installDepthEngine(engineName = "video_depth_anything") {
    if (depthEnginePollTimer.current) {
      window.clearTimeout(depthEnginePollTimer.current);
    }
    setDepthEngineInstallError("");
    try {
      const installation = await request(
        `/depth-controls/engines/${encodeURIComponent(engineName)}/installations`,
        { method: "POST" },
      );
      setDepthEngineInstallation(installation);
      onNotice?.({
        type: "info",
        title: "开始安装深度引擎",
        message: "安装在独立环境中进行，可以继续浏览当前页面。",
      });
      await pollDepthEngineInstallation(installation.id);
    } catch (installError) {
      const message = installError?.message || "无法启动深度引擎安装";
      setDepthEngineInstallError(message);
      onNotice?.({ type: "error", title: "无法安装深度引擎", message });
    }
  }

  useEffect(() => {
    let cancelled = false;
    if (!plan?.id || !selectedModel?.alias || !usesDepthControl) {
      setDepthEngineCapabilities([]);
      setDepthEngineLoadError("");
      return () => {
        cancelled = true;
      };
    }
    setDepthEngineLoadBusy(true);
    setDepthEngineLoadError("");
    request("/depth-controls/engines")
      .then((items) => {
        if (!cancelled) setDepthEngineCapabilities(Array.isArray(items) ? items : []);
      })
      .catch((loadError) => {
        if (!cancelled) {
          setDepthEngineCapabilities([]);
          setDepthEngineLoadError(
            loadError?.message || "无法读取真实深度引擎状态",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setDepthEngineLoadBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [plan?.id, request, selectedModel?.alias, usesDepthControl]);

  useEffect(() => {
    let cancelled = false;
    if (!plan?.id || !selectedModel?.alias || selectedInputSources.size === 0) {
      setReferenceStrategy(null);
      setReferenceStrategyError("");
      return () => {
        cancelled = true;
      };
    }
    setReferenceStrategyError("");
    request(
      `/video-references/shots/${plan.id}/strategy?model_alias=${encodeURIComponent(selectedModel.alias)}`,
    )
      .then((payload) => {
        if (!cancelled) setReferenceStrategy(payload);
      })
      .catch((strategyError) => {
        if (!cancelled) {
          setReferenceStrategy(null);
          setReferenceStrategyError(
            strategyError?.message || "无法解析当前模型的人物与动作参考路由",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    plan?.id,
    request,
    selectedModel?.alias,
    selectedDepthCount,
    usesApprovedImages,
    usesDepthControl,
    usesManagedAssets,
    usesProjectAssets,
    usesReferenceVideo,
    managedAssetBinding?.id,
    shotDetail?.current_revision_id,
  ]);
  const managedAssetCompatible = !routeUsesManagedIdentity || !managedAssetBinding || Boolean(
    selectedManagedAssetCapability?.supported
    && selectedManagedAssetCapability.provider === managedAssetBinding.provider
    && (selectedManagedAssetCapability.asset_kinds || []).includes(managedAssetBinding.kind)
    && (selectedManagedAssetCapability.roles || []).includes(managedAssetBinding.role),
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
  const mentionBlockedReason = (() => {
    for (const mention of explicitVideoMentions) {
      const token = videoMentionToken(mention);
      if (token && !String(videoDraft.videoPrompt || "").includes(token)) {
        return `${token} 已从提示词中删除，请移除或重新插入该引用`;
      }
      const requiredSource = requiredSourceForVideoMention(mention);
      if (requiredSource && !selectedInputSources.has(requiredSource)) {
        return `${token || "该素材"} 尚未加入本次生成输入`;
      }
      if (
        ["approved_image", "project_asset"].includes(mention.reference_kind)
        && selectedModel
        && !selectedModel.capabilities?.image_to_video
      ) {
        return `当前模型不支持 ${token || "图片素材"} 图片输入`;
      }
      if (
        mention.reference_kind === "reference_video"
        && selectedModel
        && !selectedModel.capabilities?.reference_video
      ) {
        return `当前模型不支持 ${token || "参考视频"} 视频输入`;
      }
      if (
        mention.reference_kind === "depth_control"
        && selectedModel
        && !(
          selectedModel.capabilities?.depth_control_video
          || selectedModel.capabilities?.reference_route?.supports_depth_control_video
        )
      ) {
        return `当前模型不支持 ${token || "深度视频"} 深度控制输入`;
      }
    }
    return null;
  })();
  const generationBlockedReason = modelCatalogLoading
    ? "正在读取视频模型目录，请稍候"
    : modelCatalogFailed
      ? "视频模型目录读取失败，请重新加载"
    : !videoGenerationSettings?.enabled
    ? "视频生成尚未启用"
    : compatibleVideoModels.length === 0
      ? "没有已开放的视频生成模型"
    : !selectedModel
      ? "请选择视频生成模型"
      : mentionBlockedReason
        ? mentionBlockedReason
      : selectedInputSources.size === 0 && !selectedModel.capabilities?.text_to_video
        ? "当前模型不支持纯文生视频，请增加图片输入或切换模型"
      : usesApprovedImages && !selectedModel.capabilities?.image_to_video
        ? "当前模型不支持分镜图片输入"
      : usesProjectAssets && !selectedModel.capabilities?.image_to_video
        ? "当前模型不支持项目图片资产输入"
      : usesProjectAssets && projectAssetCount === 0
        ? "当前提示词尚未关联项目图片资产"
      : usesManagedAssets && !managedAssetCompatible
        ? "当前模型不支持已绑定的 Provider 托管人物资产，请切换到 Seedance 2.0 系列"
      : usesManagedAssets && !managedAssetBinding
        ? "请先选择 Provider 托管人物资产"
      : usesReferenceVideo && !selectedModel.capabilities?.reference_video
        ? "当前模型不支持普通动作/参考视频"
      : usesDepthControl && !(
        selectedModel.capabilities?.depth_control_video
        || selectedModel.capabilities?.reference_route?.supports_depth_control_video
      )
        ? "当前模型不支持深度视频控制"
      : usesDepthControl && selectedDepthCount === 0
        ? "请先生成并启用一个深度控制视频"
      : selectedInputSources.size > 0 && managedIdentityRequired && !managedAssetBinding
        ? "当前模型不接收原始真人身份素材，请先绑定 Provider 托管演员"
      : usesApprovedImages && referenceFrames.length === 0
        ? "当前分镜还没有可用于视频生成的画面"
        : usesApprovedImages && !allReferencesApproved
          ? `请先确认全部必需画面（${approvedReferenceCount}/${referenceFrames.length}）`
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
    onClearError?.();
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

  return (
    <section className="shot-video-workspace">
      <header className="shot-video-stage-header">
        <div>
          <h3>分段视频工作台</h3>
          <p>按需组合提示词、图片、资产、参考视频或深度控制，逐分镜生成和审核视频候选。</p>
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

      <ContinuityQualityPanel
        busy={busy}
        onDecide={onDecideContinuity}
        onRun={onRunContinuity}
        report={continuityReport}
      />

      <div className="shot-video-foundation-note">
        <MagicWand size={18} weight="fill" />
        <span><strong>可组合生成输入</strong>：提示词始终提交；媒体输入只有在下方主动选择后才会发送，音频留到视频剪辑阶段处理。</span>
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
            {usesApprovedImages && <article className="shot-video-preview-card shot-video-reference-card">
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
            </article>}

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
            onNotice={onNotice}
            plan={plan}
            request={request}
            resolveUrl={resolveUrl}
          />

          <div className="shot-video-prompt-panel">
            <VideoInputComposer
              managedAssetBinding={managedAssetBinding}
              model={selectedModel}
              onChange={(inputSources) => setVideoDraft((current) => ({
                ...current,
                inputSources,
              }))}
              onOpenManagedAssets={() => setManagedAssetPickerOpen(true)}
              projectAssetCount={projectAssetCount}
              referenceFrameCount={approvedReferenceCount}
              selectedSources={videoDraft.inputSources || []}
            />
            {usesDepthControl && (
              <DepthControlPanel
                busy={busy || depthEngineLoadBusy}
                engineCapabilities={depthEngineCapabilities}
                engineError={depthEngineLoadError}
                generationError={depthGeneration.error}
                generationJob={depthGeneration.job}
                installation={depthEngineInstallation}
                installationError={depthEngineInstallError}
                managedAssetBinding={managedAssetBinding}
                model={selectedModel}
                onCancelGeneration={depthGeneration.cancel}
                onCreate={depthGeneration.start}
                onDelete={onDeleteDepthControl}
                onInstall={installDepthEngine}
                onOpenManagedAssets={() => setManagedAssetPickerOpen(true)}
                onRetryGeneration={depthGeneration.retry}
                onToggle={onToggleDepthControl}
                onNotice={onNotice}
                plan={plan}
                referenceFrames={referenceFrames}
                request={request}
                resolveUrl={resolveUrl}
                sourceVideoUrl={sourceVideoUrl}
                strategy={referenceStrategy}
                strategyError={referenceStrategyError}
              />
            )}
            <VideoPromptReferenceEditor
              assets={assets}
              depthAssets={plan?.depth_control_assets || []}
              managedAssetBinding={managedAssetBinding}
              onChange={({
                videoPrompt,
                videoPromptMentions,
                requiredInputSource,
              }) => setVideoDraft((current) => ({
                ...current,
                videoPrompt,
                videoPromptMentions,
                inputSources: requiredInputSource
                  ? Array.from(new Set([
                      ...(current.inputSources || []),
                      requiredInputSource,
                    ]))
                  : current.inputSources,
              }))}
              referenceFrames={referenceFrames}
              resolveUrl={resolveUrl}
              value={videoDraft.videoPrompt}
              videoPromptMentions={videoDraft.videoPromptMentions || []}
              videoReferenceBindings={plan?.video_reference_bindings || []}
            />
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
            <ShotVideoGenerationControls
              activeRun={activeRun}
              allReferencesApproved={!generationBlockedReason}
              busy={busy}
              compatibleVideoModels={compatibleVideoModels}
              durationAdjustmentMessage={durationAdjustmentMessage}
              durationControlId={durationControlId}
              durationHelpId={durationHelpId}
              durationIndex={durationIndex}
              durationNumber={durationNumber}
              durationOptions={durationOptions}
              durationScaleValues={durationScaleValues}
              estimatedCostKnown={estimatedCostMicros != null}
              estimatedCostLabel={estimatedCostLabel}
              generationBlockedReason={generationBlockedReason}
              failureAlias={latestFailedVideoRun?.model_alias || ""}
              latestRun={latestRun}
              modelCatalogError={videoGenerationSettingsError}
              modelCatalogStatus={videoGenerationSettingsStatus}
              onCancelRun={onCancelRun}
              onCandidateCountChange={(candidateCount) => setVideoDraft((current) => ({
                ...current,
                candidateCount,
              }))}
              onDurationChange={selectDuration}
              onGenerate={onGenerate}
              onModelChange={selectVideoModel}
              onOpenModelSettings={onOpenModelSettings}
              onReloadModels={onReloadVideoGenerationSettings}
              onResolutionChange={(resolution) => setVideoDraft((current) => ({
                ...current,
                resolution,
              }))}
              onRetryRun={onRetryRun}
              project={project}
              providerOptions={videoGenerationSettings?.providers || []}
              selectedModel={selectedModel}
              supportedResolutions={supportedResolutions}
              videoDraft={videoDraft}
            />
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
      {managedAssetPickerOpen && (
        <ManagedAssetPicker
          currentBinding={managedAssetBinding}
          onClose={() => setManagedAssetPickerOpen(false)}
          onOpenModelSettings={onOpenModelSettings}
          onSelect={async (binding) => {
            const saved = await onManagedAssetChange?.(binding);
            if (saved !== false) {
              setVideoDraft((current) => ({
                ...current,
                inputSources: Array.from(new Set([
                  ...(current.inputSources || []),
                  "provider_managed_assets",
                ])),
              }));
              setManagedAssetPickerOpen(false);
            }
          }}
          request={request}
        />
      )}
    </section>
  );
}
