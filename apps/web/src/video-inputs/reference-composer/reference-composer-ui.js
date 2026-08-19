import {
  VIDEO_REFERENCE_SOURCE_BY_KIND,
  requiredSourceForVideoMention,
  videoReferenceKey,
} from "../video-prompt-references.js";

const SOURCE_LABELS = Object.freeze({
  approved_images: "分镜图片",
  project_assets: "项目资产",
  provider_managed_assets: "托管人物",
  reference_video: "参考视频",
  depth_control: "深度控制",
});

const SOURCE_KIND = Object.freeze({
  approved_images: "approved_image",
  project_assets: "project_asset",
  provider_managed_assets: "provider_managed_asset",
  reference_video: "reference_video",
  depth_control: "depth_control",
});

export function referenceAlias(item = {}, index = 0) {
  const ordinal = index + 1;
  if (item.reference_kind === "provider_managed_asset") return `角色${ordinal}`;
  if (item.reference_kind === "reference_video") return `视频${ordinal}`;
  if (item.reference_kind === "depth_control") return `深度${ordinal}`;
  return `图${ordinal}`;
}
export function selectedReferenceItems({
  mentions = [],
  options = [],
  selectedSources = [],
} = {}) {
  const optionByKey = new Map(options.map((option) => [videoReferenceKey(option), option]));
  const items = [];
  const representedSources = new Set();

  [...mentions]
    .sort((left, right) => Number(left.order || 0) - Number(right.order || 0))
    .forEach((mention) => {
      const source = requiredSourceForVideoMention(mention);
      if (source) representedSources.add(source);
      items.push({
        ...mention,
        ...(optionByKey.get(videoReferenceKey(mention)) || {}),
        explicit: true,
      });
    });

  for (const source of selectedSources) {
    if (representedSources.has(source)) continue;
    const candidates = options.filter(
      (option) => VIDEO_REFERENCE_SOURCE_BY_KIND[option.reference_kind] === source,
    );
    const first = candidates[0] || {};
    items.push({
      ...first,
      id: `source:${source}`,
      reference_id: `source:${source}`,
      reference_kind: SOURCE_KIND[source] || "project_asset",
      label: SOURCE_LABELS[source] || "参考素材",
      description: candidates.length > 1
        ? `${candidates.length} 项已启用参考`
        : first.description || "已启用该类参考",
      source,
      source_count: candidates.length,
      explicit: false,
      grouped: candidates.length > 1,
    });
  }

  return items.map((item, index) => ({
    ...item,
    display_alias: referenceAlias(item, index),
    display_order: index + 1,
  }));
}

export function referenceSource(item = {}) {
  return item.source || requiredSourceForVideoMention(item);
}
