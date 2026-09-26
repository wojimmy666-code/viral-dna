export const PURPOSE_LABELS = Object.freeze({ identity: '人物身份', actor_identity: '人物身份', spatial: '空间参考', scene: '场景参考', wardrobe: '服装参考', product: '产品参考', style: '风格参考', layout: '道具／其他', composition: '构图／其他' });

export function purposeOptions(part = 'image', assetType) {
  return [assetType === 'person' && (part === 'video' ? 'actor_identity' : 'identity'), 'spatial', 'scene', 'wardrobe', 'product', 'style', part === 'video' ? 'composition' : 'layout']
    .filter(Boolean).map(value => ({ value, label: PURPOSE_LABELS[value] }));
}

export function referenceRailOrder(references) {
  return [...references].sort((left, right) => Number(right.role === 'spatial') - Number(left.role === 'spatial'));
}

export function spatialConflict(references) {
  return new Set(references.filter(item => item.role === 'spatial').map(item => item.reference_asset_id || item.reference_id || item.id)).size > 1;
}
