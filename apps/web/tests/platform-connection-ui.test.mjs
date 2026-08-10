import assert from "node:assert/strict";
import test from "node:test";

import {
  connectionHealthMeta,
  detectPlatformFromUrl,
  findPlatformConnection,
  isCredentialAnalysisError,
} from "../src/platform-connection-ui.js";

test("detects supported platform links without accepting disguised hosts", () => {
  assert.equal(detectPlatformFromUrl("https://www.douyin.com/video/123"), "douyin");
  assert.equal(detectPlatformFromUrl("https://v.douyin.com/a1"), "douyin");
  assert.equal(
    detectPlatformFromUrl("https://www.xiaohongshu.com/explore/a1"),
    "xiaohongshu",
  );
  assert.equal(detectPlatformFromUrl("https://xiaohongshu.com.evil.example/a1"), null);
  assert.equal(detectPlatformFromUrl("not-a-url"), null);
});

test("maps account connection health to actionable states", () => {
  assert.equal(connectionHealthMeta(null).label, "未配置");
  assert.equal(connectionHealthMeta({ configured: true, health: "ready" }).usable, true);
  assert.equal(connectionHealthMeta({ configured: true, health: "expired" }).usable, false);
});

test("finds the selected platform and recognizes credential analysis failures", () => {
  const payload = { items: [{ platform: "douyin", configured: true }] };
  assert.equal(findPlatformConnection(payload, "douyin")?.configured, true);
  assert.equal(findPlatformConnection(payload, "xiaohongshu"), null);
  assert.equal(isCredentialAnalysisError("link_auth_required"), true);
  assert.equal(isCredentialAnalysisError("link_duration_exceeded"), false);
});
