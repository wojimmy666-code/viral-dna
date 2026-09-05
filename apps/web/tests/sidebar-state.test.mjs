import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { resolveAppRoute } from "../src/app-routing.js";
import {
  SIDEBAR_PREFERENCE_KEY, createSidebarState, isSidebarCollapsed, readSidebarPreference,
  reconcileSidebarRoute, saveSidebarPreference, sidebarProjectKey, toggleSidebarState,
} from "../src/app-sidebar/sidebar-state.js";

const route = resolveAppRoute;
const move = (state, path) => reconcileSidebarRoute(state, route(path));

test("only actual source and Skill projects automatically collapse", () => {
  for (const path of ["/projects/a", "/projects/a/skill"]) {
    assert.ok(sidebarProjectKey(route(path)));
    assert.equal(isSidebarCollapsed(createSidebarState(route(path))), true);
  }
  for (const path of ["/projects", "/projects/new", "/projects/archived", "/projects/trash", "/skills", "/skills/product/start", "/assets", "/category-profiles", "/settings/profile", "/missing"]) {
    assert.equal(sidebarProjectKey(route(path)), "", path);
    assert.equal(isSidebarCollapsed(createSidebarState(route(path))), false, path);
  }
});

test("manual project expansion survives same-project rerenders and workspace step changes", () => {
  let state = createSidebarState(route("/projects/a/skill"));
  state = toggleSidebarState(state);
  assert.equal(isSidebarCollapsed(state), false);
  const previous = state;
  state = reconcileSidebarRoute(state, { ...route("/projects/a/skill"), step: "images", shotId: "b" });
  assert.equal(state, previous);
  assert.equal(isSidebarCollapsed(state), false);
});

test("a different project, project type or re-entry collapses again", () => {
  for (const path of ["/projects/b", "/projects/a/skill"]) {
    const expanded = toggleSidebarState(createSidebarState(route("/projects/a")));
    assert.equal(isSidebarCollapsed(move(expanded, path)), true);
  }
  const expanded = toggleSidebarState(createSidebarState(route("/projects/a")));
  const outside = move(expanded, "/skills");
  assert.equal(isSidebarCollapsed(move(outside, "/projects/a")), true);
});

test("leaving a project restores both expanded and collapsed ordinary-page preferences", () => {
  for (const preferred of [false, true]) {
    let state = createSidebarState(route("/projects"), preferred);
    state = move(state, "/projects/a");
    assert.equal(isSidebarCollapsed(state), true);
    state = toggleSidebarState(state);
    assert.equal(state.preferredCollapsed, preferred);
    state = move(state, "/assets");
    assert.equal(isSidebarCollapsed(state), preferred);
    state = move(state, "/projects/trash");
    assert.equal(isSidebarCollapsed(state), preferred);
  }
});

test("direct links and full reload reset only temporary project expansion", () => {
  const expanded = toggleSidebarState(createSidebarState(route("/projects/a"), true));
  const refreshed = createSidebarState(route("/projects/a"), expanded.preferredCollapsed);
  assert.equal(isSidebarCollapsed(refreshed), true);
  assert.equal(isSidebarCollapsed(move(refreshed, "/skills")), true);
});

test("ordinary-page toggle survives navigation and browser preference reload", () => {
  const data = new Map();
  const storage = { getItem: (key) => data.get(key), setItem: (key, value) => data.set(key, value) };
  let state = toggleSidebarState(createSidebarState(route("/projects")));
  saveSidebarPreference(storage, state.preferredCollapsed);
  assert.equal(data.get(SIDEBAR_PREFERENCE_KEY), "true");
  state = createSidebarState(route("/skills"), readSidebarPreference(storage));
  assert.equal(isSidebarCollapsed(state), true);
  assert.equal(isSidebarCollapsed(move(state, "/assets")), true);
});

test("unavailable, invalid or full browser storage cannot break navigation", () => {
  const denied = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("full"); } };
  assert.equal(readSidebarPreference(denied), false);
  assert.equal(readSidebarPreference(null), false);
  assert.equal(readSidebarPreference({ getItem: () => "invalid" }), false);
  assert.doesNotThrow(() => saveSidebarPreference(denied, true));
});

test("sidebar layout never keys or replaces the project body and exposes accessible controls", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const sidebar = readFileSync(new URL("../src/app-sidebar/AppSidebar.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../src/app-sidebar/app-sidebar.css", import.meta.url), "utf8");
  const baseCss = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(app, /<div className="app-body">/);
  assert.doesNotMatch(app, /key=\{[^}]*sidebar/i);
  assert.match(app, /aria-label="打开导航"/);
  assert.match(sidebar, /"展开侧边栏" : "收起侧边栏"/);
  assert.match(sidebar, /popover="auto"/);
  assert.match(sidebar, /dialog\.showModal\(\)/);
  assert.match(sidebar, /onCancel=\{onCloseMobile\}/);
  assert.match(sidebar, /aria-label="选择项目范围"/);
  assert.match(sidebar, /event\.shiftKey && document\.activeElement === first/);
  assert.match(css, /grid-template-columns: 72px minmax\(0, 1fr\)/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /min-height: 44px/);
  assert.doesNotMatch(baseCss, /\.topbar\.focus-mode\s*\{\s*display:\s*none/);
});
