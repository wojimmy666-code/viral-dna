export const ORIGINAL_STYLE = Object.freeze({ preset: "original" });

const STYLE_FIELDS = ["description", "lighting", "color", "texture", "camera", "motion"];

// API responses fill optional fields. Those defaults are acknowledgements,
// not a new selection that should reset an input the user is still editing.
export function visualStyleKey(value) {
  if (value === null) return "null";
  if (value?.catalog_id) return JSON.stringify({ catalog_id: value.catalog_id, catalog_version: value.catalog_version });
  return JSON.stringify({ preset: value?.preset || "original", ...Object.fromEntries(STYLE_FIELDS.map(key => [key, value?.[key] || ""])) });
}

export function styleRecoverySummary(values) {
  if (!Object.hasOwn(values || {}, "visual_style")) return "未包含画面风格设置，保留服务器风格";
  const names = { description: "描述", lighting: "光照", color: "色彩", texture: "材质", camera: "摄影表现", motion: "动态表现" };
  const describe = (value, snapshot) => [snapshot?.label || (value?.preset === "original" ? "沿用现有风格" : value?.preset || "沿用现有风格"),
    ...STYLE_FIELDS.filter(key => value?.[key]).map(key => `${names[key]}：${value[key]}`)].join("\n");
  return [`整片：${describe(values.visual_style, values.visual_style_snapshot)}`,
    ...Object.entries(values.shot_styles || {}).sort(([a], [b]) => a.localeCompare(b)).map(([id, style]) => `分镜 ${id}：${describe(style, values.shot_style_snapshots?.[id])}`),
    `分镜覆盖：${Object.keys(values.shot_styles || {}).length} 项，其余继承整片`].join("\n\n");
}

export function hasVisualStyle(value) {
  return Boolean(value && ((value.preset && value.preset !== "original") || Object.entries(value).some(([key, text]) => key !== "preset" && String(text || "").trim())));
}

export function effectiveStyleSnapshot(context, shotKey) {
  return context?.shot_style_snapshots?.[shotKey] ?? context?.visual_style_snapshot ?? {};
}

export function filterStyles(items, { query = "", category = "", tab = "all", part } = {}) {
  const search = query.trim().toLocaleLowerCase();
  const result = items.filter(item => (!category || item.category === category)
    && (!part || part === "both" || item.applies_to.includes(part))
    && (tab !== "favorites" || item.favorite) && (tab !== "recent" || item.used_at)
    && (!search || [item.name, item.description, ...(item.tags || [])].join(" ").toLocaleLowerCase().includes(search)));
  return tab === "recent" ? result.sort((a, b) => b.used_at.localeCompare(a.used_at)) : result;
}

export function stylePrompt(context, shotKey, part) {
  return effectiveStyleSnapshot(context, shotKey)[`${part}_prompt`] || "";
}

export function styleValidation(value) {
  if (value?.preset === "custom" && !value.description?.trim()) return "请填写自定义风格描述";
  return "";
}

export function presetSettingsPayload(response, name, style, id) {
  const presets = response.settings.visual_style_presets || [];
  const clean = name.trim();
  if (!clean) throw new Error("请填写预设名称");
  if (presets.length >= 20) throw new Error("本账户已保存 20 个风格预设，请先移除不再使用的预设");
  if (presets.some(item => item.name.trim().toLocaleLowerCase() === clean.toLocaleLowerCase())) throw new Error("同名预设已存在，请换一个名称");
  return { revision: response.revision, settings: { ...response.settings, visual_style_presets: [...presets, { id, name: clean, style }] } };
}
