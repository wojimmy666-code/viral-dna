import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const WORKSPACE_PAGES_URL = new URL("../src/WorkspacePages.jsx", import.meta.url);
const DURATION_HELPERS_URL = new URL("../src/analysis-import-ui.js", import.meta.url);

test("analysis import accepts at most two minutes", async () => {
  const {
    ANALYSIS_VIDEO_DURATION_ERROR,
    MAX_ANALYSIS_VIDEO_SECONDS,
    validateAnalysisVideoDuration,
  } = await import(DURATION_HELPERS_URL);

  assert.equal(MAX_ANALYSIS_VIDEO_SECONDS, 120);
  assert.equal(validateAnalysisVideoDuration(120).valid, true);
  assert.equal(validateAnalysisVideoDuration(120.001).valid, false);
  assert.equal(validateAnalysisVideoDuration(120.001).message, ANALYSIS_VIDEO_DURATION_ERROR);
  assert.equal(validateAnalysisVideoDuration(null).valid, true);
});

test("new analysis page keeps only task-relevant import copy", async () => {
  const app = await readFile(APP_URL, "utf8");
  const page = await readFile(WORKSPACE_PAGES_URL, "utf8");

  assert.match(app, /最长 2 分钟/);
  assert.doesNotMatch(app, /最长 5 分钟|原视频与内容结构|<span className="eyebrow">新建任务/);
  assert.doesNotMatch(page, /导入一个本地视频或公开链接，创建独立的拆解任务/);
});
