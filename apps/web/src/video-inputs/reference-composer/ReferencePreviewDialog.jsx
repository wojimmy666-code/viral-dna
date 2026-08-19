import { createPortal } from "react-dom";
import { useEffect } from "react";
import { X } from "@phosphor-icons/react";
import { referenceMediaUrls } from "./ReferenceThumbnail.jsx";

export function ReferencePreviewDialog({ item, onClose, resolveUrl, shotPlanId }) {
  useEffect(() => {
    if (!item || typeof document === "undefined") return undefined;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [item, onClose]);

  if (!item || typeof document === "undefined") return null;
  const urls = referenceMediaUrls(item, resolveUrl, shotPlanId);
  const isVideo = ["reference_video", "depth_control"].includes(item.reference_kind);
  return createPortal(
    <div
      aria-label="生成参考预览"
      aria-modal="true"
      className="generation-reference-preview-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
      role="dialog"
    >
      <section className="generation-reference-preview-dialog">
        <header>
          <div><strong>{item.label}</strong><small>{item.description}</small></div>
          <button aria-label="关闭参考预览" onClick={onClose} type="button"><X size={20} /></button>
        </header>
        <div className="generation-reference-preview-media">
          {isVideo && urls.content ? (
            <video autoPlay controls playsInline poster={urls.preview} src={urls.content} />
          ) : urls.preview ? (
            <img alt={item.label || "参考预览"} src={urls.preview} />
          ) : (
            <p>该参考暂无可预览媒体，但仍会按对象 ID 提交给模型。</p>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
