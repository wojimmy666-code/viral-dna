import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceSource = await readFile(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const panelSource = await readFile(
  new URL("../src/video-enhancement/VideoEnhancementPanel.jsx", import.meta.url),
  "utf8",
);
const hookSource = await readFile(
  new URL("../src/video-enhancement/useVideoEnhancement.js", import.meta.url),
  "utf8",
);
const settingsSource = await readFile(
  new URL("../src/video-enhancement/VideoEnhancementSettings.jsx", import.meta.url),
  "utf8",
);
const userSettingsSource = await readFile(
  new URL("../src/settings/UserSettingsPage.jsx", import.meta.url),
  "utf8",
);
const styles = await readFile(
  new URL("../src/video-enhancement/video-enhancement.css", import.meta.url),
  "utf8",
);

test("offers AI enhancement only for the current adopted video candidate", () => {
  assert.match(workspaceSource, /displayedCandidateApproved/);
  assert.match(workspaceSource, /plan\?\.video_status === "approved"/);
  assert.match(workspaceSource, /plan\?\.approved_video_candidate_id === displayedCandidate\.id/);
  assert.match(workspaceSource, /displayedCandidateApproved && \(/);
  assert.match(workspaceSource, /<VideoEnhancementPanel/);
});

test("keeps Real-ESRGAN work durable and explicitly selects the final version", () => {
  assert.match(hookSource, /\/video-enhancements\/candidates\/\$\{candidateId\}\/jobs/);
  assert.match(hookSource, /\/video-enhancements\/jobs\/\$\{activeView\.job\.id\}/);
  assert.match(hookSource, /\/cancel/);
  assert.match(hookSource, /\/retry/);
  assert.match(hookSource, /\/use-for-final/);
  assert.match(hookSource, /\/use-original/);
  assert.match(panelSource, /用于成片/);
  assert.match(panelSource, /成片改用原始版/);
  assert.match(panelSource, /原视频始终保留/);
  assert.match(panelSource, /可以离开此页面，任务将在后台继续/);
});

test("installs the optional engine inline without triggering an automatic download", () => {
  assert.match(panelSource, /首次使用需安装本地引擎/);
  assert.match(panelSource, /onClick=\{enhancement\.install\}/);
  assert.doesNotMatch(hookSource, /useEffect\([\s\S]{0,240}install\(/);
  assert.match(hookSource, /\/video-enhancements\/engine\/installations/);
  assert.match(hookSource, /\["succeeded", "failed"\]\.includes\(next\.status\)/);
  assert.match(panelSource, /Real-ESRGAN 本地处理，不消耗视频生成额度/);
  assert.match(panelSource, /安装位置：/);
  assert.match(settingsSource, /settings\.capability\.installation_path/);
});

test("switches the shared player between original and enhanced media", () => {
  assert.match(workspaceSource, /enhancementPreview/);
  assert.match(workspaceSource, /displayedVideoUrl/);
  assert.match(panelSource, /previewOriginal/);
  assert.match(panelSource, /previewResult/);
  assert.match(panelSource, /variant=original/);
  assert.match(panelSource, /提升到 4K 主要改善边缘与观感，不等于获得原生 4K 细节/);
});

test("disables output sizes the adopted source has already reached", () => {
  assert.match(panelSource, /sourceShortEdge/);
  assert.match(panelSource, /sourceShortEdge >= item\.shortEdge/);
  assert.match(panelSource, /disabled=\{Boolean\(runningJob\) \|\| reached\}/);
  assert.match(panelSource, /reached \? "已达到" : item\.note/);
  assert.match(panelSource, /当前视频已达到 4K，无需再次放大/);
});

test("uses the product visual system and stays responsive", () => {
  assert.match(styles, /font-size: var\(--type-label-size\)/);
  assert.match(styles, /color: var\(--text-secondary\)/);
  assert.match(styles, /background: var\(--surface-panel\)/);
  assert.match(styles, /@media \(max-width: 760px\)/);
  assert.doesNotMatch(styles, /linear-gradient|radial-gradient/);
  assert.doesNotMatch(styles, /font-size:\s*(?:10|11|12|13|14|15|16|18|20)px/);
});

test("exposes conservative enhancement defaults in user generation settings", () => {
  assert.match(userSettingsSource, /<VideoEnhancementSettings request=\{request\}/);
  assert.match(settingsSource, /1080p（推荐）/);
  assert.match(settingsSource, /自动选择 Vulkan/);
  assert.match(settingsSource, /1 个本地任务/);
  assert.match(settingsSource, /\/settings\/video-enhancement\/probe/);
  assert.match(settingsSource, /保存清晰化设置/);
});
