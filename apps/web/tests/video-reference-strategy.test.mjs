import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panelSource = readFileSync(
  new URL("../src/video-controls/DepthControlPanel.jsx", import.meta.url),
  "utf8",
);
const panelStyles = readFileSync(
  new URL("../src/video-controls/depth-control.css", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const workflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);

test("renders identity, appearance and full-scene depth as separate sources", () => {
  assert.match(panelSource, /className="depth-source-grid"/);
  assert.match(panelSource, /managedAssetBinding/);
  assert.match(panelSource, /appearanceCount/);
  assert.match(panelSource, /activeDepth/);
  assert.match(panelSource, /full_scene_depth_video|depth_control_assets/);
});

test("keeps depth controls advanced and collapsed by default", () => {
  assert.match(panelSource, /<details className="depth-control-advanced">/);
  assert.doesNotMatch(panelSource, /<details className="depth-control-advanced" open/);
  assert.match(panelSource, /sourceVideoUrl/);
  assert.match(panelSource, /thumbnail: true/);
  assert.match(panelSource, /<video/);
});

test("persists depth assets through dedicated create toggle and delete endpoints", () => {
  assert.match(workflowSource, /async function createDepthControl/);
  assert.match(workflowSource, /\/depth-controls\/shots\/\$\{shotDetail\.plan\.id\}/);
  assert.match(workflowSource, /async function toggleDepthControl/);
  assert.match(workflowSource, /async function deleteDepthControl/);
  assert.match(workflowSource, /onCreateDepthControl=\{createDepthControl\}/);
  assert.match(workflowSource, /onDeleteDepthControl=\{deleteDepthControl\}/);
  assert.match(workflowSource, /onToggleDepthControl=\{toggleDepthControl\}/);
});

test("loads the real depth engine capability instead of a proxy engine", () => {
  assert.match(workspaceSource, /request\("\/depth-controls\/engines"\)/);
  assert.match(workspaceSource, /<DepthControlPanel/);
  assert.match(panelSource, /video_depth_anything/);
  assert.match(panelSource, /Video Depth Anything Small/);
});

test("installs the isolated depth engine with visible progress", () => {
  assert.match(workspaceSource, /depth-controls\/engines\/\$\{encodeURIComponent\(engineName\)\}\/installations/);
  assert.match(workspaceSource, /pollDepthEngineInstallation/);
  assert.match(panelSource, /安装深度引擎/);
  assert.match(panelSource, /<progress[\s\S]*aria-label="深度引擎安装进度"[\s\S]*max="100"/);
  assert.match(panelStyles, /\.depth-engine-installation/);
});

test("uses responsive grids without allowing source labels to overflow", () => {
  assert.match(panelStyles, /\.depth-source-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/s);
  assert.match(panelStyles, /\.depth-reference-copy\s*\{[^}]*min-width:\s*0/s);
  assert.match(panelStyles, /text-overflow:\s*ellipsis/);
  assert.match(panelStyles, /@container \(max-width: 760px\)/);
});

test("does not retain legacy white-model or DWPose compatibility hooks", () => {
  const combined = `${panelSource}\n${workspaceSource}\n${workflowSource}`;
  assert.doesNotMatch(combined, /reference_proxy|ReferenceProxy|DWPose|pose_proxy|motion_proxy/);
  assert.doesNotMatch(combined, /白模/);
});
