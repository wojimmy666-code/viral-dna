import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRecordBreadcrumb,
  isProductionDetailView,
  isRecordDetailView,
  shouldShowTopbarCreate,
} from "../src/app-layout.js";

test("uses a focused layout for analysis reports and production plans", () => {
  const report = { analysis_id: "analysis-1" };

  assert.equal(isRecordDetailView("workspace", report), true);
  assert.equal(isRecordDetailView("new-analysis", report), false);
  assert.equal(isRecordDetailView("history", report), false);
  assert.equal(isRecordDetailView("workspace", null), false);
});

test("uses a full-width production view without the analysis side panel", () => {
  const report = { analysis_id: "analysis-1" };

  assert.equal(isProductionDetailView("workspace", report, "production"), true);
  assert.equal(isProductionDetailView("workspace", report, "analysis"), false);
  assert.equal(isProductionDetailView("history", report, "production"), false);
});

test("keeps new-analysis in the workbench but removes it from records and details", () => {
  const report = { analysis_id: "analysis-1" };

  assert.equal(shouldShowTopbarCreate("workspace", null), true);
  assert.equal(shouldShowTopbarCreate("new-analysis", report), true);
  assert.equal(shouldShowTopbarCreate("history", null), false);
  assert.equal(shouldShowTopbarCreate("assets", null), false);
  assert.equal(shouldShowTopbarCreate("workspace", report), false);
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
