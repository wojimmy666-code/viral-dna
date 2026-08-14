const UNFILED_ASSET_LABEL = "未分类";

export function assetDirectoryLabel(asset = {}) {
  return String(asset.folder_name || "").trim() || UNFILED_ASSET_LABEL;
}

export function assetMentionLabel(asset = {}) {
  const name = String(asset.name || "参考资产").trim() || "参考资产";
  return `${assetDirectoryLabel(asset)}/${name}`;
}

export function assetMentionToken(asset = {}) {
  return `@${assetMentionLabel(asset)}`;
}

export function mentionToken(mention = {}, asset = null) {
  if (asset) return assetMentionToken(asset);
  const label = String(mention.label || "").trim().replace(/^@+/, "");
  return label ? `@${label}` : "";
}

export function assetMentionSearchText(asset = {}) {
  return [
    assetDirectoryLabel(asset),
    asset.name,
    asset.type,
    assetMentionLabel(asset),
  ].filter(Boolean).join(" ").toLocaleLowerCase("zh-CN");
}

export function removeMentionFromPrompt(prompt, mention, asset = null) {
  const canonicalToken = mentionToken(mention, asset);
  const storedToken = mentionToken(mention);
  return [canonicalToken, storedToken]
    .filter(Boolean)
    .reduce((value, token) => value.replaceAll(token, ""), String(prompt || ""))
    .replace(/\s{2,}/g, " ")
    .trimStart();
}

export function normalizePromptMentionDraft(prompt, mentions = [], assets = []) {
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  let nextPrompt = String(prompt || "");
  let changed = false;
  const nextMentions = mentions.map((mention) => {
    const asset = assetsById.get(mention.reference_asset_id);
    if (!asset) return mention;
    const canonicalLabel = assetMentionLabel(asset);
    if (mention.label === canonicalLabel) return mention;
    const storedToken = mentionToken(mention);
    const canonicalToken = assetMentionToken(asset);
    if (storedToken && nextPrompt.includes(storedToken) && !nextPrompt.includes(canonicalToken)) {
      nextPrompt = nextPrompt.replace(storedToken, canonicalToken);
    }
    changed = true;
    return { ...mention, label: canonicalLabel };
  });
  return { changed, imagePrompt: nextPrompt, imagePromptMentions: nextMentions };
}

export function isUserDeletedCandidate(candidate = {}) {
  return candidate.status === "archived" && (
    candidate.archive_reason === "user_deleted"
    || candidate.quality_report?.archive_reason === "user_deleted"
  );
}

export function isVisibleImageCandidate(candidate = {}) {
  return candidate.status !== "rejected" && !isUserDeletedCandidate(candidate);
}
