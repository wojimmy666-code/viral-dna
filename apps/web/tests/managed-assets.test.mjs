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

test("browses provider managed people without a manual asset id field", () => {
  assert.match(pickerSource, /\/managed-assets\/providers\/volc_ark\/catalog/);
  assert.doesNotMatch(pickerSource, /name="asset_id"/);
  assert.match(pickerSource, /initialQuery/);
});

test("binds one provider actor identity to the active shot revision", () => {
  assert.match(bindingSource, /managed-assets\/providers\/\$\{binding\.provider\}\/assets/);
  assert.doesNotMatch(bindingSource, /src=\{binding\.preview_url\}/);
  assert.match(workflowSource, /async function updateManagedAssetBinding/);
  assert.match(workflowSource, /managed_asset_bindings: binding \? \[binding\] : \[\]/);
  assert.match(workflowSource, /onManagedAssetChange=\{updateManagedAssetBinding\}/);
  assert.match(workspaceSource, /managed_asset_bindings/);
  assert.match(workspaceSource, /onRequestManagedAssetMention=\{openManagedAssetPicker\}/);
  assert.match(workflowSource, /savedBinding = binding/);
});

test("configures the managed asset directory with separate access credentials", () => {
  assert.match(appSource, /videoManagedAssetAccessKey/);
  assert.match(appSource, /videoManagedAssetSecretKey/);
  assert.match(appSource, /videoManagedAssetProjectName/);
});

test("treats managed identity and depth control as independent optional inputs", () => {
  assert.match(workspaceSource, /capabilities\?\.managed_assets/);
  assert.match(workspaceSource, /managedIdentityRequired/);
  assert.match(workspaceSource, /selectedDepthCount/);
  assert.match(workspaceSource, /depth_control_assets/);
  assert.match(workspaceSource, /selectedInputSources\.has\("provider_managed_assets"\)/);
  assert.match(workspaceSource, /selectedInputSources\.has\("depth_control"\)/);
  assert.match(workspaceSource, /\{usesDepthControl && sourceVideoUrl && \(/);
});
