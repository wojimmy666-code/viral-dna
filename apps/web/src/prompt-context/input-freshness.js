// This is an advisory only; it must never participate in generation/advance guards.
export function globalPromptWasEdited(detail, values, part) {
  const key = `common_${part}_prompt`;
  const baseline = detail?.current_global_prompts?.[key];
  const previousStyle = detail?.current_global_prompts?.[`${part}_style_prompt`];
  const styleChanged = typeof previousStyle === "string" && Object.hasOwn(values || {}, "visual_style")
    && previousStyle !== stylePrompt(values, detail?.plan?.id, part);
  return styleChanged || (typeof baseline === "string" && typeof values?.[key] === "string"
    && baseline !== values[key]);
}
import { stylePrompt } from "../visual-styles/visual-style.js";
