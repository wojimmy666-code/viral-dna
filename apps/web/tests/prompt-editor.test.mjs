import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const EDITOR_URL = new URL("../src/prompt-editor/PromptEditor.jsx", import.meta.url);
const SHOT_URL = new URL("../src/prompt-editor/PromptShotEditor.jsx", import.meta.url);
const TIMELINE_URL = new URL("../src/prompt-editor/PromptTimelineEditor.jsx", import.meta.url);
const HELPERS_URL = new URL("../src/prompt-editor/prompt-editor-ui.js", import.meta.url);
const CSS_URL = new URL("../src/prompt-editor/prompt-editor.css", import.meta.url);

test("prompt report uses the isolated structured editor", async () => {
  const app = await readFile(APP_URL, "utf8");
  const editor = await readFile(EDITOR_URL, "utf8");

  assert.match(app, /import \{ PromptEditor \} from "\.\/prompt-editor\/index\.js"/);
  assert.match(app, /<PromptEditor/);
  assert.doesNotMatch(app, /function PromptsTab\(/);
  assert.match(editor, /\/analyses\/\$\{analysisId\}\/prompt-draft/);
  assert.match(editor, /method: "PATCH"/);
  assert.match(editor, /expected_revision_id: basePackage\.revision_id/);
  assert.match(editor, /onBlurCapture=\{saveWhenLeavingEditor\}/);
  assert.match(editor, /await saveChainRef\.current/);
  assert.match(editor, /onDownload\(packageRef\.current\)/);
});

test("prompt editing separates visual facts, timeline, transition, and compiled input", async () => {
  const shot = await readFile(SHOT_URL, "utf8");
  const timeline = await readFile(TIMELINE_URL, "utf8");
  const css = await readFile(CSS_URL, "utf8");

  for (const label of ["基础画面", "出场转场", "约束与补充说明", "查看模型输入"]) {
    assert.match(shot, new RegExp(label));
  }
  assert.match(shot, /<textarea/);
  assert.match(shot, /defaultOpen=\{index === 0\}/);
  assert.match(timeline, /新增阶段/);
  assert.match(timeline, /主体动作/);
  assert.match(timeline, /镜头运动/);
  assert.match(css, /\.prompt-compiled-preview pre\s*\{[^}]*white-space:\s*pre-wrap/s);
  assert.match(css, /\.prompt-legacy-preview pre\s*\{[^}]*white-space:\s*pre-wrap/s);
});

test("prompt draft helpers preserve pending edits during server revision merges", async () => {
  const {
    containsUnlabeledEnglish,
    mergePendingDrafts,
    hasReportableGlobalPrompt,
    PROMPT_AUTOSAVE_DELAY_MS,
    promptDraftContainsUnlabeledEnglish,
    replaceShotDraft,
  } = await import(HELPERS_URL);
  const base = {
    shots: [
      { shot_id: "shot_001", draft: { custom_notes: "server" } },
      { shot_id: "shot_002", draft: { custom_notes: "unchanged" } },
    ],
  };
  const localDraft = { custom_notes: "local" };

  assert.equal(PROMPT_AUTOSAVE_DELAY_MS, 700);
  assert.equal(
    hasReportableGlobalPrompt("逐镜头视觉事实和复刻提示词已生成；全局实体连续性待归并"),
    false,
  );
  assert.equal(hasReportableGlobalPrompt("同一人物与场景贯穿全片"), true);
  assert.equal(containsUnlabeledEnglish("Static / Locked-off"), true);
  assert.equal(containsUnlabeledEnglish("英文标识：“Customer Map”"), false);
  assert.equal(promptDraftContainsUnlabeledEnglish({
    visual: { scene: "城市天际线" },
    phases: [{ subject_motion: "Standing still" }],
  }), true);
  assert.equal(replaceShotDraft(base, "shot_001", localDraft).shots[0].draft, localDraft);
  assert.equal(
    mergePendingDrafts(base, new Map([["shot_001", localDraft]])).shots[0].draft,
    localDraft,
  );
  assert.equal(base.shots[0].draft.custom_notes, "server");
});
