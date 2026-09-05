export const SIDEBAR_PREFERENCE_KEY = "viral-dna:sidebar-collapsed:v1";

export function sidebarProjectKey(route) {
  if (!["record-workspace", "skill-workspace"].includes(route?.name) || !route.recordId) return "";
  return `${route.name}:${route.recordId}`;
}

export function readSidebarPreference(storage) {
  try {
    return storage?.getItem(SIDEBAR_PREFERENCE_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveSidebarPreference(storage, collapsed) {
  try {
    storage?.setItem(SIDEBAR_PREFERENCE_KEY, String(Boolean(collapsed)));
  } catch {
    // A blocked/full browser store must not disable navigation.
  }
}

export function createSidebarState(route, preferredCollapsed = false) {
  return { projectKey: sidebarProjectKey(route), preferredCollapsed, projectCollapsed: true };
}

export function reconcileSidebarRoute(state, route) {
  const projectKey = sidebarProjectKey(route);
  return projectKey === state.projectKey ? state : { ...state, projectKey, projectCollapsed: true };
}

export function isSidebarCollapsed(state) {
  return state.projectKey ? state.projectCollapsed : state.preferredCollapsed;
}

export function toggleSidebarState(state) {
  return state.projectKey
    ? { ...state, projectCollapsed: !state.projectCollapsed }
    : { ...state, preferredCollapsed: !state.preferredCollapsed };
}
