import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const strategySource = readFileSync(
  new URL("../src/video-references/VideoReferenceStrategyBar.jsx", import.meta.url),
  "utf8",
);
const strategyStyles = readFileSync(
  new URL("../src/video-references/video-references.css", import.meta.url),
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

test("renders model-specific identity and motion routes", () => {
  assert.match(strategySource, /policy !== "managed_required"/);
  assert.match(strategySource, /人物与动作来源/);
  assert.match(strategySource, /routeCapability\.show_motion_proxy_controls/);
  assert.match(strategySource, /strategy\?\.motion_semantics === "structural_control"/);
  assert.match(strategySource, /生成依据与中间过程/);
  assert.match(strategySource, /已回退 · 动作还原较弱/);
});

test("keeps full-width route details from crushing the strategy summary", () => {
  assert.match(
    strategyStyles,
    /\.video-reference-strategy\s*\{[^}]*flex-wrap:\s*wrap;/s,
  );
  assert.match(
    strategyStyles,
    /\.video-reference-strategy-copy\s*\{[^}]*flex:\s*1 1 320px;/s,
  );
  assert.match(
    strategyStyles,
    /\.video-reference-route-details\s*\{[^}]*flex:\s*1 0 100%;[^}]*width:\s*100%;/s,
  );
  assert.doesNotMatch(
    strategyStyles,
    /> div:not\(\.video-reference-strategy-actions\)/,
  );
});

test("offers distinct image and source-video privacy proxies", () => {
  assert.match(strategySource, /生成图片白模/);
  assert.match(strategySource, /生成原视频白模/);
  assert.match(workspaceSource, /kind: "pose_proxy_image"/);
  assert.match(workspaceSource, /kind: "motion_proxy_video"/);
  assert.match(workspaceSource, /sourceKind: "source_shot_video"/);
});

test("installs a checksum-pinned WholeBody engine and gates proxy enablement by quality", () => {
  assert.match(workspaceSource, /proxy-engines\/\$\{encodeURIComponent\(engineName\)\}\/install/);
  assert.match(strategySource, /dwpose_wholebody_mannequin/);
  assert.match(strategySource, /semantic_validation_status === "passed"/);
  assert.match(strategySource, /姿态质量未通过，只能预览或下载/);
  assert.doesNotMatch(
    strategySource,
    /managedAssetBinding && wholeBodyEngine && !wholeBodyEngine\.available/,
  );
  assert.match(strategySource, /重新检测 DWPose WholeBody/);
  assert.match(workspaceSource, /proxyEngineLoadError/);
  assert.match(workspaceSource, /proxy-engines\/\$\{encodeURIComponent\(engineName\)\}\/installations/);
  assert.match(workspaceSource, /onNotice\?\.\(\{/);
  assert.match(strategySource, /DWPose WholeBody 安装进度/);
  assert.match(strategySource, /<progress/);
});

test("persists generated proxy assets before they are used", () => {
  assert.match(workflowSource, /async function createReferenceProxy/);
  assert.match(workflowSource, /\/video-references\/shots\/\$\{shotDetail\.plan\.id\}\/proxies/);
  assert.match(workflowSource, /expected_revision_id: detail\.project\.current_revision_id/);
  assert.match(workflowSource, /onCreateReferenceProxy=\{createReferenceProxy\}/);
});

test("lets users disable a proxy without deleting its historical asset", () => {
  assert.match(strategySource, /boundProxyIds/);
  assert.match(strategySource, /停用但保留历史白模资产/);
  assert.match(strategySource, /旧绑定不可提交/);
  assert.match(strategySource, /解除旧绑定/);
  assert.match(workflowSource, /async function disableReferenceProxy/);
  assert.match(workflowSource, /video_reference_bindings: nextBindings/);
  assert.match(workflowSource, /onDisableReferenceProxy=\{disableReferenceProxy\}/);
});

test("only counts semantically verified proxy bindings as generation inputs", () => {
  assert.match(workspaceSource, /function referenceProxyUsable/);
  assert.match(workspaceSource, /usableProxyIds\.has\(item\.proxy_asset_id\)/);
  assert.match(strategySource, /boundProxyIds\.has\(item\.id\) && proxyUsable\(item\)/);
});

test("previews persisted image and video proxies with safe media routes", () => {
  assert.match(strategySource, /白模预览/);
  assert.match(strategySource, /<MediaLightbox/);
  assert.match(strategySource, /<video/);
  assert.match(strategySource, /download: true/);
  assert.match(strategySource, /query\.set\("v", options\.version\)/);
  assert.match(strategySource, /proxy\.sha256 \|\| proxy\.updated_at/);
  assert.match(
    strategySource,
    /\/api\/v1\/video-references\/shots\/\$\{shotPlanId\}\/proxies\/\$\{proxyId\}\/content/,
  );
});

test("keeps historical proxies selectable and only enables one proxy per media type", () => {
  assert.match(strategySource, /历史白模可重新启用/);
  assert.match(strategySource, /onEnableProxy/);
  assert.match(workflowSource, /async function enableReferenceProxy/);
  assert.match(workflowSource, /binding\.media_type === target\.media_type/);
  assert.match(workflowSource, /onEnableReferenceProxy=\{enableReferenceProxy\}/);
});

test("permanently deletes only unused image or video proxies", () => {
  assert.match(strategySource, /onDeleteProxy/);
  assert.match(strategySource, /!bound && \(/);
  assert.match(strategySource, /<Trash size=\{17\}/);
  assert.match(workflowSource, /async function deleteReferenceProxy/);
  assert.match(workflowSource, /永久删除此\$\{label\}及其本地文件/);
  assert.match(workflowSource, /method: "DELETE"/);
  assert.match(workflowSource, /onDeleteReferenceProxy=\{deleteReferenceProxy\}/);
});
