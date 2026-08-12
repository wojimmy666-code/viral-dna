import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const EXECUTIVE_URL = new URL("../src/viral-report/ViralExecutiveSummary.jsx", import.meta.url);
const REPLICATION_URL = new URL("../src/viral-report/ReplicationWorkspace.jsx", import.meta.url);
const MECHANISM_URL = new URL("../src/viral-report/ViralMechanismWorkspace.jsx", import.meta.url);
const SHOT_TRAFFIC_URL = new URL("../src/viral-report/ShotTrafficRoles.jsx", import.meta.url);
const CONCEPT_URL = new URL("../src/viral-report/ConceptComparison.jsx", import.meta.url);
const UI_HELPERS_URL = new URL("../src/viral-report/viral-report-ui.js", import.meta.url);
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

test("overview omits internal narrative placeholders without hiding real structure", async () => {
  const { hasReportableNarrativeStructure } = await import(UI_HELPERS_URL);
  const source = await readFile(APP_URL, "utf8");

  assert.equal(
    hasReportableNarrativeStructure("逐镜头视觉事实已生成；全局叙事与爆点待下一阶段推理"),
    false,
  );
  assert.equal(
    hasReportableNarrativeStructure("真实分镜时间线已生成；叙事结构待 VLM 分析"),
    false,
  );
  assert.equal(hasReportableNarrativeStructure("开场钩子 → 证据展示 → 结果兑现"), true);
  assert.match(source, /showNarrativeStructure && \(/);
  assert.doesNotMatch(source, /<p>\{overview\.narrative_structure\}<\/p>/);
});

test("report summary prioritizes decisions and moves technical metadata behind disclosure", async () => {
  const app = await readFile(APP_URL, "utf8");
  const executive = await readFile(EXECUTIVE_URL, "utf8");

  assert.match(executive, /判断置信度/);
  assert.match(executive, /复刻难度/);
  assert.doesNotMatch(executive, /<span>证据覆盖<\/span>/);
  assert.doesNotMatch(executive, /<span>机制数量<\/span>/);
  assert.match(executive, /开始复刻/);
  assert.match(app, /<details className="overview-technical-details">/);
  assert.match(app, /<p>\{report\.shots\.length\} 个镜头 · 分析完成<\/p>/);
});

test("long report content uses progressive disclosure", async () => {
  const app = await readFile(APP_URL, "utf8");
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  const traffic = await readFile(SHOT_TRAFFIC_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");

  assert.match(mechanism, /<details className="viral-mechanism-row"/);
  assert.match(mechanism, /open=\{index === 0\}/);
  assert.match(mechanism, /distinctScores\.size > 1/);
  assert.match(traffic, /<details className="viral-report-page shot-traffic-section">/);
  assert.match(traffic, /shot-traffic-preserve-details/);
  assert.match(replication, /<details className="replication-dna-locks">/);
  assert.match(replication, /\bCaretDown\b[\s\S]*from "@phosphor-icons\/react"/);
  assert.doesNotMatch(replication, /replication-empty/);
  assert.match(app, /<details className="shot-secondary-facts">/);
  assert.match(app, /<details className="prompt-box shot-prompt-disclosure">/);
  assert.match(app, /promptPackage\.continuity_locks\.length > 0/);
  assert.match(app, /<details key=\{shot\.shot_id\} open=\{index === 0\}>/);
});

test("concept details do not repeat already locked DNA", async () => {
  const source = await readFile(CONCEPT_URL, "utf8");
  assert.match(source, /本策略锁定/);
  assert.doesNotMatch(source, /<strong>保留 DNA<\/strong>/);
});

test("replication concepts expose distinct strategy goals and stale-batch recovery", async () => {
  const concept = await readFile(CONCEPT_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");
  const helper = await import(UI_HELPERS_URL);
  const duplicated = [
    {
      why_it_can_work: "相同说明",
      improvements: ["相同改进"],
      risks: ["相同风险"],
      retained_dna: ["相同 DNA"],
      shots: [{ image_prompt: "相同图片", video_prompt: "相同视频" }],
    },
    {
      why_it_can_work: "相同说明",
      improvements: ["相同改进"],
      risks: ["相同风险"],
      retained_dna: ["相同 DNA"],
      shots: [{ image_prompt: "相同图片", video_prompt: "相同视频" }],
    },
  ];

  assert.deepEqual(helper.findConceptDuplicateFields(duplicated), [
    "有效性说明",
    "重点改进",
    "制作风险",
    "DNA 保留策略",
    "逐镜头图片提示词",
    "逐镜头视频提示词",
  ]);
  assert.match(concept, /改动幅度/);
  assert.match(concept, /本方案重点改进/);
  assert.match(concept, /重新生成后可创建/);
  assert.match(replication, /conceptSet\?\.status === "stale"/);
  assert.match(replication, /现有三套方案需要更新/);
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

test("viral workspaces use the same dense report frame and a responsive preparation grid", async () => {
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");
  assert.match(mechanism, /viral-report-page viral-mechanism-workspace/);
  assert.match(replication, /viral-report-page replication-workspace/);
  assert.match(replication, /replication-preparation-grid/);
  assert.match(source, /\.viral-report-page\s*\{[^}]*width:\s*100%[^}]*padding:\s*1\.25rem/s);
  assert.match(source, /\.replication-preparation-grid\s*\{[^}]*grid-template-columns:/s);
  assert.match(source, /@media \(max-width: 1080px\)[\s\S]*\.replication-preparation-grid\s*\{\s*grid-template-columns:\s*1fr/);
});

test("overview, mechanisms, and replication share the report typography hierarchy", async () => {
  const source = await readFile(CSS_URL, "utf8");
  const styles = await readFile(STYLES_URL, "utf8");

  assert.match(source, /\.viral-summary-heading h2,\s*\.viral-section-header h2\s*\{[^}]*font-size:\s*var\(--type-heading-size\)/s);
  assert.match(source, /\.viral-mechanism-summary-copy > strong\s*\{[^}]*font-size:\s*var\(--type-body-size\)/s);
  assert.match(source, /\.viral-logic-chain p\s*\{[^}]*font-size:\s*var\(--type-body-size\)/s);
  assert.match(source, /\.concept-shot-list p\s*\{[^}]*font-size:\s*var\(--type-body-size\)[^}]*line-height:\s*var\(--type-leading-editor\)/s);
  assert.doesNotMatch(source, /font-size:\s*clamp\(/);
  assert.match(styles, /\.section-block h3\s*\{[^}]*font-size:\s*var\(--type-body-size\)/s);
  assert.match(styles, /\.score-value strong\s*\{[^}]*font-size:\s*var\(--type-page-size\)/s);
});

test("report tabs keep keyboard focus inside the clipped tab strip", async () => {
  const source = await readFile(STYLES_URL, "utf8");
  assert.match(source, /\.report-tabs button:focus-visible\s*\{[^}]*outline:\s*0[^}]*box-shadow:\s*inset/s);
});

test("shot traffic roles keep long preservation guidance out of tag pills", async () => {
  const component = await readFile(SHOT_TRAFFIC_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");
  assert.match(component, /viral-report-page shot-traffic-section/);
  assert.match(component, /shot-traffic-preserve-list/);
  assert.doesNotMatch(component, /shot-traffic-tags/);
  assert.match(source, /\.shot-traffic-list > article > button\s*\{[^}]*grid-template-columns:\s*7rem minmax\(0, 1fr\)/s);
  assert.match(source, /\.shot-traffic-preserve-details\s*\{[^}]*margin-left:\s*8rem/s);
});
