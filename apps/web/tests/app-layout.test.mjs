import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildRecordBreadcrumb,
} from "../src/app-layout.js";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const appStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("keeps the primary sidebar focused on active first-phase workflows", () => {
  assert.match(appSource, /\{ id: "new-analysis", label: "新建项目", icon: Plus \}/);
  assert.match(appSource, /\{ id: "history", label: "项目", icon: Briefcase \}/);
  assert.match(appSource, /\{ id: "skills", label: "Skill 广场", icon: Compass \}/);
  assert.match(appSource, /\{ id: "assets", label: "资产库", icon: FolderOpen \}/);
  assert.match(appSource, /\{ id: "categories", label: "品类库", icon: Tag \}/);
  assert.doesNotMatch(appSource, /\{ id: "workspace", label: "工作台"/);
  assert.doesNotMatch(appSource, /\{ id: "templates", label: "提示词模板"/);
  assert.match(appSource, /\{ id: "prompts", label: "提示词", icon: TextT \}/);
});

test("keeps every project detail state full-width without the analysis side panel", () => {
  assert.doesNotMatch(appSource, /InsightsPanel/);
  assert.doesNotMatch(appStyles, /\.insights-panel/);
  assert.match(
    appStyles,
    /\.workspace-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
  );
  assert.doesNotMatch(
    appStyles,
    /\.workspace-layout\s*\{[^}]*grid-template-columns:[^;}]*(?:320px|286px)/s,
  );
});

test("keeps project creation in the sidebar and page content", () => {
  assert.match(appSource, /<Topbar[\s\S]*?hideCreate/);
  assert.match(appSource, /创建项目并开始分析/);
});

test("renders new analysis and record workspaces through separate page branches", () => {
  assert.match(appSource, /appRoute\.name === "new-analysis"/);
  assert.match(appSource, /<NewAnalysisPage>/);
  assert.match(appSource, /appRoute\.name === "record-workspace"/);
  assert.match(appSource, /<RecordWorkspacePage>/);
  assert.match(appSource, /appRoute\.name === "skill-plaza"/);
  assert.match(appSource, /appRoute\.name === "skill-workspace"/);
  assert.match(appSource, /<SkillProjectWorkspace/);
  assert.doesNotMatch(appSource, /WorkbenchHomePage/);
  assert.doesNotMatch(appSource, /!recordDetailMode\s*&&\s*\(\s*<ImportPanel/);
});

test("builds concise breadcrumbs for report, production list and project detail", () => {
  assert.deepEqual(
    buildRecordBreadcrumb("analysis").map(({ label, current }) => ({ label, current })),
    [
      { label: "项目", current: false },
      { label: "分析报告", current: true },
    ],
  );
  assert.deepEqual(
    buildRecordBreadcrumb("production").map(({ label, current }) => ({ label, current })),
    [
      { label: "项目", current: false },
      { label: "创作方案", current: true },
    ],
  );
  assert.deepEqual(
    buildRecordBreadcrumb("production", "Batch 4.1 验收方案")
      .map(({ label, current }) => ({ label, current })),
    [
      { label: "项目", current: false },
      { label: "创作方案", current: false },
      { label: "Batch 4.1 验收方案", current: true },
    ],
  );
});
