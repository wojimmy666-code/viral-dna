// Keep the displayed input mode and the submitted request in agreement.
export function imageBindingsForDraft(plan, beat, draft) {
  const bindings = draft.referenceBindings || [];
  if (plan?.source_kind !== "skill_generated" && (plan?.visual_beats || []).length <= 1) return bindings;
  const ids = new Set((draft.imagePromptMentions || beat?.image_prompt_mentions || []).map(item => item.reference_asset_id));
  return bindings.filter(item => ids.has(item.reference_asset_id));
}

export function resolveImageInputMode({ inputMode, sourceUrl = "", baseImageId = "", referenceCount = 0 }) {
  // An explicitly selected but unavailable base stays in edit mode and must error.
  if (inputMode === "keyframe_edit" && (sourceUrl || baseImageId)) return "keyframe_edit";
  return referenceCount > 0 ? "reference_to_image" : "text_to_image";
}

export function imageBaseCandidateId(inputMode, baseImageId) {
  return inputMode === "keyframe_edit" && baseImageId && !["source", "select"].includes(baseImageId) ? baseImageId : null;
}
