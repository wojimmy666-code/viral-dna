import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { LEASE_CHECK_INTERVAL_MS, startProjectLeaseRecovery } from "../src/accounts/project-lease-recovery.js";

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = () => new Promise(resolve => setImmediate(resolve));
function fixture(request = async () => ({ occupied: true, display_name: "LC" })) {
  const windowTarget = new EventTarget(), documentTarget = new EventTarget();
  documentTarget.visibilityState = "visible";
  const intervals = new Map(), timeouts = new Map();
  let id = 0, current = true, acquisitions = 0;
  const requests = [], states = [], errors = [];
  windowTarget.setInterval = (fn, ms) => { const key = ++id; intervals.set(key, { fn, ms }); return key; };
  windowTarget.clearInterval = key => intervals.delete(key);
  windowTarget.setTimeout = (fn, ms) => { const key = ++id; timeouts.set(key, { fn, ms }); return key; };
  windowTarget.clearTimeout = key => timeouts.delete(key);
  const recovery = startProjectLeaseRecovery({ projectId: "project-a", windowTarget, documentTarget,
    isCurrent: () => current,
    request: (path, options) => { requests.push({ path, options }); return request(path, options); },
    onState: state => states.push(state), onAvailable: async () => { acquisitions++; },
    onError: error => errors.push(error),
  });
  return { recovery, requests, states, errors, intervals, timeouts, windowTarget, documentTarget,
    acquisitions: () => acquisitions, invalidate: () => { current = false; },
    poll: () => [...intervals.values()][0]?.fn(),
  };
}

test("readonly recovery checks at a bounded interval and never takes an occupied lease", async () => {
  const f = fixture();
  assert.equal(f.requests.length, 0, "no immediate acquire/retry loop");
  assert.equal([...f.intervals.values()][0].ms, LEASE_CHECK_INTERVAL_MS);
  await f.poll();
  assert.equal(f.requests[0].path, "/projects/project-a/edit-lease");
  assert.equal(f.requests[0].options.method, undefined, "availability is a read, not a renewal");
  assert.equal(f.states[0].display_name, "LC");
  assert.equal(f.acquisitions(), 0);
  f.recovery.stop();
});

test("a released or expired lease triggers the ordinary acquire flow", async () => {
  let occupied = true;
  const f = fixture(async () => ({ occupied }));
  await f.poll();
  occupied = false;
  await f.poll();
  assert.equal(f.acquisitions(), 1);
  assert.equal(f.states.at(-1).occupied, false);
  f.recovery.stop();
});

test("hidden tabs cannot acquire, including a response that arrives after hiding", async () => {
  const response = deferred();
  const f = fixture(() => response.promise);
  f.documentTarget.visibilityState = "hidden";
  await f.poll();
  assert.equal(f.requests.length, 0);
  f.documentTarget.visibilityState = "visible";
  f.documentTarget.dispatchEvent(new Event("visibilitychange"));
  assert.equal(f.requests.length, 1);
  f.documentTarget.visibilityState = "hidden";
  response.resolve({ occupied: false });
  await settle();
  assert.equal(f.acquisitions(), 0);
  assert.equal(f.states.length, 0);
  f.documentTarget.visibilityState = "visible";
  f.windowTarget.dispatchEvent(new Event("focus"));
  await settle();
  assert.equal(f.acquisitions(), 1);
  f.recovery.stop();
});

test("focus, reconnect and restored pages recheck without overlapping requests", async () => {
  const response = deferred();
  const f = fixture(() => response.promise);
  f.windowTarget.dispatchEvent(new Event("online"));
  f.windowTarget.dispatchEvent(new Event("focus"));
  f.windowTarget.dispatchEvent(new Event("pageshow"));
  await f.poll();
  assert.equal(f.requests.length, 1);
  response.resolve({ occupied: true });
  await settle();
  f.windowTarget.dispatchEvent(new Event("pageshow"));
  await settle();
  assert.equal(f.requests.length, 2);
  f.recovery.stop();
});

test("late checks cannot apply to another project, session or unmounted page", async () => {
  for (const terminate of ["invalidate", "stop"]) {
    const response = deferred();
    const f = fixture(() => response.promise);
    const check = f.recovery.check();
    terminate === "stop" ? f.recovery.stop() : f.invalidate();
    response.resolve({ occupied: false }); await check;
    assert.equal(f.states.length, 0);
    assert.equal(f.acquisitions(), 0);
    f.recovery.stop();
    f.windowTarget.dispatchEvent(new Event("online"));
    assert.equal(f.requests.length, 1);
    assert.equal(f.intervals.size, 0);
    assert.equal(f.timeouts.size, 0);
  }
});

test("network failure and malformed state never imply availability, but later recovery works", async () => {
  const outcomes = [new Error("offline"), {}, { occupied: false }];
  const f = fixture(async () => { const outcome = outcomes.shift(); if (outcome instanceof Error) throw outcome; return outcome; });
  await f.poll(); await f.poll();
  assert.equal(f.acquisitions(), 0);
  assert.equal(f.errors.length, 2);
  await f.poll();
  assert.equal(f.acquisitions(), 1);
  f.recovery.stop();
});

test("stalled state reads time out and may be retried without blocking the page", async () => {
  const f = fixture((_path, { signal }) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("timeout")), { once: true })));
  const check = f.recovery.check();
  [...f.timeouts.values()][0].fn(); await check;
  assert.equal(f.errors.length, 1);
  assert.equal(f.acquisitions(), 0);
  const retry = f.recovery.check();
  assert.equal(f.requests.length, 2);
  f.recovery.stop(); await retry;
  assert.equal(f.errors.length, 1, "unmount abort is not shown as another error");
});

test("authentication and permanent authorization failures stop background checks", async () => {
  for (const failure of [{ status: 401 }, { status: 403 }, { status: 404 }, { code: "session_changed" }]) {
    const f = fixture(async () => { throw failure; });
    await f.poll();
    f.windowTarget.dispatchEvent(new Event("focus"));
    await f.recovery.check();
    assert.equal(f.requests.length, 1);
    assert.equal(f.acquisitions(), 0);
    assert.equal(f.intervals.size, 0);
  }
});

test("AccountRoot observes only initial readonly views, never auto-unfreezes unsaved drafts", () => {
  const source = readFileSync(new URL("../src/accounts/AccountRoot.jsx", import.meta.url), "utf8");
  const effect = source.slice(source.indexOf("if (admin || auth.auth_mode"), source.indexOf("if (!projectId || !lease?.editable)"));
  assert.match(effect, /lease\.loading \|\| lease\.acquiring \|\| lease\.editable \|\| lease\.lost/);
  assert.match(effect, /sessionBlocked/);
  assert.match(effect, /generation\.current === version/);
  assert.match(effect, /onAvailable: \(\) => acquire\(\)/);
  assert.match(source, /loading=\{lease\.acquiring\}/);
});
