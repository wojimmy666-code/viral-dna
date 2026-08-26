import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const userSettings = fs.readFileSync(
  new URL("../src/settings/UserSettingsPage.jsx", import.meta.url),
  "utf8",
);
const adminSettings = fs.readFileSync(
  new URL("../src/admin/PlatformAdminConsole.jsx", import.meta.url),
  "utf8",
);
const userSettingsStyles = fs.readFileSync(
  new URL("../src/settings/settings-center.css", import.meta.url),
  "utf8",
);
const settingsPrimitives = fs.readFileSync(
  new URL("../src/ui/settings/settings-primitives.css", import.meta.url),
  "utf8",
);
const adminSettingsStyles = fs.readFileSync(
  new URL("../src/admin/platform-admin.css", import.meta.url),
  "utf8",
);
const app = fs.readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");

test("user settings cannot render or submit platform credentials", () => {
  assert.doesNotMatch(userSettings, /API Key\s*<\/span>/);
  assert.doesNotMatch(userSettings, /api_key\s*:/);
  assert.match(userSettings, /API Key、Provider 地址和计费规则由平台管理员统一维护/);
});

test("platform admin uses an independent page shell", () => {
  assert.match(adminSettings, /platform-admin-shell/);
  assert.match(adminSettings, /对所有账户生效/);
  assert.match(adminSettings, /type="password"/);
  assert.match(app, /appRoute\.name === "platform-admin"/);
  assert.match(app, /appRoute\.name === "user-settings"/);
  assert.doesNotMatch(app, /\{settingsOpen && \(/);
});

test("platform admin exposes manual Codex model and reasoning controls", () => {
  assert.match(adminSettings, /<span>模型选择<\/span>/);
  assert.match(adminSettings, /imageLocalModelPolicy/);
  assert.match(adminSettings, /<span>推理等级<\/span>/);
  assert.match(adminSettings, /imageLocalReasoningEffort/);
  assert.match(adminSettings, /不会因生成速度自动切换模型/);
  assert.match(adminSettings, /不会根据耗时自动调整等级/);
});

test("platform admin keeps desktop navigation and content in independent scroll regions", () => {
  assert.match(
    adminSettingsStyles,
    /\.platform-admin-shell\s*\{[\s\S]*?height:\s*100dvh;[\s\S]*?overflow:\s*hidden;/,
  );
  assert.match(
    adminSettingsStyles,
    /\.platform-admin-sidebar\s*\{[\s\S]*?overflow-y:\s*auto;/,
  );
  assert.match(
    adminSettingsStyles,
    /\.platform-admin-main\s*\{[\s\S]*?overflow-y:\s*auto;/,
  );
  assert.match(
    adminSettingsStyles,
    /@media \(max-width:\s*900px\)[\s\S]*?\.platform-admin-shell\s*\{[\s\S]*?height:\s*auto;[\s\S]*?overflow:\s*visible;/,
  );
});

test("effective generation defaults overlay account preferences without credentials", () => {
  assert.match(app, /effectiveImageSettings/);
  assert.match(app, /effectiveVideoSettings/);
  assert.match(app, /userPreferences\?\.settings/);
});

test("settings pages share the product typography and button vocabulary", () => {
  assert.doesNotMatch(userSettings, /primary-action/);
  assert.doesNotMatch(adminSettings, /primary-action/);
  assert.match(userSettings, /className="primary-button"/);
  assert.match(userSettings, /className="secondary-button"/);
  assert.match(adminSettings, /className="primary-button"/);
  assert.doesNotMatch(userSettingsStyles, /clamp\(/);
  assert.match(userSettingsStyles, /font-size: var\(--type-page-size\)/);
  assert.match(settingsPrimitives, /min-height: var\(--control-height\)/);
  assert.match(settingsPrimitives, /font-size: var\(--type-body-size\)/);
});
