import { useState } from "react";
import { accountStorageKey } from "../accounts/account-client.js";

// Generation choices are UI preferences, not edits to the frozen creative brief.
// Each shot/batch has its own key; background refresh never resets a selection.
export function restoreGenerationPreferences(saved, defaults, defaultVersions = {}) {
  const { _defaultVersions: versions = {}, ...choices } = (
    saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {}
  );
  // Reset only fields whose default policy changed; retain all unrelated choices.
  // Subsequent explicit choices are saved with the policy version and survive reload.
  for (const [field, version] of Object.entries(defaultVersions)) {
    if (versions?.[field] !== version) delete choices[field];
  }
  return { ...defaults, ...choices };
}

export function useGenerationPreferences(key, defaults, { defaultVersions = {} } = {}) {
  key = accountStorageKey(key);
  const [state, setState] = useState({});
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Storage may be unavailable. */ }
  const value = restoreGenerationPreferences(state[key] || saved, defaults, defaultVersions);
  function update(patch) {
    setState((current) => {
      const previous = restoreGenerationPreferences(current[key] || saved, defaults, defaultVersions);
      const next = { ...previous, ...(typeof patch === "function" ? patch(previous) : patch) };
      if (JSON.stringify(previous) === JSON.stringify(next)) return current;
      const stored = Object.keys(defaultVersions).length
        ? { ...next, _defaultVersions: defaultVersions } : next;
      try { localStorage.setItem(key, JSON.stringify(stored)); } catch { /* Keep in-memory preferences. */ }
      return { ...current, [key]: stored };
    });
  }
  return [value, update];
}
