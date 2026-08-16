import { useEffect, useId, useRef } from "react";
import {
  CheckCircle,
  Gear,
  VideoCamera,
  WarningCircle,
} from "@phosphor-icons/react";
import { AnchoredPopover } from "./AnchoredPopover.jsx";
import {
  isVideoModelConfigured,
  videoModelCapabilitySummary,
} from "./video-generation-ui.js";

function ModelOption({
  attention,
  configured,
  disabled,
  model,
  onOpenSettings,
  onSelect,
  providers,
  selected,
}) {
  function activate() {
    if (configured) onSelect(model.alias);
    else onOpenSettings();
  }

  return (
    <button
      aria-pressed={selected}
      className={`video-model-option${selected ? " selected" : ""}${attention ? " attention" : ""}`}
      data-model-option
      disabled={disabled}
      onClick={activate}
      type="button"
    >
      <span className="video-model-option-icon" aria-hidden="true">
        <VideoCamera size={21} weight="fill" />
      </span>
      <span className="video-model-option-copy">
        <span className="video-model-option-title">
          <strong>{model.label}</strong>
          {model.recommended && <small className="video-model-badge recommended">推荐</small>}
          {!configured && <small className="video-model-badge missing">Key 未配置</small>}
          {attention && <small className="video-model-badge warning">需处理</small>}
        </span>
        <small>{videoModelCapabilitySummary(model, providers)}</small>
      </span>
      <span className="video-model-option-state" aria-hidden="true">
        {selected && configured
          ? <CheckCircle size={20} weight="fill" />
          : configured
            ? null
            : <Gear size={19} />}
      </span>
    </button>
  );
}

export function VideoModelPopover({
  anchorRef,
  disabled,
  failureAlias,
  models,
  onClose,
  onOpenSettings,
  onSelect,
  open,
  popoverId,
  providers,
  selectedAlias,
}) {
  const generatedId = useId().replaceAll(":", "");
  const titleId = `video-model-popover-title-${generatedId}`;
  const contentRef = useRef(null);
  const configuredModels = models.filter((model) => isVideoModelConfigured(model, providers));
  const unconfiguredModels = models.filter((model) => !isVideoModelConfigured(model, providers));

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      const current = contentRef.current?.querySelector('[aria-pressed="true"]');
      const first = contentRef.current?.querySelector("[data-model-option]");
      (current || first)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  function handleKeyDown(event) {
    if (!(["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key))) return;
    const options = [...contentRef.current.querySelectorAll("[data-model-option]:not(:disabled)")];
    if (options.length === 0) return;
    event.preventDefault();
    const currentIndex = options.indexOf(document.activeElement);
    let nextIndex = currentIndex;
    if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = options.length - 1;
    else if (event.key === "ArrowDown") nextIndex = (currentIndex + 1 + options.length) % options.length;
    else nextIndex = (currentIndex - 1 + options.length) % options.length;
    options[nextIndex]?.focus();
  }

  function selectModel(alias) {
    onSelect(alias);
    onClose();
    window.requestAnimationFrame(() => anchorRef.current?.focus());
  }

  function openSettings() {
    onClose();
    onOpenSettings();
  }

  return (
    <AnchoredPopover
      anchorRef={anchorRef}
      className="video-model-popover"
      id={popoverId}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      preferredWidth={460}
    >
      <div className="video-popover-heading">
        <div>
          <h4 id={titleId}>视频生成模型</h4>
          <p>按模型能力自动选择人物身份、动作和画面参考路由</p>
        </div>
        <span className="video-popover-count">{models.length} 个</span>
      </div>

      <div className="video-model-list" onKeyDown={handleKeyDown} ref={contentRef}>
        {configuredModels.length > 0 && (
          <section className="video-model-group" aria-label="可用模型">
            <h5>可用模型</h5>
            {configuredModels.map((model) => (
              <ModelOption
                attention={failureAlias === model.alias}
                configured
                disabled={disabled}
                key={model.alias}
                model={model}
                onOpenSettings={openSettings}
                onSelect={selectModel}
                providers={providers}
                selected={selectedAlias === model.alias}
              />
            ))}
          </section>
        )}

        {unconfiguredModels.length > 0 && (
          <section className="video-model-group" aria-label="尚未配置的模型">
            <h5>尚未配置</h5>
            {unconfiguredModels.map((model) => (
              <ModelOption
                attention={failureAlias === model.alias}
                configured={false}
                disabled={disabled}
                key={model.alias}
                model={model}
                onOpenSettings={openSettings}
                onSelect={selectModel}
                providers={providers}
                selected={selectedAlias === model.alias}
              />
            ))}
          </section>
        )}

        {models.length === 0 && (
          <div className="video-model-empty">
            <WarningCircle size={22} />
            <span>暂无具备可用参考素材路由的视频模型。</span>
          </div>
        )}
      </div>
    </AnchoredPopover>
  );
}
