import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  connectionHealthMeta,
  detectPlatformFromUrl,
  findPlatformConnection,
  isCredentialAnalysisError,
  PLATFORM_IDS,
  platformLabel,
  sourceTypeLabel,
} from "../src/platform-connection-ui.js";

const brandLogoSource = readFileSync(
  new URL("../src/PlatformBrandLogo.jsx", import.meta.url),
  "utf8",
);
const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const connectionsSource = readFileSync(
  new URL("../src/PlatformConnections.jsx", import.meta.url),
  "utf8",
);
const connectionsCssSource = readFileSync(
  new URL("../src/platform-connections.css", import.meta.url),
  "utf8",
);

test("detects supported platform links without accepting disguised hosts", () => {
  assert.equal(detectPlatformFromUrl("https://www.douyin.com/video/123"), "douyin");
  assert.equal(detectPlatformFromUrl("https://v.douyin.com/a1"), "douyin");
  assert.equal(
    detectPlatformFromUrl("https://www.xiaohongshu.com/explore/a1"),
    "xiaohongshu",
  );
  assert.equal(
    detectPlatformFromUrl("https://www.tiktok.com/@creator/video/123"),
    "tiktok",
  );
  assert.equal(detectPlatformFromUrl("https://vm.tiktok.com/ZMexample/"), "tiktok");
  assert.equal(
    detectPlatformFromUrl("https://www.instagram.com/reel/example/"),
    "instagram",
  );
  assert.equal(detectPlatformFromUrl("https://instagr.am/p/example/"), "instagram");
  assert.equal(detectPlatformFromUrl("https://xiaohongshu.com.evil.example/a1"), null);
  assert.equal(detectPlatformFromUrl("https://tiktok.com.evil.example/a1"), null);
  assert.equal(detectPlatformFromUrl("https://instagram.com.evil.example/a1"), null);
  assert.equal(detectPlatformFromUrl("not-a-url"), null);
});

test("exposes one shared four-platform presentation registry", () => {
  assert.deepEqual(PLATFORM_IDS, ["douyin", "xiaohongshu", "tiktok", "instagram"]);
  assert.equal(platformLabel("tiktok"), "TikTok");
  assert.equal(sourceTypeLabel("upload"), "本地文件");
  assert.equal(sourceTypeLabel("instagram"), "Instagram");
});

test("renders reusable vector brand logos instead of letter placeholders", () => {
  assert.match(brandLogoSource, /const TIKTOK_PATH/);
  assert.match(brandLogoSource, /const XIAOHONGSHU_PATH/);
  assert.match(brandLogoSource, /const INSTAGRAM_PATH/);
  assert.match(connectionsSource, /<PlatformBrandLogo className="platform-logo"/);
  assert.match(appSource, /className="link-platform-mark"/);
  assert.doesNotMatch(connectionsSource, /platformMark/);
  assert.doesNotMatch(appSource, /platformMark/);
});

test("keeps platform cards compact and content-driven", () => {
  assert.match(connectionsSource, /const cardState = connection\?\.configured/);
  assert.match(connectionsSource, /\$\{cardState\}/);
  assert.match(connectionsCssSource, /\.platform-card-grid \{[^}]*align-items: start;/s);
  assert.doesNotMatch(connectionsCssSource, /min-height: 340px/);
  assert.doesNotMatch(connectionsCssSource, /min-height: 230px/);
  assert.doesNotMatch(connectionsCssSource, /\.platform-card-actions \{[^}]*margin-top: auto;/s);
  assert.match(connectionsCssSource, /\.platform-card-metadata div \+ div \{[^}]*border-left:/s);
});

test("maps account connection health to actionable states", () => {
  assert.equal(connectionHealthMeta(null).label, "未配置");
  assert.equal(connectionHealthMeta({ configured: true, health: "ready" }).usable, true);
  assert.equal(connectionHealthMeta({ configured: true, health: "expired" }).usable, false);
});

test("local Cookie readability is not presented as verified platform access", () => {
  const ready = connectionHealthMeta({ configured: true, health: "ready" });
  assert.equal(ready.label, "已导入 · 未验证");
  assert.equal(ready.tone, "warning");
  assert.equal(connectionHealthMeta({ configured: true, health: "valid" }).label, "视频读取成功");
  assert.equal(connectionHealthMeta({
    configured: true, health: "error", last_error_code: "link_access_denied",
  }).label, "访问受限");
  assert.equal(connectionHealthMeta({
    configured: true, health: "error", last_error_code: "link_metadata_unavailable",
  }).label, "视频信息未获取");
  assert.equal(connectionHealthMeta({
    configured: true, health: "valid", usage_strategy: "disabled",
  }).usable, false);
  assert.equal(isCredentialAnalysisError("link_access_denied"), false);
  assert.equal(isCredentialAnalysisError("link_metadata_unavailable"), false);
});

test("separates optional network test from local inspection and automatic analysis", () => {
  assert.match(connectionsSource, /检查本机信息/);
  assert.match(connectionsSource, /test_url: videoUrl\.trim\(\) \|\| null/);
  assert.match(connectionsSource, /validateConnection\(platform, testUrls\[platform\] \|\| ""\)/);
  assert.match(connectionsSource, /connection\.last_checked_at/);
  assert.match(connectionsSource, /connection\.last_tested_at/);
  assert.doesNotMatch(connectionsSource, /最近验证|检查状态/);
  assert.match(appSource, /粘贴链接后自动下载并分析/);
  assert.match(connectionsSource, /无需提前测试/);
});

test("finds the selected platform and recognizes credential analysis failures", () => {
  const payload = { items: [{ platform: "douyin", configured: true }] };
  assert.equal(findPlatformConnection(payload, "douyin")?.configured, true);
  assert.equal(findPlatformConnection(payload, "xiaohongshu"), null);
  assert.equal(isCredentialAnalysisError("link_auth_required"), true);
  assert.equal(isCredentialAnalysisError("link_duration_exceeded"), false);
});

test("local browser assistance keeps verification actionable without automatic login claims", () => {
  const source = readFileSync(new URL("../src/BrowserAssist.jsx", import.meta.url), "utf8");
  assert.match(connectionsSource, /platform === "douyin" && <BrowserAssistConnection/);
  assert.match(source, /if \(!status\?\.available\)/);
  assert.match(source, /打开验证窗口/);
  assert.match(source, /我已完成，继续读取/);
  assert.match(source, /取消采集/);
  assert.match(source, /AbortSignal\.timeout\(10000\)/);
  assert.match(source, /currentRevision === revision\.current && !connecting\.current/);
  const refresh = source.slice(source.indexOf("async function refresh()"), source.indexOf("async function connect()"));
  assert.doesNotMatch(refresh, /setError\(/, "polling must not clear action failures");
  assert.match(appSource, /<BrowserAssistControls/);
  assert.match(appSource, /等待操作/);
});
