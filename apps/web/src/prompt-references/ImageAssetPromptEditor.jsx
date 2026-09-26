import { forwardRef } from "react";
import { AssetReferenceEditor } from "./AssetReferenceEditor.jsx";
import { assetMentionLabel } from "../shot-image-ui.js";
import { promptMentionData } from './prompt-assets.js';

const roles = { person: 'identity', product: 'product', wardrobe: 'wardrobe', clothing: 'wardrobe', scene: 'scene', style: 'style', prop: 'layout' };
const order = { identity: 0, product: 1, wardrobe: 2, scene: 3, style: 4, layout: 5, spatial: 6 };

export const ImageAssetPromptEditor = forwardRef(function ImageAssetPromptEditor({ assets, draft, setDraft, disabled, resolveUrl, onBlur, onAddAssets, onApplySpatial, sourceFrame, labelledBy, styleControl, referenceLimit, inheritedMentions = [], activeBindings, retainedReferenceIds = [] }, ref) {
  const mentions = draft.imagePromptMentions || [];
  const bindings = (activeBindings || draft.referenceBindings || []).map(binding => ({ ...binding, role: mentions.find(item => item.reference_asset_id === binding.reference_asset_id)?.role || binding.role }));
  const eligibleIds = new Set(mentions.map((item) => item.reference_asset_id));
  const localIds = new Set(bindings.map(item => item.reference_asset_id));
  const inheritedBindings = inheritedMentions.filter(item => !localIds.has(item.reference_asset_id)).map(item => ({ reference_asset_id: item.reference_asset_id, role: item.role || roles[assets.find(asset => asset.id === item.reference_asset_id)?.type] || 'layout', weight: 1 }));
  const ordered = [...bindings, ...inheritedBindings].sort((a, b) =>
    (order[a.role] ?? 99) - (order[b.role] ?? 99) || (b.weight ?? 1) - (a.weight ?? 1)
    || String(a.created_at || '').localeCompare(String(b.created_at || '')));
  const numbers = new Map(ordered.map((item, index) => [item.reference_asset_id, index + (sourceFrame ? 2 : 1)]));
  const options = assets.filter((asset) => asset.media_kind !== 'video' && asset.type !== 'logo').map((asset) => ({
    key: asset.id, reference_asset_id: asset.id, label: assetMentionLabel(asset),
    thumbnail_url: asset.thumbnail_url || `/api/v1/references/${asset.id}/thumbnail`,
    description: roles[asset.type] === 'identity' ? '人物身份参考' : asset.description || '画面参考',
    available: !asset.archived_at && asset.rights_confirmed !== false,
    number: numbers.get(asset.id), role: roles[asset.type] || 'layout', asset_type: asset.type,
  }));
  const byId = new Map(options.map((item) => [item.key, item]));
  const references = mentions.map((mention) => ({ ...byId.get(mention.reference_asset_id), ...mention,
    key: mention.reference_asset_id, available: byId.get(mention.reference_asset_id)?.available ?? false,
    role: mention.role || bindings.find(item => item.reference_asset_id === mention.reference_asset_id)?.role || byId.get(mention.reference_asset_id)?.role,
    binding: bindings.find((binding) => binding.reference_asset_id === mention.reference_asset_id),
  }));
  return <AssetReferenceEditor ref={ref} value={draft.imagePrompt} references={references} options={options}
    styleControl={styleControl}
    onApplySpatial={onApplySpatial}
    referenceLimit={referenceLimit} reservedReferenceIds={[...bindings.filter((item) => !eligibleIds.has(item.reference_asset_id)).map(item => item.reference_asset_id), ...inheritedMentions.map(item => item.reference_asset_id)]}
    label="局部图片提示词" labelledBy={labelledBy} disabled={disabled} resolveUrl={resolveUrl}
    onAddAssets={onAddAssets && ((insert, pickerOptions) => onAddAssets((assets) => insert((Array.isArray(assets) ? assets : [assets]).map((asset) => ({
      key:asset.id, reference_asset_id:asset.id, label:assetMentionLabel(asset),
      thumbnail_url:asset.thumbnail_url, available:true, role:asset.reference_role || roles[asset.type] || 'layout', asset_type: asset.type,
    }))), pickerOptions)) }
    indexOffset={sourceFrame ? 1 : 0} onBlur={() => Promise.resolve(onBlur?.()).catch(() => undefined)}
    onChange={(value, nextReferences) => setDraft((current) => {
      const nextIds = new Set(nextReferences.map((item) => item.reference_asset_id));
      const removed = new Set((current.imagePromptMentions || []).filter((item) => !nextIds.has(item.reference_asset_id)).map((item) => item.reference_asset_id));
      const nextBindings = current.referenceBindings.filter((item) => !removed.has(item.reference_asset_id) || retainedReferenceIds.includes(item.reference_asset_id));
      nextReferences.forEach((item) => {
        if (!nextBindings.some((binding) => binding.reference_asset_id === item.reference_asset_id)) {
          nextBindings.push(item.binding ? { ...item.binding, role: item.role || item.binding.role } : { reference_asset_id: item.reference_asset_id, role: item.role || 'layout', weight: 1 });
        }
      });
      return { ...current, imagePrompt: value,
        imagePromptMentions: promptMentionData(nextReferences, 'image'),
        referenceBindings: nextBindings };
    })} />;
});
