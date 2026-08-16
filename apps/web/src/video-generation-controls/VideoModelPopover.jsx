import { useEffect, useId, useRef } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  CircleNotch,
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
  loadError = "",
  loadStatus = "ready",
  models = [],
  onClose,
  onOpenSettings,
  onRetry,
  onSelect,
  open,
  popoverId,
  providers,
  selectedAlias,
}) {
  const generatedId = useId().replaceAll(":", "");
  const titleId = `video-model-popover-title-${generatedId}`;
  const contentRef = useRef(null);
  const loading = ["idle", "loading"].includes(loadStatus) && models.length === 0;
  const failed = loadStatus === "error" && models.length === 0;
  const usingCachedCatalog = loadStatus === "error" && models.length > 0;
  const configuredModels = models.filter((model) => isVideoModelConfigured(model, providers));
  const unconfiguredModels = models.filter((model) => !isVideoModelConfigured(model, providers));

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      const current = contentRef.current?.querySelector('[aria-pressed="true"]');
      const first = contentRef.current?.querySelector(
        "[data-model-option], [data-model-retry]",
      );
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

  function retryLoad() {
    Promise.resolve(onRetry?.()).catch(() => undefined);
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
        <span className="video-popover-count">
          {loading ? "读取中" : failed ? "读取失败" : `${models.length} 个`}
        </span>
      </div>

      <div className="video-model-list" onKeyDown={handleKeyDown} ref={contentRef}>
        {usingCachedCatalog && (
          <div className="video-model-cache-warning" role="status">
            <WarningCircle size={18} weight="fill" />
            <span>模型目录刷新失败，当前仍使用上次成功读取的结果。</span>
            <button className="text-button compact" onClick={retryLoad} type="button">
              重新加载
            </button>
          </div>
        )}

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

        {loading && (
          <div className="video-model-empty" role="status">
            <CircleNotch className="spin" size={22} />
            <span className="video-model-empty-copy">
              <strong>正在读取视频模型目录</strong>
              <small>服务恢复后会自动显示可用模型。</small>
            </span>
          </div>
        )}

        {failed && (
          <div className="video-model-empty error" role="alert">
            <WarningCircle size={22} weight="fill" />
            <span className="video-model-empty-copy">
              <strong>模型目录读取失败</strong>
              <small>{loadError || "请检查 API 服务后重新加载。"}</small>
            </span>
            <button
              className="secondary-button compact"
              data-model-retry
              onClick={retryLoad}
              type="button"
            >
              <ArrowClockwise size={15} />重新加载
            </button>
          </div>
        )}

        {loadStatus === "ready" && models.length === 0 && (
          <div className="video-model-empty">
            <WarningCircle size={22} />
            <span className="video-model-empty-copy">
              <strong>暂无可用视频模型</strong>
              <small>当前没有已开放且具备参考素材路由的模型。</small>
            </span>
            <button className="secondary-button compact" onClick={openSettings} type="button">
              <Gear size={15} />打开模型设置
            </button>
          </div>
        )}
      </div>
    </AnchoredPopover>
  );
}
