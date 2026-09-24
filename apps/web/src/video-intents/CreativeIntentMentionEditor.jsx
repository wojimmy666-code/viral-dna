import { useEffect, useMemo } from 'react';
import { WarningCircle } from '@phosphor-icons/react';
import { AssetReferenceEditor } from '../prompt-references/AssetReferenceEditor.jsx';
import { referenceSegments } from '../prompt-references/reference-document.js';
import { buildVideoReferenceOptions, normalizeVideoPromptMentions, videoReferenceKey } from '../video-inputs/video-prompt-references.js';

// Creative intent uses the same caret menu, atomic tags and asset library.
// Provider-managed characters retain their separate explicit binding workflow.
export function CreativeIntentMentionEditor({ assets, depthAssets, disabled = false,
  managedAssetBinding, mentions = [], onChange, onAddAssets, onRequestManagedAssetMention,
  onValidityChange, referenceFrames, resolveUrl, value, videoReferenceBindings }) {
  const options = useMemo(() => buildVideoReferenceOptions({ assets, depthAssets,
    managedAssetBinding, referenceFrames, videoReferenceBindings }),
  [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const optionMap = new Map(options.map(item => [videoReferenceKey(item), item]));
  const references = mentions.map(item => ({ ...optionMap.get(videoReferenceKey(item)), ...item,
    available: optionMap.has(videoReferenceKey(item)) }));
  const invalidMentions = references.filter(item => !item.available);
  const hasUnboundMention = referenceSegments(value, mentions).some(segment => !segment.reference && segment.text.includes('@'));
  useEffect(() => { onValidityChange?.(!invalidMentions.length && !hasUnboundMention); },
    [invalidMentions.length, hasUnboundMention, onValidityChange]);

  return <div className="creative-intent-reference-field">
    <AssetReferenceEditor label="创作意图" rows={3} maxLength={4000} value={value} disabled={disabled}
      references={references} options={options} resolveUrl={resolveUrl}
      placeholder="描述创作要求；输入 @ 引用人物、服装或场景资产"
      onAddAssets={onAddAssets && ((insert, pickerOptions) => onAddAssets(selected => insert(buildVideoReferenceOptions({ assets: selected })), pickerOptions))}
      onAddManagedAssets={onRequestManagedAssetMention && ((insert, pickerOptions) => onRequestManagedAssetMention({
        query: pickerOptions.query.replace(/^(?:托管角色|托管资产|演员|人物)(?:[/：:\s]+)?/u, '').trim(),
        insert, onCancel: pickerOptions.onCancel,
      }))}
      onChange={(intentText, selected) => {
        const intentMentions = normalizeVideoPromptMentions(intentText, selected.map((item, index) => ({
          reference_kind: item.reference_kind, reference_id: item.reference_id, label: item.label,
          role: item.role, order: index + 1,
        })), [...options, ...selected]);
        const nextKeys = new Set(intentMentions.map(videoReferenceKey));
        const oldKeys = new Set(mentions.map(videoReferenceKey));
        const addedReferences = selected.filter(item => !oldKeys.has(videoReferenceKey(item)));
        onChange?.({ intentText, intentMentions, addedReferences, addedReference: addedReferences[0] || null,
          removedMentions: mentions.filter(item => !nextKeys.has(videoReferenceKey(item))) });
      }} />
    {invalidMentions.length > 0 && <p className="creative-intent-invalid-mentions" role="alert"><WarningCircle aria-hidden="true" size={15} />
      {invalidMentions.map(item => '@' + item.label).join('、')} 已失效，请删除后重新选择</p>}
    {hasUnboundMention && !invalidMentions.length && <p className="creative-intent-invalid-mentions" role="status"><WarningCircle aria-hidden="true" size={15} />存在尚未选择完成的 @ 引用，请从资产列表中选择</p>}
  </div>;
}
