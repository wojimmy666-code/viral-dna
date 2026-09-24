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
const mime = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png", ".mp4": "video/mp4", ".ttf": "font/ttf", ".html": "text/html; charset=utf-8" };

test("public homepage: privacy boundary, responsive UI, keyboard controls and login return", { timeout: 180000 }, async t => {
  await stat(join(buildRoot, "index.html"));
  const requests = [], errors = [], interceptionErrors = [];
  const pendingInterceptions = new Set();
  let finishingBrowser = false;
  let imageFailure = false;
  let videoFailure = false, holdVideo = false;
  const releaseVideo = [];
  let statusFailure = false, initialized = true, setupAllowed = false, authenticated = false;
  let rejectLogin = false, holdLogin = false, loginPosts = 0;
  const releaseLogin = [];
  const fixtureAccount = { user_id: "fixture-user", account_id: "fixture-account", auth_mode: "password", account_kind: "personal", account_name: "验收示意账户", display_name: "验收用户", role: "owner", csrf_token: "fixture-only" };
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, "http://local.fixture"), path = url.pathname;
    requests.push(path);
    const json = (body, code = 200) => { response.writeHead(code, { "Content-Type": "application/json" }); response.end(JSON.stringify(body)); };
    if (path === "/api/v1/auth/status") {
      if (statusFailure) { response.writeHead(502, { "Content-Type": "text/html" }); response.end("Gateway unavailable"); return; }
      return json({ auth_mode: "password", initialized, setup_allowed: setupAllowed });
    }
    if (path === "/api/v1/session" && authenticated) return json(fixtureAccount);
    if (path === "/api/v1/session" || path === "/api/v1/admin/session") return json({ detail: { message: "请先登录" } }, 401);
    if (path === "/api/v1/auth/login") {
      loginPosts++;
      if (holdLogin) await new Promise(release => releaseLogin.push(release));
      return rejectLogin ? json({ detail: { message: "登录失败" } }, 401) : json(fixtureAccount);
    }
    if (path.startsWith("/api/")) return json({ items: [], records: [], projects: [], skills: [], total: 0 });
    if (imageFailure && path.startsWith("/home/") && /\.(webp|png)$/.test(path)) { response.writeHead(404); response.end(); return; }
    if (videoFailure && path.endsWith(".mp4")) { response.writeHead(404, { "Cache-Control": "no-store" }); response.end(); return; }
    if (holdVideo && path.endsWith(".mp4")) await new Promise(release => releaseVideo.push(release));
    try {
      let file = resolve(buildRoot, "." + decodeURIComponent(path));
      if (!file.startsWith(buildRoot + sep)) file = join(buildRoot, "index.html");
      if (!extname(file)) file = join(buildRoot, "index.html");
      const data = await readFile(file);
      const headers = { "Content-Type": mime[extname(file)] || "application/octet-stream", "Cache-Control": "no-store", "Accept-Ranges": "bytes" };
      const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || "");
      if (range) {
        const start = Number(range[1]), end = Math.min(range[2] ? Number(range[2]) : data.length - 1, data.length - 1);
        if (start > end) { response.writeHead(416, { "Content-Range": `bytes */${data.length}` }); response.end(); return; }
        response.writeHead(206, { ...headers, "Content-Range": `bytes ${start}-${end}/${data.length}`, "Content-Length": end - start + 1 }); response.end(data.subarray(start, end + 1));
      } else {
        response.writeHead(200, { ...headers, "Content-Length": data.length }); response.end(data);
      }
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolveServer => server.listen(0, "127.0.0.1", resolveServer));
  const base = `http://127.0.0.1:${server.address().port}`, browser = await localBrowser();
  const { evaluate, ready, send } = browser;
  browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
  browser.on("Runtime.consoleAPICalled", event => { if (event.type === "error") errors.push(event.args.map(arg => arg.value || arg.description).join(" ")); });
  // Prevent page-origin external requests; local files only during acceptance.
  browser.on("Fetch.requestPaused", event => {
    if (finishingBrowser) return;
    const allowed = event.request.url.startsWith(base + "/") || event.request.url.startsWith("data:");
    const continuation = send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest", { requestId: event.requestId, ...(!allowed ? { errorReason: "BlockedByClient" } : {}) });
    pendingInterceptions.add(continuation);
    void continuation.then(
      () => pendingInterceptions.delete(continuation),
      error => {
        pendingInterceptions.delete(continuation);
        // Navigation can cancel an intercepted request before its reply; closing
        // Fetch also releases paused IDs. Neither is an application failure.
        if (!finishingBrowser && !error.message.includes("Invalid InterceptionId.")) interceptionErrors.push(error.message);
      },
    );
  });
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  async function load(path = "/", width = 1536, height = 1024) {
    await browser.viewport(width, height); await browser.navigate(base + path);
    await ready("document.querySelector('.vd-home,.account-login-panel')");
    await evaluate("document.fonts.ready");
  }
  async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); await pause(80); }
  async function fillLogin() {
    for (const [name, value] of [["username", "13800000001"], ["password", "test-only-password"]]) {
      await evaluate(`(()=>{const input=document.querySelector('.vd-login [name=${name}]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    }
  }
  async function loginReady() { await ready("document.querySelector('.vd-login[open]') && document.querySelector('.vd-login fieldset') && !document.querySelector('.vd-login fieldset').disabled"); }
  async function shot(name, full = false) {
    if (!screenshots) return;
    // Error/checking states may settle before the dialog's entrance animation.
    // Await the actual animation so visual evidence never captures a mid-frame.
    if (name.startsWith("login-")) await evaluate("Promise.all((document.querySelector('.vd-login')?.getAnimations() || []).map(animation => animation.finished.catch(() => {})))");
    await mkdir(screenshots, { recursive: true }); await browser.screenshot(join(screenshots, name + ".png"), full);
  }
  async function key(keyName, code = keyName) { const windowsVirtualKeyCode = ({ Escape: 27, ArrowDown: 40, End: 35, Tab: 9 })[keyName]; await send("Input.dispatchKeyEvent", { type: "keyDown", key: keyName, code, windowsVirtualKeyCode }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: keyName, code, windowsVirtualKeyCode }); }
  async function resetHero() {
    await evaluate("window.scrollTo({top:0,behavior:'instant'})");
    await click('[aria-label="查看光线唤醒"]');
    await click('[aria-label="暂停视频"]');
    await ready("!document.querySelector('.vd-hero.is-playing')");
    await ready("document.querySelector('.vd-hero video').paused");
    await ready("document.querySelector('.vd-hero-image img').complete && document.querySelector('.vd-hero-image img').naturalWidth");
    assert.equal(await evaluate("document.querySelector('[aria-label=\"查看光线唤醒\"]').getAttribute('aria-pressed')"), "true");
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
    await t.test("ICP filing link is centered at the footer bottom and keyboard accessible on desktop and mobile", async () => {
      for (const width of [1440, 390, 320]) {
        await load("/", width, width === 1440 ? 960 : 844);
        await evaluate("document.querySelector('.vd-footer').scrollIntoView({block:'end',behavior:'instant'})");
        const filing = await evaluate(`(() => {
          const footer = document.querySelector('.vd-footer'), row = footer.querySelector('.vd-footer-legal'), link = row.querySelector('a');
          const bounds = link.getBoundingClientRect(), footerBounds = footer.getBoundingClientRect();
          const style = getComputedStyle(link);
          const luminance = color => color.match(/[\\d.]+/g).slice(0,3).map(Number).map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126,.7152,.0722][index], 0);
          const foreground = luminance(style.color), background = luminance(getComputedStyle(document.querySelector('.vd-home')).backgroundColor);
          return {
            text: link.textContent, href: link.href, target: link.target, rel: link.rel,
            centerOffset: Math.abs(bounds.left + bounds.width / 2 - footerBounds.left - footerBounds.width / 2),
            height: bounds.height, visible: bounds.top >= 0 && bounds.bottom <= innerHeight,
            last: [...footer.children].filter(child => child !== row).every(child => child.getBoundingClientRect().bottom <= bounds.top),
            overflow: document.documentElement.scrollWidth > innerWidth,
            contrast: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05),
          };
        })()`);
        assert.equal(filing.text, "沪ICP备15044279号-7");
        assert.equal(filing.href, "https://beian.miit.gov.cn/");
        assert.equal(filing.target, "_blank");
        assert.equal(filing.rel, "noopener noreferrer");
        assert.ok(filing.centerOffset <= 1, `centered at ${width}px`);
        assert.ok(filing.height >= 44, `touch target at ${width}px`);
        assert.ok(filing.visible && filing.last && !filing.overflow, `bottom row fits at ${width}px`);
        assert.ok(filing.contrast >= 4.5, `readable contrast at ${width}px`);
        await shot(`icp-footer-${width}`);
        await evaluate("document.querySelector('.vd-footer > a[href=\"/admin/login\"]').focus()");
        await key("Tab");
        assert.equal(await evaluate("document.activeElement === document.querySelector('.vd-footer-legal a')"), true);
        assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"), "solid");
        assert.ok(await evaluate("parseFloat(getComputedStyle(document.activeElement).outlineWidth) >= 2"));
      }
      assert.deepEqual(requests.filter(path => path.startsWith("/api/")), []);
      await load();
    });
    await t.test("samples, pause, dialog, focus restoration and workflow keyboard navigation", async () => {
      await click('[aria-label="查看材质特写"]');
      await ready("document.querySelector('.vd-hero video').currentTime >= 121 / 24 && !document.querySelector('.vd-hero video').paused");
      assert.equal(await evaluate("document.querySelector('[aria-label=\"查看材质特写\"]').getAttribute('aria-pressed')"), "true");
      await click('[aria-label="暂停视频"]');
      await ready("document.querySelector('.vd-hero video').paused");
      const pausedTime = await evaluate("document.querySelector('.vd-hero video').currentTime");
      await pause(250);
      assert.equal(await evaluate("document.querySelector('.vd-hero video').currentTime"), pausedTime);
      await click('[aria-label="播放视频"]');
      await ready("document.querySelector('.vd-hero.is-playing') && !document.querySelector('.vd-hero video').paused");
      await evaluate("document.querySelector('.vd-hero-actions button').focus()");
      await click('.vd-hero-actions button'); await ready("document.querySelector('dialog[open]')");
      await ready("document.querySelector('.vd-demo video').currentTime >= 121 / 24 && !document.querySelector('.vd-demo video').paused");
      assert.equal(await evaluate("document.querySelector('.vd-hero video').paused"), true);
      assert.match(await evaluate("document.querySelector('dialog').innerText"), /静音分镜短片/);
      assert.equal(await evaluate("document.querySelector('.vd-demo video').controls"), true);
      await click('.vd-demo-steps button:last-child');
      await ready("document.querySelector('.vd-demo video').currentTime >= 242 / 24");
      assert.equal(await evaluate("document.querySelector('.vd-demo h3').textContent"), "英雄定格");
      await shot("demo-desktop"); await key("Escape"); await ready("!document.querySelector('dialog')");
      assert.equal(await evaluate("document.activeElement === document.querySelector('.vd-hero-actions button')"), true);
      await evaluate("document.getElementById('vd-step-0').focus()"); await key("ArrowDown");
      assert.equal(await evaluate("document.querySelector('[role=tab][aria-selected=true]').id"), "vd-step-1");
      assert.match(await evaluate("document.querySelector('[role=tabpanel]').innerText"), /产品特写/);
      await key("End"); assert.equal(await evaluate("document.activeElement.id"), "vd-step-4");
      assert.deepEqual(errors, []);
    });
    await t.test("actual film advances chapters, loops, pauses offscreen and honors page visibility", async () => {
      await load(); await ready("document.querySelector('.vd-hero video').currentTime > 0 && !document.querySelector('.vd-hero video').paused");
      assert.equal(await evaluate("document.querySelectorAll('.vd-home video').length"), 1);
      assert.equal(await evaluate("document.querySelector('.vd-hero video').muted && document.querySelector('.vd-hero video').playsInline"), true);
      assert.equal(await evaluate("document.querySelector('.vd-hero video').videoWidth"), 1280);
      assert.ok(Math.abs(await evaluate("document.querySelector('.vd-hero video').duration") - 15.125) < 0.01);
      await evaluate("document.querySelector('.vd-hero video').currentTime = 4.9");
      await ready("document.querySelector('[aria-label=\"查看材质特写\"]').getAttribute('aria-pressed') === 'true'");
      await evaluate("document.querySelector('.vd-hero video').currentTime = 10");
      await ready("document.querySelector('[aria-label=\"查看英雄定格\"]').getAttribute('aria-pressed') === 'true'");
      await evaluate("document.querySelector('.vd-hero video').currentTime = 14.95");
      await ready("document.querySelector('.vd-hero video').currentTime < 1 && document.querySelector('[aria-label=\"查看光线唤醒\"]').getAttribute('aria-pressed') === 'true'");
      await evaluate("document.getElementById('workflow').scrollIntoView({behavior:'instant'})");
      await ready("document.querySelector('.vd-hero video').paused");
      await evaluate("window.scrollTo({top:0,behavior:'instant'})");
      await ready("!document.querySelector('.vd-hero video').paused");
      // Deterministic visibility event fixture; no access to a user's real tabs.
      await evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))");
      await ready("document.querySelector('.vd-hero video').paused");
      await evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))");
      await ready("!document.querySelector('.vd-hero video').paused");
      for (const label of ["材质特写", "英雄定格", "光线唤醒"]) await click(`[aria-label="查看${label}"]`);
      await ready("document.querySelector('.vd-hero video').currentTime < 2 && document.querySelector('[aria-label=\"查看光线唤醒\"]').getAttribute('aria-pressed') === 'true'");
      assert.deepEqual(requests.filter(path => path.startsWith("/api/")), []);
      assert.deepEqual(errors, []);
    });
    await t.test("slow video keeps a poster visible, and failed media can be retried", async () => {
      holdVideo = true;
      try {
        await load();
        await ready("document.querySelector('.vd-hero-image img').complete && document.querySelector('.vd-hero-image img').naturalWidth");
        assert.equal(await evaluate("document.querySelector('.vd-hero-image').dataset.ready"), "false");
        assert.equal(await evaluate("getComputedStyle(document.querySelector('.vd-hero video')).opacity"), "0");
      } finally { holdVideo = false; releaseVideo.splice(0).forEach(release => release()); }
      await ready("document.querySelector('.vd-hero-image').dataset.ready === 'true'");
      videoFailure = true; await load();
      await ready("document.querySelector('.vd-hero-image').dataset.failed === 'true'");
      assert.equal(await evaluate("document.querySelector('.vd-hero-image img').naturalWidth"), 1280);
      assert.match(await evaluate("document.querySelector('.vd-sample-note').textContent"), /视频暂不可用/);
      await shot("video-error");
      videoFailure = false; await click('[aria-label="重试播放视频"]');
      await ready("document.querySelector('.vd-hero-image').dataset.ready === 'true' && !document.querySelector('.vd-hero video').paused");
    });
    await t.test("autoplay denial remains recoverable with an explicit play action", async () => {
      const script = await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const original = HTMLMediaElement.prototype.play; let denied = false; HTMLMediaElement.prototype.play = function () { if (!denied) { denied = true; return Promise.reject(new DOMException('Fixture autoplay denial', 'NotAllowedError')); } return original.call(this); }; })();` });
      try {
        await load(); await ready("document.querySelector('.vd-play-toggle').getAttribute('aria-label') === '播放视频'");
        await click('[aria-label="播放视频"]');
        await ready("document.querySelector('.vd-hero-image').dataset.ready === 'true' && !document.querySelector('.vd-hero video').paused");
      } finally { await send("Page.removeScriptToEvaluateOnNewDocument", { identifier: script.identifier }); }
    });
    await t.test("mobile/tablet layouts and reduced-motion behavior", async () => {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      const requestStart = requests.length;
      await load("/", 390, 844);
      await ready("[...document.querySelectorAll('.vd-hero img')].every(img => img.complete && img.naturalWidth)");
      assert.equal(await evaluate("document.querySelector('.vd-play-toggle').disabled"), false);
      assert.equal(await evaluate("document.querySelector('.vd-hero video').getAttribute('src')"), null);
      await click('[aria-label="查看材质特写"]');
      assert.equal(await evaluate("document.querySelector('.vd-hero video').getAttribute('src')"), null);
      assert.equal(requests.slice(requestStart).some(path => path.endsWith(".mp4")), false);
      await click('[aria-label="查看光线唤醒"]');
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
    await t.test("reduced-motion and data-saving allow explicit playback without unsolicited video loads", async () => {
      await load("/", 390, 844);
      await click('[aria-label="查看材质特写"]');
      await click('[aria-label="播放视频"]');
      await ready("document.querySelector('.vd-hero video').currentTime >= 121 / 24 && !document.querySelector('.vd-hero video').paused");
      await click('[aria-label="暂停视频"]');
      await ready("document.querySelector('.vd-hero video').paused");
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
      const script = await send("Page.addScriptToEvaluateOnNewDocument", { source: `Object.defineProperty(navigator, 'connection', { configurable: true, value: { saveData: true, addEventListener() {}, removeEventListener() {} } });` });
      try {
        const requestStart = requests.length;
        await load(); await pause(250);
        assert.equal(requests.slice(requestStart).some(path => path.endsWith(".mp4")), false);
        await click('[aria-label="查看英雄定格"]');
        assert.equal(await evaluate("document.querySelector('.vd-hero video').getAttribute('src')"), null);
        await click('[aria-label="播放视频"]');
        await ready("document.querySelector('.vd-hero video').currentTime >= 242 / 24 && !document.querySelector('.vd-hero video').paused");
      } finally { await send("Page.removeScriptToEvaluateOnNewDocument", { identifier: script.identifier }); }
    });
    await t.test("missing images remain recoverable and don't block creation entry", async () => {
      imageFailure = true; await load("/", 390, 844); await ready("document.querySelector('.vd-image-unavailable')");
      assert.match(await evaluate("document.querySelector('.vd-hero-actions a').getAttribute('href')"), /\/login\?returnTo=/);
      imageFailure = false;
    });
    await t.test("login overlays the same homepage, pauses playback and restores focus, scroll and history", async () => {
      await load(); await ready("document.querySelector('.vd-hero video').currentTime > 0");
      await evaluate("window.__loginHero = document.querySelector('.vd-hero video'); document.querySelector('.vd-hero-actions a').focus()");
      const previousCanvas = await evaluate("[document.documentElement.style.backgroundColor,document.documentElement.style.colorScheme,document.documentElement.style.scrollbarGutter]");
      const requestStart = requests.length;
      await click('.vd-hero-actions a'); await loginReady();
      assert.equal(await evaluate("window.__loginHero === document.querySelector('.vd-hero video')"), true);
      assert.equal(await evaluate("document.querySelector('.vd-hero video').paused"), true);
      assert.equal(await evaluate("document.body.style.overflow"), "hidden");
      assert.equal(await evaluate("getComputedStyle(document.documentElement).backgroundColor"), "rgb(16, 15, 18)");
      assert.equal(await evaluate("getComputedStyle(document.documentElement).colorScheme"), "dark");
      assert.equal(requests.slice(requestStart).some(path => /PrivateApplication|\/assets\/App-/.test(path)), false);
      assert.equal(await evaluate("document.querySelector('.vd-login').contains(document.activeElement)"), true);
      for (let index = 0; index < 9; index++) { await key("Tab"); assert.equal(await evaluate("document.querySelector('.vd-login').contains(document.activeElement)"), true); }
      await shot("login-desktop");
      const submitCenter = await evaluate("(()=>{const r=document.querySelector('.vd-login-submit').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", ...submitCenter }); await pause(200);
      const hover = await evaluate("(()=>{const s=getComputedStyle(document.querySelector('.vd-login-submit'));return {color:s.color,background:s.backgroundColor}})()");
      assert.equal(hover.background, "rgb(99, 85, 246)");
      const luminance = rgb => rgb.match(/\d+(?:\.\d+)?/g).slice(0,3).map(Number).map(value => { const channel = value / 255; return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4; }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const foreground = luminance(hover.color), background = luminance(hover.background);
      assert.ok((Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05) >= 4.5, "login hover text contrast must reach 4.5:1");
      await shot("login-hover");
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 0, y: 0 });
      await key("Escape"); await ready("location.pathname === '/' && !document.querySelector('.vd-login')");
      assert.deepEqual(await evaluate("[document.documentElement.style.backgroundColor,document.documentElement.style.colorScheme,document.documentElement.style.scrollbarGutter]"), previousCanvas);
      assert.equal(await evaluate("document.activeElement === document.querySelector('.vd-hero-actions a')"), true);
      await ready("!document.querySelector('.vd-hero video').paused");
      await evaluate("history.forward()"); await loginReady();
      await evaluate("history.back()"); await ready("!document.querySelector('.vd-login')");
      await evaluate("document.querySelector('.vd-paths').scrollIntoView({behavior:'instant'}); document.querySelector('.vd-paths a').focus(); window.__loginScroll = scrollY");
      await click('.vd-paths a'); await loginReady();
      assert.equal(await evaluate("scrollY === window.__loginScroll"), true);
      await click('[aria-label="关闭登录"]'); await ready("!document.querySelector('.vd-login')");
      assert.equal(await evaluate("scrollY === window.__loginScroll"), true);
      assert.equal(await evaluate("document.activeElement === document.querySelector('.vd-paths a')"), true);
      assert.deepEqual(errors, []);
    });
    await t.test("password reveal, credential errors, single submission and abandoned requests are safe", async () => {
      await load('/login'); await loginReady(); await fillLogin();
      await click('[aria-label="显示密码"]'); assert.equal(await evaluate("document.querySelector('#vd-login-password').type"), "text");
      await click('[aria-label="隐藏密码"]'); assert.equal(await evaluate("document.querySelector('#vd-login-password').type"), "password");
      rejectLogin = true;
      await click('.vd-login-submit'); await ready("document.querySelector('.vd-login-error')");
      assert.match(await evaluate("document.querySelector('.vd-login-error').textContent"), /手机号或密码不正确/);
      assert.equal(await evaluate("document.querySelector('#vd-login-phone').value"), "13800000001");
      await shot("login-invalid-credentials");
      rejectLogin = false; holdLogin = true;
      const before = loginPosts;
      await click('.vd-login-submit'); await click('.vd-login-submit');
      assert.equal(loginPosts - before, 1);
      assert.equal(await evaluate("document.querySelector('.vd-login-submit').textContent"), "正在登录…");
      await click('[aria-label="关闭登录"]'); await ready("location.pathname === '/'");
      holdLogin = false; releaseLogin.splice(0).forEach(release => release()); await pause(150);
      assert.equal(await evaluate("location.pathname"), "/");
      await click('.vd-hero-actions a'); await loginReady();
      assert.equal(await evaluate("document.querySelector('#vd-login-password').value"), "");
      await click('[aria-label="关闭登录"]');
    });
    await t.test("server failures keep the homepage and form, then recover through retry", async () => {
      statusFailure = true;
      await load('/login'); await ready("document.querySelector('.vd-login-retry')");
      assert.match(await evaluate("document.querySelector('.vd-login').innerText"), /连接登录服务/);
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-home .vd-hero'))"), true);
      assert.equal(await evaluate("document.querySelector('.vd-login fieldset').disabled"), true);
      await shot("login-service-error");
      statusFailure = false; await click('.vd-login-retry'); await loginReady();
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-login-retry'))"), false);
      // Actual backdrop pointer press; a form-to-backdrop drag must not dismiss.
      await send("Input.dispatchMouseEvent", { type: "mousePressed", x: 8, y: 8, button: "left", clickCount: 1 });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: 8, y: 8, button: "left", clickCount: 1 });
      await ready("location.pathname === '/' && !document.querySelector('.vd-login')");
    });
    await t.test("mobile, reduced motion, short keyboard viewport and direct refresh remain usable", async () => {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      for (const [width, height] of [[390,844], [320,568], [768,900], [390,360]]) {
        await load('/login?returnTo=%2Fprojects%2Fnew', width, height); await loginReady();
        assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
        assert.equal(await evaluate("(()=>{const r=document.querySelector('.vd-login').getBoundingClientRect();return r.top>=15 && r.bottom<=innerHeight-15 && r.left>=15 && r.right<=innerWidth-15})()"), true);
        assert.equal(await evaluate("getComputedStyle(document.querySelector('.vd-login input')).fontSize"), "16px");
        assert.equal(await evaluate("getComputedStyle(document.documentElement).backgroundColor"), "rgb(16, 15, 18)");
        assert.equal(await evaluate("document.querySelector('.vd-hero video').getAttribute('src')"), null);
        assert.equal(await evaluate("performance.getEntriesByType('resource').some(entry => new URL(entry.name).pathname.endsWith('.mp4'))"), false);
        assert.equal(await evaluate("getComputedStyle(document.querySelector('.vd-login-submit')).fontSize"), "16px");
        const buttonHeight = await evaluate("document.querySelector('.vd-login-submit').getBoundingClientRect().height");
        assert.ok(buttonHeight >= 48 && buttonHeight < 50, `48px control with fractional line height: ${buttonHeight}`);
        assert.equal(await evaluate("getComputedStyle(document.querySelector('.vd-login')).animationName"), "none");
        if (height === 360) {
          await evaluate("document.querySelector('#vd-login-password').focus();document.querySelector('.vd-login-submit').scrollIntoView({block:'nearest',behavior:'instant'})");
          assert.equal(await evaluate("(()=>{const r=document.querySelector('.vd-login-submit').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()"), true);
          assert.equal(await evaluate("(()=>{const r=document.querySelector('.vd-login-close').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()"), true);
        }
        await shot(`login-${width}-${height}`);
      }
      await click('[aria-label="关闭登录"]'); await ready("location.pathname === '/'");
      assert.equal(await evaluate("document.querySelector('.vd-hero video').paused"), true);
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
    });
    await t.test("admin and first setup stay separate from the public login dialog", async () => {
      await load('/admin/login'); await ready("document.querySelector('.account-login-panel')");
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-home'))"), false);
      assert.equal(await evaluate("document.querySelector('[name=username]').value"), "admin");
      await click('.account-login-panel footer a'); await loginReady();
      assert.equal(await evaluate("getComputedStyle(document.querySelector('.vd-login')).backgroundColor"), "rgb(28, 27, 32)");
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-login a[href=\"/admin/login\"]'))"), false);
      initialized = false; setupAllowed = false;
      await load('/login'); await ready("document.querySelector('.vd-login-status')?.innerText.includes('部署本机')");
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-login-setup'))"), false);
      setupAllowed = true; await load('/login'); await ready("document.querySelector('.vd-login-setup')");
      await click('.vd-login-setup'); await ready("location.pathname === '/setup' && document.querySelector('[name=admin_password]')");
      initialized = true; setupAllowed = false;
      assert.equal(requests.some(path => path === '/api/v1/auth/setup'), false);
    });
    await t.test("existing sessions bypass the form and rejected return targets stay inside the app", async () => {
      authenticated = true;
      await load('/login?returnTo=%2Fskills'); await ready("location.pathname === '/skills'");
      await load('/login?returnTo=https%3A%2F%2Fevil.example'); await ready("location.pathname === '/projects'");
      authenticated = false;
    });
    await t.test("private destinations still require login and preserve returnTo", async () => {
      await load("/login?returnTo=%2Fskills", 1280, 900);
      await loginReady();
      assert.equal(await evaluate("Boolean(document.querySelector('.vd-home'))"), true);
      assert.match(await evaluate("document.querySelector('.vd-login').innerText"), /手机号/);
      await fillLogin();
      await click('.vd-login-submit'); await ready("location.pathname === '/skills'");
      // The success route is the actual app; synthetic fixtures do not claim to
      // exercise the full Skill backend. Its regression tests remain separate.
    });
  } finally {
    holdVideo = false; holdLogin = false;
    releaseLogin.splice(0).forEach(release => release()); releaseVideo.splice(0).forEach(release => release());
    finishingBrowser = true;
    try {
      // Stop interception and drain in-flight acknowledgements before closing
      // CDP, so successful app checks cannot leave rejected teardown promises.
      await send("Fetch.disable");
      await Promise.allSettled([...pendingInterceptions]);
    } finally {
      await browser.close(); await new Promise(resolveClose => server.close(resolveClose));
    }
    assert.deepEqual(interceptionErrors, []);
  }
});
