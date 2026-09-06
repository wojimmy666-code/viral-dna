import { useState } from "react";

// Generation choices are UI preferences, not edits to the frozen creative brief.
// Each shot/batch has its own key; background refresh never resets a selection.
export function useGenerationPreferences(key, defaults) {
  const [state, setState] = useState({});
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Storage may be unavailable. */ }
  const value = { ...defaults, ...(state[key] || saved || {}) };
  function update(patch) {
    setState((current) => {
      const previous = { ...defaults, ...(current[key] || saved || {}) };
      const next = { ...previous, ...(typeof patch === "function" ? patch(previous) : patch) };
      if (JSON.stringify(previous) === JSON.stringify(next)) return current;
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* Keep in-memory preferences. */ }
      return { ...current, [key]: next };
    });
  }
  return [value, update];
}
