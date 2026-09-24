import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { parse } from "@babel/parser";
import { createGlobalPromptSession } from "../src/prompt-context/global-prompt-session.js";
import { effectiveStyleSnapshot, filterStyles, hasVisualStyle, presetSettingsPayload, stylePrompt, styleRecoverySummary, styleValidation, visualStyleKey } from "../src/visual-styles/visual-style.js";
import { productionPromptsToText, promptDocumentBody } from "../src/prompt-editor/prompt-sources.js";
import { draftToPayload } from "../src/category-profiles/category-profile-ui.js";

const natural = { version: "visual-style-v1", selection: { preset: "natural" }, label: "自然实拍", image_prompt: "自然实拍的静态规则", video_prompt: "自然实拍的动作规则" };
const anime = { version: "visual-style-v1", selection: { preset: "anime" }, label: "二维动漫", image_prompt: "动漫静态规则", video_prompt: "动漫动作规则" };
const initial = { id: "r1", common_image_prompt: "手写全局 @服装", common_video_prompt: "手写动作", visual_style: natural.selection, visual_style_snapshot: natural, shot_styles: {}, shot_style_snapshots: {} };

test("effective style prioritizes shot override, including an explicit existing-style choice", () => {
  const context = { ...initial, shot_style_snapshots: { b: anime, c: {} } };
  assert.equal(stylePrompt(context, "a", "image"), natural.image_prompt);
  assert.equal(stylePrompt(context, "b", "video"), anime.video_prompt);
  assert.equal(stylePrompt(context, "c", "image"), "");
  assert.deepEqual(effectiveStyleSnapshot({}, "a"), {});
  assert.ok(styleValidation({ preset: "custom", description: "  " }));
  assert.equal(styleValidation({ preset: "custom", description: "自然光摄影" }), "");
});

test("global session saves structured style separately and preserves manual bodies", async () => {
  const calls = [];
  const session = createGlobalPromptSession(initial, { save: async payload => {
    calls.push(payload);
    return { ...initial, ...payload, id: "r2", shot_style_snapshots: { shot2: anime } };
  } });
  session.editStyle(anime.selection, anime, "shot2");
  assert.equal(stylePrompt(session.snapshot().values, "shot2", "image"), anime.image_prompt);
  assert.equal(await session.flush(), true);
  assert.deepEqual(calls[0].shot_styles, { shot2: anime.selection });
  assert.equal(calls[0].common_image_prompt, initial.common_image_prompt);
  assert.ok(!Object.hasOwn(calls[0], "shot_style_snapshots"));
  assert.ok(!Object.hasOwn(calls[0], "visual_style_snapshot"));
  session.editStyle(null, {}, "shot2");
  assert.deepEqual(session.snapshot().values.shot_styles, {});
  assert.equal(stylePrompt(session.snapshot().values, "shot2", "image"), natural.image_prompt);
});

test("in-flight acknowledgement cannot discard a newer style or manual draft", async () => {
  let resolveFirst;
  const calls = [];
  const session = createGlobalPromptSession(initial, { save: payload => {
    calls.push(payload);
    if (calls.length === 1) return new Promise(resolve => { resolveFirst = () => resolve({ ...initial, ...payload, id: "r2" }); });
    return Promise.resolve({ ...initial, ...payload, id: "r3", visual_style_snapshot: anime });
  } });
  session.edit("image", "新的手写内容");
  const saving = session.flush();
  await Promise.resolve();
  session.editStyle(anime.selection, anime);
  resolveFirst();
  assert.equal(await saving, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].expected_revision_id, "r2");
  assert.deepEqual(calls[1].visual_style, anime.selection);
  assert.equal(session.snapshot().values.common_image_prompt, "新的手写内容");
  assert.equal(session.snapshot().dirty, false);
});

test("failed saves retain style drafts and restoring cached drafts includes overrides", async () => {
  const session = createGlobalPromptSession(initial, { save: async () => { throw new Error("版本冲突"); } });
  session.editStyle(anime.selection, anime, "shot2");
  assert.equal(await session.flush(), false);
  assert.equal(session.snapshot().error, "版本冲突");
  const restored = createGlobalPromptSession(initial, { save: async payload => ({ ...initial, ...payload, id: "r2" }) });
  restored.restoreStyles(session.snapshot().values);
  assert.equal(restored.snapshot().dirty, true);
  assert.deepEqual(restored.snapshot().values.shot_styles, { shot2: anime.selection });
});

function pickerHandler(name, scope) {
  const source = readFileSync(new URL("../src/visual-styles/VisualStyleControl.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const owner = ast.program.body.map(node => node.declaration || node).find(node => node.id?.name === "StylePicker");
  const handler = owner.body.body.find(node => node.type === "FunctionDeclaration" && node.id.name === name);
  return new Function("scope", `with(scope) { return (${source.slice(handler.start, handler.end)}); }`)(scope);
}

test("style library filters previews without mutating catalog and preserves version identity", () => {
  const sparse = { preset: "natural" };
  const filled = { motion: "", camera: "", texture: "", color: "", lighting: "", description: "", preset: "natural" };
  assert.equal(visualStyleKey(sparse), visualStyleKey(filled));
  assert.notEqual(visualStyleKey(null), visualStyleKey({ preset: "original" }));
  assert.equal(visualStyleKey({ catalog_id: "a", catalog_version: 1 }), visualStyleKey({ ...filled, catalog_id: "a", catalog_version: 1 }));
  assert.notEqual(visualStyleKey({ catalog_id: "a", catalog_version: 1 }), visualStyleKey({ catalog_id: "a", catalog_version: 2 }));
  const items = [{ id: "a", name: "自然实拍", category: "摄影", tags: ["街拍"], applies_to: ["image", "video"], favorite: true, used_at: "2026-09-21" }, { id: "b", name: "二维动漫", category: "艺术", applies_to: ["video"], used_at: "2026-09-23" }];
  assert.deepEqual(filterStyles(items, { query: " 街拍 " }).map(x => x.id), ["a"]);
  assert.deepEqual(filterStyles(items, { part: "image", tab: "favorites" }).map(x => x.id), ["a"]);
  assert.deepEqual(filterStyles(items, { tab: "recent" }).map(x => x.id), ["b", "a"]);
  assert.deepEqual(filterStyles(items, { category: "艺术", part: "image" }), []);
  assert.equal(items[0].id, "a");
});

test("actual picker applies once after preview, retains a failed choice, and ignores unmounted previews", async () => {
  let finish, applied = 0, closed = 0, error = "", calls = 0;
  const scope = { submitting: { current: false }, mounted: { current: true }, validSelection: true, selected: natural.selection,
    setSaving: () => {}, setError: value => { error = value; }, hasVisualStyle, BASE: "/styles", json: x => x,
    request: () => { calls++; return new Promise(resolve => { finish = resolve; }); },
    onApply: async () => { applied++; }, onClose: () => { closed++; } };
  const apply = pickerHandler("apply", scope);
  const pending = apply(); await apply(); assert.equal(calls, 1); assert.equal(applied, 0);
  finish(natural); await pending; assert.equal(applied, 1); assert.equal(closed, 1);
  scope.onApply = async () => { throw new Error("版本冲突"); };
  const failed = apply(); finish(natural); await failed; assert.equal(error, "版本冲突"); assert.equal(closed, 1);
  const stale = apply(); scope.mounted.current = false; finish(natural); await stale;
  assert.equal(applied, 1); assert.equal(closed, 1);
});

test("style-only recovery shows both full selections and explicit shot overrides", () => {
  const local = { ...initial, visual_style: { ...natural.selection, description: "自然阴天" }, shot_styles: { shot2: { preset: "original" }, shot1: anime.selection }, shot_style_snapshots: { shot1: anime, shot2: {} } };
  const summary = styleRecoverySummary(local);
  assert.match(summary, /整片：自然实拍/); assert.match(summary, /描述：自然阴天/);
  assert.match(summary, /分镜 shot1：二维动漫/); assert.match(summary, /分镜 shot2：沿用现有风格/);
  assert.match(summary, /分镜覆盖：2 项/);
  assert.notEqual(summary, styleRecoverySummary(initial));
  assert.match(styleRecoverySummary({}), /保留服务器风格/);
  const source = readFileSync(new URL("../src/prompt-context/GlobalPromptEditor.jsx", import.meta.url), "utf8");
  assert.match(source, /\["本地画面风格", recovery\], \["服务器画面风格", state\?\.values\]/);
});

test("account presets merge latest preferences with CAS, reject duplicates, and never overwrite", () => {
  const state = { revision: 4, settings: { text_model_alias: "existing", max_cost_cny: 5, visual_style_presets: [] } };
  const next = presetSettingsPayload(state, " 街拍 ", natural.selection, "id1");
  assert.equal(next.revision, 4);
  assert.equal(next.settings.text_model_alias, "existing");
  assert.equal(next.settings.max_cost_cny, 5);
  assert.equal(next.settings.visual_style_presets[0].name, "街拍");
  assert.equal(state.settings.visual_style_presets.length, 0);
  assert.throws(() => presetSettingsPayload(next, "街拍", anime.selection, "id2"), /同名/);
  assert.throws(() => presetSettingsPayload(state, " ", anime.selection, "id2"), /名称/);
});

test("TXT includes each effective style but document edits cannot overwrite style metadata", () => {
  const document = { name: "制作方案", token: "token", common_image_prompt: "共用图像", common_video_prompt: "共用动作", visual_style_snapshot: natural,
    shots: [{ id: "s1", index: 1, duration_seconds: 1.5, visual_style_snapshot: anime, images: [{ id: "b1", prompt: "本镜静态", negative_constraints: [] }], video_prompt: "本镜行走", video_negative_constraints: [] },
      { id: "s2", index: 2, duration_seconds: 1.5, visual_style_snapshot: {}, images: [{ id: "b2", prompt: "保持原片", negative_constraints: [] }], video_prompt: "原来动作", video_negative_constraints: [] }] };
  const text = productionPromptsToText(document);
  assert.ok(text.includes(anime.image_prompt) && text.includes(anime.video_prompt));
  assert.ok(!text.includes(natural.image_prompt));
  assert.ok(!Object.hasOwn(promptDocumentBody(document).shots[0], "visual_style_snapshot"));
  assert.deepEqual(draftToPayload({ default_visual_style: natural.selection }).default_visual_style, natural.selection);
  assert.ok(!Object.hasOwn(draftToPayload({}), "default_visual_style"));
});

function creativeHandler(name, scope) {
  const source = readFileSync(new URL("../src/viral-report/ReplicationWorkspace.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const owner = ast.program.body.map(node => node.declaration || node).find(node => node.id?.name === "ReplicationWorkspace");
  const fn = owner.body.body.find(node => node.type === "FunctionDeclaration" && node.id.name === name);
  return new Function("scope", `with(scope) { return (${source.slice(fn.start, fn.end)}); }`)(scope);
}

function productionStyleHandler(name, scope) {
  const source = readFileSync(new URL("../src/visual-styles/ProductionStyleControl.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const owner = ast.program.body.map(node => node.declaration || node).find(node => node.id?.name === "ProductionStyleControl");
  const fn = name === "effect"
    ? owner.body.body.find(node => node.expression?.callee?.name === "useEffect").expression.arguments[0]
    : owner.body.body.find(node => node.type === "FunctionDeclaration" && node.id.name === name);
  return new Function("scope", `with(scope) { return (${source.slice(fn.start, fn.end)}); }`)(scope);
}

test("failed production-style reads clear pending without falsely reporting availability", async () => {
  const pending = [], available = []; let error;
  const scope = { active: { current: false }, callbacks: { current: { onPending: value => pending.push(value), onAvailable: value => available.push(value) } },
    setState: () => {}, setError: value => { error = value; }, path: "/style", AbortSignal,
    request: async () => { throw new Error("读取失败"); } };
  const cleanup = productionStyleHandler("effect", scope)();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(pending, [true, false]); assert.ok(available.every(value => value === false));
  assert.equal(error, "读取失败"); cleanup(); assert.equal(scope.active.current, false);
});

test("production style 409 reads the new revision but never silently replays the chosen style", async () => {
  const calls = []; let conflict = true;
  const scope = { state: { revision: "1" }, path: "/style", active: { current: true }, AbortSignal, setError: () => {},
    setState: value => { scope.state = value; }, request: async (_path, options = {}) => {
      calls.push(options);
      if (options.method === "PUT" && conflict) throw Object.assign(new Error("版本冲突"), { status: 409 });
      return { revision: options.method === "PUT" ? "3" : "2", snapshot: natural, selection: natural.selection };
    } };
  const save = productionStyleHandler("save", scope);
  await assert.rejects(save(anime.selection), /当前选择仍保留.*再次应用/);
  assert.equal(calls.length, 2); assert.equal(scope.state.revision, "2");
  assert.deepEqual(JSON.parse(calls[0].body).visual_style, anime.selection);
  conflict = false; await save(anime.selection);
  assert.equal(JSON.parse(calls[2].body).expected_revision, "2"); assert.equal(scope.state.revision, "3");
});

test("actual creative handlers include style in new requests and block unapplied edits", () => {
  const calls = [];
  const scope = { selectedCategoryId: "jk", styleBlocked: false, styleAvailable: true, hasVisualStyle, analysisId: "analysis", effectiveFeedback: "五个地标", selectedReplacements: [], effectiveStyle: natural.selection, visualStyle: null, ORIGINAL_STYLE: { preset: "original" }, revisionSupported: true, ideaBatch: { id: "batch" }, setConceptError: error => calls.push(error), submit: (path, body) => calls.push({ path, body }) };
  const generate = creativeHandler("generateConcepts", scope);
  generate(); assert.deepEqual(calls[0].body.visual_style, natural.selection);
  scope.styleBlocked = true; generate(); assert.equal(calls.length, 1);
  scope.styleBlocked = false;
  const act = creativeHandler("actOnIdea", scope);
  act({ id: "idea", visual_style_snapshot: anime }, "expand");
  assert.deepEqual(calls[1].body.visual_style, anime.selection);
  scope.visualStyle = natural.selection;
  act({ id: "idea", visual_style_snapshot: anime }, "regenerate", "保留地标");
  assert.deepEqual(calls[2].body.visual_style, natural.selection);
  assert.equal(calls[2].body.revision_notes, "保留地标");
  scope.visualStyle = null; scope.effectiveStyle = scope.ORIGINAL_STYLE; scope.styleAvailable = false;
  act({ id: "other-idea", visual_style_snapshot: anime }, "regenerate", "保持色调");
  assert.match(calls[3].message, /风格服务不可用/);
  assert.equal(calls.length, 4);
});
