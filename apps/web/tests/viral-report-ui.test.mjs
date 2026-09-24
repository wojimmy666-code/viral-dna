import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as PhosphorIcons from "@phosphor-icons/react";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const EXECUTIVE_URL = new URL("../src/viral-report/ViralExecutiveSummary.jsx", import.meta.url);
const REPLICATION_URL = new URL("../src/viral-report/ReplicationWorkspace.jsx", import.meta.url);
const MECHANISM_URL = new URL("../src/viral-report/ViralMechanismWorkspace.jsx", import.meta.url);
const SHOT_TRAFFIC_URL = new URL("../src/viral-report/ShotTrafficRoles.jsx", import.meta.url);
const CONCEPT_URL = new URL("../src/viral-report/ConceptComparison.jsx", import.meta.url);
const PLAN_URL = new URL("../src/viral-report/CreativePlanReview.jsx", import.meta.url);
const PROMPT_EDITOR_URL = new URL("../src/prompt-editor/PromptEditor.jsx", import.meta.url);
const PROMPT_SHOT_URL = new URL("../src/prompt-editor/PromptShotEditor.jsx", import.meta.url);
const UI_HELPERS_URL = new URL("../src/viral-report/viral-report-ui.js", import.meta.url);
const CSS_URL = new URL("../src/viral-report/viral-report.css", import.meta.url);

test("a failed or pending creative batch never silently displays previous results", async () => {
  const { visibleCreativeBatch } = await import("../src/viral-report/creative-workflow.js");
  const previous = { id: "old", phase: "ideas", status: "completed", ideas: [{ name: "旧创意" }] };
  assert.equal(visibleCreativeBatch(), null);
  for (const status of ["cancelled", "queued", "running"]) {
    assert.equal(visibleCreativeBatch({ ...previous, id: "new", status }), null);
  }
  assert.equal(visibleCreativeBatch(previous), previous);
  const failed = { ...previous, id: "failed-with-own-result", status: "failed" };
  assert.equal(visibleCreativeBatch(failed), failed);
  assert.equal(visibleCreativeBatch({ ...failed, ideas: [] }), null);
  const plan = { phase: "expanded", status: "completed" };
  assert.equal(visibleCreativeBatch(plan), plan);
  const legacy = { phase: "legacy", status: "stale" };
  assert.equal(visibleCreativeBatch(legacy), legacy);
  const source = await readFile(REPLICATION_URL, "utf8");
  assert.match(source, /const display = visibleCreativeBatch\(current\)/);
  assert.doesNotMatch(source, /const fallback =|current : fallback/);
});

test("creative brief restores the frozen text and preserves an intentional empty brief", async () => {
  const { creativeBriefText } = await import("../src/viral-report/creative-workflow.js");
  const feedback = "多场景切换，并且都是全世界标志性的场景";
  assert.equal(creativeBriefText(), "");
  assert.equal(creativeBriefText({ phase: "legacy", feedback }), "");
  assert.equal(creativeBriefText({ phase: "ideas", feedback }), feedback);
  assert.equal(creativeBriefText({ phase: "expanded", input_snapshot: { original_creative_brief: feedback } }), feedback);
  assert.equal(creativeBriefText({ phase: "ideas", feedback, input_snapshot: { creative_brief: { text: "" }, original_creative_brief: feedback } }), "");
  assert.equal(creativeBriefText({ phase: "ideas", feedback: "old", input_snapshot: { creative_brief: { text: feedback } } }), feedback);
});

test("creative actions submit the full visible brief and keep copy concise", async () => {
  const source = await readFile(REPLICATION_URL, "utf8");
  assert.match(source, /feedback \?\? creativeBriefText\(current \|\| display\)/);
  assert.match(source, /textarea[^>]*value=\{effectiveFeedback\}/);
  assert.equal((source.match(/feedback: effectiveFeedback/g) || []).length, 2);
  assert.match(source, /body\.revision_notes = revisionNotes/);
  assert.match(source, /onRegenerate=\{\(item, notes\) => actOnIdea\(item, "regenerate", notes\)\}/);
  assert.match(source, /setFeedback\(\(value\) => value === feedback \? null : value\)/);
  assert.match(source, /setCurrentId\(event\.target\.value\); setFeedback\(null\)/);
  for (const copy of [
    "先选创意，再展开分镜。借鉴原片的表达方式，不照搬原片画面",
    "本批次依据",
    "后续品类或报告更新不会改写已有创意",
    "旧批次和已创建的方案不会被覆盖",
  ]) assert.equal(source.includes(copy), false, copy);
  assert.match(source, /历史批次/);
});

test("idea cards remove review clutter and keep a deliberate note-based AI action", async () => {
  const ideas = await readFile(new URL("../src/viral-report/CreativeIdeas.jsx", import.meta.url), "utf8");
  const workspace = await readFile(REPLICATION_URL, "utf8");
  for (const text of ["待核对", "待修订", "项具体问题", "记忆画面", "关键画面与品类适配", "修改与核对"]) {
    assert.equal(ideas.includes(text), false, text);
  }
  assert.doesNotMatch(workspace, /creative-review-summary|原批次失败记录和费用保留|CreativeIdeaEditor/);
  assert.match(ideas, /<span>修改意见<\/span><textarea[^>]*required[^>]*maxLength=\{2000\}/);
  assert.match(ideas, /onRegenerate\(idea, notes\.trim\(\)\)/);
  assert.match(ideas, /将调用文案模型并计费，仅修改本条/);
  assert.match(ideas, /确认并 AI 修订/);
  assert.match(ideas, /registerAccountFlusher/);
  assert.match(workspace, /Object\.hasOwn\(ideaBatch, "revision_notes"\)/);
});

test("expanded plans omit fulfillment and production reminders without removing production actions", async () => {
  const concept = await readFile(CONCEPT_URL, "utf8");
  const plan = await readFile(PLAN_URL, "utf8");
  assert.doesNotMatch(plan, /补充想法落实说明|制作提醒|CreativeBriefChecks|selected\.brief_checks|selected\.risks/);
  assert.doesNotMatch(concept, /补充想法落实说明|制作提醒|CreativeBriefChecks|selected\.brief_checks|selected\.risks/);
  assert.match(concept, /所需资产/);
  assert.match(concept, /查看逐镜头创作指令/);
  assert.match(concept, /onClick=\{\(\) => onPublish\(selected\)\}/);
  const css = await readFile(CSS_URL, "utf8");
  const workflowCss = await readFile(new URL("../src/viral-report/creative-workflow.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /\.concept-risk-title/);
  assert.doesNotMatch(workflowCss, /\.creative-brief-checks/);
});

test("expanded plan renders a sequential review with unchanged publish guards and legacy rendering", async () => {
  const bundle = await build({ entryPoints: [fileURLToPath(CONCEPT_URL)], write: false, bundle: true, format: "cjs", platform: "node", packages: "external", jsx: "automatic", loader: { ".css": "empty" } });
  const module = { exports: {} };
  const require = createRequire(import.meta.url);
  new Function("require", "module", "exports", bundle.outputFiles[0].text)((specifier) => specifier === "@phosphor-icons/react" ? PhosphorIcons : require(specifier), module, module.exports);
  const plan = { id: "plan1", name: "地标行走", thesis: "人物居中，背景硬切。", narrative_structure: "非线性蒙太奇", payoff: "结束画面", category_fit_summary: "服装", changed_elements: ["调整场景"], retained_dna: ["硬切"], required_assets: ["服装参考图"], brief_checks: [{ explanation: "不可见核对依据" }], risks: ["不可见风险内容"], shots: [{ index: 1, title: "巴黎", description: "女孩居中向左走。", traffic_role: "视觉吸引", duration_seconds: 0.8, image_prompt: "静态场景", video_prompt: "向左行走" }] };
  const render = (batch = {}, props = {}, concept = plan) => renderToStaticMarkup(createElement(module.exports.ConceptComparison, { conceptSet: { id: "expanded", phase: "expanded", status: "completed", concepts: [concept], ...batch }, onPublish() { throw new Error("render must not publish"); }, onPromptPreview() { throw new Error("render must not preview"); }, ...props }));
  const html = render();
  assert.match(html, /creative-plan-header[\s\S]*查看方案提示词/);
  assert.match(html, /creative-plan-overview[\s\S]*<p>人物居中，背景硬切。<\/p>/);
  assert.doesNotMatch(html, /方案详情/);
  assert.match(html, /aria-expanded="false" aria-controls="[^"]+"/);
  assert.match(html, /aria-label="展开创意说明"/);
  assert.match(html, /class="creative-plan-details" hidden=""/);
  assert.match(html, /creative-plan-shot-heading[\s\S]*creative-plan-shot-title[\s\S]*creative-plan-shot-duration/);
  const shotToggle = html.match(/<span class="creative-plan-shot-toggle"[^>]*>[\s\S]*?<\/span>/)?.[0];
  assert.ok(shotToggle, "shot summary keeps its disclosure arrow");
  assert.match(shotToggle, /aria-hidden="true"[\s\S]*<svg/);
  assert.doesNotMatch(shotToggle, /展开|收起|when-closed|when-open/);
  assert.equal(html.split(plan.shots[0].description).length - 1, 1, "shot description appears once, including after expansion");
  assert.doesNotMatch(html, /creative-plan-shot-description/);
  assert.match(html, /creative-plan-shot-list[\s\S]*creative-plan-assets[\s\S]*creative-plan-footer/);
  assert.equal((html.match(/class="ui-button primary-button"/g) || []).length, 1);
  assert.doesNotMatch(html, /不可见核对依据|不可见风险内容|制作提醒|补充想法落实说明|<details[^>]+open/);
  const primary = value => value.match(/<button[^>]*class="ui-button primary-button"[^>]*>/)?.[0] || "";
  assert.doesNotMatch(primary(html), /disabled/);
  for (const [batch, props] of [[{ status: "stale" }, {}], [{ language_issues: ["English"] }, {}], [{ input_snapshot: { prompt_language_project_id: "existing" } }, {}], [{}, { publishingId: "plan1" }]]) {
    assert.match(primary(render(batch, props)), /disabled=""/);
  }
  assert.match(render({}, { publishingId: "plan1" }), /aria-busy="true"/);
  const published = render({ language_issues: ["English"], published_result: { project_id: "existing" } });
  assert.match(published, /进入已创建方案/);
  assert.doesNotMatch(primary(published), /disabled/);
  assert.doesNotMatch(render({}, {}, { ...plan, required_assets: [] }), /creative-plan-assets/);
  assert.doesNotMatch(render({}, {}, { ...plan, narrative_structure: "", payoff: "", category_fit_summary: "", changed_elements: [], retained_dna: [] }), /creative-plan-details|展开创意说明/);
  for (const count of [1, 5, 12]) {
    const markup = render({}, {}, { ...plan, shots: Array.from({ length: count }, (_, index) => ({ ...plan.shots[0], index: index + 1 })) });
    assert.equal((markup.match(/class="creative-plan-shot"/g) || []).length, count);
  }
  const legacy = render({ phase: "legacy" }, { historical: true });
  assert.match(legacy, /历史完整方案/);
  assert.match(legacy, /concept-summary-grid/);
  assert.doesNotMatch(legacy, /creative-plan-review/);
});

test("creative batches merge without dropping history and keep unreported costs honest", async () => {
  const { mergeCreativeBatch, creativeCost, creativeTiming, creativeTimingParts, isCreativeRunning } = await import("../src/viral-report/creative-workflow.js");
  const first = { id: "one", created_at: "2026-09-19T00:00:00Z", status: "completed" };
  const next = { id: "two", created_at: "2026-09-19T00:01:00Z", status: "running" };
  const merged = mergeCreativeBatch([first, next], { ...next, status: "completed" });
  assert.deepEqual(merged.map((item) => item.id), ["two", "one"]);
  assert.equal(merged[1], first);
  assert.equal(isCreativeRunning(merged[0]), false);
  assert.equal(isCreativeRunning(next), true);
  assert.match(creativeCost({ cost_status: "unreported", model_cost_micros: 0 }), /不代表免费/);
  assert.match(creativeCost({ cost_status: "measured", model_cost_micros: 1200 }), /0\.0012/);
  assert.equal(creativeTiming({ ...first, started_at: "2026-09-19T00:00:02Z", completed_at: "2026-09-19T00:00:20Z", model_elapsed_ms: 15000 }), "总计 20 秒 · 排队 2 秒 · 模型 15 秒");
  assert.deepEqual(creativeTimingParts({ ...first, started_at: "2026-09-19T00:00:02Z", completed_at: "2026-09-19T00:00:20Z", model_elapsed_ms: 15000 }), { total: 20, queue: 2, model: 15 });
  assert.deepEqual(creativeTimingParts({ ...next, started_at: "2026-09-19T00:01:02Z", model_elapsed_ms: 5000 }, Date.parse("2026-09-19T00:01:20Z")), { total: 20, queue: 2, model: 18 });
});

test("two-stage UI requires explicit selection, reuses request IDs and only polls on reload", async () => {
  const source = await readFile(REPLICATION_URL, "utf8");
  const ideas = await readFile(new URL("../src/viral-report/CreativeIdeas.jsx", import.meta.url), "utf8");
  assert.match(source, /request_id: crypto\.randomUUID\(\)/);
  assert.match(source, /body: retry \? body/);
  assert.match(source, /disabled=\{!idea \|\| locked/);
  assert.doesNotMatch(source, /已选《/);
  assert.match(source, /!idea && <span>选择一个喜欢的方向后，再展开完整分镜<\/span>/);
  assert.match(source, /const locked = busy \|\| revising \|\| Boolean\(retryRequest\)/);
  assert.match(source, /AbortController/);
  assert.match(source, /version !== epoch\.current/);
  assert.match(source, /停止任务/);
  assert.match(ideas, /type="radio"/);
  assert.match(ideas, /disabled=\{busy \|\| Boolean\(confirmId\)\}/);
  assert.doesNotMatch(ideas, /ideaReviewState|state !== "ready"/);
  assert.match(source, /const idea = ideaBatch\?\.ideas\?\.find\(\(item\) => item\.id === selectedId\);/);
  assert.match(source, /failure\.status === 409 && failure\.code === "idea_review_required"\) setRetryRequest\(null\)/);
  assert.match(source, /conceptError\.recovery === "query" && <Button/);
  assert.match(source, /<span>\{conceptError\.message\}<\/span>/);
  assert.match(ideas, /AI 修订本条/);
  assert.doesNotMatch(ideas, /faithful|scenario|proof/);
});
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
  assert.match(source, /<ReplicationWorkspace\s+key=\{report\.analysis_id\}/s);
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

  assert.doesNotMatch(executive, /判断置信度|复刻难度|viral-summary-metrics/);
  assert.match(executive, /viral-hook-evidence/);
  assert.match(executive, /formatInsightTime/);
  assert.match(executive, /大模型综合 · 证据校验/);
  assert.doesNotMatch(executive, /核心视觉信号前置/);
  assert.doesNotMatch(executive, /<span>证据覆盖<\/span>/);
  assert.doesNotMatch(executive, /<span>机制数量<\/span>/);
  assert.match(executive, /开始复刻/);
  assert.doesNotMatch(executive, /重新整理|refresh:\s*true|viral-refresh-button/);
  assert.doesNotMatch(helpers, /viral-insight\/refresh|refresh\s*=\s*false/);
  assert.match(app, /<details className="overview-technical-details">/);
  assert.match(app, /<OverviewTab\s+analysis=\{analysis\}/s);
  assert.match(app, /<dt>总耗时<\/dt>/);
  assert.match(app, /formatAnalysisElapsedTime\(analysis\?\.created_at, analysis\?\.completed_at\)/);
  assert.match(app, /<p>\{report\.shots\.length\} 个镜头 · 分析完成<\/p>/);
  assert.doesNotMatch(app, /内容置信度 \$\{Math\.round\(activeShot\.confidence/);
  assert.doesNotMatch(app, /程序边界 · VLM 已降级|程序候选 \+ VLM 确认|查看边界候选证据|segmentation-evidence/);
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
  assert.doesNotMatch(mechanism, /distinctScores|showScores|mechanism\.score/);
  assert.doesNotMatch(mechanism, /先看结论|流量作用来自内容结构推断|内容推断 ·|置信度 |跳到 \{/);
  assert.match(traffic, /<details className="viral-report-page shot-traffic-section">/);
  assert.match(traffic, /shot-traffic-preserve-details/);
  assert.doesNotMatch(replication, /replication-dna-locks|内容 DNA 已锁定/);
  assert.doesNotMatch(replication, /replication-empty/);
  assert.match(app, /<details className="shot-secondary-facts">/);
  assert.match(app, /<details className="prompt-box shot-prompt-disclosure">/);
  assert.match(app, /<PromptSectionView prompt=\{activeShot\.prompt\} \/>/);
  assert.doesNotMatch(app, /<p>\{activeShot\.prompt\}<\/p>/);
  assert.match(promptEditor, /workingPackage\.continuity_locks\?\.length > 0/);
  assert.match(promptShot, /prompt-document-shot-row/);
  assert.match(promptShot, /<PromptRichTextEditor/);
  assert.doesNotMatch(promptShot, /prompt-document-compiled|PromptSectionView/);
});

test("concept details expose the creative brief while keeping locked DNA in disclosure metadata", async () => {
  const source = await readFile(CONCEPT_URL, "utf8");
  assert.match(source, /保留 \{selected\.retained_dna\.length\} 项 DNA/);
  assert.match(source, /concept-detail-actions/);
  assert.match(source, /selected\.thesis \|\| selected\.why_it_can_work/);
  assert.match(source, /creative \? selected\.name/);
  assert.doesNotMatch(source, /本策略锁定|<strong>保留 DNA<\/strong>/);
});

test("shot creation instructions adapt to available width without leaving a dead column", async () => {
  const component = await readFile(CONCEPT_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");

  assert.match(component, /concept-shot-content/);
  assert.match(component, /<PromptSectionView prompt=\{shot\.video_prompt\}/);
  assert.match(component, /creative &&.*图片提示词/s);
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
  assert.match(source, /\.prompt-section-block h5\s*\{[^}]*color:\s*var\(--accent-hover\)[^}]*font-size:\s*var\(--type-label-size\)/s);
  assert.match(source, /\.prompt-field-list > div\s*\{[^}]*grid-template-columns:\s*4rem minmax\(0, 1fr\)/s);
  assert.match(source, /\.prompt-timeline > li\s*\{[^}]*grid-template-columns:\s*6rem minmax\(0, 1fr\)/s);
  assert.match(source, /\.prompt-timeline time\s*\{[^}]*color:\s*var\(--accent-hover\)[^}]*background:\s*var\(--accent-soft\)/s);
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
  assert.match(concept, /创意主张/);
  assert.match(concept, /叙事结构/);
  assert.match(concept, /品类适配/);
  assert.doesNotMatch(concept, /制作提醒|补充想法落实说明|CreativeBriefChecks|selected\.brief_checks|selected\.risks/);
  assert.match(concept, /所需资产/);
  assert.match(concept, /查看逐镜头创作指令/);
  assert.match(concept, /concept-risk-disclosure/);
  assert.match(concept, /保留 \{selected\.retained_dna\.length\} 项 DNA/);
  assert.doesNotMatch(concept, /本方案重点改进|本策略锁定|concept-strategy-goal|meta\.goal/);
  assert.match(concept, /重新生成后可创建/);
  assert.doesNotMatch(concept, /历史方案基于|不会自动成为本次品类选择/);
  assert.match(replication, /旧版规则方案/);
  assert.match(replication, /历史批次/);
  assert.match(replication, /category_profile_id: selectedCategoryId/);
  assert.match(replication, /historical=\{display\?\.phase === "legacy"\}/);
  assert.doesNotMatch(replication, /历史方案不会自动回填/);
  assert.doesNotMatch(replication, /尚未选择品类档案/);
  assert.doesNotMatch(replication, /setSelectedCategoryId\(payload/);
  assert.doesNotMatch(replication, /\["faithful", "scenario", "proof"\]/);
  assert.match(replication, /展开这个创意/);
  assert.match(replication, /生成 3 个简短创意/);
  assert.doesNotMatch(replication, /可选，对换新和展开都有效|creative-step-path|比较简短创意|展开并确认分镜/);
  assert.match(replication, /<label className="creative-feedback"><span>补充想法<\/span><textarea/);
  const creativeStyles = await readFile(new URL("../src/viral-report/creative-workflow.css", import.meta.url), "utf8");
  assert.doesNotMatch(creativeStyles, /creative-step-path|\.creative-feedback small/);
  assert.doesNotMatch(replication, /仅生成创意与分镜，不会立即生成图片或视频/);
  assert.match(replication, /<section className="replication-generate-bar action-only"><Button/);
  assert.match(replication, /onClick=\{generateConcepts\}/);
  assert.match(replication, /creative-run-meta/);
  assert.match(replication, /creativeCost\(current\)/);
});

test("viral report modules receive the request boundary instead of calling fetch", async () => {
  const replication = await readFile(REPLICATION_URL, "utf8");
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  assert.doesNotMatch(replication, /\bfetch\s*\(/);
  assert.doesNotMatch(mechanism, /\bfetch\s*\(/);
  assert.match(replication, /submit\(`\/analyses\/\$\{analysisId\}\/viral-concepts`/);
  assert.match(replication, /onPublished/);
});

test("viral report layout has responsive fallbacks without a fixed side panel", async () => {
  const source = await readFile(CSS_URL, "utf8");
  assert.match(source, /@media \(max-width: 1080px\)/);
  assert.match(source, /@media \(max-width: 760px\)/);
  assert.doesNotMatch(source, /position:\s*fixed/);
  assert.match(source, /\.concept-summary-grid/);
  assert.match(source, /overflow-x:\s*auto/);
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.concept-summary-grid\s*\{[^}]*grid-template-columns:\s*1fr/s);
});

test("viral workspaces use the same dense report frame without redundant DNA preparation UI", async () => {
  const mechanism = await readFile(MECHANISM_URL, "utf8");
  const replication = await readFile(REPLICATION_URL, "utf8");
  const source = await readFile(CSS_URL, "utf8");
  assert.match(mechanism, /viral-report-page viral-mechanism-workspace/);
  assert.match(replication, /viral-report-page replication-workspace/);
  assert.match(replication, /<details className="creative-replacements"/);
  assert.doesNotMatch(replication, /replication-preparation-grid|replication-dna-locks/);
  assert.match(source, /\.viral-report-page\s*\{[^}]*width:\s*100%[^}]*padding:\s*1\.25rem/s);
  assert.doesNotMatch(source, /\.replication-preparation-grid|\.replication-dna-locks|\.dna-lock-list/);
  assert.match(source, /\.replication-generate-bar\s*\{[^}]*min-height:\s*var\(--control-height-prominent\)[^}]*align-items:\s*center/s);
  assert.match(source, /\.replication-generate-bar\.action-only\s*\{[^}]*justify-content:\s*flex-end/s);
  assert.doesNotMatch(source, /\.replication-generate-bar\s*\{[^}]*padding:|\.replication-generate-bar\s*\{[^}]*background:/s);
  assert.doesNotMatch(replication, /一次生成结构迁移、场景叙事、证据说服三套独立方案/);
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
