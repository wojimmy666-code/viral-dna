import assert from "node:assert/strict";
import test from "node:test";

import {
  pathForNav,
  projectLifecyclePath,
  recordWorkspacePath,
  resolveAppRoute,
  skillProjectWorkspacePath,
} from "../src/app-routing.js";

test("maps first-phase navigation to independent page URLs", () => {
  assert.equal(pathForNav("new-analysis"), "/projects/new");
  assert.equal(pathForNav("history"), "/projects");
  assert.equal(pathForNav("skills"), "/skills");
  assert.equal(pathForNav("assets"), "/assets");
  assert.equal(pathForNav("categories"), "/category-profiles");
  assert.equal(pathForNav("platform-connections"), "/settings/platform-connections");
  assert.equal(pathForNav("settings"), "/settings/profile");
  assert.equal(pathForNav("admin"), "/admin/providers");
  assert.equal(pathForNav("unknown"), "/projects");
});

test("resolves platform Skill discovery, start and project workspace routes", () => {
  assert.equal(resolveAppRoute("/skills").name, "skill-plaza");
  assert.deepEqual(resolveAppRoute("/skills/cinematic-product-story"), {
    name: "skill-detail",
    activeNav: "skills",
    recordId: "",
    skillSlug: "cinematic-product-story",
  });
  assert.equal(
    resolveAppRoute("/skills/cinematic-product-story/start").name,
    "skill-start",
  );
  assert.deepEqual(resolveAppRoute("/projects/project-1/skill"), {
    name: "skill-workspace",
    activeNav: "project-detail",
    recordId: "project-1",
    skillSlug: "",
  });
  assert.equal(skillProjectWorkspacePath("项目 1"), "/projects/%E9%A1%B9%E7%9B%AE%201/skill");
});

test("maps project lifecycle navigation to canonical URLs", () => {
  assert.equal(projectLifecyclePath("active"), "/projects");
  assert.equal(projectLifecyclePath("archived"), "/projects/archived");
  assert.equal(projectLifecyclePath("trashed"), "/projects/trash");
});

test("resolves the account category library as a primary page", () => {
  assert.deepEqual(resolveAppRoute("/category-profiles"), {
    name: "category-profiles",
    activeNav: "categories",
    recordId: "",
  });
});

test("keeps user settings and platform administration on separate route trees", () => {
  assert.deepEqual(resolveAppRoute("/settings/generation"), {
    name: "user-settings",
    activeNav: "settings",
    recordId: "",
    settingsSection: "generation",
  });
  assert.deepEqual(resolveAppRoute("/admin/media"), {
    name: "platform-admin",
    activeNav: "admin",
    recordId: "",
    adminSection: "media",
  });
  assert.equal(resolveAppRoute("/admin/skills").adminSection, "skills");
});
test("resolves new projects and project details as different pages", () => {
  assert.deepEqual(resolveAppRoute("/projects/new"), {
    name: "new-analysis",
    activeNav: "new-analysis",
    recordId: "",
  });
  assert.deepEqual(resolveAppRoute("/projects/record-1"), {
    name: "record-workspace",
    activeNav: "project-detail",
    recordId: "record-1",
  });
  assert.equal(recordWorkspacePath("项目 1"), "/projects/%E9%A1%B9%E7%9B%AE%201");
});

test("resolves each project lifecycle as an independent page", () => {
  assert.equal(resolveAppRoute("/projects").lifecycle, "active");
  assert.equal(resolveAppRoute("/projects/archived").lifecycle, "archived");
  assert.equal(resolveAppRoute("/projects/trash").lifecycle, "trashed");
});

test("redirects removed workbench and legacy record URLs", () => {
  assert.deepEqual(resolveAppRoute("/"), {
    name: "redirect",
    activeNav: "history",
    recordId: "",
    to: "/projects",
  });
  assert.equal(resolveAppRoute("/workbench/").to, "/projects");
  assert.equal(resolveAppRoute("/records").to, "/projects");
  assert.equal(resolveAppRoute("/analyses/new").to, "/projects/new");
  assert.equal(
    resolveAppRoute("/workbench/records/record-1").to,
    "/projects/record-1",
  );
  assert.equal(resolveAppRoute("/missing").name, "not-found");
});
