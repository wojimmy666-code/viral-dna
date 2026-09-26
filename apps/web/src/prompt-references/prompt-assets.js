const imageRoles = { person: 'identity', product: 'product', clothing: 'wardrobe', wardrobe: 'wardrobe', scene: 'scene', style: 'style' };
const videoRoles = { person: 'actor_identity', product: 'product', clothing: 'wardrobe', wardrobe: 'wardrobe', scene: 'scene', style: 'style' };

export function promptAssetReference(asset, part = 'image') {
  const id = asset.asset_id || asset.id;
  return {
    ...(part === 'image' ? { reference_asset_id: id, role: asset.reference_role || imageRoles[asset.type] || 'layout' }
      : { reference_kind: 'project_asset', reference_id: id, role: asset.reference_role || videoRoles[asset.type] || 'composition' }),
    asset_type: asset.type,
    label: `${part === 'video' ? '资产/' : ''}${asset.folder_name || '未分类'}/${asset.name}`,
    thumbnail_url: asset.thumbnail_url,
    available: !asset.archived_at && asset.rights_confirmed !== false && asset.image_eligible !== false && asset.media_kind !== 'video' && asset.type !== 'logo',
  };
}

export function promptMentionData(references, part) {
  return references.map((item, index) => part === 'image'
    ? { reference_asset_id: item.reference_asset_id, label: item.label, ...(item.role ? { role: item.role } : {}) }
    : { reference_kind: item.reference_kind, reference_id: item.reference_id, label: item.label, role: item.role, order: index + 1 });
}
