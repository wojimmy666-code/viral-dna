import assert from "node:assert/strict";
import test from "node:test";
import { accountSessionPaused, currentAccountSession, setAccountSession } from "../src/accounts/account-client.js";
import { startSessionActivity, samePrincipal } from "../src/accounts/session-activity.js";

function target() {
  const listeners = new Map();
  return {
    addEventListener(name, fn) { (listeners.get(name) || listeners.set(name, new Set()).get(name)).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
    emit(name, data = {}) { for (const fn of listeners.get(name) || []) fn({ isTrusted: true, ...data }); },
    size: () => [...listeners.values()].reduce((sum, items) => sum + items.size, 0),
  };
}
const settled = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function fixture(t, { admin = false, request } = {}) {
  let clock = 1000000, response, mode = "ok";
  const doc = Object.assign(target(), { visibilityState: "visible", focused: true, hasFocus() { return this.focused; } });
  const win = Object.assign(target(), { setInterval: () => 1, clearInterval() {}, setTimeout: () => 2, clearTimeout() {} });
  const messages = [], states = [], recovered = [], calls = [];
  const channel = Object.assign(target(), { postMessage(value) { messages.push(value); }, close() { this.closed = true; } });
  const duration = admin ? 7200 : 43200;
  const session = { ...(admin ? { admin_id: "admin-one" } : { user_id: "user-one", account_id: "account-one" }),
    csrf_token: "secret-csrf", session_started_at: 1000, session_server_time: 1000,
    session_expires_at: 1000 + duration, session_renew_after: 1300 };
  response = { ...session };
  setAccountSession(session, admin);
  const tracker = startSessionActivity({ admin, now: () => clock, documentTarget: doc, windowTarget: win,
    channelFactory: () => channel, onState: state => states.push(state), onRecovered: value => recovered.push(value),
    request: async (path, options) => {
      calls.push({ path, options });
      if (request) return request(path, options);
      if (mode !== "ok") throw Object.assign(new Error(mode), mode === "expired" ? { status: 401 } : mode === "csrf" ? { status: 403, code: "csrf_invalid" } : { status: 503 });
      if (path.endsWith("/refresh")) response = { ...response, session_expires_at: clock / 1000 + duration, session_renew_after: clock / 1000 + 300 };
      return { ...response, session_server_time: clock / 1000 };
    },
  });
  t.after(() => { tracker.stop(); setAccountSession(null, admin); });
  return { tracker, doc, win, channel, messages, states, recovered, calls, session,
    advance: ms => { clock += ms; }, mode: value => { mode = value; }, response: value => { response = value; } };
}

test("typing, dragging and scrolling renew at most once per five minutes without any save request", async t => {
  const f = fixture(t);
  f.doc.emit("input"); await settled(); assert.equal(f.calls.length, 0);
  f.advance(300000); f.doc.emit("input"); await settled();
  assert.equal(f.calls.length, 1); assert.equal(f.calls[0].path, "/auth/refresh");
  for (let i = 0; i < 20; i++) f.doc.emit("keydown");
  await settled(); assert.equal(f.calls.length, 1);
  f.advance(300000); f.doc.emit("dragend"); await settled();
  f.advance(300000); f.doc.emit("wheel"); await settled();
  assert.equal(f.calls.length, 3); assert.equal(f.recovered.length, 0);
  assert.ok(f.messages.every(message => !JSON.stringify(message).includes("secret-csrf")));
});

test("idle, background, synthetic events and passive playback/polling cannot keep a session alive", async t => {
  const f = fixture(t); f.advance(300001);
  await f.tracker.tick(); f.doc.emit("input", { isTrusted: false }); await settled();
  assert.equal(f.calls.length, 0);
  f.doc.visibilityState = "hidden"; f.doc.emit("input"); await f.tracker.tick();
  f.doc.visibilityState = "visible"; f.doc.focused = false; f.doc.emit("input");
  await settled(); assert.equal(f.calls.length, 0);
  f.doc.focused = true; f.win.emit("focus"); await settled();
  assert.equal(f.calls[0].path, "/session"); assert.equal(f.calls[0].options.method, undefined);
});

test("network failure keeps authentication and input; reconnect probes without replaying business writes", async t => {
  const f = fixture(t); f.advance(300000); f.mode("offline"); f.doc.emit("input"); await settled();
  assert.deepEqual(f.states, ["offline"]); assert.equal(accountSessionPaused(), false);
  await f.tracker.tick(); assert.equal(f.calls.length, 1);
  f.mode("ok"); f.advance(5000); await f.tracker.tick();
  assert.deepEqual(f.states, ["offline", "active"]);
  assert.equal(f.calls[1].path, "/session");
});

test("real expiry freezes only its principal, recovery requires the same user AND account", async t => {
  const f = fixture(t); setAccountSession({ admin_id: "admin-other" }, true);
  t.after(() => setAccountSession(null, true));
  f.mode("expired"); f.advance(300000); f.doc.emit("input"); await settled();
  assert.equal(accountSessionPaused(), true); assert.equal(accountSessionPaused(true), false);
  assert.deepEqual(f.states, ["expired"]);
  f.tracker.recover({ ...f.session, user_id: "different" });
  assert.equal(f.recovered.length, 0); assert.equal(accountSessionPaused(), true);
  f.tracker.recover({ ...f.session, csrf_token: "new-secret" });
  assert.equal(accountSessionPaused(), false); assert.equal(f.recovered.length, 1);
  assert.equal(samePrincipal(f.session, { ...f.session, account_id: "different" }), false);
});

test("admin activity uses a separate endpoint and does not alter front-end credentials", async t => {
  setAccountSession({ user_id: "front", account_id: "enterprise", csrf_token: "front-secret" });
  t.after(() => setAccountSession(null));
  const f = fixture(t, { admin: true }); f.advance(300000); f.doc.emit("pointerdown"); await settled();
  assert.equal(f.calls[0].path, "/admin/auth/refresh");
  assert.equal(currentAccountSession().csrf_token, "front-secret");
});

test("another tab's renewal is verified with the server; its message cannot resurrect a revoked session", async t => {
  const f = fixture(t);
  f.channel.emit("message", { data: { type: "renewed", scope: "user:account-one:user-one", started: 1000 } });
  await settled(); assert.equal(f.calls[0].path, "/session");
  f.tracker.expire(); f.channel.emit("message", { data: { type: "renewed", scope: "user:account-one:user-one", started: 1000 } });
  await settled(); assert.equal(f.calls.length, 1); assert.equal(accountSessionPaused(), true);
  f.mode("expired"); f.channel.emit("message", { data: { type: "recovered", scope: "user:account-one:user-one" } });
  await settled(); assert.equal(f.calls.length, 2); assert.equal(accountSessionPaused(), true);
});

test("resume after sleep checks server expiry even without an API save; missing cookie is not silently recreated", async t => {
  const f = fixture(t); f.advance(13 * 3600000); f.mode("expired");
  await f.tracker.tick(); assert.equal(f.calls[0].path, "/session");
  assert.deepEqual(f.states, ["expired"]);
});

test("late renewal cannot undo revocation or a new login; cleanup removes listeners and aborts work", async t => {
  let resolve;
  const f = fixture(t, { request: () => new Promise(done => { resolve = done; }) });
  f.advance(300000); f.doc.emit("input"); await settled();
  f.tracker.expire(); resolve({ ...f.session, session_expires_at: 9999999 }); await settled();
  assert.equal(accountSessionPaused(), true); assert.equal(f.recovered.length, 0);
  f.tracker.stop(); assert.equal(f.doc.size(), 0); assert.equal(f.win.size(), 0); assert.equal(f.channel.closed, true);
});
