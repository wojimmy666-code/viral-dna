import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const hookSource = await readFile(
  new URL("../src/video-controls/depth/useDepthControlJob.js", import.meta.url),
  "utf8",
);
const statusSource = await readFile(
  new URL("../src/video-controls/depth/DepthGenerationStatus.jsx", import.meta.url),
  "utf8",
);
const panelSource = await readFile(
  new URL("../src/video-controls/DepthControlPanel.jsx", import.meta.url),
  "utf8",
);
const workflowSource = await readFile(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const settingsSource = await readFile(
  new URL("../src/depth-settings/DepthGenerationSettings.jsx", import.meta.url),
  "utf8",
);
const settingsCss = await readFile(
  new URL("../src/depth-settings/depth-generation-settings.css", import.meta.url),
  "utf8",
);

test("depth generation uses durable background job endpoints", () => {
  assert.match(hookSource, /\/depth-controls\/shots\/\$\{shotPlanId\}\/jobs/);
  assert.match(hookSource, /\/depth-controls\/jobs\/\$\{job\.id\}/);
  assert.match(hookSource, /\/cancel/);
  assert.match(hookSource, /\/retry/);
  assert.doesNotMatch(workflowSource, /request\(`\/depth-controls\/shots\/\$\{shotDetail\.plan\.id\}`/);
});

test("depth generation never serializes React click events as job presets", () => {
  assert.match(panelSource, /onClick=\{\(\) => onCreate\?\.\(\)\}/);
  assert.match(hookSource, /function normalizePreset\(value\)/);
  assert.match(hookSource, /preset: normalizedPreset/);
});

test("depth generation status exposes progress cancel retry and diagnostics", () => {
  assert.match(statusSource, /progress_percent/);
  assert.match(statusSource, /estimated_seconds_remaining/);
  assert.match(statusSource, /取消任务/);
  assert.match(statusSource, /快速重试/);
  assert.match(statusSource, /technical_detail/);
  assert.match(statusSource, /aria-live="polite"/);
});

test("depth settings expose automatic CPU and GPU modes with a device probe", () => {
  assert.match(settingsSource, /auto: \{/);
  assert.match(settingsSource, /cpu: \{/);
  assert.match(settingsSource, /gpu: \{/);
  assert.match(settingsSource, /\/settings\/depth-generation\/probe/);
  assert.match(settingsSource, /depth_anything_v2_onnx\/installations/);
  assert.match(settingsSource, /role="radiogroup"/);
  assert.match(settingsCss, /grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(settingsCss, /@media \(max-width: 820px\)/);
});
