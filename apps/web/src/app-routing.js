const NAV_PATHS = Object.freeze({
  workspace: "/workbench",
  "new-analysis": "/analyses/new",
  history: "/records",
  assets: "/assets",
  "platform-connections": "/settings/platform-connections",
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
  if (normalized === NAV_PATHS["platform-connections"]) {
    return {
      name: "platform-connections",
      activeNav: "platform-connections",
      recordId: "",
    };
  }
  return { name: "not-found", activeNav: "workspace", recordId: "" };
}
