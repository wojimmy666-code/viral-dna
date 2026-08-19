import { useId } from "react";
import { AnchoredPopover } from "../video-generation-controls/AnchoredPopover.jsx";

function ratioShape(aspectRatio) {
  const [width, height] = String(aspectRatio || "").split(":").map(Number);
  if (!width || !height) return { width: 18, height: 18 };
  const maximum = 22;
  return width >= height
    ? { width: maximum, height: Math.max(10, maximum * (height / width)) }
    : { width: Math.max(10, maximum * (width / height)), height: maximum };
}

export function ImageGenerationSettingsPopover({
  anchorRef,
  aspectRatio,
  candidateCount,
  controlsDisabled,
  estimatedCostLabel,
  identityLocked,
  inputMode,
  maxCandidates,
  onCandidateCountChange,
  onClose,
  onInputModeChange,
  open,
  popoverId,
  providerReady,
}) {
  const generatedId = useId().replaceAll(":", "");
  const titleId = `image-settings-popover-title-${generatedId}`;
  const shape = ratioShape(aspectRatio);
  const candidates = [1, 2, 3, 4].filter((count) => count <= maxCandidates);

  return (
    <AnchoredPopover
      anchorRef={anchorRef}
      className="image-settings-popover"
      id={popoverId}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      preferredWidth={420}
    >
      <div className="video-popover-heading compact">
        <div>
          <h4 id={titleId}>生成参数</h4>
          <p>修改后用于当前分镜的下一次生成</p>
        </div>
      </div>
      <div className="image-settings-scroll-region">
        <fieldset className="image-setting-section">
          <legend>生成方式</legend>
          <div className="image-setting-segments two">
            <button
              aria-pressed={inputMode === "keyframe_edit"}
              className={inputMode === "keyframe_edit" ? "active" : ""}
              disabled={controlsDisabled}
              onClick={() => onInputModeChange("keyframe_edit")}
              type="button"
            >
              图生图
            </button>
            <button
              aria-pressed={inputMode === "text_to_image"}
              className={inputMode === "text_to_image" ? "active" : ""}
              disabled={controlsDisabled || identityLocked}
              onClick={() => onInputModeChange("text_to_image")}
              title={identityLocked ? "已绑定人物身份资产，必须使用图生图" : ""}
              type="button"
            >
              纯文生图
            </button>
          </div>
        </fieldset>
        <section className="image-setting-section">
          <div className="image-setting-heading"><strong>比例</strong><span>跟随创作方案</span></div>
          <div className="image-aspect-value">
            <span
              aria-hidden="true"
              className="image-aspect-shape"
              style={{ height: `${shape.height}px`, width: `${shape.width}px` }}
            />
            <strong>{aspectRatio || "未设置"}</strong>
            <small>项目画幅</small>
          </div>
        </section>
        <section className="image-setting-section">
          <div className="image-setting-heading"><strong>清晰度</strong><span>由模型自动适配</span></div>
          <div className="image-readonly-value">自适应</div>
        </section>
        <fieldset className="image-setting-section">
          <legend>生成数量</legend>
          <div className="image-setting-segments candidates">
            {candidates.map((count) => (
              <button
                aria-pressed={candidateCount === count}
                className={candidateCount === count ? "active" : ""}
                disabled={controlsDisabled}
                key={count}
                onClick={() => onCandidateCountChange(count)}
                type="button"
              >
                {count} 张
              </button>
            ))}
          </div>
        </fieldset>
      </div>
      <footer className="image-settings-footer">
        <span>生成前自动保存提示词与参考资产</span>
        {estimatedCostLabel && (
          <strong>{estimatedCostLabel} · {providerReady ? "已配置" : "未配置"}</strong>
        )}
      </footer>
    </AnchoredPopover>
  );
}
