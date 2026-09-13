import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { checkLoginState, loginFailureMessage, requestPasswordLogin } from "../src/accounts/login-service.js";
import { currentAccountSession, setAccountSession } from "../src/accounts/account-client.js";

const originalFetch = globalThis.fetch;
const account = { user_id: "fixture-user", account_id: "fixture-account", csrf_token: "fixture-csrf" };
const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
test.afterEach(() => { globalThis.fetch = originalFetch; setAccountSession(null); setAccountSession(null, true); });

test("public gate shows the form only after checking the installation and unauthenticated session", async () => {
  const requests = [];
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    requests.push(url); assert.equal(options.signal, controller.signal); assert.equal(options.credentials, "include");
    return url.endsWith("/auth/status") ? Response.json({ auth_mode: "password", initialized: true }) : Response.json({ detail: "请先登录" }, { status: 401 });
  };
  assert.deepEqual(await checkLoginState(controller.signal), { phase: "ready" });
  assert.deepEqual(requests, ["/api/v1/auth/status", "/api/v1/session"]);
});

test("first setup is explicit and does not request a session or initialize anything", async () => {
  for (const setupAllowed of [true, false]) {
    let calls = 0;
    globalThis.fetch = async url => { calls++; assert.equal(url, "/api/v1/auth/status"); return Response.json({ auth_mode: "password", initialized: false, setup_allowed: setupAllowed }); };
    assert.deepEqual(await checkLoginState(), { phase: "setup", setupAllowed });
    assert.equal(calls, 1);
  }
});

test("existing sessions are returned without password submission or changing session state", async () => {
  globalThis.fetch = async url => url.endsWith("/auth/status") ? Response.json({ auth_mode: "password", initialized: true }) : Response.json(account);
  setAccountSession(null);
  assert.deepEqual(await checkLoginState(), { phase: "authenticated", session: account });
  assert.equal(currentAccountSession(), null);
});

test("missing and malformed login responses never become a successful login", async () => {
  globalThis.fetch = async () => new Response("<!doctype html>", { status: 200 });
  await assert.rejects(checkLoginState(), /返回异常/);
  globalThis.fetch = async () => Response.json({ auth_mode: "password", initialized: true });
  await assert.rejects(checkLoginState(), /返回异常/);
  await assert.rejects(requestPasswordLogin({ username: "13800000001", password: "12345678" }), /返回异常/);
});

test("shared password login enforces existing rules, propagates abort, and never stores credentials", async () => {
  let calls = 0;
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    calls++; assert.equal(url, "/api/v1/auth/login"); assert.equal(options.signal, controller.signal);
    assert.deepEqual(JSON.parse(options.body), { username: "13800000001", password: "12345678" });
    return Response.json(account);
  };
  await assert.rejects(requestPasswordLogin({ username: "name", password: "12345678" }), /手机号/);
  await assert.rejects(requestPasswordLogin({ username: "13800000001", password: "1234567" }), /8–128/);
  assert.equal(calls, 0);
  assert.deepEqual(await requestPasswordLogin({ username: " 13800000001 ", password: "12345678" }, { signal: controller.signal }), account);
  assert.equal(currentAccountSession(), null);
});

test("admin login remains independent and does not require a phone number", async () => {
  const admin = { admin_id: "fixture-admin", csrf_token: "fixture-admin-csrf" };
  globalThis.fetch = async (url, options) => { assert.equal(url, "/api/v1/admin/auth/login"); assert.equal(JSON.parse(options.body).username, "admin"); return Response.json(admin); };
  assert.deepEqual(await requestPasswordLogin({ username: "admin", password: "12345678" }, { admin: true }), admin);
  assert.equal(currentAccountSession(true), null);
});

test("connection failure, credential rejection and input validation have distinct recovery copy", () => {
  for (const error of [new TypeError("Failed to fetch"), { status: 500 }, { status: 502 }, { name: "AbortError" }]) assert.match(loginFailureMessage(error), /连接登录服务/);
  assert.match(loginFailureMessage({ status: 401 }), /手机号或密码不正确/);
  assert.match(loginFailureMessage({ status: 429 }), /频繁/);
  assert.equal(loginFailureMessage(new Error("请填写手机号")), "请填写手机号");
});

test("public dialog is lazy, scoped, abortable and does not load the private account root", () => {
  const main = read("../src/main.jsx"), dialog = read("../src/landing/LoginDialog.jsx"), form = read("../src/landing/PublicLoginForm.jsx"), home = read("../src/landing/HomePage.jsx"), css = read("../src/landing/login.css");
  assert.match(main, /location.pathname === "\/" \|\| location.pathname === "\/login"/);
  assert.match(dialog, /lazy\(\(\) => import\("\.\/PublicLoginForm.jsx"\)/);
  assert.doesNotMatch(dialog + form, /AccountRoot|StorageManagement|\.\.\/styles\.css|localStorage|sessionStorage/);
  assert.match(dialog, /showModal\(\)/); assert.match(dialog, /onCancel=/); assert.match(dialog, /visualViewport/);
  assert.match(form, /submitRequest.current\?\.abort\(\)/);
  assert.match(form, /submitRequest.current !== controller/);
  assert.match(home, /!loginOpen/); assert.match(home, /homepageLogin: true/); assert.match(home, /to="\/admin\/login"/);
  assert.match(css, /prefers-reduced-motion: no-preference/);
  assert.doesNotMatch(css, /:root\s*\{|--type-|--text-primary/);
});
