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
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trimStart();
}

export function ensurePromptMentionTokens(prompt, mentions = [], assets = []) {
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  let nextPrompt = String(prompt || "");
  const missingTokens = mentions
    .map((mention) => mentionToken(
      mention,
      assetsById.get(mention.reference_asset_id),
    ))
    .filter((token, index, tokens) => (
      token && !nextPrompt.includes(token) && tokens.indexOf(token) === index
    ));
  if (missingTokens.length > 0) {
    nextPrompt = `${missingTokens.join(" ")}${nextPrompt.trim() ? `\n${nextPrompt.trimStart()}` : ""}`;
  }
  return nextPrompt;
}

export function reconcilePromptReferenceRemoval(
  prompt,
  mentions = [],
  referenceBindings = [],
  assets = [],
) {
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  const imagePromptMentions = mentions.filter((mention) => {
    const asset = assetsById.get(mention.reference_asset_id);
    return String(prompt || "").includes(mentionToken(mention, asset))
      || String(prompt || "").includes(mentionToken(mention));
  });
  const retainedIds = new Set(
    imagePromptMentions.map((mention) => mention.reference_asset_id),
  );
  const removedIds = new Set(
    mentions
      .filter((mention) => !retainedIds.has(mention.reference_asset_id))
      .map((mention) => mention.reference_asset_id),
  );
  return {
    imagePromptMentions,
    referenceBindings: referenceBindings.filter(
      (binding) => !removedIds.has(binding.reference_asset_id),
    ),
  };
}

export function normalizePromptMentionDraft(
  prompt,
  mentions = [],
  assets = [],
  referenceBindings = [],
) {
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  let nextPrompt = String(prompt || "");
  let changed = false;
  const seenIds = new Set();
  const nextMentions = [];
  mentions.forEach((mention) => {
    if (seenIds.has(mention.reference_asset_id)) {
      changed = true;
      return;
    }
    seenIds.add(mention.reference_asset_id);
    const asset = assetsById.get(mention.reference_asset_id);
    if (!asset) {
      nextMentions.push(mention);
      return;
    }
    const canonicalLabel = assetMentionLabel(asset);
    if (mention.label !== canonicalLabel) {
      const storedToken = mentionToken(mention);
      const canonicalToken = assetMentionToken(asset);
      if (
        storedToken
        && nextPrompt.includes(storedToken)
        && !nextPrompt.includes(canonicalToken)
      ) {
        nextPrompt = nextPrompt.replaceAll(storedToken, canonicalToken);
      }
      changed = true;
    }
    nextMentions.push({ ...mention, label: canonicalLabel });
  });
  referenceBindings.forEach((binding) => {
    if (seenIds.has(binding.reference_asset_id)) return;
    const asset = assetsById.get(binding.reference_asset_id);
    if (!asset) return;
    seenIds.add(binding.reference_asset_id);
    nextMentions.push({
      reference_asset_id: asset.id,
      label: assetMentionLabel(asset),
    });
    changed = true;
  });
  const promptWithTokens = ensurePromptMentionTokens(nextPrompt, nextMentions, assets);
  if (promptWithTokens !== nextPrompt) changed = true;
  nextPrompt = promptWithTokens;
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
