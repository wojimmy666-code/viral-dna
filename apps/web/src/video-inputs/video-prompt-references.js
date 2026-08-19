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
      preview_url: managedAssetBinding.preview_url || "",
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
        preview_url: "",
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
    const storedTokenPresent = String(prompt || "").includes(videoMentionToken(mention));
    const canonicalTokenPresent = String(prompt || "").includes(videoMentionToken(canonical));
    if (storedTokenPresent || canonicalTokenPresent) {
      nextMentions.push({
        ...(canonicalTokenPresent ? canonical : mention),
        order: nextMentions.length + 1,
      });
    }
  }
  return nextMentions;
}
