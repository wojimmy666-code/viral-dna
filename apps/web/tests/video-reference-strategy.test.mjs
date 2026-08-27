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

test("treats the original shot as the only input for depth generation", () => {
  assert.match(panelSource, /从原始分镜生成深度视频/);
  assert.match(panelSource, /唯一输入：原始视频/);
  assert.match(panelSource, /不使用人物身份或外观资产/);
  assert.match(panelSource, /无需人物或场景资产/);
  assert.match(panelSource, /className="depth-source-note"/);
  assert.match(panelSource, /activeDepth/);
  assert.match(panelSource, /depth_control_assets/);
  assert.doesNotMatch(panelSource, /managedAssetBinding|appearanceCount|onOpenManagedAssets|选择托管演员/);
});

test("keeps one depth section collapsed by default without nesting another disclosure", () => {
  assert.match(workspaceSource, /useState\(false\)[\s\S]*className="shot-video-depth-input-details"/);
  assert.match(workspaceSource, /<summary><span>深度视频<\/span><small>仅使用原始分镜生成/);
  assert.doesNotMatch(panelSource, /<details className="depth-control-advanced"/);
  assert.match(panelSource, /sourceVideoUrl/);
  assert.match(panelSource, /thumbnail: true/);
  assert.match(panelSource, /<video/);
});

test("keeps managed actor validation in final video generation only", () => {
  assert.match(workspaceSource, /managedIdentityRequired && !managedAssetBinding/);
  assert.match(workspaceSource, /当前模型不接收原始真人身份素材，请先绑定 Provider 托管演员/);
  assert.doesNotMatch(workspaceSource, /\/video-references\/shots\/\$\{plan\.id\}\/strategy/);
  assert.match(workspaceSource, /if \(!plan\?\.id \|\| !usesDepthControl\)/);
  assert.match(panelSource, /engine\?\.available \? \(\s*!generationRunning && \(/);
  assert.doesNotMatch(panelSource, /disabled=\{busy \|\| generationRunning\}/);
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

test("uses a compact responsive source note without allowing labels to overflow", () => {
  assert.match(panelStyles, /\.depth-source-note\s*\{[^}]*grid-template-columns:\s*20px minmax\(0, 1fr\) auto/s);
  assert.match(panelStyles, /\.depth-reference-copy\s*\{[^}]*min-width:\s*0/s);
  assert.match(panelStyles, /text-overflow:\s*ellipsis/);
  assert.match(panelStyles, /@container \(max-width: 760px\)/);
  assert.match(panelStyles, /@container \(max-width: 520px\)[\s\S]*\.depth-source-note/s);
});

test("does not retain legacy white-model or DWPose compatibility hooks", () => {
  const combined = `${panelSource}\n${workspaceSource}\n${workflowSource}`;
  assert.doesNotMatch(combined, /reference_proxy|ReferenceProxy|DWPose|pose_proxy|motion_proxy/);
  assert.doesNotMatch(combined, /白模/);
});
