export const DEFAULT_TEXT_MODEL_ALIAS = "qwen37";

export const TEXT_MODEL_PURPOSES = Object.freeze({
  replicationPlan: "replication_plan",
  shotImagePrompt: "shot_image_prompt",
  videoPrompt: "video_prompt",
});

const KNOWN_MODEL_LABELS = Object.freeze({
  qwen37: "Qwen3.7 Plus",
  qwen36flash: "Qwen3.6 Flash",
});

export function textModelOptionLabel(model) {
  return model?.label || model?.display_name || model?.alias || "";
}

export function effectiveTextModelAlias(preferences, purpose) {
  const settings = preferences?.settings || preferences || {};
  return (
    settings.text_model_task_overrides?.[purpose]
    || settings.text_model_alias
    || DEFAULT_TEXT_MODEL_ALIAS
  );
}

export function effectiveTextModelLabel(preferences, purpose) {
  const alias = effectiveTextModelAlias(preferences, purpose);
  const option = (preferences?.text_models || []).find((model) => model.alias === alias);
  return textModelOptionLabel(option) || KNOWN_MODEL_LABELS[alias] || alias;
}

export function normalizeTextModelOverrides(overrides = {}) {
  return Object.fromEntries(
    Object.entries(overrides).filter(([, alias]) => Boolean(String(alias || "").trim())),
  );
}
