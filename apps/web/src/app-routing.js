const NAV_PATHS = Object.freeze({
  "new-analysis": "/projects/new",
  history: "/projects",
  skills: "/skills",
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
  return NAV_PATHS[navId] || NAV_PATHS.history;
}

export function projectLifecyclePath(lifecycle) {
  if (lifecycle === "archived") return "/projects/archived";
  if (lifecycle === "trashed") return "/projects/trash";
  return NAV_PATHS.history;
}

export function recordWorkspacePath(recordId) {
  const normalizedId = String(recordId || "").trim();
  return normalizedId
    ? `/projects/${encodeURIComponent(normalizedId)}`
    : NAV_PATHS.history;
}

export function skillProjectWorkspacePath(projectId) {
  const normalizedId = String(projectId || "").trim();
  return normalizedId
    ? `/projects/${encodeURIComponent(normalizedId)}/skill`
    : NAV_PATHS.skills;
}

export function resolveAppRoute(pathname) {
  const normalized = normalizePathname(pathname);
  if (normalized === "/projects/new") {
    return { name: "new-analysis", activeNav: "new-analysis", recordId: "" };
  }
  if (normalized === "/projects/archived") {
    return { name: "history", activeNav: "history", recordId: "", lifecycle: "archived" };
  }
  if (normalized === "/projects/trash") {
    return { name: "history", activeNav: "history", recordId: "", lifecycle: "trashed" };
  }
  if (normalized === NAV_PATHS.history) {
    return { name: "history", activeNav: "history", recordId: "", lifecycle: "active" };
  }
  if (normalized === NAV_PATHS.skills) {
    return { name: "skill-plaza", activeNav: "skills", recordId: "", skillSlug: "" };
  }
  const skillStartMatch = normalized.match(/^\/skills\/([^/]+)\/start$/);
  if (skillStartMatch) {
    return {
      name: "skill-start",
      activeNav: "skills",
      recordId: "",
      skillSlug: decodeURIComponent(skillStartMatch[1]),
    };
  }
  const skillDetailMatch = normalized.match(/^\/skills\/([^/]+)$/);
  if (skillDetailMatch) {
    return {
      name: "skill-detail",
      activeNav: "skills",
      recordId: "",
      skillSlug: decodeURIComponent(skillDetailMatch[1]),
    };
  }
  const skillProjectMatch = normalized.match(/^\/projects\/([^/]+)\/skill$/);
  if (skillProjectMatch) {
    return {
      name: "skill-workspace",
      activeNav: "project-detail",
      recordId: decodeURIComponent(skillProjectMatch[1]),
      skillSlug: "",
    };
  }
  const recordMatch = normalized.match(/^\/projects\/([^/]+)$/);
  if (recordMatch) {
    return {
      name: "record-workspace",
      activeNav: "project-detail",
      recordId: decodeURIComponent(recordMatch[1]),
    };
  }

  const legacyRecordMatch = normalized.match(/^\/workbench\/records\/([^/]+)$/);
  if (legacyRecordMatch) {
    return {
      name: "redirect",
      activeNav: "history",
      recordId: "",
      to: recordWorkspacePath(decodeURIComponent(legacyRecordMatch[1])),
    };
  }
  if (["/", "/workbench", "/records"].includes(normalized)) {
    return { name: "redirect", activeNav: "history", recordId: "", to: NAV_PATHS.history };
  }
  if (normalized === "/analyses/new") {
    return {
      name: "redirect",
      activeNav: "new-analysis",
      recordId: "",
      to: NAV_PATHS["new-analysis"],
    };
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
  const adminMatch = normalized.match(/^\/admin\/(providers|models|media|runtime|skills)$/);
  if (adminMatch || normalized === "/admin") {
    return {
      name: "platform-admin",
      activeNav: "admin",
      recordId: "",
      adminSection: adminMatch?.[1] || "providers",
    };
  }
  return { name: "not-found", activeNav: "history", recordId: "" };
}
