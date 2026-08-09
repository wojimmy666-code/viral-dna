const MAX_REMEMBERED_THUMBNAILS = 240;
const loadedThumbnailUrls = new Set();

export function recordThumbnailInitialState(imageUrl) {
  if (!imageUrl) return "missing";
  return loadedThumbnailUrls.has(imageUrl) ? "loaded" : "loading";
}

export function rememberRecordThumbnailLoaded(imageUrl) {
  if (!imageUrl) return;
  loadedThumbnailUrls.delete(imageUrl);
  loadedThumbnailUrls.add(imageUrl);
  while (loadedThumbnailUrls.size > MAX_REMEMBERED_THUMBNAILS) {
    loadedThumbnailUrls.delete(loadedThumbnailUrls.values().next().value);
  }
}

export function forgetRecordThumbnailLoaded(imageUrl) {
  if (imageUrl) loadedThumbnailUrls.delete(imageUrl);
}
