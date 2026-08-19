import { useEffect, useId, useRef } from "react";
import {
  CheckCircle,
  Gear,
  ImageSquare,
  WarningCircle,
} from "@phosphor-icons/react";
import { AnchoredPopover } from "../video-generation-controls/AnchoredPopover.jsx";
import {
  imageModelCapabilitySummary,
  imageModelCompatibility,
} from "./image-generation-ui.js";

export function ImageModelPopover({
  anchorRef,
  disabled,
  inputCount,
  inputMode,
  models,
  onClose,
  onSelect,
  open,
  popoverId,
  selectedAlias,
}) {
  const generatedId = useId().replaceAll(":", "");
  const titleId = `image-model-popover-title-${generatedId}`;
  const contentRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const frame = window.requestAnimationFrame(() => {
      const selected = contentRef.current?.querySelector('[aria-pressed="true"]');
      const first = contentRef.current?.querySelector("[data-image-model]:not(:disabled)");
      (selected || first)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  function select(alias) {
    onSelect(alias);
    onClose();
    window.requestAnimationFrame(() => anchorRef.current?.focus());
  }

  function handleKeyDown(event) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const options = [...contentRef.current.querySelectorAll("[data-image-model]:not(:disabled)")];
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

  return (
    <AnchoredPopover
      anchorRef={anchorRef}
      className="image-model-popover"
      id={popoverId}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      preferredWidth={440}
    >
      <div className="video-popover-heading">
        <div>
          <h4 id={titleId}>图片生成模型</h4>
          <p>仅影响当前分镜的下一次生成</p>
        </div>
        <span className="video-popover-count">{models.length} 个</span>
      </div>
      <div className="image-model-list" onKeyDown={handleKeyDown} ref={contentRef}>
        {models.map((model) => {
          const compatibility = imageModelCompatibility(model, { inputCount, inputMode });
          const selected = selectedAlias === model.alias;
          return (
            <button
              aria-pressed={selected}
              className={`image-model-option${selected ? " selected" : ""}`}
              data-image-model
              disabled={disabled || !compatibility.compatible}
              key={model.alias}
              onClick={() => select(model.alias)}
              title={compatibility.reason || model.description}
              type="button"
            >
              <span className="image-model-option-icon" aria-hidden="true">
                <ImageSquare size={20} weight="fill" />
              </span>
              <span className="image-model-option-copy">
                <span>
                  <strong>{model.label}</strong>
                  {model.recommended && <em>推荐</em>}
                </span>
                <small>{model.providerLabel} · {imageModelCapabilitySummary(model)}</small>
              </span>
              <span className="image-model-option-state" aria-hidden="true">
                {selected && compatibility.compatible
                  ? <CheckCircle size={20} weight="fill" />
                  : compatibility.compatible
                    ? null
                    : model.configured
                      ? <WarningCircle size={19} />
                      : <Gear size={19} />}
              </span>
            </button>
          );
        })}
      </div>
    </AnchoredPopover>
  );
}
