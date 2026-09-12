import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

// Disposable browser + in-memory HTTP fixture. Never connects to the live app/API.
const webRoot = fileURLToPath(new URL("..", import.meta.url));
const browserPath = [process.env.CHROME_BIN,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium",
].find(path => path && existsSync(path));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const projectId = "11111111-1111-4111-8111-111111111111";
function connect(url) {
  return new Promise((resolveConnection, rejectConnection) => {
    const socket = new WebSocket(url), pending = new Map(); let nextId = 0;
    socket.addEventListener("error", rejectConnection, { once: true });
    socket.addEventListener("message", event => {
      const result = JSON.parse(event.data), task = pending.get(result.id);
      if (!task) return;
      pending.delete(result.id); clearTimeout(task.timer);
      result.error ? task.reject(new Error(JSON.stringify(result.error))) : task.resolve(result.result);
    });
    socket.addEventListener("open", () => resolveConnection({ close: () => socket.close(), send(method, params = {}) {
      const id = ++nextId;
      return new Promise((resolveTask, reject) => {
        const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
        pending.set(id, { resolve: resolveTask, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
      });
    } }), { once: true });
  });
}

test("account UI: independent login, management, exclusive editing, lost draft, responsive layout", { skip: !browserPath }, async t => {
  const bundle = await build({ bundle: true, write: false, format: "esm", jsx: "automatic", outdir: "out", logLevel: "silent",
    define: { "import.meta.env.VITE_API_BASE_URL": "undefined" },
    stdin: { resolveDir: webRoot, loader: "jsx", contents: `
      import React, {useEffect,useState} from 'react'; import {createRoot} from 'react-dom/client';
      import {BrowserRouter,Link,useLocation} from 'react-router-dom';
      import {AccountRoot} from './src/accounts/AccountRoot.jsx';
      import {registerAccountFlusher,accountRequest} from './src/accounts/account-client.js';
      import './src/styles.css';
      function Fixture() {
        const location=useLocation(), [value,setValue]=useState('原始局部提示词');
        useEffect(()=>registerAccountFlusher(async()=>{window.flushes=(window.flushes||0)+1;if(window.blockFlush)throw new Error('保存尚未完成');return true;}),[]);
        return <main className="account-readonly"><h1>创作工作台</h1><Link to="/projects/${projectId}">打开项目</Link>
          {location.pathname.includes('${projectId}') && <label className="account-field"><span>局部提示词</span><textarea value={value} onChange={e=>setValue(e.target.value)} /></label>}
          <button className="secondary-button" onClick={()=>accountRequest('/productions/${projectId}/fixture',{method:'PUT',body:{value}}).catch(()=>{})}>保存草稿</button>
        </main>;
      }
      createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><AccountRoot><Fixture/></AccountRoot></BrowserRouter></React.StrictMode>);
    ` },
  });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).contents;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).contents;
  const html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/fixture.js"></script></html>';
  const user = { user_id: "user-1", account_id: "account-1", auth_mode: "password", role: "owner", account_kind: "enterprise", account_name: "企业账户", display_name: "负责人", csrf_token: "user-csrf" };
  const admin = { admin_id: "admin-1", auth_mode: "password", principal_type: "platform_admin", display_name: "admin", csrf_token: "admin-csrf" };
  const state = { lease: null, requests: [], rejectWrite: false, initialized: false,
    quota: 10000000000, storageConnection: {}, historyTrashed: false, storageFailed: false,
    historyDeleted: false, memberPhone: "13800000001", phoneFailure: null, holdPhone: false };
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://fixture").pathname;
    if (!path.startsWith("/api/")) {
      response.setHeader("Content-Type", path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css" : "text/html; charset=utf-8");
      response.end(path === "/fixture.js" ? js : path === "/fixture.css" ? css : html); return;
    }
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    state.requests.push({ path, method: request.method, headers: request.headers, body });
    response.setHeader("Content-Type", "application/json");
    const send = (value, status = 200) => { response.statusCode = status; response.end(JSON.stringify(value)); };
    const isAdmin = path.includes("/admin/");
    if (path.endsWith("/auth/status")) return send({ auth_mode: "password", initialized: state.initialized, setup_allowed: true });
    if (path.endsWith("/auth/setup")) { state.initialized = true; return send({ initialized: true }); }
    if (path.endsWith("/auth/login")) {
      response.setHeader("Set-Cookie", `${isAdmin ? "test_admin" : "test_user"}=active; Path=/; HttpOnly; SameSite=Lax`);
      return send(isAdmin ? admin : user);
    }
    const cookieName = isAdmin ? "test_admin=active" : "test_user=active";
    if (!request.headers.cookie?.includes(cookieName)) return send({ detail: { code: "login_required", message: "请先登录" } }, 401);
    if (path.endsWith("/session")) return send(isAdmin ? admin : user);
    const quota = () => ({ used_bytes: 8500000000, limit_bytes: state.quota, reserved_bytes: 1000000, available_bytes: state.quota - 8501000000 });
    if (path === "/api/v1/admin/storage/server") return send({ url: "https://server.example.com" });
    if (path === "/api/v1/admin/accounts/account-1/storage") {
      if (request.method === "PATCH") state.quota = body.limit_bytes;
      return send({ ...quota(), audit: [{ id: "audit-1", created_at: 1700000000, details: JSON.stringify({ previous: 10000000000, next: state.quota, note: "测试扩容" }) }] });
    }
    if (path === "/api/v1/account/storage") return send({ ...quota(), connection: state.storageConnection, server_url: "https://server.example.com", secret_store_available: true, jobs: [], inventory_state: "ready" });
    if (path === "/api/v1/account/storage/remote-usage") return state.storageFailed ? send({ detail: { code: "storage_device_expired", message: "请重新连接服务器" } }, 409) : send(quota());
    if (path === "/api/v1/account/storage/connection") {
      state.storageConnection = request.method === "DELETE" ? {} : { account_id: "remote-account", account_kind: "enterprise", account_name: "服务器企业账户", server_url: "https://server.example.com", confirmed: false };
      return send(state.storageConnection);
    }
    if (path === "/api/v1/account/storage/connection/confirm") { state.storageConnection.confirmed = true; return send(state.storageConnection); }
    if (path === "/api/v1/account/storage/sync") return send({ started: true });
    if (path === "/api/v1/account/storage/history") {
      const query = new URL(request.url, "http://fixture").searchParams;
      const show = !state.historyDeleted && query.get("kind") === "image" && (query.get("trash") === "true") === state.historyTrashed;
      return send({ total: show ? 1 : 0, items: show ? [{ key: "candidate:fixture", kind: "image", created_at: 1700000000, size_bytes: 1230000,
        metadata: { project_name: "电影感产品故事 · 黄色滤芯的多角度产品画面", model: "本机 ImageGen", prompt_snapshot: "产品特写，柔和光照。" }, content_url: "/api/v1/account/storage/entries/fixture/content" }] : [] });
    }
    if (path.endsWith("/entries/fixture/content")) { response.setHeader("Content-Type", "image/png"); response.end(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG3cAAAAASUVORK5CYII=", "base64")); return; }
    if (path.includes("/account/storage/entries/candidate")) {
      if (path.endsWith("/trash")) state.historyTrashed = true;
      if (path.endsWith("/restore")) state.historyTrashed = false;
      if (request.method === "DELETE") state.historyDeleted = true;
      return send({ done: true });
    }
    if (path.endsWith("/auth/logout")) {
      response.setHeader("Set-Cookie", `${isAdmin ? "test_admin" : "test_user"}=; Path=/; Max-Age=0`); state.lease = null; return send({ logged_out: true });
    }
    if (path.includes("/edit-lease/")) {
      const action = path.split("/").at(-1), owns = state.lease?.token === body.token;
      if (action === "release") { if (owns) state.lease = null; return send({ editable: false }); }
      if (!state.lease || owns) { state.lease = body; return send({ editable: true, occupied: true }); }
      return send({ editable: false, occupied: true, display_name: "另一位成员" });
    }
    if (path.endsWith("/readonly")) return send({ name: "只读项目", productions: [{ id: "p", name: "分镜图片", shots: [{ id: "s", index: 1, images: [], image_prompt: "已保存提示词" }] }] });
    if (path.endsWith("/fixture")) return send(state.rejectWrite ? { detail: { code: "edit_lease_lost", message: "编辑权已失效" } } : {}, state.rejectWrite ? 423 : 200);
    if (path === "/api/v1/admin/accounts/account-1/members/user-1/phone") {
      if (state.phoneFailure) return send({ detail: state.phoneFailure }, 409);
      if (body.username === "13800000002") return send({ detail: { code: "username_exists", message: "该手机号已被其他用户使用，请更换手机号" } }, 409);
      if (state.holdPhone) await new Promise(resolvePhone => { state.releasePhone = resolvePhone; });
      state.memberPhone = body.username;
      return send({ updated: true, id: "user-1", username: body.username });
    }
    if (path.endsWith("/members")) {
      if (request.method === "POST") return send({ activation_token: "one-time-activation", username: body.username });
      return send({ items: [{ id: "user-1", display_name: "负责人", username: state.memberPhone, role: "owner", status: "active" }, { id: "user-2", display_name: "另一位成员", username: "13800000002", role: "member", status: "active" }] });
    }
    if (path.endsWith("/admin/accounts")) {
      if (request.method === "POST") return send({ activation_token: "one-time-activation", username: body.username });
      return send({ items: [{ id: "account-1", kind: "enterprise", name: "企业账户", status: "active", member_count: 2, storage: quota() }] });
    }
    return send({});
  });
  await new Promise(resolveServer => server.listen(0, "127.0.0.1", resolveServer));
  const base = `http://127.0.0.1:${server.address().port}`;
  const profile = await mkdtemp(join(tmpdir(), "viral-account-browser-"));
  const chrome = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  const exited = new Promise(resolveExit => chrome.once("exit", resolveExit));
  let client;
  try {
    const debug = await new Promise((resolveDebug, reject) => {
      let output = ""; const timer = setTimeout(() => reject(new Error("Browser startup timed out")), 10000);
      chrome.once("error", error => { clearTimeout(timer); reject(error); });
      chrome.stderr.on("data", data => { output += data; const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timer); resolveDebug(match[1]); } });
    });
    const target = await fetch(`http://${new URL(debug).host}/json/new?about:blank`, { method: "PUT" }).then(response => response.json());
    client = await connect(target.webSocketDebuggerUrl);
    const send = (method, params) => client.send(method, params);
    async function evaluate(expression) {
      const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    }
    async function ready(expression) {
      for (let attempt = 0; attempt < 120; attempt++) { if (await evaluate(`Boolean(${expression})`)) return; await pause(25); }
      assert.fail(`Timed out: ${expression}; ${await evaluate("document.body.innerText")}`);
    }
    async function load(path, width = 1280) {
      await send("Emulation.setDeviceMetricsOverride", { width, height: 860, deviceScaleFactor: 1, mobile: false });
      await send("Page.navigate", { url: base + path });
      await ready("document.querySelector('.account-login-panel,.account-session-bar')");
    }
    async function fill(name, value) {
      await evaluate(`(()=>{const el=document.querySelector('[name="${name}"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    }
    async function screenshot(name, width) {
      if (!process.env.ACCOUNT_SCREENSHOT_DIR) return;
      if (name.startsWith('account-phone-')) {
        await evaluate("document.querySelector('.account-phone-form').scrollIntoView({block:'center',behavior:'instant'})");
        await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");
      }
      const shot = await send("Page.captureScreenshot", { format: "png" });
      await writeFile(join(process.env.ACCOUNT_SCREENSHOT_DIR, `${name}-${width}.png`), Buffer.from(shot.data, "base64"));
    }
    await send("Page.enable"); await send("Runtime.enable");
    await t.test("initial setup needs no code and submits mobile plus eight-character passwords", async () => {
      await load("/login");
      await ready("document.querySelector('input[name=admin_password]')");
      assert.equal(await evaluate("document.querySelector('input[name=setup_token]')"), null);
      assert.doesNotMatch(await evaluate("document.body.innerText"), /初始化码|setup-token/);
      assert.equal(await evaluate("document.querySelector('input[name=admin_password]').minLength"), 8);
      assert.equal(await evaluate("document.querySelector('input[name=owner_password]').minLength"), 8);
      await screenshot("account-initialization", 1280);
      await fill("name", "测试企业"); await fill("username", "13800000001");
      await fill("display_name", "负责人"); await fill("admin_password", "1234567");
      await fill("owner_password", "abcdefgh");
      await evaluate("document.querySelector('.account-checkbox input').click()");
      await evaluate("document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");
      await ready("document.querySelector('.account-error')?.textContent.includes('8–128')");
      assert.equal(state.requests.filter(item => item.path.endsWith('/auth/setup')).length, 0);
      await fill("admin_password", "12345678");
      await evaluate("document.querySelector('form').requestSubmit()");
      await ready("document.querySelector('input[name=password]')");
      const setup = state.requests.filter(item => item.path.endsWith('/auth/setup'));
      assert.equal(setup.length, 1);
      assert.equal(setup[0].body.username, "13800000001");
      assert.equal(setup[0].body.admin_password.length, 8);
      assert.equal(setup[0].body.owner_password.length, 8);
      assert.equal(Object.hasOwn(setup[0].body, 'setup_token'), false);
      assert.equal(Object.hasOwn(setup[0].body, 'password'), false);
    });
    await t.test("front login is independent and responsive", async () => {
      for (const width of [1280, 700, 390]) {
        await load("/login", width); await ready("document.querySelector('input[name=username]')");
        assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false);
        if (width <= 760) assert.equal(await evaluate("getComputedStyle(document.querySelector('input')).fontSize"), "16px");
        await screenshot("account-login", width);
      }
      assert.equal(await evaluate("document.querySelector('input[name=username]').type"), "tel");
      assert.equal(await evaluate("document.querySelector('input[name=password]').minLength"), 8);
      await fill("username", "not-mobile"); await fill("password", "12345678");
      await evaluate("document.querySelector('form').requestSubmit()");
      assert.equal(await evaluate("document.querySelector('input[name=username]').validity.patternMismatch"), true);
      assert.equal(state.requests.filter(item => item.path.endsWith('/auth/login')).length, 0);
      await evaluate("(()=>{const data=new DataTransfer();data.setData('text',' 13800000001 ');document.querySelector('input[name=username]').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));})()");
      assert.equal(await evaluate("document.querySelector('input[name=username]').value"), "13800000001");
      assert.equal(await evaluate("document.querySelector('input[name=password]').hasAttribute('maxlength')"), false);
      await evaluate("document.querySelector('form').requestSubmit()");
      await ready("document.querySelector('.account-session-bar')");
      assert.doesNotMatch(await evaluate("document.body.innerText"), /切换空间|个人空间|企业空间/);
    });
    await t.test("StrictMode acquisition does not lock out its own editor; failed save preserves draft", async () => {
      state.requests = [];
      await evaluate(`document.querySelector('a[href="/projects/${projectId}"]').click()`);
      await ready("document.querySelector('textarea')");
      assert.equal(state.requests.filter(item => item.path.endsWith("/edit-lease/acquire")).length, 1);
      await evaluate("(()=>{const el=document.querySelector('textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el,'未提交的新提示词');el.dispatchEvent(new Event('input',{bubbles:true}));})()");
      state.rejectWrite = true;
      await evaluate("document.querySelector('main button').click()");
      await ready("document.querySelector('[inert]')");
      assert.equal(await evaluate("document.querySelector('textarea').value"), "未提交的新提示词");
      assert.match(await evaluate("document.querySelector('.account-edit-notice').textContent"), /下载备份/);
      const write = state.requests.find(item => item.path.endsWith("/fixture"));
      assert.equal(write.headers["x-csrf-token"], "user-csrf"); assert.ok(write.headers["x-edit-token"]);
      state.rejectWrite = false;
    });
    await t.test("occupied project never mounts the editable form or writes drafts", async () => {
      state.lease = { token: "another-browser" }; state.requests = [];
      await load(`/projects/${projectId}`, 390);
      await ready("document.querySelector('.account-readonly h1')?.textContent==='只读项目'");
      assert.equal(await evaluate("document.querySelector('textarea')"), null);
      assert.match(await evaluate("document.body.innerText"), /另一位成员 正在编辑/);
      assert.equal(state.requests.filter(item => ["PUT", "PATCH", "DELETE"].includes(item.method)).length, 0);
      await screenshot("account-readonly", 390);
    });
    await t.test("member list and long account names remain within the viewport", async () => {
      user.display_name = "负责人姓名".repeat(20); user.account_name = "企业名称".repeat(20);
      for (const width of [1280, 390]) {
        await load("/account/members", width); await ready("document.querySelector('.account-table-wrap tbody tr')");
        assert.equal(await evaluate("document.querySelector('button[aria-label$=\"：修改手机号\"]')"), null);
        assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false);
        assert.equal(await evaluate("document.querySelector('.account-table-wrap').scrollWidth >= 640"), true);
        await screenshot("account-members", width);
      }
      user.display_name = "负责人"; user.account_name = "企业账户";
    });
    await t.test("enterprise invitations require a mobile number and explain eight-character passwords", async () => {
      await evaluate("document.querySelector('.account-management-heading button').click()");
      await ready("document.querySelector('.account-create-form')");
      await fill("username", "not-mobile"); await fill("display_name", "新成员");
      await evaluate("document.querySelector('.account-create-form').requestSubmit()");
      assert.equal(await evaluate("document.querySelector('input[name=username]').validity.patternMismatch"), true);
      assert.match(await evaluate("document.querySelector('.account-create-form').textContent"), /至少 8 位密码/);
      await fill("username", "13800000003");
      await evaluate("document.querySelector('.account-create-form').requestSubmit()");
      await ready("document.querySelector('.account-activation-link')");
      assert.equal(state.requests.find(item => item.path.endsWith('/account/members') && item.method === 'POST').body.username, '13800000003');
    });
    await t.test("logout waits for successful draft flush", async () => {
      state.lease = null; await load("/projects"); await ready("document.querySelector('.account-menu > button')");
      await evaluate("window.blockFlush=true;document.querySelector('.account-menu > button').click()");
      await evaluate("[...document.querySelectorAll('.account-menu-panel button')].find(b=>b.textContent.includes('退出登录')).click()");
      await ready("document.querySelector('.account-error')?.textContent.includes('保存尚未完成')");
      assert.ok(await evaluate("document.querySelector('.account-session-bar')!==null"));
      await evaluate("window.blockFlush=false;[...document.querySelectorAll('.account-menu-panel button')].find(b=>b.textContent.includes('退出登录')).click()");
      await ready("document.querySelector('.account-login-panel')");
      assert.equal(await evaluate("window.flushes"), 2);
    });
    await t.test("admin has its own login and account creation form", async () => {
      await load("/admin/login"); await ready("document.querySelector('input[name=username]')?.value==='admin'");
      await fill("password", "fixture-admin-password"); await evaluate("document.querySelector('form').requestSubmit()");
      await ready("document.querySelector('.account-management h1')?.textContent==='账户管理'");
      await evaluate("document.querySelector('.account-management-heading button').click()");
      await ready("document.querySelector('.account-create-form')");
      assert.equal(await evaluate("[...document.querySelectorAll('.account-create-form select option')].map(o=>o.textContent).join(',')"), "个人账户,企业账户");
      await screenshot("account-admin", 1280);
      assert.equal(await evaluate("document.querySelector('input[name=username]').type"), "tel");
      await fill("name", "新个人账户"); await fill("display_name", "新用户");
      await fill("username", "13900000001");
      await evaluate("document.querySelector('.account-create-form').requestSubmit()");
      await ready("document.querySelector('.account-activation-link')");
      assert.equal(state.requests.find(item => item.path.endsWith('/admin/accounts') && item.method === 'POST').body.username, '13900000001');
    });
    await t.test("admin can inspect and increase shared storage quota", async () => {
      await load("/admin/accounts");
      await ready("[...document.querySelectorAll('button')].some(b=>b.textContent==='用户与容量')");
      await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='用户与容量').click()");
      await ready("document.querySelector('.storage-quota-form input[type=number]')?.value==='10'");
      await evaluate("(()=>{const input=document.querySelector('.storage-quota-form input[type=number]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'20');input.dispatchEvent(new Event('input',{bubbles:true}));})()");
      await evaluate("document.querySelector('.storage-quota-form:has(input[type=number])').requestSubmit()");
      await ready("document.querySelector('.storage-quota-form:has(input[type=number])').textContent.includes('20 GB')");
      assert.equal(state.quota, 20000000000);
      await screenshot("storage-admin", 1280);
    });
    await t.test("admin phone edit validates, confirms, cancels, keeps failed drafts and prevents duplicate writes", async () => {
      const changes = () => state.requests.filter(item => item.path.endsWith('/phone'));
      const open = async () => {
        await ready("document.querySelector('button[aria-label=\"负责人：修改手机号\"]') && !document.querySelector('button[aria-label=\"负责人：修改手机号\"]').disabled");
        await evaluate("document.querySelector('button[aria-label=\"负责人：修改手机号\"]').click()");
        await ready("document.querySelector('[name=new_phone]')");
      };
      const submit = () => evaluate("document.querySelector('.account-phone-form').requestSubmit()");
      for (const width of [1440, 1280, 1024, 768, 390]) {
        await load('/admin/accounts', width);
        await ready("[...document.querySelectorAll('button')].some(b=>b.textContent==='用户与容量')");
        await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='用户与容量').click()");
        await ready("document.querySelector('button[aria-label=\"负责人：修改手机号\"]')");
        await open();
        assert.equal(await evaluate("document.activeElement.name"), 'new_phone');
        assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false);
        await screenshot('account-phone-edit', width);
        await fill('new_phone', '13900000009'); await submit();
        await ready("document.querySelector('.account-phone-review')");
        assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false);
        assert.match(await evaluate("document.querySelector('.account-phone-form').textContent"), /13800000001[\s\S]*13900000009/);
        await screenshot('account-phone-confirm', width);
        await evaluate("[...document.querySelectorAll('.account-phone-form button')].find(b=>b.textContent==='取消').click()");
        await ready("!document.querySelector('.account-phone-form')");
        assert.equal(await evaluate("document.activeElement.getAttribute('aria-label')"), '负责人：修改手机号');
      }
      assert.equal(changes().length, 0);
      await open();
      await evaluate("document.querySelector('.account-phone-form').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))");
      await ready("!document.querySelector('.account-phone-form')");
      assert.equal(await evaluate("document.activeElement.getAttribute('aria-label')"), '负责人：修改手机号');
      await open();
      await fill('new_phone', '123'); await submit();
      await ready("document.querySelector('.account-phone-form [role=alert]')?.textContent.includes('11 位')");
      await fill('new_phone', '13800000001'); await submit();
      await ready("document.querySelector('.account-phone-form [role=alert]')?.textContent.includes('不能与当前')");
      assert.equal(changes().length, 0);
      await fill('new_phone', '13800000002'); await submit();
      await ready("document.querySelector('.account-phone-review')"); await submit();
      await ready("document.querySelector('.account-phone-form [role=alert]')?.textContent.includes('已被其他')");
      assert.equal(await evaluate("document.querySelector('[name=new_phone]').value"), '13800000002');
      assert.equal(state.memberPhone, '13800000001');
      state.phoneFailure = { code: 'username_changed', message: '手机号已被修改，请重新读取用户列表后再试' };
      await fill('new_phone', '13900000009'); await submit();
      await ready("document.querySelector('.account-phone-review')"); await submit();
      await ready("document.querySelector('.account-phone-form [role=alert]')?.textContent.includes('重新读取')");
      assert.equal(await evaluate("document.querySelector('.account-phone-form button[type=submit]')"), null);
      state.phoneFailure = null;
      await evaluate("[...document.querySelectorAll('.account-phone-form button')].find(b=>b.textContent==='重新读取用户列表').click()");
      await ready("!document.querySelector('.account-phone-form') && document.querySelector('button[aria-label=\"负责人：修改手机号\"]')?.disabled === false");
      await open(); await fill('new_phone', '13900000009'); await submit();
      await ready("document.querySelector('.account-phone-review')");
      state.holdPhone = true;
      const count = changes().length;
      await evaluate("(()=>{const form=document.querySelector('.account-phone-form');form.requestSubmit();form.requestSubmit();})()");
      await ready("document.querySelector('.account-phone-form fieldset').disabled");
      for (let i = 0; i < 100 && !state.releasePhone; i++) await pause(20);
      assert.equal(changes().length, count + 1);
      await evaluate("document.querySelector('.account-phone-form').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))");
      assert.equal(await evaluate("Boolean(document.querySelector('.account-phone-form'))"), true);
      state.releasePhone(); state.holdPhone = false;
      await ready("!document.querySelector('.account-phone-form')");
      assert.equal(state.memberPhone, '13900000009');
      assert.match(await evaluate("document.querySelector('.account-management').textContent"), /手机号已修改/);
      assert.equal(await evaluate("document.activeElement.getAttribute('aria-label')"), '负责人：修改手机号');
      const request = changes().at(-1);
      assert.equal(request.method, 'PATCH');
      assert.equal(request.headers['x-csrf-token'], 'admin-csrf');
      assert.deepEqual(request.body, { current_username: '13800000001', username: '13900000009', confirm_change: true });
    });
    await t.test("storage needs target confirmation, survives remote failure and fits narrow screens", async () => {
      state.quota = 10000000000;
      await load("/login"); await ready("document.querySelector('input[name=username]')");
      await fill("username", "13800000001"); await fill("password", "12345678");
      await evaluate("document.querySelector('.account-login-panel form').requestSubmit()");
      await ready("document.querySelector('.account-session-bar')");
      for (const width of [1440, 1024, 390]) {
        await load("/account/storage", width);
        await ready("document.querySelector('.storage-history-row')");
        assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"), false);
        assert.equal(await evaluate("document.querySelector('.storage-history-info details').open"), false);
        assert.equal(await evaluate("document.querySelector('.storage-sync-section .primary-button').disabled"), true);
        await screenshot("storage-history", width);
      }
      await evaluate("document.querySelector('.storage-sync-section details').open=true");
      await evaluate("(()=>{for (const [selector,value] of [['input[type=tel]','13800000009'],['input[type=password]','12345678']]){const input=document.querySelector('.storage-connection-form '+selector);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));}})()");
      await evaluate("document.querySelector('.storage-connection-form').requestSubmit()");
      await ready("document.querySelector('.storage-confirmation')?.textContent.includes('确认目标账户')");
      assert.equal(state.storageConnection.confirmed, false);
      assert.equal(state.requests.some(item=>item.path==='/api/v1/account/storage/sync'), false);
      await evaluate("document.querySelector('.storage-confirmation button').click()");
      await ready("!document.querySelector('.storage-sync-section .primary-button').disabled");
      await evaluate("document.querySelector('.storage-sync-section .primary-button').click()");
      await ready("document.body.textContent.includes('已开始后台同步')");
      state.storageFailed = true;
      await evaluate("document.querySelector('.account-management-heading button').click()");
      await ready("document.body.textContent.includes('服务器容量暂不可用')");
      assert.ok(await evaluate("Boolean(document.querySelector('.account-session-bar'))"));
      assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"), false);
      await screenshot("storage-remote-error", 390);
    });
    await t.test("history deletion requires the recycle bin and explicit confirmation", async () => {
      await evaluate("[...document.querySelectorAll('.storage-row-actions button')].find(b=>b.textContent==='移入回收站').click()");
      await ready("document.body.textContent.includes('暂无此类记录')");
      await evaluate("document.querySelector('.storage-history-heading input[type=checkbox]').click()");
      await ready("document.querySelector('.storage-history-row')");
      await evaluate("[...document.querySelectorAll('.storage-row-actions button')].find(b=>b.textContent==='永久删除').click()");
      assert.equal(state.historyDeleted, false);
      await ready("document.querySelector('.storage-confirmation')?.textContent.includes('不可撤销') || document.querySelector('.storage-confirmation')?.textContent.includes('不能撤销')");
      await evaluate("[...document.querySelectorAll('.storage-tabs button')].find(b=>b.textContent==='生成视频').click()");
      await ready("!document.querySelector('.storage-confirmation')");
      assert.equal(state.historyDeleted, false);
      await evaluate("[...document.querySelectorAll('.storage-tabs button')].find(b=>b.textContent==='生成图片').click()");
      await ready("document.querySelector('.storage-history-row')");
      await evaluate("document.querySelector('.storage-history-info details').open=true");
      assert.equal(await evaluate("Boolean(document.querySelector('.storage-history-preview'))"), true);
      await evaluate("[...document.querySelectorAll('.storage-row-actions button')].find(b=>b.textContent==='永久删除').click()");
      await ready("document.querySelector('.storage-history-row .storage-confirmation')?.textContent.includes('电影感产品故事')");
      await evaluate("[...document.querySelectorAll('.storage-confirmation button')].find(b=>b.textContent==='确认永久删除').click()");
      await ready("document.body.textContent.includes('回收站中没有此类文件')");
      assert.equal(state.historyDeleted, true);
    });
  } finally {
    state.releasePhone?.();
    await client?.send("Browser.close").catch(() => {}); client?.close();
    if (chrome.exitCode === null) await Promise.race([exited, pause(3000)]);
    if (chrome.exitCode === null) { chrome.kill(); await Promise.race([exited, pause(3000)]); }
    await new Promise(resolveServer => server.close(resolveServer));
    if (dirname(resolve(profile)) === resolve(tmpdir()) && basename(profile).startsWith("viral-account-browser-")) await rm(profile, { recursive: true, force: true, maxRetries: 4, retryDelay: 250 });
  }
});
