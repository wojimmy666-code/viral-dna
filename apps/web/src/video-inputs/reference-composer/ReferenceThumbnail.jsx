import {
  FilmStrip,
  ImageSquare,
  Stack,
  UserCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

function fallbackIcon(kind) {
  if (kind === "provider_managed_asset") return <UserCircle size={24} />;
  if (kind === "depth_control") return <Stack size={24} />;
  if (kind === "reference_video") return <FilmStrip size={24} />;
  return <ImageSquare size={24} />;
}
export function referenceMediaUrls(item, resolveUrl, shotPlanId) {
  let preview = item?.preview_url || "";
  let content = item?.content_url || "";
  if (item?.reference_kind === "depth_control" && shotPlanId && item.reference_id) {
    const base = `/api/v1/depth-controls/shots/${shotPlanId}/${item.reference_id}/content`;
    preview ||= `${base}?thumbnail=true`;
    content ||= base;
  }
  return {
    preview: preview ? resolveUrl?.(preview) || preview : "",
    content: content ? resolveUrl?.(content) || content : "",
  };
}

export function ReferenceThumbnail({
  item,
  previewOnHover = false,
  resolveUrl,
  shotPlanId,
}) {
  const videoRef = useRef(null);
  const [failed, setFailed] = useState(false);
  const urls = useMemo(
    () => referenceMediaUrls(item, resolveUrl, shotPlanId),
    [item, resolveUrl, shotPlanId],
  );
  const isVideo = ["reference_video", "depth_control"].includes(item?.reference_kind);

  useEffect(() => setFailed(false), [urls.preview, urls.content]);

  if (isVideo && previewOnHover && urls.content && !failed) {
    return (
      <video
        aria-hidden="true"
        loop
        muted
        onError={() => setFailed(true)}
        onMouseEnter={() => videoRef.current?.play().catch(() => undefined)}
        onMouseLeave={() => {
          if (!videoRef.current) return;
          videoRef.current.pause();
          videoRef.current.currentTime = 0;
        }}
        playsInline
        poster={urls.preview}
        preload="metadata"
        ref={videoRef}
        src={urls.content}
      />
    );
  }

  if (urls.preview && !failed) {
    return <img alt="" loading="lazy" onError={() => setFailed(true)} src={urls.preview} />;
  }
  return fallbackIcon(item?.reference_kind);
}
