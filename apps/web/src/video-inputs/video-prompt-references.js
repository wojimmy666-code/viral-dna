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

export const VIDEO_REFERENCE_ROLE_LABELS = Object.freeze({
  actor_identity: "人物身份",
  composition: "构图与画面",
  scene: "场景",
  product: "产品外观",
  wardrobe: "服装",
  motion: "人物动作",
  camera: "镜头运动",
  depth: "动作与空间",
  transition: "转场",
  style: "视觉风格",
});

export function videoReferenceRoleLabel(item = {}) {
  return VIDEO_REFERENCE_ROLE_LABELS[item.role] || "参考输入";
}

export function buildVideoReferenceSystemConstraints(references = []) {
  const ordered = [...(references || [])].sort(
    (left, right) => Number(left.order || 0) - Number(right.order || 0),
  );
  const entries = [];
  const seen = new Set();
  for (const reference of ordered) {
    const key = videoReferenceKey(reference);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const token = videoMentionToken(reference);
    if (reference.reference_kind === "depth_control") {
      entries.push({
        key,
        kind: "depth_control",
        roleLabel: "动作与空间",
        token,
        summary: "按创作意图提供动作、节奏、空间与镜头参考",
        text: `${token} 只提供动作、姿态、节奏、空间位置和镜头关系，不提供人物身份、服装、颜色或纹理。保留强度以创作意图中的明确要求为准；未要求逐帧复刻时允许模型自然调整。`,
      });
    } else if (reference.reference_kind === "provider_managed_asset") {
      entries.push({
        key,
        kind: "provider_managed_asset",
        roleLabel: "人物身份",
        token,
        summary: "唯一的人物身份与外观来源",
        text: `${token} 是画面中唯一的人物身份来源。人物的面部、年龄、发型、体型和身份特征必须来自该托管角色，不得继承深度视频或其他参考画面中的人物身份。该引用不改变动作、时序、主体位置或镜头运动。`,
      });
    }
  }
  return entries;
}

export function videoReferenceConflictPriority(references = []) {
  const kinds = new Set((references || []).map((item) => item.reference_kind));
  if (!kinds.has("depth_control") || !kinds.has("provider_managed_asset")) return "";
  return "发生冲突时按职责分离处理：人物身份以托管角色为准；动作、姿态、节奏、空间位置和镜头关系以深度视频为准。";
}

export function compileVideoPromptWithReferences(prompt, references = []) {
  const userPrompt = String(prompt || "").trim();
  const constraints = buildVideoReferenceSystemConstraints(references);
  const priority = videoReferenceConflictPriority(references);
  if (constraints.length === 0) return userPrompt;
  return [
    `用户视频提示词：\n${userPrompt}`,
    `系统引用约束：\n${constraints.map((item) => `- ${item.text}`).join("\n")}`,
    priority,
  ].filter(Boolean).join("\n\n");
}

const LEGACY_REFERENCE_POLICY_PATTERNS = Object.freeze([
  /@托管角色\/[^@\n]+?\s+是画面中唯一的人物身份来源。\s*人物的面部、年龄、发型、体型和身份特征必须来自该托管角色[，,]\s*不(?:得)?继承深度视频或其他参考画面中的人物身份。\s*(?:该引用不改变动作、时序、主体位置或镜头运动。\s*)?/gu,
  /@深度视频\/[^@\n]+?\s+是唯一的动作、姿态、运动节奏、空间位置、镜头关系和遮挡转场来源。\s*严格逐帧遵循深度视频中的身体姿态、手臂轨迹、动作顺序、速度、停顿、主体位置、景别变化和镜头运动。\s*不得重新设计、简化、增加、删除、交换或提前任何动作。\s*(?:该引用不提供人物身份、面部或外观特征。\s*)?/gu,
]);

export function stripLegacyVideoReferencePolicies(prompt) {
  let nextPrompt = String(prompt || "");
  for (const pattern of LEGACY_REFERENCE_POLICY_PATTERNS) {
    nextPrompt = nextPrompt.replace(pattern, "");
  }
  return nextPrompt
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

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
  style: "style",
});

export function videoReferenceKey(item = {}) {
  return `${item.reference_kind || item.kind}:${item.reference_id || item.id}`;
}

export function videoReferenceStableKey(item = {}) {
  if (item.reference_kind === "approved_image" && item.visual_beat_id) {
    return `approved_image:visual_beat:${item.visual_beat_id}`;
  }
  return videoReferenceKey(item);
}

export function isAutomaticVideoReference(item = {}) {
  return item.reference_kind === "approved_image";
}

export function approvedVisualBeatFramesFromDetail(detail) {
  const beats = [...(detail?.plan?.visual_beats || [])]
    .sort((left, right) => left.index - right.index);
  const requiredBeats = beats.filter((item) => item.required);
  const targets = requiredBeats.length > 0 ? requiredBeats : beats;
  const firstBeatId = beats[0]?.id;
  const imageRuns = (detail?.generation_runs || []).filter((run) => run.kind === "image");
  return targets.map((beat) => {
    const runs = imageRuns.filter((run) => (
      run.visual_beat_id === beat.id
      || (!run.visual_beat_id && beat.id === firstBeatId)
    ));
    const candidate = beat.approved_image_candidate_id
      ? runs
        .flatMap((run) => run.candidates || [])
        .find((item) => item.id === beat.approved_image_candidate_id) || null
      : null;
    return { beat, candidate };
  });
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
    const normalizedReference = {
      reference_kind: option?.reference_kind || reference.reference_kind,
      reference_id: option?.reference_id || reference.reference_id,
      label: option?.label || reference.label,
      role: option?.role || reference.role,
      order: normalized.length + 1,
    };
    const visualBeatId = option?.visual_beat_id || reference.visual_beat_id;
    const automatic = option?.automatic ?? reference.automatic;
    const scope = option?.scope || reference.scope;
    const origin = option?.origin || reference.origin;
    const locked = option?.locked ?? reference.locked;
    if (visualBeatId) normalizedReference.visual_beat_id = visualBeatId;
    if (automatic) normalizedReference.automatic = true;
    if (scope) normalizedReference.scope = scope;
    if (origin) normalizedReference.origin = origin;
    if (locked) normalizedReference.locked = true;
    normalized.push(normalizedReference);
  }
  return normalized;
}

export function ensureVideoGenerationReference(references = [], option = {}) {
  const key = videoReferenceKey(option);
  const normalized = normalizeVideoGenerationReferences(references);
  if (!key || normalized.some((item) => videoReferenceKey(item) === key)) {
    return normalized;
  }
  const nextReference = {
    reference_kind: option.reference_kind,
    reference_id: option.reference_id,
    label: option.label,
    role: option.role,
    order: normalized.length + 1,
  };
  if (option.visual_beat_id) nextReference.visual_beat_id = option.visual_beat_id;
  if (option.automatic) nextReference.automatic = true;
  if (option.scope) nextReference.scope = option.scope;
  if (option.origin) nextReference.origin = option.origin;
  if (option.locked) nextReference.locked = true;
  return [
    ...normalized,
    nextReference,
  ];
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

function videoMentionRanges(prompt, mentions = []) {
  const source = String(prompt || "");
  const ranges = [];
  const uniqueTokens = new Set(mentions.map(videoMentionToken).filter(Boolean));
  for (const token of uniqueTokens) {
    let cursor = 0;
    while (cursor < source.length) {
      const start = source.indexOf(token, cursor);
      if (start < 0) break;
      ranges.push({ start, end: start + token.length, token });
      cursor = start + token.length;
    }
  }
  return ranges.sort((left, right) => left.start - right.start);
}

export function deleteVideoMentionAtSelection(
  prompt,
  mentions = [],
  { key = "", selectionStart = 0, selectionEnd = selectionStart } = {},
) {
  if (!["Backspace", "Delete"].includes(key)) return null;
  const source = String(prompt || "");
  const start = Math.max(0, Math.min(Number(selectionStart) || 0, source.length));
  const end = Math.max(start, Math.min(Number(selectionEnd) || start, source.length));
  const ranges = videoMentionRanges(source, mentions);
  let affected = [];
  if (start !== end) {
    affected = ranges.filter((range) => start < range.end && end > range.start);
  } else if (key === "Backspace") {
    affected = ranges.filter((range) => (
      (start > range.start && start <= range.end)
      || (start === range.end + 1 && /\s/u.test(source[range.end] || ""))
    ));
  } else {
    affected = ranges.filter((range) => (
      (start >= range.start && start < range.end)
      || (start + 1 === range.start && /\s/u.test(source[start] || ""))
    ));
  }
  if (affected.length === 0) return null;

  let deleteStart = start === end
    ? Math.min(...affected.map((range) => range.start))
    : Math.min(start, ...affected.map((range) => range.start));
  let deleteEnd = start === end
    ? Math.max(...affected.map((range) => range.end))
    : Math.max(end, ...affected.map((range) => range.end));
  if (/\s/u.test(source[deleteEnd] || "")) {
    deleteEnd += 1;
  } else if (deleteStart > 0 && /\s/u.test(source[deleteStart - 1] || "")) {
    deleteStart -= 1;
  }
  return {
    value: `${source.slice(0, deleteStart)}${source.slice(deleteEnd)}`,
    cursor: deleteStart,
  };
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

export function buildManagedAssetReferenceOption(managedAssetBinding = null) {
  if (!managedAssetBinding?.id) return null;
  return {
    id: managedAssetBinding.id,
    reference_kind: "provider_managed_asset",
    reference_id: managedAssetBinding.id,
    label: `托管角色/${managedAssetBinding.name}`,
    role: "actor_identity",
    category: "Provider 托管角色",
    description: `${managedAssetBinding.provider} · ${managedAssetBinding.project_name}`,
    preview_url: managedAssetPreviewPath(managedAssetBinding),
    search_text: `${managedAssetBinding.name} ${managedAssetBinding.group_name || ""} 托管角色`,
  };
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
        label: `分镜图/图${beat.index}`,
        role: "composition",
        category: "已采用分镜图",
        description: `${beat.title} · ${Math.round(beat.start_ratio * 100)}%–${Math.round(beat.end_ratio * 100)}%`,
        preview_url: candidate.thumbnail_url || candidate.content_url || "",
        search_text: `${beat.index} ${beat.title} 分镜图`,
        visual_beat_id: beat.id,
        beat_index: beat.index,
        automatic: true,
        origin: "visual_beat_auto",
        scope: {
          kind: "visual_beats",
          visual_beat_ids: [beat.id],
          start_ratio: beat.start_ratio,
          end_ratio: beat.end_ratio,
        },
      });
    });
  const managedAssetOption = buildManagedAssetReferenceOption(managedAssetBinding);
  if (managedAssetOption) options.push(managedAssetOption);
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
        role: binding.role === "transition" ? "transition" : "motion",
        category: "普通参考视频",
        description: "动作或镜头参考",
        preview_url: binding.thumbnail_url || "",
        content_url: binding.content_url || binding.source_url || "",
        search_text: `${binding.label || ""} 参考视频 动作 镜头`,
      });
    });
  return options;
}

export function synchronizeAutomaticVideoReferences({
  selectedReferences = [],
  referenceFrames = [],
  excludedVisualBeatIds = [],
  orderOverride = [],
} = {}) {
  if ((referenceFrames || []).length === 0) {
    return normalizeVideoGenerationReferences(selectedReferences);
  }
  const excluded = new Set((excludedVisualBeatIds || []).map(String));
  const automaticOptions = buildVideoReferenceOptions({ referenceFrames })
    .filter((item) => (
      item.reference_kind === "approved_image"
      && item.visual_beat_id
      && !excluded.has(String(item.visual_beat_id))
    ));
  const automaticReferences = automaticOptions.map((option, index) => ({
    reference_kind: option.reference_kind,
    reference_id: option.reference_id,
    label: option.label,
    role: option.role,
    order: index + 1,
    visual_beat_id: option.visual_beat_id,
    automatic: true,
    origin: "visual_beat_auto",
    scope: option.scope,
  }));
  const manualReferences = normalizeVideoGenerationReferences(selectedReferences)
    .filter((item) => item.reference_kind !== "approved_image");
  const base = [...automaticReferences, ...manualReferences];
  const baseOrder = new Map(base.map((item, index) => [videoReferenceStableKey(item), index]));
  const overrideOrder = new Map(
    (orderOverride || []).map((key, index) => [String(key), index]),
  );
  const ordered = [...base].sort((left, right) => {
    const leftOverride = overrideOrder.get(videoReferenceStableKey(left));
    const rightOverride = overrideOrder.get(videoReferenceStableKey(right));
    if (leftOverride != null && rightOverride != null) return leftOverride - rightOverride;
    if (leftOverride != null) return -1;
    if (rightOverride != null) return 1;
    return (
      baseOrder.get(videoReferenceStableKey(left))
      - baseOrder.get(videoReferenceStableKey(right))
    );
  });
  return normalizeVideoGenerationReferences(
    ordered.map((item, index) => ({ ...item, order: index + 1 })),
    automaticOptions,
  );
}

export function synchronizeAutomaticVideoPrompt({
  prompt = "",
  mentions = [],
  selectedReferences = [],
} = {}) {
  const references = normalizeVideoGenerationReferences(selectedReferences);
  const selectedKeys = new Set(references.map(videoReferenceKey));
  const selectedTokens = references.map(videoMentionToken).filter(Boolean);
  const knownTokens = new Set([
    ...selectedTokens,
    ...(mentions || []).map(videoMentionToken).filter(Boolean),
  ]);
  const removedTokens = new Set(
    (mentions || [])
      .filter((item) => !selectedKeys.has(videoReferenceKey(item)))
      .map(videoMentionToken)
      .filter(Boolean),
  );
  const declarationOnly = (line) => {
    let remainder = String(line || "");
    for (const token of [...knownTokens].sort((left, right) => right.length - left.length)) {
      remainder = remainder.replaceAll(token, "");
    }
    return remainder.trim() === "" && String(line || "").trim() !== "";
  };
  const lines = String(prompt || "").split("\n");
  while (lines.length > 0 && lines[0].trim() === "") lines.shift();
  while (lines.length > 0 && declarationOnly(lines[0])) lines.shift();
  while (lines.length > 0 && lines[0].trim() === "") lines.shift();
  let body = lines.join("\n");
  for (const token of removedTokens) body = body.replaceAll(token, "");
  body = body
    .replace(/[ \t]+\n/g, "\n")
    .replace(/^[ \t]*\n+/u, "")
    .trim();
  const tokenLine = selectedTokens.join(" ");
  const videoPrompt = [tokenLine, body].filter(Boolean).join("\n\n");
  return {
    videoPrompt,
    videoPromptMentions: normalizeVideoPromptMentions(
      videoPrompt,
      references,
      references,
    ),
  };
}

export function reconcileVideoDraftReferences(
  draft = {},
  change = {},
  referenceFrames = [],
) {
  const removedReferences = [
    ...(change.removedReferences || []),
    ...(change.removedReference ? [change.removedReference] : []),
  ];
  const excluded = new Set((draft.autoReferenceExclusions || []).map(String));
  const removedIntentReferenceKeys = new Set(
    (draft.removedIntentReferenceKeys || []).map(String),
  );
  const currentVisualBeatIds = new Set(
    (referenceFrames || []).map(({ beat }) => String(beat.id)),
  );
  if (currentVisualBeatIds.size > 0) {
    for (const id of excluded) {
      if (!currentVisualBeatIds.has(id)) excluded.delete(id);
    }
  }
  for (const reference of removedReferences) {
    if (reference.reference_kind === "approved_image" && reference.visual_beat_id) {
      excluded.add(String(reference.visual_beat_id));
    }
    if (["intent_generated", "intent_explicit"].includes(reference.origin)) {
      removedIntentReferenceKeys.add(videoReferenceStableKey(reference));
    }
  }
  if (
    change.addedReference?.reference_kind === "approved_image"
    && change.addedReference.visual_beat_id
  ) {
    excluded.delete(String(change.addedReference.visual_beat_id));
  }
  if (change.addedReference) {
    removedIntentReferenceKeys.delete(videoReferenceStableKey(change.addedReference));
  }
  if (change.restoreAutomaticReferences) excluded.clear();

  const requestedOrder = Object.prototype.hasOwnProperty.call(change, "referenceOrderOverride")
    ? change.referenceOrderOverride
    : draft.referenceOrderOverride;
  const selectedReferences = synchronizeAutomaticVideoReferences({
    selectedReferences: change.selectedReferences || draft.selectedReferences || [],
    referenceFrames,
    excludedVisualBeatIds: [...excluded],
    orderOverride: change.restoreAutomaticReferences ? [] : requestedOrder,
  });
  const selectedStableKeys = new Set(selectedReferences.map(videoReferenceStableKey));
  const referenceOrderOverride = (change.restoreAutomaticReferences ? [] : requestedOrder || [])
    .filter((key) => selectedStableKeys.has(String(key)));
  const synchronizedPrompt = synchronizeAutomaticVideoPrompt({
    prompt: Object.prototype.hasOwnProperty.call(change, "videoPrompt")
      ? change.videoPrompt
      : draft.videoPrompt,
    mentions: Object.prototype.hasOwnProperty.call(change, "videoPromptMentions")
      ? change.videoPromptMentions
      : draft.videoPromptMentions,
    selectedReferences,
  });
  const inputSources = new Set(change.inputSources || draft.inputSources || []);
  for (const reference of removedReferences) {
    const source = requiredSourceForVideoMention(reference);
    if (
      source
      && !selectedReferences.some((item) => requiredSourceForVideoMention(item) === source)
    ) {
      inputSources.delete(source);
    }
  }
  for (const reference of selectedReferences) {
    const source = requiredSourceForVideoMention(reference);
    if (source) inputSources.add(source);
  }
  return {
    ...draft,
    ...synchronizedPrompt,
    selectedReferences,
    inputSources: [...inputSources],
    referenceSyncMode: "auto",
    autoReferenceExclusions: [...excluded],
    referenceOrderOverride,
    removedIntentReferenceKeys: [...removedIntentReferenceKeys],
  };
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
          ...(option.visual_beat_id ? { visual_beat_id: option.visual_beat_id } : {}),
          ...(option.automatic ? { automatic: true } : {}),
          ...(option.scope ? { scope: option.scope } : {}),
          ...(option.origin ? { origin: option.origin } : {}),
          ...(option.locked ? { locked: true } : {}),
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
