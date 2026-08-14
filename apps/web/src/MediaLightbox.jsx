import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  ArrowRight,
  ArrowsOutSimple,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  X,
} from "@phosphor-icons/react";
import "./media-lightbox.css";

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const SCALE_STEP = 0.25;

function clampScale(value) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

export function MediaLightbox({ activeId, items = [], onActiveChange, onClose }) {
  const [scale, setScale] = useState(1);
  const [failed, setFailed] = useState(false);
  const activeIndex = useMemo(
    () => items.findIndex((item) => item.id === activeId),
    [activeId, items],
  );
  const activeItem = activeIndex >= 0 ? items[activeIndex] : null;

  useEffect(() => {
    setScale(1);
    setFailed(false);
  }, [activeId]);

  useEffect(() => {
    if (!activeItem) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose?.();
      if (event.key === "ArrowLeft" && activeIndex > 0) {
        onActiveChange?.(items[activeIndex - 1].id);
      }
      if (event.key === "ArrowRight" && activeIndex < items.length - 1) {
        onActiveChange?.(items[activeIndex + 1].id);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [activeIndex, activeItem, items, onActiveChange, onClose]);

  if (!activeItem || typeof document === "undefined") return null;

  const canGoPrevious = activeIndex > 0;
  const canGoNext = activeIndex < items.length - 1;

  return createPortal(
    <div
      aria-label="图片放大查看"
      aria-modal="true"
      className="media-lightbox-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
      role="dialog"
    >
      <section className="media-lightbox-panel">
        <header>
          <div>
            <strong>{activeItem.title || "图片预览"}</strong>
            {activeItem.meta && <small>{activeItem.meta}</small>}
          </div>
          <button aria-label="关闭图片预览" onClick={onClose} type="button">
            <X size={20} />
          </button>
        </header>

        <div
          className="media-lightbox-canvas"
          onWheel={(event) => {
            event.preventDefault();
            setScale((current) => clampScale(
              current + (event.deltaY < 0 ? SCALE_STEP : -SCALE_STEP),
            ));
          }}
        >
          {failed ? (
            <p>图片暂时无法加载</p>
          ) : (
            <img
              alt={activeItem.alt || activeItem.title || "放大图片"}
              draggable="false"
              onError={() => setFailed(true)}
              src={activeItem.src}
              style={{ "--media-lightbox-scale": scale }}
            />
          )}
          {items.length > 1 && (
            <>
              <button
                aria-label="查看上一张图片"
                className="media-lightbox-nav previous"
                disabled={!canGoPrevious}
                onClick={() => onActiveChange?.(items[activeIndex - 1].id)}
                type="button"
              >
                <ArrowLeft size={22} />
              </button>
              <button
                aria-label="查看下一张图片"
                className="media-lightbox-nav next"
                disabled={!canGoNext}
                onClick={() => onActiveChange?.(items[activeIndex + 1].id)}
                type="button"
              >
                <ArrowRight size={22} />
              </button>
            </>
          )}
        </div>

        <footer>
          <span>{activeIndex + 1} / {items.length}</span>
          <div>
            <button
              aria-label="缩小图片"
              disabled={scale <= MIN_SCALE}
              onClick={() => setScale((current) => clampScale(current - SCALE_STEP))}
              type="button"
            >
              <MagnifyingGlassMinus size={18} />
            </button>
            <output>{Math.round(scale * 100)}%</output>
            <button
              aria-label="放大图片"
              disabled={scale >= MAX_SCALE}
              onClick={() => setScale((current) => clampScale(current + SCALE_STEP))}
              type="button"
            >
              <MagnifyingGlassPlus size={18} />
            </button>
            <button onClick={() => setScale(1)} type="button">
              <ArrowsOutSimple size={18} />适应窗口
            </button>
          </div>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
