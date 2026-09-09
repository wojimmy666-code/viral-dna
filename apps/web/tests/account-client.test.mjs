import assert from "node:assert/strict";
import test from "node:test";
import {
  accountFetch, accountHeaders, accountRequest, accountStorageKey,
  flushAccountDrafts, registerAccountFlusher, setAccountSession, setProjectEditing,
} from "../src/accounts/account-client.js";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
const user = () => ({ account_id: "enterprise-a", user_id: "owner-a", csrf_token: "user-csrf" });
const editor = () => ({ projectId: "project-a", editor_id: "tab-a", token: "edit-token-a" });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
let events;
test.beforeEach(() => {
  events = [];
  globalThis.window = { dispatchEvent: event => events.push(event) };
  setAccountSession(user()); setAccountSession({ csrf_token: "admin-csrf" }, true);
  setProjectEditing(editor());
});
test.afterEach(() => { globalThis.fetch = originalFetch; globalThis.window = originalWindow; setAccountSession(null); setAccountSession(null, true); setProjectEditing(null); });

test("cookies and user/admin CSRF remain separate; admin receives no edit token", async () => {
  const headers = accountHeaders("/api/v1/projects", { "Content-Type": "application/json" });
  assert.equal(headers.get("X-CSRF-Token"), "user-csrf");
  assert.equal(headers.get("X-Editor-Id"), "tab-a");
  assert.equal(headers.get("Content-Type"), "application/json");
  const admin = accountHeaders("/api/v1/admin/accounts");
  assert.equal(admin.get("X-CSRF-Token"), "admin-csrf");
  assert.equal(admin.has("X-Edit-Token"), false);
  globalThis.fetch = async (url, options) => { assert.equal(options.credentials, "include"); return Response.json({ ok: true }); };
  assert.deepEqual(await accountRequest("/projects"), { ok: true });
});

test("private browser draft keys are isolated by account AND enterprise member", () => {
  const ownerKey = accountStorageKey("draft");
  setAccountSession({ ...user(), user_id: "member-a" });
  const memberKey = accountStorageKey("draft");
  setAccountSession({ ...user(), account_id: "personal-b" });
  const personalKey = accountStorageKey("draft");
  assert.equal(new Set([ownerKey, memberKey, personalKey]).size, 3);
  setAccountSession(null); assert.equal(accountStorageKey("legacy"), "legacy");
});

test("a real lost lease freezes only its active editor; busy list actions do not", async () => {
  globalThis.fetch = async () => Response.json({ detail: { code: "project_busy" } }, { status: 423 });
  await accountFetch("/api/v1/projects/batch", { method: "POST" });
  assert.equal(events.length, 0);
  globalThis.fetch = async () => Response.json({ detail: { code: "edit_lease_lost" } }, { status: 423 });
  await accountFetch("/api/v1/production-shots/shot-a", { method: "PATCH" });
  assert.equal(events[0].type, "viraldna:edit-unavailable");
  assert.equal(events[0].detail.projectId, "project-a");
});

test("late 423 responses cannot freeze a new editor, including during JSON decoding", async () => {
  const response = deferred();
  globalThis.fetch = () => response.promise;
  const pending = accountFetch("/api/v1/production-shots/shot-a");
  setProjectEditing({ ...editor(), token: "new-token" });
  response.resolve(Response.json({ detail: { code: "edit_lease_lost" } }, { status: 423 }));
  await pending; assert.equal(events.length, 0);
  const payload = deferred();
  globalThis.fetch = async () => ({ status: 423, clone: () => ({ json: () => payload.promise }) });
  const decoding = accountFetch("/api/v1/production-shots/shot-a");
  await Promise.resolve();
  setProjectEditing({ ...editor(), token: "newer-token" });
  payload.resolve({ detail: { code: "edit_lease_lost" } });
  await decoding; assert.equal(events.length, 0);
});

test("late 401 responses do not expire a newly logged-in user; admin expiry is separate", async () => {
  const response = deferred(); globalThis.fetch = () => response.promise;
  const pending = accountFetch("/api/v1/projects");
  setAccountSession({ ...user(), user_id: "new-user" });
  response.resolve(new Response(null, { status: 401 }));
  await pending; assert.equal(events.length, 0);
  globalThis.fetch = async () => new Response(null, { status: 401 });
  await accountFetch("/api/v1/admin/accounts");
  assert.equal(events[0].type, "viraldna:session-expired");
  assert.equal(events[0].detail.admin, true);
  events.length = 0;
  await accountFetch("/api/v1/auth/login"); assert.equal(events.length, 0);
});

test("failed draft saving stops account navigation and unregister removes stale flushers", async () => {
  let called = 0;
  const stop = registerAccountFlusher(async () => { called++; return false; });
  await assert.rejects(flushAccountDrafts, /请先完成/);
  stop(); await flushAccountDrafts(); assert.equal(called, 1);
  const success = registerAccountFlusher(async () => { called++; return true; });
  try { await flushAccountDrafts(); assert.equal(called, 2); } finally { success(); }
});
