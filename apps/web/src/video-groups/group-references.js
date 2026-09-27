import { promptAssetReference } from '../prompt-references/prompt-assets.js';

export const groupReferenceKey = item => `${item.reference_kind}:${item.reference_id}`;

// Keep the server's actual input order. Only group-owned mentions are editable;
// adopted images and inherited references cannot disappear with a deleted token.
export function groupReferences(group, mentions, assets = [], inherited = []) {
  const options = assets.map(asset => promptAssetReference(asset, 'video'));
  const savedMentions = group.video_prompt_mentions || [];
  const supplied = group.input_plan?.references || [];
  const pinned = supplied.filter(item => !savedMentions.some(mention =>
    groupReferenceKey(mention) === groupReferenceKey(item) && mention.label === item.label)
    || inherited.some(mention => groupReferenceKey(mention) === groupReferenceKey(item)));
  const all = [...pinned];
  mentions.forEach(item => { if (!all.some(ref => groupReferenceKey(ref) === groupReferenceKey(item))) all.push(item); });
  // Saved references use the API order; unsaved additions are provisional until
  // the group is saved and projected again. Generation is blocked while dirty.
  all.sort((a, b) => {
    const index = item => supplied.findIndex(ref => groupReferenceKey(ref) === groupReferenceKey(item));
    return (index(a) < 0 ? supplied.length : index(a)) - (index(b) < 0 ? supplied.length : index(b));
  });
  const enriched = all.map((item, index) => {
    const image = group.images?.find(image => image.id === item.reference_id);
    const asset = options.find(option => groupReferenceKey(option) === groupReferenceKey(item));
    return { ...asset, ...item, number: index + 1,
      thumbnail_url: image?.url || asset?.thumbnail_url,
      description: image ? `本组第 ${index + 1} 张已采用分镜图` : asset?.label || item.label,
      available: item.reference_kind === 'approved_image' ? Boolean(image) : asset?.available !== false };
  });
  const numbers = new Map(enriched.map(item => [groupReferenceKey(item), item.number]));
  return {
    all: enriched,
    pinned: pinned.map(item => enriched.find(ref => groupReferenceKey(ref) === groupReferenceKey(item))),
    mentions: mentions.map(item => ({ ...enriched.find(ref => groupReferenceKey(ref) === groupReferenceKey(item)), ...item, number: numbers.get(groupReferenceKey(item)) })),
    options: options.map(item => ({ ...item, number: numbers.get(groupReferenceKey(item)) })),
  };
}

export function adjacentSelection(shots, selected) {
  const ids = shots.map(row => (row.plan || row).id);
  const positions = selected.map(id => ids.indexOf(id)).sort((a, b) => a - b);
  return positions.length >= 2 && positions[0] >= 0 && positions.every((position, index) => !index || position === positions[index - 1] + 1);
}

export function groupShotLabel(group, shots = []) {
  const members = group.shots || group.shot_plan_ids.map(id => shots.map(row => row.plan || row).find(plan => plan.id === id)).filter(Boolean);
  return members.length ? `分镜 ${members.map(item => item.index).join('、')}` : `${group.shot_plan_ids.length} 个分镜`;
}
