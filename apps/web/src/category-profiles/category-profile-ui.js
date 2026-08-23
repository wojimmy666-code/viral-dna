export const EMPTY_CATEGORY_PROFILE = Object.freeze({
  display_name: "",
  category_name: "",
  brand_name: "",
  brief: "",
  audiences: "",
  selling_points: "",
  scenes: "",
  forbidden_claims: "",
  visual_style: "",
});

export function splitProfileItems(value) {
  return [...new Set(
    String(value || "")
      .split(/[\n,，、]+/)
      .map((item) => item.trim())
      .filter(Boolean),
  )];
}

export function profileToDraft(profile) {
  if (!profile) return { ...EMPTY_CATEGORY_PROFILE };
  return {
    ...profile,
    brand_name: profile.brand_name || "",
    audiences: (profile.audiences || []).join("、"),
    selling_points: (profile.selling_points || []).join("\n"),
    scenes: (profile.scenes || []).join("、"),
    forbidden_claims: (profile.forbidden_claims || []).join("\n"),
    visual_style: profile.visual_style || "",
  };
}

export function draftToPayload(draft) {
  return {
    display_name: String(draft.display_name || "").trim(),
    category_name: String(draft.category_name || "").trim(),
    brand_name: String(draft.brand_name || "").trim() || null,
    brief: String(draft.brief || "").trim(),
    audiences: splitProfileItems(draft.audiences),
    selling_points: splitProfileItems(draft.selling_points),
    scenes: splitProfileItems(draft.scenes),
    forbidden_claims: splitProfileItems(draft.forbidden_claims),
    visual_style: String(draft.visual_style || "").trim() || null,
  };
}

export function categoryProfileValidationMessage(payload) {
  if (!payload.display_name) return "请填写档案名称";
  if (!payload.category_name) return "请填写所属品类";
  if (!payload.brief) return "请用一句话说明定位";
  if (!payload.audiences.length) return "请至少填写一项目标人群";
  if (!payload.selling_points.length) return "请至少填写一项核心卖点";
  return "";
}

export function profileSearchText(profile) {
  return [
    profile.display_name,
    profile.category_name,
    profile.brand_name,
    profile.brief,
    ...(profile.audiences || []),
    ...(profile.selling_points || []),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}
