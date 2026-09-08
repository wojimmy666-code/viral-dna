// This is an advisory only; it must never participate in generation/advance guards.
export function globalPromptWasEdited(detail, values, part) {
  const key = `common_${part}_prompt`;
  const baseline = detail?.current_global_prompts?.[key];
  return typeof baseline === "string" && typeof values?.[key] === "string"
    && baseline !== values[key];
}
