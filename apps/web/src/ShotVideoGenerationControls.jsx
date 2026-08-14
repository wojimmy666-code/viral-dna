import { useCallback, useId, useRef, useState } from "react";
import {
  CaretUp,
  CircleNotch,
  MagicWand,
  Prohibit,
  SpeakerSlash,
  VideoCamera,
  WarningCircle,
} from "@phosphor-icons/react";
import { VideoGenerationSettingsPopover } from "./video-generation-controls/VideoGenerationSettingsPopover.jsx";
import { VideoModelPopover } from "./video-generation-controls/VideoModelPopover.jsx";
import {
  isVideoModelConfigured,
  videoOutputSummary,
  videoProviderLabel,
} from "./video-generation-controls/video-generation-ui.js";
import "./shot-video-generation-controls.css";

export function ShotVideoGenerationControls({
  activeRun,
  allReferencesApproved,
  busy,
  compatibleVideoModels,
  durationAdjustmentMessage,
  durationControlId,
  durationHelpId,
  durationIndex,
  durationNumber,
  durationOptions,
  durationScaleValues,
  estimatedCostKnown,
  estimatedCostLabel,
  generationBlockedReason,
  latestFailure,
  latestRun,
  modelSelectRef,
  onCancelRun,
  onCandidateCountChange,
  onDurationChange,
  onGenerate,
  onModelChange,
  onOpenModelSettings,
  onResolutionChange,
  onRetryRun,
  project,
  providerOptions,
  selectedModel,
  supportedResolutions,
  videoDraft,
}) {
  const [openPopover, setOpenPopover] = useState(null);
  const localModelAnchorRef = useRef(null);
  const settingsAnchorRef = useRef(null);
  const generatedId = useId().replaceAll(":", "");
  const modelPopoverId = `shot-video-model-popover-${generatedId}`;
  const settingsPopoverId = `shot-video-settings-popover-${generatedId}`;
  const controlsDisabled = busy || Boolean(activeRun);
  const candidateCount = Number(videoDraft.candidateCount || 1);
  const aspectRatio = project?.output_aspect_ratio || "未设置画幅";
  const providerReady = isVideoModelConfigured(selectedModel, providerOptions);
  const providerLabel = videoProviderLabel(selectedModel, providerOptions);
  const outputSummary = videoOutputSummary({
    aspectRatio,
    candidateCount,
    duration: durationNumber,
    resolution: videoDraft.resolution,
  });
  const modelOpen = openPopover === "model";
  const settingsOpen = openPopover === "settings";
  const generateDisabled = (
    busy
    || Boolean(activeRun)
    || !allReferencesApproved
    || !videoDraft.videoPrompt.trim()
    || Boolean(generationBlockedReason)
  );

  const setModelAnchor = useCallback((node) => {
    localModelAnchorRef.current = node;
    if (typeof modelSelectRef === "function") modelSelectRef(node);
    else if (modelSelectRef) modelSelectRef.current = node;
  }, [modelSelectRef]);

  function togglePopover(name) {
    setOpenPopover((current) => (current === name ? null : name));
  }

  function openModelSettings() {
    setOpenPopover(null);
    onOpenModelSettings();
  }

  return (
    <section className="shot-video-generation-command" aria-label="视频生成设置">
      <div className="shot-video-command-bar">
        <button
          aria-controls={modelPopoverId}
          aria-expanded={modelOpen}
          className={`shot-video-model-trigger${providerReady ? "" : " missing"}`}
          disabled={controlsDisabled}
          onClick={() => togglePopover("model")}
          ref={setModelAnchor}
          title={selectedModel?.label || "选择视频模型"}
          type="button"
        >
          <span className="shot-video-command-icon" aria-hidden="true">
            <VideoCamera size={18} weight="fill" />
          </span>
          <span className="shot-video-model-trigger-copy">
            <strong>{selectedModel?.label || "选择视频模型"}</strong>
            <small>{providerReady ? providerLabel : `${providerLabel} · Key 未配置`}</small>
          </span>
          {!providerReady && <WarningCircle className="shot-video-model-warning" size={17} weight="fill" />}
          <CaretUp aria-hidden="true" size={16} />
        </button>

        <button
          aria-controls={settingsPopoverId}
          aria-expanded={settingsOpen}
          className="shot-video-output-summary"
          disabled={controlsDisabled}
          onClick={() => togglePopover("settings")}
          ref={settingsAnchorRef}
          title="打开视频生成参数"
          type="button"
        >
          <span>{outputSummary}</span>
          {!selectedModel?.capabilities?.native_audio && (
            <SpeakerSlash aria-label="不生成原生音频" size={16} />
          )}
          <CaretUp aria-hidden="true" size={16} />
        </button>

        <span className="shot-video-command-cost">
          {estimatedCostKnown ? <>预计 <strong>{estimatedCostLabel}</strong></> : "按实际用量"}
        </span>

        <div className="shot-video-command-actions">
          {activeRun && (
            <button
              className="text-button compact"
              disabled={busy}
              onClick={() => onCancelRun(activeRun.id)}
              type="button"
            >
              <Prohibit size={15} />取消任务
            </button>
          )}
          {!activeRun && latestRun?.status === "cancelled" && (
            <button
              className="secondary-button compact"
              disabled={busy}
              onClick={() => onRetryRun(latestRun.id)}
              type="button"
            >
              重试上次任务
            </button>
          )}
          <button
            className="primary-button compact shot-video-generate-button"
            disabled={generateDisabled}
            onClick={onGenerate}
            title={generationBlockedReason || "生成前会自动保存当前提示词"}
            type="button"
          >
            {activeRun || busy
              ? <CircleNotch className="spin" size={17} />
              : <MagicWand size={17} weight="fill" />}
            {activeRun
              ? "正在生成"
              : busy
                ? "正在保存并提交"
                : `生成 ${candidateCount} 个`}
          </button>
        </div>
      </div>

      <VideoModelPopover
        anchorRef={localModelAnchorRef}
        disabled={controlsDisabled}
        failureAlias={latestFailure && latestRun?.model_alias}
        models={compatibleVideoModels}
        onClose={() => setOpenPopover(null)}
        onOpenSettings={openModelSettings}
        onSelect={onModelChange}
        open={modelOpen}
        popoverId={modelPopoverId}
        providers={providerOptions}
        selectedAlias={videoDraft.modelAlias}
      />

      <VideoGenerationSettingsPopover
        anchorRef={settingsAnchorRef}
        aspectRatio={aspectRatio}
        candidateCount={candidateCount}
        controlsDisabled={controlsDisabled}
        durationAdjustmentMessage={durationAdjustmentMessage}
        durationControlId={durationControlId}
        durationHelpId={durationHelpId}
        durationIndex={durationIndex}
        durationNumber={durationNumber}
        durationOptions={durationOptions}
        durationScaleValues={durationScaleValues}
        estimatedCostKnown={estimatedCostKnown}
        estimatedCostLabel={estimatedCostLabel}
        onCandidateCountChange={onCandidateCountChange}
        onClose={() => setOpenPopover(null)}
        onDurationChange={onDurationChange}
        onResolutionChange={onResolutionChange}
        open={settingsOpen}
        popoverId={settingsPopoverId}
        providerReady={providerReady}
        selectedModel={selectedModel}
        selectedResolution={videoDraft.resolution}
        supportedResolutions={supportedResolutions}
      />

      {generationBlockedReason && (
        <div className="production-inline-error shot-video-command-error" role="status">
          <WarningCircle size={17} />
          <span>{generationBlockedReason}</span>
          {!providerReady && (
            <button className="text-button compact" onClick={openModelSettings} type="button">
              打开模型设置
            </button>
          )}
        </div>
      )}
    </section>
  );
}
