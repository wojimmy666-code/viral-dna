import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as PhosphorIcons from "@phosphor-icons/react";
import { CREATION_STEPS, mainCreationStep, productionNavigation, readWorkspaceLocation, rememberWorkspaceLocation, savedWorkspaceLocation, sourceCapabilities, workspaceSearch } from "../src/creation-workspace/workspace-ui.js";
import { SKILL_WORKFLOW_STAGES, resolveSkillSection, skillCreationNavigation, skillImageGenerationSettings, skillSectionEnabled } from "../src/skill-workflow/skill-workflow-ui.js";
import { imageModelOptions } from "../src/image-generation-controls/image-generation-ui.js";
import { resolveImageExecutionMode } from "../src/production-ui.js";

function skillWorkspace(approvedCount, currentStage = SKILL_WORKFLOW_STAGES[approvedCount]?.id || "export") {
  return {
    production_project_id: approvedCount >= 3 ? "production-1" : null,
    run: { run: { current_stage: currentStage }, steps: [], gates: SKILL_WORKFLOW_STAGES.slice(0, approvedCount).map((stage, index) => ({ gate: stage.gate, decision: "approve", created_at: `2026-09-05T00:00:0${index}Z` })) },
  };
}

test("both project sources expose the same five production steps", () => {
  assert.deepEqual(CREATION_STEPS.map((item) => item.label), ["创作方案", "分镜图片", "分镜视频", "视频剪辑", "导出成片"]);
  assert.deepEqual(skillCreationNavigation(skillWorkspace(3)).map((step) => step.id), productionNavigation({ active_step: "shot_images" }).map((step) => step.id));
  for (const stage of SKILL_WORKFLOW_STAGES.slice(0, 3)) assert.equal(mainCreationStep(stage.id), "project_setup");
  assert.equal(mainCreationStep("audio_caption"), "editing");
  assert.equal(mainCreationStep("reference_assets"), "");
  assert.equal(mainCreationStep("revisions"), "");
});

test("source projects unlock editing and export without imposing Skill gates", () => {
  const images = productionNavigation({ active_step: "shot_images" });
  assert.equal(images.find((step) => step.id === "editing").enabled, false);
  const editing = productionNavigation({ active_step: "editing" });
  assert.ok(editing.every((step) => step.enabled));
  assert.equal(editing.find((step) => step.id === "editing").complete, false);
});

test("a completed execution cannot bypass any Skill human approval", () => {
  const workspace = skillWorkspace(0, "export");
  workspace.run.steps = SKILL_WORKFLOW_STAGES.map((stage) => ({ stage: stage.id, execution_status: "succeeded", validation_status: "passed", attempt: 1 }));
  assert.deepEqual(skillCreationNavigation(workspace).map((step) => step.enabled), [true, false, false, false, false]);
  assert.equal(resolveSkillSection(workspace, "export"), "creative_brief");
});

test("each Skill gate unlocks only its successor and completed stages remain accessible", () => {
  for (let count = 0; count < SKILL_WORKFLOW_STAGES.length; count++) {
    const workspace = skillWorkspace(count);
    for (let index = 0; index < SKILL_WORKFLOW_STAGES.length; index++) {
      assert.equal(skillSectionEnabled(workspace, SKILL_WORKFLOW_STAGES[index].id), index <= count, `${count} approvals: ${SKILL_WORKFLOW_STAGES[index].id}`);
    }
  }
  assert.equal(skillSectionEnabled(skillWorkspace(3), "reference_assets"), true);
  assert.equal(skillSectionEnabled(skillWorkspace(0), "revisions"), false);
});

test("picture lock and audio-caption approval remain independent inside editing", () => {
  const picture = skillWorkspace(5);
  assert.equal(skillSectionEnabled(picture, "editing"), true);
  assert.equal(skillSectionEnabled(picture, "audio_caption"), false);
  const audio = skillWorkspace(6);
  assert.equal(skillSectionEnabled(audio, "audio_caption"), true);
  assert.equal(skillCreationNavigation(audio).find((step) => step.id === "export").enabled, false);
  const ready = skillWorkspace(7);
  assert.equal(skillCreationNavigation(ready).find((step) => step.id === "export").enabled, true);
  assert.equal(skillCreationNavigation(ready).find((step) => step.id === "editing").complete, true);
});

test("deep links resolve to accessible stages without bypassing the preparation gates", () => {
  assert.equal(resolveSkillSection(skillWorkspace(1), "project_setup"), "style_confirmation");
  assert.equal(resolveSkillSection(skillWorkspace(2), "export"), "storyboard_design");
  assert.equal(resolveSkillSection(skillWorkspace(3), "storyboard_design"), "storyboard_design");
  assert.equal(resolveSkillSection(skillWorkspace(5), "audio_caption"), "editing");
});

test("a newer request for revision relocks the next step", () => {
  const workspace = skillWorkspace(3);
  workspace.run.gates.push({ gate: "storyboard_approved", decision: "request_revision", created_at: "2026-09-05T01:00:00Z" });
  assert.equal(skillCreationNavigation(workspace).find((step) => step.id === "shot_images").enabled, false);
  assert.equal(skillSectionEnabled(workspace, "shot_images"), false);
});

test("workspace URLs preserve stage, shot, beat and candidate while retaining unrelated query parameters", () => {
  const search = workspaceSearch("?filter=active", { productionId: "p-1", section: "shot_images", shotId: "s-2", visualBeatId: "b-3", candidateId: "c-4" });
  assert.equal(new URLSearchParams(search).get("filter"), "active");
  assert.deepEqual(readWorkspaceLocation(search), { productionId: "p-1", section: "shot_images", shotId: "s-2", visualBeatId: "b-3", candidateId: "c-4" });
  assert.equal(readWorkspaceLocation(workspaceSearch(search, { candidateId: "" })).candidateId, "");
  assert.equal(readWorkspaceLocation("?studio=unknown").section, "");
});

test("revising an earlier Skill gate disables every dependent step even with old downstream approvals", () => {
  const workspace = skillWorkspace(8);
  workspace.run.gates.push({ gate: "style_approved", decision: "request_revision", created_at: "2026-09-05T01:00:00Z" });
  const steps = skillCreationNavigation(workspace);
  assert.deepEqual(steps.map((step) => step.enabled), [true, false, false, false, false]);
  assert.ok(steps.every((step) => !step.complete));
  for (const step of steps) assert.equal(step.enabled, skillSectionEnabled(workspace, step.id));
});

test("session restoration is isolated per project and explicit deep links win", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const values = new Map();
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) } });
  try {
    rememberWorkspaceLocation("one", "?studio=shot_videos&production=p-1&shot=s-1");
    assert.equal(savedWorkspaceLocation("one").section, "shot_videos");
    assert.equal(savedWorkspaceLocation("two").section, "");
    assert.equal(savedWorkspaceLocation("one", "?studio=editing").section, "editing");
    globalThis.sessionStorage.getItem = () => { throw new Error("storage disabled"); };
    assert.doesNotThrow(() => savedWorkspaceLocation("one"));
  } finally {
    if (previous) Object.defineProperty(globalThis, "sessionStorage", previous);
    else delete globalThis.sessionStorage;
  }
});

test("source-video controls require real source capabilities", () => {
  assert.deepEqual(sourceCapabilities({}, { hasAudio: true }), { hasVideo: false, hasAudio: false });
  assert.deepEqual(sourceCapabilities({ video_id: "v" }, { hasAudio: true }), { hasVideo: true, hasAudio: true });
  assert.deepEqual(sourceCapabilities({ video_id: "v" }, { hasAudio: true, hasSourceVideo: false }), { hasVideo: false, hasAudio: false });
});

test("the real shared shell renders one title and five accessible navigation buttons", async () => {
  const result = await build({ entryPoints: [fileURLToPath(new URL("../src/creation-workspace/CreationWorkspace.jsx", import.meta.url))], write: false, bundle: true, format: "cjs", platform: "node", packages: "external", jsx: "automatic", loader: { ".css": "empty" } });
  const module = { exports: {} };
  const require = createRequire(import.meta.url);
  new Function("require", "module", "exports", result.outputFiles[0].text)((specifier) => specifier === "@phosphor-icons/react" ? PhosphorIcons : require(specifier), module, module.exports);
  const { CreationWorkspace, CreationNavigation } = module.exports;
  const navigation = createElement(CreationNavigation, { active: "audio_caption", steps: skillCreationNavigation(skillWorkspace(6)) });
  const markup = renderToStaticMarkup(createElement(CreationWorkspace, { title: "工厂宣传片", source: "工业 Skill", navigation }));
  assert.equal((markup.match(/<h1>/g) || []).length, 1);
  assert.equal((markup.match(/<button /g) || []).length, 5);
  assert.equal((markup.match(/aria-current="step"/g) || []).length, 1);
  assert.match(markup, /aria-label="创作工作流"/);
  assert.match(markup, /disabled=""/);
  assert.match(markup, /production-workspace creation-workspace/);
});

test("step switches flush every editor and audio subviews reuse the same timeline component", () => {
  const source = readFileSync(new URL("../src/ProductionWorkflow.jsx", import.meta.url), "utf8");
  const barrier = source.slice(source.indexOf("async function flushWorkspace()"), source.indexOf("useImperativeHandle(workspaceRef"));
  assert.match(barrier, /await flushShotDraft\(\)/);
  assert.match(barrier, /await flushVideoDraft\(\)/);
  assert.match(barrier, /await editorRef\.current\?\.flush\(\)/);
  assert.match(source, /await flushWorkspace\(\);\s*setActionError\(""\);\s*setActiveSection\(next\)/);
  assert.match(source, /\["editing", "audio_caption"\]\.includes\(activeSection\) && \(\s*<VideoEditorWorkspace/);
});

test("Skill preparation shows one outline and keeps the entire Look Test frame visible", () => {
  const source = readFileSync(new URL("../src/skill-workflow/SkillExperience.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../src/skill-workflow/skill-workflow.css", import.meta.url), "utf8");
  assert.match(source, /!\(stage\.id === "storyboard_design" && workspace\.shot_manifest\) && <StageSummary/);
  assert.match(source, /style=\{lookTestLayoutStyle\(contract, candidates\.length\)\}/);
  const imageStyle = css.match(/\.skill-look-grid img\s*\{([^}]+)\}/)[1];
  assert.match(imageStyle, /object-fit: contain/);
  assert.match(imageStyle, /height: 100%/);
  const frameStyle = css.match(/\.skill-look-grid button\s*\{([^}]+)\}/)[1];
  assert.match(frameStyle, /aspect-ratio: var\(--skill-look-ratio/);
  assert.match(frameStyle, /width: min\(100%, calc\(var\(--skill-look-max-height\) \* var\(--skill-look-ratio/);
  assert.doesNotMatch(imageStyle, /max-height: 320px/);
  assert.match(source, /aria-label=\{`采用风格候选 \$\{index \+ 1\}`\}/);
});

test("preparation fills its container without stretching shared toolbar buttons", () => {
  const css = readFileSync(new URL("../src/skill-workflow/skill-workflow.css", import.meta.url), "utf8");
  assert.match(css, /\.skill-preparation-panel\s*\{[^}]*container-type: inline-size/);
  assert.match(css, /\.skill-preparation-panel > \.skill-stage-actions-stack\s*\{[^}]*justify-items: stretch/);
  assert.match(css, /\.skill-preparation-panel > \.skill-stage-actions-stack > button\s*\{[^}]*justify-self: start/);
  assert.match(css, /\.skill-look-workspace\s*\{[^}]*width: 100%/);
  assert.match(css, /\.skill-storyboard-progress\s*\{[^}]*width: 100%/);
  assert.match(css, /@container skill-preparation \(min-width: 600px\)/);
  assert.match(css, /@container skill-preparation \(min-width: 1120px\)/);
  assert.doesNotMatch(css, /repeat\(2, minmax\(0, 320px\)\)/);
});

test("storyboard task status has a responsive summary and an accessible full-width progress track", () => {
  const source = readFileSync(new URL("../src/skill-workflow/SkillExperience.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../src/skill-workflow/skill-workflow.css", import.meta.url), "utf8");
  assert.match(source, /className="skill-storyboard-progress-summary"/);
  assert.match(source, /role="progressbar" aria-label="大纲与分镜生成进度" aria-valuemin=\{0\} aria-valuemax=\{100\} aria-valuenow=\{progress\}/);
  assert.match(css, /@container skill-preparation \(min-width: 900px\)/);
  assert.match(css, /\.skill-storyboard-progress > p\s*\{[^}]*overflow-wrap: anywhere/);
});

test("storyboard prompt columns respond to editor width as well as mobile viewport", () => {
  const css = readFileSync(new URL("../src/skill-workflow/storyboard-prompt-editor.css", import.meta.url), "utf8");
  assert.match(css, /\.storyboard-prompt-editor\s*\{[^}]*container-name: storyboard-prompts/);
  assert.match(css, /\.storyboard-prompt-columns\s*\{[^}]*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(css, /@container storyboard-prompts \(max-width: 900px\)/);
  assert.match(css, /@media \(max-width: 760px\)/);
});

test("Skill image generation uses the selected contract model even when global settings prefer a local tool", () => {
  const globalSettings = { enabled: true, execution_mode: "local_tool", api_key_configured: true, local_executable_path: "local-tool", local_tool_id: "imagegen", models: [{ alias: "chosen" }, { alias: "other" }] };
  const settings = skillImageGenerationSettings(globalSettings, { image_model_id: "chosen", candidate_count_by_stage: { shot_image: 2 } });
  assert.equal(resolveImageExecutionMode(settings), "remote_api");
  assert.equal(settings.remote_model_alias, "chosen");
  assert.equal(settings.default_candidate_count, 2);
  assert.deepEqual(imageModelOptions(settings).map((model) => model.alias), ["chosen"]);
  assert.equal(resolveImageExecutionMode(globalSettings), "local_tool");
});

test("a missing contracted image model never falls back to another model or local execution", () => {
  const settings = skillImageGenerationSettings({ enabled: true, models: [{ alias: "other" }], local_executable_path: "local-tool" }, { image_model_id: "missing" });
  assert.equal(settings.remote_model_alias, "missing");
  assert.deepEqual(imageModelOptions(settings), []);
});

test("timeline source-audio controls require both a source project and a real audio track", () => {
  const source = readFileSync(new URL("../src/video-editor/VideoEditorWorkspace.jsx", import.meta.url), "utf8");
  assert.match(source, /hasSourceAudio && <option value="source">/);
  assert.equal((source.match(/hasSourceAudio=\{Boolean\(project\.video_id && timeline\.audio_track\.source_audio_url\)\}/g) || []).length, 2);
  assert.match(source, /hasSourceAudio && !hasCandidateAudio && <option value="continuous_source_track">/);
});
