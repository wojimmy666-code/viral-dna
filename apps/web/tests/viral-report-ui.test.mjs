import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const EXECUTIVE_URL = new URL("../src/viral-report/ViralExecutiveSummary.jsx", import.meta.url);
const REPLICATION_URL = new URL("../src/viral-report/ReplicationWorkspace.jsx", import.meta.url);
const MECHANISM_URL = new URL("../src/viral-report/ViralMechanismWorkspace.jsx", import.meta.url);
const SHOT_TRAFFIC_URL = new URL("../src/viral-report/ShotTrafficRoles.jsx", import.meta.url);
const CONCEPT_URL = new URL("../src/viral-report/ConceptComparison.jsx", import.meta.url);
const PROMPT_EDITOR_URL = new URL("../src/prompt-editor/PromptEditor.jsx", import.meta.url);
const PROMPT_SHOT_URL = new URL("../src/prompt-editor/PromptShotEditor.jsx", import.meta.url);
const UI_HELPERS_URL = new URL("../src/viral-report/viral-report-ui.js", import.meta.url);
const CSS_URL = new URL("../src/viral-report/viral-report.css", import.meta.url);
const PROMPT_PRESENTATION_CSS_URL = new URL("../src/prompt-presentation/prompt-presentation.css", import.meta.url);
const PROMPT_SECTION_PARSER_URL = new URL("../src/prompt-presentation/prompt-section-parser.js", import.meta.url);
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
  const helpers = await readFile(UI_HELPERS_URL, "utf8");

  assert.match(executive, /判断置信度/);
  assert.match(executive, /复刻难度/);
  assert.doesNotMatch(executive, /<span>证据覆盖<\/span>/);
  assert.doesNotMatch(executive, /<span>机制数量<\/span>/);
  assert.match(executive, /开始复刻/);
  assert.doesNotMatch(executive, /重新整理|refresh:\s*true|viral-refresh-button/);
  assert.doesNotMatch(helpers, /viral-insight\/refresh|refresh\s*=\s*false/);
  assert.match(app, /<details className="overview-technical-details">/);
  assert.match(app, /<p>\{report\.shots\.length\} 个镜头 · 分析完成<\/p>/);
});

test("long report content uses progressive disclosure", async () => {
  const app = await readFile(APP_URL, "utf8");
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  const traffic = await readFile(SHOT_TRAFFIC_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");
  const promptEditor = await readFile(PROMPT_EDITOR_URL, "utf8");
  const promptShot = await readFile(PROMPT_SHOT_URL, "utf8");

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
  assert.match(app, /<PromptSectionView prompt=\{activeShot\.prompt\} \/>/);
  assert.doesNotMatch(app, /<p>\{activeShot\.prompt\}<\/p>/);
  assert.match(promptEditor, /workingPackage\.continuity_locks\?\.length > 0/);
  assert.match(promptShot, /<details className="prompt-shot-editor" defaultOpen=\{index === 0\}>/);
});

test("concept details reduce locked DNA to disclosure metadata", async () => {
  const source = await readFile(CONCEPT_URL, "utf8");
  assert.match(source, /保留 \{selected\.retained_dna\.length\} 项 DNA/);
  assert.match(source, /concept-detail-actions/);
  assert.doesNotMatch(source, /selected\.name|selected\.why_it_can_work|concept-detail-heading/);
  assert.doesNotMatch(source, /本策略锁定|<strong>保留 DNA<\/strong>/);
});

test("shot creation instructions adapt to available width without leaving a dead column", async () => {
  const component = await readFile(CONCEPT_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");

  assert.match(component, /concept-shot-content/);
  assert.match(component, /<PromptSectionView prompt=\{shot\.video_prompt\}/);
  assert.doesNotMatch(component, /concept-shot-image-prompt|shot\.image_prompt/);
  assert.match(source, /\.concept-shot-list\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit, minmax\(min\(100%, 32rem\), 1fr\)\)[^}]*align-items:\s*start/s);
  assert.match(source, /\.concept-shot-list > article:only-child\s*\{\s*grid-column:\s*1 \/ -1/);
  assert.doesNotMatch(source, /\.concept-shot-list p\s*\{/);
  assert.doesNotMatch(source, /@container \(min-width: 80rem\)/);
  assert.doesNotMatch(source, /\.concept-shot-list p\s*\{[^}]*max-width:\s*72ch/s);
});

test("shot prompts recover semantic sections from flattened legacy text", async () => {
  const { parsePromptSections } = await import(PROMPT_SECTION_PARSER_URL);
  const parsed = parsePromptSections(
    "忠实复刻原动作阶段，不新增镜头。 【基础画面】 主体：长发女子，白色口罩 场景：户外公园 构图：中心构图 "
    + "【时间轴】 0.00–0.80s 主体：右臂前伸 镜头：固定机位 0.80–1.60s 主体：右手变掌向外 "
    + "【出场转场】 3.12–3.75s｜前景遮挡画面 动作过程：遮挡物覆盖镜头 运镜：固定机位",
  );

  assert.deepEqual(parsed.intro, ["忠实复刻原动作阶段，不新增镜头。"]);
  assert.deepEqual(parsed.sections.map((section) => section.key), ["visual", "timeline", "transition"]);
  assert.deepEqual(parsed.sections[0].fields.map((field) => field.label), ["主体", "场景", "构图"]);
  assert.equal(parsed.sections[1].segments.length, 2);
  assert.equal(parsed.sections[1].segments[0].time, "0.00–0.80s");
  assert.equal(parsed.sections[2].fields[0].label, "动作过程");
});

test("structured prompt typography uses the report type system and responsive timeline", async () => {
  const source = await readFile(PROMPT_PRESENTATION_CSS_URL, "utf8");
  assert.match(source, /\.prompt-section-view\s*\{[^}]*width:\s*min\(100%, 78ch\)[^}]*font-size:\s*var\(--type-body-size\)[^}]*line-height:\s*var\(--type-leading-copy\)/s);
  assert.match(source, /\.prompt-section-block h5\s*\{[^}]*color:\s*var\(--purple-dark\)[^}]*font-size:\s*var\(--type-label-size\)/s);
  assert.match(source, /\.prompt-field-list > div\s*\{[^}]*grid-template-columns:\s*4rem minmax\(0, 1fr\)/s);
  assert.match(source, /\.prompt-timeline > li\s*\{[^}]*grid-template-columns:\s*6rem minmax\(0, 1fr\)/s);
  assert.match(source, /\.prompt-timeline time\s*\{[^}]*color:\s*var\(--purple-dark\)[^}]*background:\s*var\(--purple-soft\)/s);
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.prompt-timeline > li\s*\{[^}]*grid-template-columns:\s*1fr/s);
});

test("replication concepts expose distinct change levels and stale-batch recovery", async () => {
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
  assert.match(concept, /制作提醒/);
  assert.match(concept, /concept-risk-disclosure/);
  assert.match(concept, /保留 \{selected\.retained_dna\.length\} 项 DNA/);
  assert.doesNotMatch(concept, /本方案重点改进|本策略锁定|concept-strategy-goal|meta\.goal/);
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
