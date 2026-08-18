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

test("effective generation defaults overlay account preferences without credentials", () => {
  assert.match(app, /effectiveImageSettings/);
  assert.match(app, /effectiveVideoSettings/);
  assert.match(app, /userPreferences\?\.settings/);
});
