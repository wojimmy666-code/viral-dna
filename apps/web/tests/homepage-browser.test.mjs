import assert from "node:assert/strict";
import { readFile, stat, mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { localBrowser, pause } from "./helpers/local-browser.mjs";

// The real production build, served by a disposable loopback-only fixture.
// Auth responses are synthetic. No live API, user account or generated task is touched.
const webRoot = fileURLToPath(new URL("..", import.meta.url));
const buildRoot = join(webRoot, "dist/client");
const screenshots = process.env.HOMEPAGE_SCREENSHOT_DIR && resolve(process.env.HOMEPAGE_SCREENSHOT_DIR);
const mime = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png", ".ttf": "font/ttf", ".html": "text/html; charset=utf-8" };

test("public homepage: privacy boundary, responsive UI, keyboard controls and login return", { timeout: 180000 }, async t => {
  await stat(join(buildRoot, "index.html"));
  const requests = [], errors = [];
  let imageFailure = false;
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, "http://local.fixture"), path = url.pathname;
    requests.push(path);
    const json = (body, code = 200) => { response.writeHead(code, { "Content-Type": "application/json" }); response.end(JSON.stringify(body)); };
    if (path === "/api/v1/auth/status") return json({ auth_mode: "password", initialized: true, setup_allowed: false });
    if (path === "/api/v1/session" || path === "/api/v1/admin/session") return json({ detail: { message: "请先登录" } }, 401);
    if (path === "/api/v1/auth/login") return json({ user_id: "fixture-user", account_id: "fixture-account", auth_mode: "password", account_kind: "personal", account_name: "验收示意账户", display_name: "验收用户", role: "owner", csrf_token: "fixture-only" });
    if (path.startsWith("/api/")) return json({ items: [], records: [], projects: [], skills: [], total: 0 });
    if (imageFailure && path.startsWith("/home/") && /\.(webp|png)$/.test(path)) { response.writeHead(404); response.end(); return; }
    try {
      let file = resolve(buildRoot, "." + decodeURIComponent(path));
      if (!file.startsWith(buildRoot + sep)) file = join(buildRoot, "index.html");
      if (!extname(file)) file = join(buildRoot, "index.html");
      const data = await readFile(file);
      response.writeHead(200, { "Content-Type": mime[extname(file)] || "application/octet-stream", "Cache-Control": "no-store" }); response.end(data);
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolveServer => server.listen(0, "127.0.0.1", resolveServer));
  const base = `http://127.0.0.1:${server.address().port}`, browser = await localBrowser();
  const { evaluate, ready, send } = browser;
  browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
  browser.on("Runtime.consoleAPICalled", event => { if (event.type === "error") errors.push(event.args.map(arg => arg.value || arg.description).join(" ")); });
  // Prevent page-origin external requests; local files only during acceptance.
  browser.on("Fetch.requestPaused", event => {
    const allowed = event.request.url.startsWith(base + "/") || event.request.url.startsWith("data:");
    void send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest", { requestId: event.requestId, ...(!allowed ? { errorReason: "BlockedByClient" } : {}) });
  });
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  async function load(path = "/", width = 1536, height = 1024) {
    await browser.viewport(width, height); await browser.navigate(base + path);
    await ready("document.querySelector('.vd-home,.account-login-panel')");
    await evaluate("document.fonts.ready");
  }
  async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); await pause(80); }
  async function shot(name, full = false) {
    if (!screenshots) return;
    await mkdir(screenshots, { recursive: true }); await browser.screenshot(join(screenshots, name + ".png"), full);
  }
  async function key(keyName, code = keyName) { const windowsVirtualKeyCode = ({ Escape: 27, ArrowDown: 40, End: 35, Tab: 9 })[keyName]; await send("Input.dispatchKeyEvent", { type: "keyDown", key: keyName, code, windowsVirtualKeyCode }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: keyName, code, windowsVirtualKeyCode }); }
  async function resetHero() {
    await evaluate("window.scrollTo({top:0,behavior:'instant'})");
    // Select through the real control and leave playback paused. A screenshot
    // can take longer than the carousel interval on slower acceptance hosts.
    await click('[aria-label="查看产品特写"]');
    await ready("!document.querySelector('.vd-hero.is-playing')");
    await ready("document.querySelector('.vd-hero-image img').complete && document.querySelector('.vd-hero-image img').naturalWidth");
    assert.equal(await evaluate("document.querySelector('[aria-label=\"查看产品特写\"]').getAttribute('aria-pressed')"), "true");
    await evaluate("document.getAnimations().forEach(animation => { animation.pause(); animation.currentTime = 0; })");
  }
  try {
    await t.test("anonymous route has no API/editor requests and uses optimized images", async () => {
      await load(); await ready("[...document.querySelectorAll('.vd-hero img')].every(img => img.complete && img.naturalWidth)");
      assert.equal(await evaluate("document.querySelectorAll('h1').length"), 1);
      assert.equal(await evaluate("document.querySelector('.vd-hero-image img').currentSrc.endsWith('.webp')"), true);
      assert.deepEqual(requests.filter(path => path.startsWith("/api/")), []);
      assert.equal(requests.some(path => /PrivateApplication|App-/.test(path)), false);
      await resetHero();
      await shot("hero-repro");
      // Scroll through actual sections once so native lazy images load before full capture.
      for (const id of ["workflow", "skills", "team"]) { await evaluate(`document.getElementById('${id}').scrollIntoView({behavior:'instant'})`); await pause(200); }
      await ready("[...document.images].every(img => img.complete && img.naturalWidth)");
      await evaluate("window.scrollTo({top:0,behavior:'instant'})");
      await browser.viewport(1440, 960); await resetHero(); await shot("desktop", true);
      for (const width of [1280, 1600]) {
        await browser.viewport(width, 960);
        await resetHero();
        assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, `overflow at ${width}`);
        await shot(`desktop-${width}`);
      }
      await browser.viewport(1536, 1024);
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 0, y: 0 });
    });
    await t.test("samples, pause, dialog, focus restoration and workflow keyboard navigation", async () => {
      await click('[aria-label="查看场景演绎"]');
      assert.equal(await evaluate("document.querySelector('[aria-label=\"查看场景演绎\"]').getAttribute('aria-pressed')"), "true");
      assert.equal(await evaluate("document.querySelector('.vd-hero.is-playing') === null"), true);
      await click('[aria-label="播放画面轮播"]');
      assert.equal(await evaluate("document.querySelector('.vd-hero.is-playing') !== null"), true);
      await click('[aria-label="暂停画面轮播"]');
      await evaluate("document.querySelector('.vd-hero-actions button').focus()");
      await click('.vd-hero-actions button'); await ready("document.querySelector('dialog[open]')");
      assert.match(await evaluate("document.querySelector('dialog').innerText"), /静态分镜演示/);
      await click('.vd-demo-steps button:last-child');
      assert.equal(await evaluate("document.querySelector('.vd-demo h3').textContent"), "运镜节奏");
      await shot("demo-desktop"); await key("Escape"); await ready("!document.querySelector('dialog')");
      assert.equal(await evaluate("document.activeElement === document.querySelector('.vd-hero-actions button')"), true);
      await evaluate("document.getElementById('vd-step-0').focus()"); await key("ArrowDown");
      assert.equal(await evaluate("document.querySelector('[role=tab][aria-selected=true]').id"), "vd-step-1");
      assert.match(await evaluate("document.querySelector('[role=tabpanel]').innerText"), /产品特写/);
      await key("End"); assert.equal(await evaluate("document.activeElement.id"), "vd-step-4");
      assert.deepEqual(errors, []);
    });
    await t.test("mobile/tablet layouts and reduced-motion behavior", async () => {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      await load("/", 390, 844);
      await ready("[...document.querySelectorAll('.vd-hero img')].every(img => img.complete && img.naturalWidth)");
      assert.equal(await evaluate("document.querySelector('.vd-play-toggle').disabled"), true);
      await click('[aria-label="打开导航"]');
      assert.equal(await evaluate("document.querySelector('.vd-menu-toggle').getAttribute('aria-expanded')"), "true");
      await shot("mobile-menu"); await key("Escape");
      assert.equal(await evaluate("document.querySelector('.vd-menu-toggle').getAttribute('aria-expanded')"), "false");
      for (const id of ["workflow", "skills", "team"]) { await evaluate(`document.getElementById('${id}').scrollIntoView({behavior:'instant'})`); await pause(150); }
      await ready("[...document.images].every(img => img.complete && img.naturalWidth)");
      await evaluate("window.scrollTo({top:0,behavior:'instant'})"); await shot("mobile", true); await shot("mobile-first-viewport");
      await click('.vd-hero-actions button'); await ready("document.querySelector('dialog[open]')"); await shot("demo-mobile"); await key("Escape");
      for (const width of [320, 375, 768, 1024]) {
        await browser.viewport(width, 900); await evaluate("window.scrollTo({top:0,behavior:'instant'})");
        assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, `overflow at ${width}`);
        await shot(`responsive-${width}`);
      }
      assert.deepEqual(errors, []);
    });
    await t.test("missing images remain recoverable and don't block creation entry", async () => {
      imageFailure = true; await load("/", 390, 844); await ready("document.querySelector('.vd-image-unavailable')");
      assert.match(await evaluate("document.querySelector('.vd-hero-actions a').getAttribute('href')"), /\/login\?returnTo=/);
      imageFailure = false;
    });
    await t.test("private destinations still require login and preserve returnTo", async () => {
      await load("/login?returnTo=%2Fskills", 1280, 900);
      await ready("document.querySelector('.account-login-panel input[name=username]')");
      assert.equal(await evaluate("document.querySelector('.vd-home')"), null);
      assert.match(await evaluate("document.querySelector('.account-login-panel').innerText"), /手机号/);
      for (const [name, value] of [["username", "13800000001"], ["password", "test-only-password"]]) {
        await evaluate(`(()=>{const input=document.querySelector('[name=${name}]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      }
      await click('.account-primary'); await ready("location.pathname === '/skills'");
      // The success route is the actual app; synthetic fixtures do not claim to
      // exercise the full Skill backend. Its regression tests remain separate.
    });
  } finally { await browser.close(); await new Promise(resolveClose => server.close(resolveClose)); }
});
