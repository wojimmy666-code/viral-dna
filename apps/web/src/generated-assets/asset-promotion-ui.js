import { ASSET_TYPE_OPTIONS, normalizeAssetTags } from "../asset-library-ui.js";

export const artifactKey = (kind, id) => JSON.stringify([kind || "", id || ""]);
export const jsonRequest = body => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export function folderPreferenceKey(context, target) {
  return `viraldna:asset-promotion-folder:${context.account?.id}:${context.active_workspace?.id}:${target.projectId || target.shotPlanId || target.identity}`;
}

export function recalledFolder(key, folders) {
  try {
    const saved = window.localStorage.getItem(key);
    return folders.some(folder => folder.id === saved) ? saved : "";
  } catch { return ""; }
}

export function rememberFolder(key, folderId) {
  try { window.localStorage.setItem(key, folderId || ""); } catch { /* Storage is optional. */ }
}

export function promotionPayload(target, draft) {
  const name = draft.name.trim();
  if (!name || name.length > 120) throw new Error("请填写 1–120 字的资产名称");
  if (!ASSET_TYPE_OPTIONS.some(item => item.value === draft.assetType)) throw new Error("请选择资产类型");
  const tagCount = new Set(String(draft.tags || "").split(/[,，\n]/).map(tag => tag.trim()).filter(Boolean)).size;
  if (tagCount > 20) throw new Error("标签最多填写 20 个");
  const tags = normalizeAssetTags(draft.tags);
  return {
    kind: target.artifactKind, source_entity_id: target.sourceEntityId,
    shot_plan_id: target.shotPlanId || null, folder_id: draft.folderId || null,
    asset_type: draft.assetType, name, description: draft.description, tags,
  };
}
