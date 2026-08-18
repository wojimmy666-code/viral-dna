import assert from "node:assert/strict";
import test from "node:test";

import {
  pathForNav,
  recordWorkspacePath,
  resolveAppRoute,
} from "../src/app-routing.js";

test("maps first-phase navigation to independent page URLs", () => {
  assert.equal(pathForNav("workspace"), "/workbench");
  assert.equal(pathForNav("new-analysis"), "/analyses/new");
  assert.equal(pathForNav("history"), "/records");
  assert.equal(pathForNav("assets"), "/assets");
  assert.equal(pathForNav("platform-connections"), "/settings/platform-connections");
  assert.equal(pathForNav("settings"), "/settings/profile");
  assert.equal(pathForNav("admin"), "/admin/providers");
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
});
test("resolves new analysis and record workspaces as different pages", () => {
  assert.deepEqual(resolveAppRoute("/analyses/new"), {
    name: "new-analysis",
    activeNav: "new-analysis",
    recordId: "",
  });
  assert.deepEqual(resolveAppRoute("/workbench/records/record-1"), {
    name: "record-workspace",
    activeNav: "workspace",
    recordId: "record-1",
  });
  assert.equal(recordWorkspacePath("记录 1"), "/workbench/records/%E8%AE%B0%E5%BD%95%201");
});

test("uses the workbench home for root and explicit workbench paths", () => {
  assert.equal(resolveAppRoute("/").name, "workbench-home");
  assert.equal(resolveAppRoute("/workbench/").name, "workbench-home");
  assert.equal(resolveAppRoute("/missing").name, "not-found");
});
