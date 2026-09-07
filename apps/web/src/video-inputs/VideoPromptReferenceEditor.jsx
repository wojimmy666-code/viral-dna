import { useMemo } from "react";
import { AssetReferenceEditor } from "../prompt-references/AssetReferenceEditor.jsx";
import {
  buildVideoReferenceOptions, ensureVideoGenerationReference, normalizeVideoPromptMentions,
  requiredSourceForVideoMention, videoReferenceKey,
} from "./video-prompt-references.js";

export function VideoPromptReferenceEditor({
  assets, depthAssets, managedAssetBinding, onBlur, onChange, referenceFrames, resolveUrl,
  selectedReferences = [], value, videoPromptMentions = [], videoReferenceBindings,
  onAddAssets, disabled = false,
}) {
  const options = useMemo(() => buildVideoReferenceOptions({
    assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings,
  }), [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const byKey = new Map(options.map((item) => [videoReferenceKey(item), item]));
  const ordered = selectedReferences.slice().sort((a, b) => a.order - b.order);
  const numbers = new Map(ordered.map((item, index) => [videoReferenceKey(item), index + 1]));
  const choices = options.map((item) => ({
    ...item, key: videoReferenceKey(item), number: numbers.get(videoReferenceKey(item)),
    available: true,
  }));
  const references = videoPromptMentions.map((item) => ({
    ...byKey.get(videoReferenceKey(item)), ...item, key: videoReferenceKey(item),
    generationReference: ordered.find((reference) => videoReferenceKey(reference) === videoReferenceKey(item)),
    number: numbers.get(videoReferenceKey(item)), available: byKey.has(videoReferenceKey(item)),
  }));
  return <AssetReferenceEditor label="视频提示词" rows={7} value={value}
    references={references} options={choices} resolveUrl={resolveUrl} onBlur={onBlur}
    onAddAssets={onAddAssets && ((insert) => onAddAssets((asset) => insert(
      buildVideoReferenceOptions({ assets:[asset] })[0],
    ))) } disabled={disabled}
    placeholder="描述视频；输入 @ 引用已采用分镜图或项目已选素材"
    onChange={(nextValue, nextReferences) => {
      const nextMentions = normalizeVideoPromptMentions(nextValue, nextReferences.map((item, index) => ({
        reference_kind: item.reference_kind, reference_id: item.reference_id, label: item.label,
        role: item.role, order: index + 1,
      })), options);
      const retained = new Set(nextMentions.map(videoReferenceKey));
      const removedKeys = new Set(videoPromptMentions.filter((item) => !retained.has(videoReferenceKey(item))).map(videoReferenceKey));
      const removedReferences = selectedReferences.filter((item) => removedKeys.has(videoReferenceKey(item)));
      let selected = selectedReferences.filter((item) => !removedKeys.has(videoReferenceKey(item)));
      nextReferences.forEach((item) => {
        if (item.generationReference && !selected.some((reference) => videoReferenceKey(reference) === videoReferenceKey(item))) {
          selected = [...selected, { ...item.generationReference }];
        } else selected = ensureVideoGenerationReference(selected, item);
      });
      const previous = new Set(videoPromptMentions.map(videoReferenceKey));
      const addedReferences = nextReferences.filter((item) => !previous.has(videoReferenceKey(item)))
        .map((item) => item.generationReference || item);
      const added = addedReferences[0];
      onChange({
        videoPrompt: nextValue, videoPromptMentions: nextMentions, selectedReferences: selected,
        removedReferences, addedReferences, ...(added ? { requiredInputSource: requiredSourceForVideoMention(added) } : {}),
      });
    }} />;
}
