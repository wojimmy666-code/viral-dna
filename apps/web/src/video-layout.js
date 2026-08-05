const SQUARE_RATIO_TOLERANCE = 0.06;

function toPositiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function parseAspectRatio(aspectRatio) {
  const match = String(aspectRatio || "").match(/^\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*$/);
  if (!match) return null;
  const width = toPositiveNumber(match[1]);
  const height = toPositiveNumber(match[2]);
  return width && height ? { width, height } : null;
}

export function inferVideoOrientation({ width, height, aspectRatio } = {}) {
  const parsedAspectRatio = parseAspectRatio(aspectRatio);
  const resolvedWidth = toPositiveNumber(width) || parsedAspectRatio?.width;
  const resolvedHeight = toPositiveNumber(height) || parsedAspectRatio?.height;

  if (!resolvedWidth || !resolvedHeight) return "landscape";

  const ratio = resolvedWidth / resolvedHeight;
  if (Math.abs(1 - ratio) <= SQUARE_RATIO_TOLERANCE) return "square";
  return ratio < 1 ? "portrait" : "landscape";
}
