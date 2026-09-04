import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const exportSource = readFileSync(
  new URL("../src/ProductionExportWorkspace.jsx", import.meta.url),
  "utf8",
);
const workflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const productionUiSource = readFileSync(
  new URL("../src/production-ui.js", import.meta.url),
  "utf8",
);
const workflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);

test("unlocks a dedicated final export workflow step after editing", () => {
  assert.match(productionUiSource, /id: "export", label: "导出成片"/);
  assert.doesNotMatch(productionUiSource, /id: "export"[^\n]+locked: true/);
  assert.match(workflowSource, /<ProductionExportWorkspace/);
  assert.match(workflowSource, /project\.active_step === "editing"/);
});

test("binds final renders to an immutable timeline revision and exposes presets", () => {
  assert.match(exportSource, /expected_revision_id: timeline\.revision_id/);
  assert.match(exportSource, /value: "720p"/);
  assert.match(exportSource, /value: "1080p"/);
  assert.match(exportSource, /value: "project"/);
  assert.match(exportSource, /value: "burned"/);
  assert.match(exportSource, /value: "embedded"/);
  assert.match(exportSource, /value: "none"/);
  assert.match(exportSource, /timeline\/final-renders/);
});

test("locks Skill exports to the resolution frozen in the run contract", () => {
  assert.match(workflowSource, /lockedExportResolution = null/);
  assert.match(workflowSource, /lockedResolution=\{lockedExportResolution\}/);
  assert.match(exportSource, /lockedResolution = null/);
  assert.match(exportSource, /normalizeLockedResolution\(lockedResolution\)/);
  assert.match(exportSource, /disabled=\{Boolean\(lockedResolution\)\}/);
  assert.match(exportSource, /清晰度（项目锁定）/);
});

test("shows compact progress and downloadable render history", () => {
  assert.match(exportSource, /export-jobs\/\$\{activeJob\.id\}/);
  assert.match(exportSource, /export-jobs\/\$\{job\.id\}\/download/);
  assert.doesNotMatch(exportSource, /validation_summary|manifest_url|"manifest"|>清单</);
  assert.match(exportSource, /onNotificationsChanged/);
  assert.match(workflowStyles, /\.production-export-progress\s*\{/);
  assert.match(workflowStyles, /\.production-export-video video\s*\{[^}]+object-fit:\s*contain/s);
});

test("keeps project settings, editing preview and final export free of redundant metadata", () => {
  assert.doesNotMatch(
    workflowSource,
    /修改会创建新版本。已保存的历史版本保持不变。|用于区分人物替换版、产品版或不同成本方案。/,
  );
  assert.doesNotMatch(
    exportSource,
    /Batch 4\.6\.6|冻结时间线|每次导出绑定当前时间线版本|输出尺寸|MP4 · H\.264 · AAC|旧产物不会被新导出覆盖|时间线 v|校验通过|SHA-256 已记录/,
  );
  assert.doesNotMatch(workflowStyles, /\.production-export-(?:summary|validation)\s*\{/);
  assert.match(exportSource, /<strong>导出设置<\/strong>/);
  assert.match(exportSource, /<strong>导出历史<\/strong>/);
  assert.match(exportSource, /<DownloadSimple size=\{16\} \/>下载/);
});

test("keeps the final player canvas on the exported media aspect ratio", () => {
  assert.match(exportSource, /"--export-ratio": latestSuccess\.preview_width \/ latestSuccess\.preview_height/);
  assert.match(workflowStyles, /aspect-ratio:\s*var\(--export-aspect\)/);
  assert.match(workflowStyles, /width:\s*min\(100%, calc\(var\(--export-stage-height\) \* var\(--export-ratio\)\)\)/);
  assert.match(workflowStyles, /\.production-export-video video\s*\{[^}]+position:\s*absolute[^}]+min-height:\s*0/s);
});
