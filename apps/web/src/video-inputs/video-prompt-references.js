import {
  assetDirectoryLabel,
  assetMentionLabel,
  assetMentionSearchText,
} from "../shot-image-ui.js";

export const VIDEO_REFERENCE_SOURCE_BY_KIND = Object.freeze({
  approved_image: "approved_images",
  project_asset: "project_assets",
  provider_managed_asset: "provider_managed_assets",
  reference_video: "reference_video",
  depth_control: "depth_control",
});

export const VIDEO_REFERENCE_CATEGORY_BY_KIND = Object.freeze({
  approved_image: "image",
  project_asset: "image",
  provider_managed_asset: "actor",
  reference_video: "video",
  depth_control: "depth",
});

export function videoReferenceSourceSupported(capabilities = {}, source = "") {
  if (Array.isArray(capabilities.supported_input_sources)) {
    return capabilities.supported_input_sources.includes(source);
  }
  if (["approved_images", "project_assets"].includes(source)) {
    return Boolean(capabilities.image_to_video);
  }
  if (source === "provider_managed_assets") {
    return Boolean(capabilities.managed_assets?.supported);
  }
  if (source === "reference_video") return Boolean(capabilities.reference_video);
  if (source === "depth_control") {
    return Boolean(
      capabilities.depth_control_video
      || capabilities.reference_route?.supports_depth_control_video,
    );
  }
  return false;
}

const ROLE_BY_ASSET_TYPE = Object.freeze({
  person: "actor_identity",
  wardrobe: "wardrobe",
  product: "product",
  scene: "scene",
  prop: "composition",
  style: "composition",
});

export function videoReferenceKey(item = {}) {
  return `${item.reference_kind || item.kind}:${item.reference_id || item.id}`;
}

export function videoMentionToken(item = {}) {
  const label = String(item.label || "").trim().replace(/^@+/, "");
  return label ? `@${label}` : "";
}

export function promptContainsVideoMention(prompt, item = {}) {
  const token = videoMentionToken(item);
  return Boolean(token && String(prompt || "").includes(token));
}

export function normalizeVideoGenerationReferences(references = [], options = []) {
  const optionByKey = new Map(options.map((item) => [videoReferenceKey(item), item]));
  const seen = new Set();
  const normalized = [];
  for (const reference of [...(references || [])].sort(
    (left, right) => Number(left.order || 0) - Number(right.order || 0),
  )) {
    const key = videoReferenceKey(reference);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const option = optionByKey.get(key);
    normalized.push({
      reference_kind: option?.reference_kind || reference.reference_kind,
      reference_id: option?.reference_id || reference.reference_id,
      label: option?.label || reference.label,
      role: option?.role || reference.role,
      order: normalized.length + 1,
    });
  }
  return normalized;
}

export function selectedVideoReferenceOptions(options = [], selectedReferences = []) {
  const selectedByKey = new Map(
    normalizeVideoGenerationReferences(selectedReferences, options)
      .map((item) => [videoReferenceKey(item), item]),
  );
  return options
    .filter((item) => selectedByKey.has(videoReferenceKey(item)))
    .sort((left, right) => (
      selectedByKey.get(videoReferenceKey(left)).order
      - selectedByKey.get(videoReferenceKey(right)).order
    ));
}

export function managedAssetPreviewPath(binding = {}) {
  if (!binding.provider || !binding.asset_id) return binding.preview_url || "";
  return `/api/v1/managed-assets/providers/${encodeURIComponent(binding.provider)}/assets/${encodeURIComponent(binding.asset_id)}/preview`;
}

export function insertVideoMentionIntoPrompt(prompt, range, item) {
  const source = String(prompt || "");
  const start = Math.max(0, Math.min(Number(range?.start) || 0, source.length));
  const end = Math.max(start, Math.min(Number(range?.end) || start, source.length));
  const before = source.slice(0, start);
  const after = source.slice(end);
  const token = videoMentionToken(item);
  const leadingSeparator = before && !/[\s([\{（【《“‘，。！？；：、,.;:!?]$/u.test(before)
    ? " "
    : "";
  const trailingSeparator = !after
    ? " "
    : /^[\s)\]\}）】》”’，。！？；：、,.;:!?]/u.test(after)
      ? ""
      : " ";
  const inserted = `${leadingSeparator}${token}${trailingSeparator}`;
  return {
    value: `${before}${inserted}${after}`,
    cursor: before.length + inserted.length,
  };
}

export function buildVideoPromptHighlightSegments(prompt, mentions = []) {
  const source = String(prompt || "");
  const matches = [];
  const uniqueTokens = new Map();
  for (const mention of mentions) {
    const token = videoMentionToken(mention);
    if (token) uniqueTokens.set(token, mention);
  }
  for (const [token, mention] of uniqueTokens) {
    let cursor = 0;
    while (cursor < source.length) {
      const start = source.indexOf(token, cursor);
      if (start < 0) break;
      matches.push({ start, end: start + token.length, text: token, mention });
      cursor = start + token.length;
    }
  }
  matches.sort((left, right) => left.start - right.start || right.end - left.end);
  const segments = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start < cursor) continue;
    if (match.start > cursor) {
      segments.push({ type: "text", text: source.slice(cursor, match.start) });
    }
    segments.push({
      type: "mention",
      text: match.text,
      referenceKey: videoReferenceKey(match.mention),
    });
    cursor = match.end;
  }
  if (cursor < source.length) {
    segments.push({ type: "text", text: source.slice(cursor) });
  }
  return segments.length ? segments : [{ type: "text", text: source }];
}

export function removeVideoMentionFromPrompt(prompt, mention) {
  const token = videoMentionToken(mention);
  return String(prompt || "")
    .replaceAll(token, "")
    .replace(/\s{2,}/g, " ")
    .trimStart();
}

export function requiredSourceForVideoMention(mention = {}) {
  return VIDEO_REFERENCE_SOURCE_BY_KIND[mention.reference_kind] || "";
}

export function buildVideoReferenceOptions({
  assets = [],
  depthAssets = [],
  managedAssetBinding = null,
  referenceFrames = [],
  videoReferenceBindings = [],
} = {}) {
  const options = [];
  assets
    .filter((asset) => !asset.archived_at)
    .forEach((asset) => {
      options.push({
        id: asset.id,
        reference_kind: "project_asset",
        reference_id: asset.id,
        label: `资产/${assetMentionLabel(asset)}`,
        role: ROLE_BY_ASSET_TYPE[asset.type] || "composition",
        category: "项目图片资产",
        description: `${assetDirectoryLabel(asset)} · ${asset.type || "图片"}`,
        preview_url: asset.thumbnail_url || asset.content_url || "",
        search_text: assetMentionSearchText(asset),
      });
    });
  referenceFrames
    .filter(({ candidate }) => candidate)
    .forEach(({ beat, candidate }) => {
      options.push({
        id: candidate.id,
        reference_kind: "approved_image",
        reference_id: candidate.id,
        label: `分镜图/图${beat.index}-${beat.title}`,
        role: "composition",
        category: "已采用分镜图",
        description: `${Math.round(beat.start_ratio * 100)}%–${Math.round(beat.end_ratio * 100)}%`,
        preview_url: candidate.thumbnail_url || candidate.content_url || "",
        search_text: `${beat.index} ${beat.title} 分镜图`,
      });
    });
  if (managedAssetBinding) {
    options.push({
      id: managedAssetBinding.id,
      reference_kind: "provider_managed_asset",
      reference_id: managedAssetBinding.id,
      label: `托管角色/${managedAssetBinding.name}`,
      role: "actor_identity",
      category: "Provider 托管角色",
      description: `${managedAssetBinding.provider} · ${managedAssetBinding.project_name}`,
      preview_url: managedAssetPreviewPath(managedAssetBinding),
      search_text: `${managedAssetBinding.name} ${managedAssetBinding.group_name || ""} 托管角色`,
    });
  }
  depthAssets
    .filter((asset) => (
      asset.enabled
      && asset.status === "ready"
      && asset.validation_status === "passed"
    ))
    .forEach((asset, index) => {
      options.push({
        id: asset.id,
        reference_kind: "depth_control",
        reference_id: asset.id,
        label: `深度视频/分镜动作${index + 1}`,
        role: "depth",
        category: "动作与空间视频",
        description: `${Number(asset.duration_seconds || 0).toFixed(1)} 秒 · 近白远黑`,
        preview_url: asset.thumbnail_url || asset.preview_url || "",
        content_url: asset.content_url || "",
        search_text: `深度视频 动作 空间 ${index + 1}`,
      });
    });
  videoReferenceBindings
    .filter((binding) => binding.enabled && binding.media_type === "video")
    .forEach((binding) => {
      options.push({
        id: binding.id,
        reference_kind: "reference_video",
        reference_id: binding.id,
        label: `参考视频/${binding.label || `视频${binding.order}`}`,
        role: binding.role === "transition" ? "camera" : "motion",
        category: "普通参考视频",
        description: "动作或镜头参考",
        preview_url: binding.thumbnail_url || "",
        content_url: binding.content_url || binding.source_url || "",
        search_text: `${binding.label || ""} 参考视频 动作 镜头`,
      });
    });
  return options;
}

export function normalizeVideoPromptMentions(prompt, mentions = [], options = []) {
  const optionByKey = new Map(options.map((item) => [videoReferenceKey(item), item]));
  const nextMentions = [];
  for (const mention of mentions) {
    const option = optionByKey.get(videoReferenceKey(mention));
    const canonical = option
      ? {
          reference_kind: option.reference_kind,
          reference_id: option.reference_id,
          label: option.label,
          role: option.role,
        }
      : mention;
    if (!promptContainsVideoMention(prompt, canonical)) continue;
    nextMentions.push({
      ...canonical,
      order: nextMentions.length + 1,
    });
  }
  return nextMentions;
}
