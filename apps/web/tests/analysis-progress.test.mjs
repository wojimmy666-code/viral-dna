import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { transformSync } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as Icons from "@phosphor-icons/react";
import { isCredentialAnalysisError, platformLabel } from "../src/platform-connection-ui.js";
import { latestAnalysis, watchAnalysis } from "../src/analysis-progress.js";

const state = (stage, seconds = 0) => ({ id: "job", stage, updated_at: new Date(seconds * 1000).toISOString() });
function harness(t, request, overrides = {}) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const updates = [], errors = [], completed = [];
  let stream;
  class Events {
    constructor() { stream = this; }
    addEventListener(name, listener) { this.listener = listener; }
    close() { this.closed = true; }
    emit(next) { this.listener({ data: JSON.stringify(next) }); }
  }
  const stop = watchAnalysis({
    analysisId: "job", request, eventsUrl: "/events", EventSourceImpl: Events,
    onUpdate: (next) => updates.push(next), onConnectionError: (error) => errors.push(error),
    onComplete: (next, isCurrent) => completed.push([next, isCurrent]), ...overrides,
  });
  t.after(stop);
  return { updates, errors, completed, stop, stream };
}

test("a silent open SSE stream cannot hide failure from fallback polling", async (t) => {
  let calls = 0;
  const h = harness(t, async () => state(++calls === 1 ? "ingesting" : "failed", calls));
  await setImmediate();
  t.mock.timers.tick(2000);
  await setImmediate();
  assert.equal(h.updates.at(-1).stage, "failed");
  assert.equal(h.stream.closed, true);
  t.mock.timers.tick(60000);
  await setImmediate();
  assert.equal(calls, 2);
});

test("polling is not abandoned after 60 requests while a real job is still running", async (t) => {
  let calls = 0;
  const h = harness(t, async () => state(++calls < 65 ? "understanding" : "completed", calls));
  await setImmediate();
  for (let index = 0; index < 64; index += 1) {
    t.mock.timers.tick(2000);
    await setImmediate();
  }
  assert.equal(h.completed.length, 1);
  assert.equal(calls, 65);
});

test("timeout aborts an unresponsive status request and recovers without creating work", async (t) => {
  let calls = 0, signal;
  const h = harness(t, async (path, options) => {
    assert.equal(path, "/analyses/job");
    signal = options.signal;
    return ++calls === 1 ? new Promise(() => {}) : state("failed", 1);
  });
  t.mock.timers.tick(10000);
  await setImmediate();
  assert.ok(signal.aborted);
  assert.match(h.errors.at(-1), /尚不能确认/);
  assert.equal(h.updates.length, 0);
  t.mock.timers.tick(2000);
  await setImmediate();
  assert.equal(h.updates.at(-1).stage, "failed");
  assert.equal(h.errors.at(-1), "");
});

test("leaving a project ignores late network and event callbacks", async (t) => {
  let resolve;
  const h = harness(t, () => new Promise((done) => { resolve = done; }));
  h.stop();
  resolve(state("completed", 1));
  h.stream.emit(state("failed", 2));
  await setImmediate();
  assert.deepEqual(h.updates, []);
  assert.deepEqual(h.completed, []);
});

test("an older poll response cannot regress progress and terminal callbacks run once", async (t) => {
  let resolve;
  const h = harness(t, () => new Promise((done) => { resolve = done; }));
  h.stream.emit(state("understanding", 2));
  resolve(state("ingesting", 1));
  await setImmediate();
  assert.equal(h.updates.length, 1);
  h.stream.emit(state("completed", 3));
  h.stream.emit(state("failed", 4));
  await setImmediate();
  assert.equal(h.completed.length, 1);
  assert.equal(h.updates.at(-1).stage, "completed");
  h.stop();
  assert.equal(h.completed[0][1](), false);
});

test("visible project owns the subscription and the failure actions", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(source, /return watchAnalysis\(/);
  assert.match(source, /\[appRoute.name, appRoute.recordId, analysis\?\.id, video\?\.id\]/);
  assert.doesNotMatch(source, /connectToProgress|index < 60/);
  const card = source.split("function AnalysisProgress(")[1].split("function RecordBreadcrumb")[0];
  assert.match(card, /已停止/);
  assert.match(card, /onClick=\{onRetry\}/);
  assert.match(card, /onClick=\{onConfigurePlatform\}/);
  assert.match(card, /role="alert"/);
});

test("a delayed record detail cannot resurrect a failed job", () => {
  const failure = state("failed", 2);
  assert.equal(latestAnalysis(failure, state("ingesting", 1)), failure);
  assert.equal(latestAnalysis(failure, state("ingesting", 3)), failure);
  const retry = { ...state("queued", 3), id: "new-job" };
  assert.equal(latestAnalysis(failure, retry), retry);
  assert.equal(latestAnalysis(failure, null), null);
});

test("actual failure card renders the reason and actions without a running spinner", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const jsx = "function AnalysisProgress(" + source.split("function AnalysisProgress(")[1]
    .split("function RecordBreadcrumb")[0];
  const { code } = transformSync(jsx, { loader: "jsx", jsxFactory: "createElement" });
  const scope = { createElement, ...Icons, isCredentialAnalysisError, platformLabel, stageLabels: {} };
  const Card = new Function(...Object.keys(scope), `${code}; return AnalysisProgress;`)(...Object.values(scope));
  const html = renderToStaticMarkup(createElement(Card, {
    analysis: { ...state("failed"), progress: 3, simulated: false,
      message: "平台要求登录或人机验证", error: { code: "link_auth_required", retryable: true } },
    video: { title: "抖音链接视频", source_type: "douyin" },
    submitting: true,
  }));
  assert.match(html, /平台要求登录或人机验证/);
  assert.match(html, /已停止/);
  assert.match(html, /配置抖音登录状态/);
  assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /class="spin"|正在解析平台链接/);
});
