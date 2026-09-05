import { useEffect, useState } from "react";
import {
  createSidebarState,
  isSidebarCollapsed,
  readSidebarPreference,
  reconcileSidebarRoute,
  saveSidebarPreference,
  toggleSidebarState,
} from "./sidebar-state.js";

function localPreferences() {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function useSidebarLayout(route) {
  const [state, setState] = useState(() => createSidebarState(route, readSidebarPreference(localPreferences())));
  const current = reconcileSidebarRoute(state, route);
  // Reconcile before children render: direct links never flash the expanded rail.
  // Only a different project identity resets the temporary project preference.
  if (current !== state) setState(current);

  useEffect(() => {
    saveSidebarPreference(localPreferences(), state.preferredCollapsed);
  }, [state.preferredCollapsed]);

  return {
    collapsed: isSidebarCollapsed(current),
    toggle: () => setState((previous) => toggleSidebarState(reconcileSidebarRoute(previous, route))),
  };
}
