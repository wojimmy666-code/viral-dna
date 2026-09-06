let currentPreview = null;

export function claimSkillPreview(owner, stop) {
  if (currentPreview?.owner !== owner) currentPreview?.stop();
  currentPreview = { owner, stop };
}

export function releaseSkillPreview(owner) {
  if (currentPreview?.owner === owner) currentPreview = null;
}

export function resolveSkillMediaUrl(path, apiBase = import.meta.env?.VITE_API_BASE_URL || "/api/v1") {
  if (!path) return "";
  if (path.startsWith("/api/") && /^https?:\/\//i.test(apiBase)) return new URL(path, apiBase).toString();
  return path;
}

export function skillCoverSources(skill) {
  return [...new Set([skill?.presentation?.cover_url, skill?.presentation?.poster_url, skill?.cover_url, skill?.fallback_cover_url].filter(Boolean))];
}

export function presentationPayload(revision, itemId, image, video) {
  const items = image || video ? [{ id: itemId, image_asset_id: image?.id || null, video_asset_id: video?.id || null, sort_order: 0 }] : [];
  return { expected_revision: revision, primary_item_id: items.length ? itemId : null, items };
}
