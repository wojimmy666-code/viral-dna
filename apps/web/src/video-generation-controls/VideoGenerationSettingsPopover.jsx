import { useId } from "react";
import { SpeakerSlash } from "@phosphor-icons/react";
import {
  formatVideoDuration,
  videoDurationConstraintLabel,
} from "../production-ui.js";
import { AnchoredPopover } from "./AnchoredPopover.jsx";
import { videoCandidateCountOptions } from "./video-generation-ui.js";

function ratioShape(aspectRatio) {
  const [width, height] = String(aspectRatio || "").split(":").map(Number);
  if (!width || !height) return { width: 18, height: 18 };
  const maximum = 22;
  return width >= height
    ? { width: maximum, height: Math.max(10, maximum * (height / width)) }
    : { width: Math.max(10, maximum * (width / height)), height: maximum };
}

export function VideoGenerationSettingsPopover({
  anchorRef,
  aspectRatio,
  candidateCount,
  controlsDisabled,
  durationAdjustmentMessage,
  durationControlId,
  durationHelpId,
  durationIndex,
  durationNumber,
  durationOptions,
  durationScaleValues,
  estimatedCostKnown,
  estimatedCostLabel,
  onCandidateCountChange,
  onClose,
  onDurationChange,
  onResolutionChange,
  open,
  popoverId,
  providerReady,
  selectedModel,
  selectedResolution,
  supportedResolutions,
}) {
  const generatedId = useId().replaceAll(":", "");
  const titleId = `video-settings-popover-title-${generatedId}`;
  const shape = ratioShape(aspectRatio);
  const candidateOptions = videoCandidateCountOptions(selectedModel);

  return (
    <AnchoredPopover
      anchorRef={anchorRef}
      className="video-settings-popover"
      id={popoverId}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      preferredWidth={420}
    >
      <div className="video-popover-heading compact">
        <div>
          <h4 id={titleId}>生成参数</h4>
          <p>修改后即时写入当前分镜草稿</p>
        </div>
      </div>

      <div className="video-settings-scroll-region">
        <section className="video-setting-section">
          <div className="video-setting-section-heading">
            <strong>比例</strong>
            <span>跟随创作方案</span>
          </div>
          <div className="video-aspect-value">
            <span
              aria-hidden="true"
              className="video-aspect-shape"
              style={{ height: `${shape.height}px`, width: `${shape.width}px` }}
            />
            <strong>{aspectRatio}</strong>
            <small>项目画幅</small>
          </div>
        </section>

        <fieldset className="video-setting-section">
          <legend>清晰度</legend>
          <div className="video-setting-segments resolution">
            {supportedResolutions.map((resolution) => (
              <button
                aria-pressed={resolution === selectedResolution}
                className={resolution === selectedResolution ? "active" : ""}
                disabled={controlsDisabled}
                key={resolution}
                onClick={() => onResolutionChange(resolution)}
                type="button"
              >
                {resolution}
              </button>
            ))}
          </div>
        </fieldset>

        <section className="video-setting-section video-duration-section">
          <div className="video-setting-section-heading">
            <label htmlFor={durationControlId}>视频时长</label>
            <output htmlFor={durationControlId}>{formatVideoDuration(durationNumber)} 秒</output>
          </div>
          <input
            aria-describedby={durationHelpId}
            aria-label="生成时长"
            aria-valuetext={`${formatVideoDuration(durationNumber)} 秒`}
            disabled={controlsDisabled || !selectedModel || durationOptions.length <= 1}
            id={durationControlId}
            max={Math.max(0, durationOptions.length - 1)}
            min={0}
            onChange={(event) => onDurationChange(event.target.value)}
            step={1}
            type="range"
            value={durationIndex}
          />
          <div className="video-duration-extents" aria-hidden="true">
            {durationScaleValues.map((duration) => (
              <small key={duration}>{formatVideoDuration(duration)} 秒</small>
            ))}
          </div>
          <small className="video-duration-help" id={durationHelpId}>
            {selectedModel
              ? `${selectedModel.label}：${videoDurationConstraintLabel(selectedModel)}`
              : "选择模型后显示可用时长"}
          </small>
          {durationAdjustmentMessage && (
            <small className="video-duration-adjustment" role="status">
              {durationAdjustmentMessage}
            </small>
          )}
        </section>

        <fieldset className="video-setting-section">
          <legend>生成数量</legend>
          <div className="video-setting-segments candidates">
            {candidateOptions.map((count) => (
              <button
                aria-pressed={candidateCount === count}
                className={candidateCount === count ? "active" : ""}
                disabled={controlsDisabled}
                key={count}
                onClick={() => onCandidateCountChange(count)}
                type="button"
              >
                {count} 个
              </button>
            ))}
          </div>
        </fieldset>

        {!selectedModel?.capabilities?.native_audio && (
          <div className="video-audio-capability">
            <SpeakerSlash size={17} />
            <span>当前模型不生成原生音频，成片音频在视频剪辑阶段处理。</span>
          </div>
        )}
      </div>

      <footer className="video-settings-footer">
        <span>生成前自动保存提示词与负面约束</span>
        <strong>
          {estimatedCostKnown ? `预计 ${estimatedCostLabel}` : "按实际用量结算"}
          {" · "}
          {providerReady ? "Key 已配置" : "Key 未配置"}
        </strong>
      </footer>
    </AnchoredPopover>
  );
}
