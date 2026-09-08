import { useEffect, useMemo, useState } from "react";
import { Check, ImageSquare, PlayCircle } from "@phosphor-icons/react";

function uniqueSources(sources) {
  const urls = new Set();
  return (sources || []).filter((source) => {
    const url = source?.url?.trim?.();
    if (!url || urls.has(url)) return false;
    urls.add(url);
    return true;
  });
}

export function ShotNavigationThumbnail({
  className = "",
  index,
  showIndex = true,
  resolveUrl,
  sources,
  showImageStatus = false,
}) {
  const availableSources = useMemo(() => uniqueSources(sources), [sources]);
  const sourceSignature = availableSources
    .map((source) => `${source.kind || "image"}:${source.url}`)
    .join("|");
  const [sourceIndex, setSourceIndex] = useState(0);

  useEffect(() => {
    setSourceIndex(0);
  }, [sourceSignature]);

  const source = availableSources[sourceIndex] || null;
  const resolvedSource = source ? resolveUrl(source.url) : "";
  const isVideo = source?.kind?.includes("video") || false;
  const classes = [
    "shot-navigation-thumbnail",
    isVideo ? "video" : "",
    className,
  ].filter(Boolean).join(" ");

  return (
    <span className={classes} data-preview-kind={source?.kind || "fallback"}>
      {resolvedSource ? (
        <img
          alt=""
          decoding="async"
          loading="lazy"
          onError={() => setSourceIndex((current) => current + 1)}
          src={resolvedSource}
        />
      ) : (
        <span className="shot-navigation-thumbnail-fallback" aria-hidden="true">
          <ImageSquare size={19} />
        </span>
      )}
      {showIndex && <span className="shot-navigation-index-badge" aria-hidden="true">
        {String(index).padStart(2, "0")}
      </span>}
      {showImageStatus && resolvedSource && source.kind === "approved_image" && (
        <span className="shot-navigation-image-badge approved"
          role="img" aria-label="已采用图片" title="已采用图片">
          <Check size={11} weight="bold" />
        </span>
      )}
      {isVideo && (
        <span className="shot-navigation-video-badge" aria-hidden="true">
          <PlayCircle size={14} weight="fill" />
        </span>
      )}
    </span>
  );
}
