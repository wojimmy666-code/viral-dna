import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pickerSource = readFileSync(
  new URL("../src/managed-assets/ManagedAssetPicker.jsx", import.meta.url),
  "utf8",
);
const bindingSource = readFileSync(
  new URL("../src/managed-assets/ManagedAssetBindingCard.jsx", import.meta.url),
  "utf8",
);
const workflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const appSource = readFileSync(
  new URL("../src/App.jsx", import.meta.url),
  "utf8",
);

test("browses provider managed people without exposing a manual asset id field", () => {
  assert.match(pickerSource, /\/managed-assets\/providers\/volc_ark\/catalog/);
  assert.match(pickerSource, /虚拟人像/);
  assert.match(pickerSource, /已授权真人/);
  assert.match(pickerSource, /Provider 返回/);
  assert.doesNotMatch(pickerSource, /手动输入资产 ID[^。]*<input/);
});

test("binds one provider actor identity to a shot revision", () => {
  assert.match(bindingSource, /演员身份（Provider 托管）/);
  assert.match(bindingSource, /managed-assets\/providers\/\$\{binding\.provider\}\/assets/);
  assert.doesNotMatch(bindingSource, /src=\{binding\.preview_url\}/);
  assert.match(workflowSource, /async function updateManagedAssetBinding/);
  assert.match(workflowSource, /managed_asset_bindings: binding \? \[binding\] : \[\]/);
  assert.match(workflowSource, /onManagedAssetChange=\{updateManagedAssetBinding\}/);
  assert.match(workspaceSource, /managed_asset_bindings/);
});

test("configures the asset directory with separate AK SK credentials", () => {
  assert.match(appSource, /videoManagedAssetAccessKey/);
  assert.match(appSource, /videoManagedAssetSecretKey/);
  assert.match(appSource, /托管虚拟资产目录/);
  assert.match(appSource, /视频 API Key 不能读取目录/);
  assert.match(appSource, /ProjectName 必须与视频推理 API Key 一致/);
});

test("shows model compatibility and counts managed assets against reference limits", () => {
  assert.match(workspaceSource, /capabilities\?\.managed_assets/);
  assert.match(workspaceSource, /managedIdentityRequired/);
  assert.match(workspaceSource, /selectedProxyCount/);
  assert.match(workspaceSource, /当前策略将提交 \$\{totalReferenceCount\} 个安全参考输入/);
  assert.match(workspaceSource, /当前模型不支持已绑定的 Provider 托管人物资产/);
});
