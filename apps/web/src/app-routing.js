const NAV_PATHS = Object.freeze({
  workspace: "/workbench",
  "new-analysis": "/analyses/new",
  history: "/records",
  assets: "/assets",
  categories: "/category-profiles",
  "platform-connections": "/settings/platform-connections",
  settings: "/settings/profile",
  admin: "/admin/providers",
});

function normalizePathname(pathname) {
  const normalized = `/${String(pathname || "").replace(/^\/+|\/+$/g, "")}`;
  return normalized === "/" ? "/" : normalized;
}
export function pathForNav(navId) {
  return NAV_PATHS[navId] || NAV_PATHS.workspace;
}

export function recordWorkspacePath(recordId) {
  const normalizedId = String(recordId || "").trim();
  return normalizedId
    ? `/workbench/records/${encodeURIComponent(normalizedId)}`
    : NAV_PATHS.workspace;
}

export function resolveAppRoute(pathname) {
  const normalized = normalizePathname(pathname);
  const recordMatch = normalized.match(/^\/workbench\/records\/([^/]+)$/);
  if (recordMatch) {
    return {
      name: "record-workspace",
      activeNav: "workspace",
      recordId: decodeURIComponent(recordMatch[1]),
    };
  }
  if (normalized === "/" || normalized === NAV_PATHS.workspace) {
    return { name: "workbench-home", activeNav: "workspace", recordId: "" };
  }
  if (normalized === NAV_PATHS["new-analysis"]) {
    return { name: "new-analysis", activeNav: "new-analysis", recordId: "" };
  }
  if (normalized === NAV_PATHS.history) {
    return { name: "history", activeNav: "history", recordId: "" };
  }
  if (normalized === NAV_PATHS.assets) {
    return { name: "assets", activeNav: "assets", recordId: "" };
  }
  if (normalized === NAV_PATHS.categories) {
    return { name: "category-profiles", activeNav: "categories", recordId: "" };
  }
  if (normalized === NAV_PATHS["platform-connections"]) {
    return {
      name: "platform-connections",
      activeNav: "platform-connections",
      recordId: "",
    };
  }
  const settingsMatch = normalized.match(/^\/settings\/(profile|generation|device)$/);
  if (settingsMatch) {
    return {
      name: "user-settings",
      activeNav: "settings",
      recordId: "",
      settingsSection: settingsMatch[1],
    };
  }
  if (normalized === "/settings") {
    return {
      name: "user-settings",
      activeNav: "settings",
      recordId: "",
      settingsSection: "profile",
    };
  }
  const adminMatch = normalized.match(/^\/admin\/(providers|models|media|runtime)$/);
  if (adminMatch || normalized === "/admin") {
    return {
      name: "platform-admin",
      activeNav: "admin",
      recordId: "",
      adminSection: adminMatch?.[1] || "providers",
    };
  }
  return { name: "not-found", activeNav: "workspace", recordId: "" };
}
