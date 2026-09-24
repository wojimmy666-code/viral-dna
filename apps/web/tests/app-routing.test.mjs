import assert from "node:assert/strict";
import test from "node:test";
import { appHandler } from "./helpers/app-handlers.mjs";

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

function entryScope() {
  const location = { key: "list", pathname: "/projects", state: null };
  const scope = {
    records: [{ id: "record-1", kind: "analysis" }, { id: "skill-1", kind: "skill" }],
    location, routeLocationRef: { current: location }, projectEntryRequestIdRef: { current: 0 },
    recordWorkspacePath, skillProjectWorkspacePath,
    events: [], historyError: "", mode: "analysis", target: null,
    flushAccountDrafts: async () => { scope.events.push("flush"); },
    loadRecordWorkspace: async () => { scope.events.push("protected-read"); throw new Error("当前项目为只读，请先取得编辑权"); },
    navigate: (path, options) => { scope.navigation = { path, options }; scope.events.push("navigate"); },
    window: { scrollTo() {} },
    setHistoryError: message => { scope.historyError = message; },
    showNotice: notice => { scope.notice = notice; },
    setRecordWorkspaceMode: mode => { scope.mode = mode; },
    setNotificationTarget: target => { scope.target = target; },
    setNotificationOpen() {}, markNotificationRead: async () => {},
  };
  scope.openHistoryRecord = appHandler("openHistoryRecord", scope);
  return scope;
}

test("opening a project after restart navigates before any protected detail request", async () => {
  const scope = entryScope();
  assert.ok(await scope.openHistoryRecord("record-1"));
  assert.equal(scope.navigation.path, "/projects/record-1");
  assert.deepEqual(scope.events, ["flush", "navigate"]);
  assert.equal(scope.historyError, "");
});

test("Skill and notification-only projects use their route without a detail prefetch", async () => {
  for (const [id, path] of [["skill-1", "/projects/skill-1/skill"], ["not-in-current-page", "/projects/not-in-current-page"]]) {
    const scope = entryScope();
    assert.ok(await scope.openHistoryRecord(id));
    assert.equal(scope.navigation.path, path);
    assert.deepEqual(scope.events, ["flush", "navigate"]);
  }
});

test("project entry preserves drafts and does not navigate after a failed save", async () => {
  const scope = entryScope();
  scope.flushAccountDrafts = async () => { throw new Error("草稿保存失败"); };
  assert.equal(await scope.openHistoryRecord("record-1"), null);
  assert.equal(scope.navigation, undefined);
  assert.match(scope.historyError, /草稿保存失败/);
});

test("a delayed project entry cannot overtake newer navigation", async () => {
  let finish;
  const scope = entryScope();
  scope.flushAccountDrafts = () => new Promise(resolve => { finish = resolve; });
  const pending = scope.openHistoryRecord("record-1");
  scope.routeLocationRef.current = { key: "assets", pathname: "/assets" };
  finish();
  assert.equal(await pending, null);
  assert.equal(scope.navigation, undefined);
});

test("the production-list entry survives the lease boundary through router state", async () => {
  const scope = entryScope();
  await appHandler("openHistoryProductions", scope)("record-1");
  assert.deepEqual(scope.navigation.options.state.projectEntry, { recordId: "record-1", mode: "production", target: null });
  scope.location = { state: scope.navigation.options.state };
  appHandler("restoreRecordEntry", scope)("record-1");
  assert.equal(scope.mode, "production");
  assert.equal(scope.target, null);
});

test("notification targets survive project entry and never leak to a different record", async () => {
  const scope = entryScope();
  await appHandler("openNotificationAction", scope)({ id: "notice-1", action_kind: "production_shot", action_payload: { record_id: "record-1", project_id: "production-1", shot_plan_id: "shot-1", candidate_id: "candidate-1", step: "shot_videos" } });
  const entry = scope.navigation.options.state.projectEntry;
  assert.equal(entry.mode, "production");
  assert.equal(entry.target.shotPlanId, "shot-1");
  assert.equal(entry.target.candidateId, "candidate-1");
  scope.location = { state: { projectEntry: entry } };
  const restore = appHandler("restoreRecordEntry", scope);
  restore("another-record");
  assert.equal(scope.target, null);
  restore("record-1");
  assert.equal(scope.target, entry.target);
  assert.equal(scope.mode, "production");
});

test("loading details after the lease does not erase the requested production destination", () => {
  const scope = entryScope();
  const target = { recordId: "record-1", projectId: "production-1", shotPlanId: "shot-1", token: "notification-1" };
  scope.location = { state: { projectEntry: { recordId: "record-1", mode: "production", target } } };
  scope.window.location = { search: "" };
  scope.resetProductionWorkspace = () => { scope.mode = "analysis"; scope.target = null; };
  scope.savedWorkspaceLocation = () => ({});
  scope.restoreRecordEntry = appHandler("restoreRecordEntry", scope);
  scope.loadProductions = async () => [];
  for (const setter of ["setVideo", "setAnalysisVersions", "setAnalysis", "setReport", "setReplacementVersion", "setActiveShotId", "setActiveReportTab"]) scope[setter] = () => {};
  appHandler("applyRecordWorkspaceDetail", scope)({ record: { id: "record-1" }, analyses: [] });
  assert.equal(scope.mode, "production");
  assert.equal(scope.target, target);
});
