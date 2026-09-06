const SHORT_EDGES = { "2K": 1440, "4K": 2160 };

export function resolutionLabelShortEdge(label) {
  const normalized = String(label || "").toUpperCase();
  return SHORT_EDGES[normalized] || Number(normalized.match(/^(\d{3,4})P$/)?.[1] || 0);
}

export function resolutionDisplayLabel(label) {
  const normalized = String(label || "").toUpperCase();
  return /^(2K|4K)$/.test(normalized) ? normalized : normalized.replace(/P$/, "p");
}

export function dimensionsForResolutionLabel(ratio, label) {
  const edge = resolutionLabelShortEdge(label);
  const [w, h] = String(ratio || "").split(":").map(Number);
  if (!edge || !w || !h) return "";
  return w >= h
    ? `${Math.round(edge * w / h / 8) * 8}x${edge}`
    : `${edge}x${Math.round(edge * h / w / 8) * 8}`;
}

export function resolutionForDimensions(width, height) {
  if (height == null) [width, height] = String(width || "").split(/[x×]/i).map(Number);
  const edge = Math.min(Number(width), Number(height));
  return ({ 480: "480p", 720: "720p", 1080: "1080p", 1440: "2K", 2160: "4K" })[edge] || "原有规格";
}

export function imageResolutionOptions(ratio, model) {
  if (!model) return [];
  const cap = model.capabilities || {};
  return ["480p", "720p", "1080p", "2K", "4K"].map((label) => ({
    label, value: dimensionsForResolutionLabel(ratio, label),
  })).filter(({ value }) => {
    const [width, height] = value.split("x").map(Number);
    return width > 0 && height > 0
      && width <= (cap.maximum_width || 2048)
      && height <= (cap.maximum_height || 2048)
      && width * height <= (cap.maximum_pixels || 4_194_304);
  });
}
