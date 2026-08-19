import { useId, useMemo, useRef, useState } from "react";
import {
  CaretUp,
  CircleNotch,
  ImageSquare,
  MagicWand,
  Prohibit,
  WarningCircle,
} from "@phosphor-icons/react";
import { ImageGenerationSettingsPopover } from "./ImageGenerationSettingsPopover.jsx";
import { ImageModelPopover } from "./ImageModelPopover.jsx";
import {
  LOCAL_IMAGE_MODEL_ALIAS,
  imageGenerationSummary,
  imageModelCompatibility,
  imageModelOptions,
} from "./image-generation-ui.js";
import "./image-generation-controls.css";

export function ImageGenerationCommandBar({
  aspectRatio,
  busy,
  candidateCount,
  estimatedCostLabel,
  generationAvailable,
  identityBlocker,
  identityLocked,
  inputCount,
  inputMode,
  latestRun,
  latestRunBusy,
  modelAlias,
  onCancelRun,
  onCandidateCountChange,
  onGenerate,
  onInputModeChange,
  onModelChange,
  planApproved,
  settings,
}) {
  const [openPopover, setOpenPopover] = useState(null);
  const modelAnchorRef = useRef(null);
  const settingsAnchorRef = useRef(null);
  const generatedId = useId().replaceAll(":", "");
  const modelPopoverId = `shot-image-model-popover-${generatedId}`;
  const settingsPopoverId = `shot-image-settings-popover-${generatedId}`;
  const models = useMemo(() => imageModelOptions(settings), [settings]);
  const selectedKey = settings.execution_mode === "local_tool" && modelAlias === LOCAL_IMAGE_MODEL_ALIAS
    ? LOCAL_IMAGE_MODEL_ALIAS
    : modelAlias;
  const selectedModel = models.find((model) => model.alias === selectedKey) || models[0] || null;
  const compatibility = imageModelCompatibility(selectedModel, { inputCount, inputMode });
  const maximumCandidates = Math.min(4, Number(selectedModel?.capabilities?.max_candidates || 4));
  const controlsDisabled = busy || latestRunBusy;
  const summary = imageGenerationSummary({ aspectRatio, candidateCount, inputMode });
  const generateDisabled = (
    controlsDisabled
    || planApproved
    || !generationAvailable
    || !compatibility.compatible
    || Boolean(identityBlocker)
  );

  function selectModel(alias) {
    const model = models.find((item) => item.alias === alias);
    if (!model) return;
    onModelChange(alias, model.executionMode);
    const maximum = Math.min(4, Number(model.capabilities?.max_candidates || 4));
    if (candidateCount > maximum) onCandidateCountChange(maximum);
  }

  function submit() {
    onGenerate();
  }

  return (
    <section className="shot-image-generation-command" aria-label="图片生成设置">
      <div className={`shot-image-command-bar${estimatedCostLabel ? " has-cost" : ""}`}>
        <button
          aria-controls={modelPopoverId}
          aria-expanded={openPopover === "model"}
          className={`shot-image-model-trigger${!compatibility.compatible ? " missing" : ""}`}
          disabled={controlsDisabled}
          onClick={() => setOpenPopover((current) => current === "model" ? null : "model")}
          ref={modelAnchorRef}
          title={[
            selectedModel?.label,
            selectedModel?.providerLabel,
            selectedModel?.description,
          ].filter(Boolean).join(" · ") || "选择图片生成模型"}
          type="button"
        >
          <span className="shot-image-command-icon" aria-hidden="true">
            <ImageSquare size={18} weight="fill" />
          </span>
          <span className="shot-image-model-copy">
            <strong>{selectedModel?.label || "选择生图模型"}</strong>
          </span>
          {!compatibility.compatible && <WarningCircle size={17} weight="fill" />}
          <CaretUp size={16} />
        </button>
        <button
          aria-controls={settingsPopoverId}
          aria-expanded={openPopover === "settings"}
          className="shot-image-settings-trigger"
          disabled={controlsDisabled}
          onClick={() => setOpenPopover((current) => current === "settings" ? null : "settings")}
          ref={settingsAnchorRef}
          title="打开图片生成参数"
          type="button"
        >
          <span>{summary}</span>
          <CaretUp size={16} />
        </button>
        {estimatedCostLabel && (
          <span className="shot-image-command-cost">{estimatedCostLabel}</span>
        )}
        <div className="shot-image-command-actions">
          {latestRunBusy && (
            <button
              className="text-button compact"
              disabled={busy || latestRun.status === "cancellation_requested"}
              onClick={() => onCancelRun(latestRun.id)}
              type="button"
            >
              <Prohibit size={15} />取消任务
            </button>
          )}
          <button
            aria-label={`生成 ${candidateCount} 张图片`}
            className="primary-button compact shot-image-generate-button"
            disabled={generateDisabled}
            onClick={submit}
            title={identityBlocker || compatibility.reason || "生成前会自动保存当前提示词与参考资产"}
            type="button"
          >
            {controlsDisabled
              ? <CircleNotch className="spin" size={17} />
              : <MagicWand size={17} weight="fill" />}
            {latestRunBusy
              ? "正在生成"
              : busy
                ? "正在保存并提交"
                : "生成"}
          </button>
        </div>
      </div>
      <ImageModelPopover
        anchorRef={modelAnchorRef}
        disabled={controlsDisabled}
        inputCount={inputCount}
        inputMode={inputMode}
        models={models}
        onClose={() => setOpenPopover(null)}
        onSelect={selectModel}
        open={openPopover === "model"}
        popoverId={modelPopoverId}
        selectedAlias={selectedKey}
      />
      <ImageGenerationSettingsPopover
        anchorRef={settingsAnchorRef}
        aspectRatio={aspectRatio}
        candidateCount={candidateCount}
        controlsDisabled={controlsDisabled}
        estimatedCostLabel={estimatedCostLabel}
        identityLocked={identityLocked}
        inputMode={inputMode}
        maxCandidates={maximumCandidates}
        onCandidateCountChange={onCandidateCountChange}
        onClose={() => setOpenPopover(null)}
        onInputModeChange={onInputModeChange}
        open={openPopover === "settings"}
        popoverId={settingsPopoverId}
        providerReady={compatibility.compatible}
      />
      {(identityBlocker || (!compatibility.compatible && compatibility.reason !== "尚未配置")) && (
        <div className="production-inline-error shot-image-command-error" role="status">
          <WarningCircle size={17} />
          <span>{identityBlocker || compatibility.reason}</span>
        </div>
      )}
    </section>
  );
}
