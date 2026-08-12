import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const REPLICATION_URL = new URL("../src/viral-report/ReplicationWorkspace.jsx", import.meta.url);
const MECHANISM_URL = new URL("../src/viral-report/ViralMechanismWorkspace.jsx", import.meta.url);
const CSS_URL = new URL("../src/viral-report/viral-report.css", import.meta.url);
const STYLES_URL = new URL("../src/styles.css", import.meta.url);

test("analysis report exposes the five-step viral decision navigation", async () => {
  const source = await readFile(APP_URL, "utf8");
  for (const label of ["总览", "爆款机制", "分镜拆解", "复刻与改进", "提示词"]) {
    assert.match(source, new RegExp(`label: "${label}"`));
  }
  assert.match(source, /<ViralExecutiveSummary/);
  assert.match(source, /<ViralMechanismWorkspace/);
  assert.match(source, /<ShotTrafficRoles/);
  assert.match(source, /<ReplicationWorkspace/);
});

test("viral report modules receive the request boundary instead of calling fetch", async () => {
  const replication = await readFile(REPLICATION_URL, "utf8");
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  assert.doesNotMatch(replication, /\bfetch\s*\(/);
  assert.doesNotMatch(mechanism, /\bfetch\s*\(/);
  assert.match(replication, /request\(`\/analyses\/\$\{analysisId\}\/viral-concepts`/);
  assert.match(replication, /onPublished/);
});

test("viral report layout has responsive fallbacks without a fixed side panel", async () => {
  const source = await readFile(CSS_URL, "utf8");
  assert.match(source, /@media \(max-width: 1080px\)/);
  assert.match(source, /@media \(max-width: 760px\)/);
  assert.doesNotMatch(source, /position:\s*fixed/);
  assert.match(source, /\.concept-summary-grid/);
  assert.match(source, /overflow-x:\s*auto/);
});

test("viral workspaces use one bounded content frame and a responsive preparation grid", async () => {
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");
  assert.match(mechanism, /viral-report-page viral-mechanism-workspace/);
  assert.match(replication, /viral-report-page replication-workspace/);
  assert.match(replication, /replication-preparation-grid/);
  assert.match(source, /\.viral-report-page\s*\{[^}]*width:\s*min\(100%,\s*92rem\)/s);
  assert.match(source, /\.replication-preparation-grid\s*\{[^}]*grid-template-columns:/s);
  assert.match(source, /@media \(max-width: 1080px\)[\s\S]*\.replication-preparation-grid\s*\{\s*grid-template-columns:\s*1fr/);
});

test("report tabs keep keyboard focus inside the clipped tab strip", async () => {
  const source = await readFile(STYLES_URL, "utf8");
  assert.match(source, /\.report-tabs button:focus-visible\s*\{[^}]*outline:\s*0[^}]*box-shadow:\s*inset/s);
});
