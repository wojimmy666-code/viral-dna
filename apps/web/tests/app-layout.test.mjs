import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildRecordBreadcrumb,
  isRecordDetailView,
  shouldShowTopbarCreate,
} from "../src/app-layout.js";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const appStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("keeps the primary sidebar focused on active first-phase workflows", () => {
  assert.match(appSource, /\{ id: "assets", label: "资产库", icon: FolderOpen \}/);
  assert.match(appSource, /\{ id: "categories", label: "品类库", icon: Tag \}/);
  assert.doesNotMatch(appSource, /\{ id: "templates", label: "提示词模板"/);
  assert.match(appSource, /\{ id: "prompts", label: "提示词", icon: TextT \}/);
});

test("uses a focused layout for analysis reports and production plans", () => {
  const report = { analysis_id: "analysis-1" };

  assert.equal(isRecordDetailView("workspace", report), true);
  assert.equal(isRecordDetailView("new-analysis", report), false);
  assert.equal(isRecordDetailView("history", report), false);
  assert.equal(isRecordDetailView("workspace", null), false);
});

test("keeps every workbench state full-width without the analysis side panel", () => {
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

test("shows the topbar create action only on the workbench home", () => {
  const report = { analysis_id: "analysis-1" };

  assert.equal(shouldShowTopbarCreate("workspace", null), true);
  assert.equal(shouldShowTopbarCreate("new-analysis", null), false);
  assert.equal(shouldShowTopbarCreate("new-analysis", report), false);
  assert.equal(shouldShowTopbarCreate("history", null), false);
  assert.equal(shouldShowTopbarCreate("assets", null), false);
  assert.equal(shouldShowTopbarCreate("platform-connections", null), false);
  assert.equal(shouldShowTopbarCreate("workspace", report), false);
});

test("renders new analysis and record workspaces through separate page branches", () => {
  assert.match(appSource, /appRoute\.name === "new-analysis"/);
  assert.match(appSource, /<NewAnalysisPage>/);
  assert.match(appSource, /appRoute\.name === "record-workspace"/);
  assert.match(appSource, /<RecordWorkspacePage>/);
  assert.doesNotMatch(appSource, /!recordDetailMode\s*&&\s*\(\s*<ImportPanel/);
});

test("builds concise breadcrumbs for report, production list and project detail", () => {
  assert.deepEqual(
    buildRecordBreadcrumb("analysis").map(({ label, current }) => ({ label, current })),
    [
      { label: "工作台", current: false },
      { label: "分析记录", current: false },
      { label: "分析报告", current: true },
    ],
  );
  assert.deepEqual(
    buildRecordBreadcrumb("production").map(({ label, current }) => ({ label, current })),
    [
      { label: "工作台", current: false },
      { label: "分析记录", current: false },
      { label: "创作方案", current: true },
    ],
  );
  assert.deepEqual(
    buildRecordBreadcrumb("production", "Batch 4.1 验收方案")
      .map(({ label, current }) => ({ label, current })),
    [
      { label: "工作台", current: false },
      { label: "分析记录", current: false },
      { label: "创作方案", current: false },
      { label: "Batch 4.1 验收方案", current: true },
    ],
  );
});
