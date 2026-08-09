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

test("shows compact progress, validated history and downloadable artifacts", () => {
  assert.match(exportSource, /export-jobs\/\$\{activeJob\.id\}/);
  assert.match(exportSource, /validation_summary/);
  assert.match(exportSource, /artifact = "download"/);
  assert.match(exportSource, /download\(job, "manifest"\)/);
  assert.match(exportSource, /onNotificationsChanged/);
  assert.match(workflowStyles, /\.production-export-progress\s*\{/);
  assert.match(workflowStyles, /\.production-export-video video\s*\{[^}]+object-fit:\s*contain/s);
});

test("keeps the final player canvas on the exported media aspect ratio", () => {
  assert.match(exportSource, /"--export-ratio": latestSuccess\.preview_width \/ latestSuccess\.preview_height/);
  assert.match(workflowStyles, /aspect-ratio:\s*var\(--export-aspect\)/);
  assert.match(workflowStyles, /width:\s*min\(100%, calc\(var\(--export-stage-height\) \* var\(--export-ratio\)\)\)/);
  assert.match(workflowStyles, /\.production-export-video video\s*\{[^}]+position:\s*absolute[^}]+min-height:\s*0/s);
});
