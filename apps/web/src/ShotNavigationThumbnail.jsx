import { useEffect, useMemo, useState } from "react";
import { ImageSquare, PlayCircle } from "@phosphor-icons/react";

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
  resolveUrl,
  sources,
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
      <span className="shot-navigation-index-badge" aria-hidden="true">
        {String(index).padStart(2, "0")}
      </span>
      {isVideo && (
        <span className="shot-navigation-video-badge" aria-hidden="true">
          <PlayCircle size={14} weight="fill" />
        </span>
      )}
    </span>
  );
}
