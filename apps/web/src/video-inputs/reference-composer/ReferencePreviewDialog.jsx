import { IconButton } from "../../ui/system/Button.jsx";
import { Dialog } from '../../ui/system/Dialog.jsx';
import { X } from "@phosphor-icons/react";
import { referenceMediaUrls } from "./ReferenceThumbnail.jsx";

export function ReferencePreviewDialog({ item, onClose, resolveUrl, shotPlanId }) {
  if (!item || typeof document === "undefined") return null;
  const urls = referenceMediaUrls(item, resolveUrl, shotPlanId);
  const isVideo = ["reference_video", "depth_control"].includes(item.reference_kind);
  return (
      <Dialog aria-label="生成参考预览" className="generation-reference-preview-dialog" size="wide" onClose={onClose} closeOnBackdrop>
        <header>
          <div><strong>{item.label}</strong><small>{item.description}</small></div>
          <IconButton aria-label="关闭参考预览" onClick={onClose} type="button"><X size={20} /></IconButton>
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
      </Dialog>
  );
}
