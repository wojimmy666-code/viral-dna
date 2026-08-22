import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const APP_URL = new URL("../src/App.jsx", import.meta.url);
const EDITOR_URL = new URL("../src/prompt-editor/PromptEditor.jsx", import.meta.url);
const SHOT_URL = new URL("../src/prompt-editor/PromptShotEditor.jsx", import.meta.url);
const RICH_EDITOR_URL = new URL("../src/prompt-editor/PromptRichTextEditor.jsx", import.meta.url);
const HELPERS_URL = new URL("../src/prompt-editor/prompt-editor-ui.js", import.meta.url);
const DOCUMENT_URL = new URL("../src/prompt-editor/prompt-document.js", import.meta.url);
const CSS_URL = new URL("../src/prompt-editor/prompt-editor.css", import.meta.url);

function sampleDraft() {
  return {
    visual: {
      subjects: "@托管角色/小喵酱 站在公园中",
      scene: "户外公园",
      composition: "中心构图",
      lighting: "自然散射光",
      color: "自然绿色",
    },
    phases: [{
      id: "phase_1",
      start_seconds: 0,
      end_seconds: 3,
      subject_motion: "右臂前伸",
      camera_motion: "固定机位",
      foreground_motion: "树叶轻晃",
      focus_change: "焦点保持在人物面部",
    }],
    transition: {
      kind: "foreground_occlusion",
      start_seconds: 2.6,
      end_seconds: 3,
      instruction: "前景树叶覆盖镜头",
      mask_object: "树叶",
      direction: "从右向左",
      terminal_frame: "画面完全被覆盖",
    },
    continuity_refs: ["保持白色口罩"],
    negative_constraints: ["不要改变动作顺序"],
    custom_notes: "保持原节奏",
  };
}

test("prompt report keeps structured autosave while downloading plain text", async () => {
  const app = await readFile(APP_URL, "utf8");
  const editor = await readFile(EDITOR_URL, "utf8");

  assert.match(app, /PromptEditor,[\s\S]*promptPackageToPlainText,[\s\S]*promptTextFilename/);
  assert.match(app, /function downloadPromptText\(/);
  assert.match(app, /type: "text\/plain;charset=utf-8"/);
  assert.match(app, /document\.body\.appendChild\(anchor\)/);
  assert.match(app, /window\.setTimeout\(\(\) => URL\.revokeObjectURL\(href\), 0\)/);
  assert.match(app, /onDownload=\{downloadPromptText\}/);
  assert.match(editor, /"\/analyses\/" \+ analysisId \+ "\/prompt-draft"/);
  assert.match(editor, /method: "PATCH"/);
  assert.match(editor, /expected_revision_id: basePackage\.revision_id/);
  assert.match(editor, /onBlurCapture=\{saveWhenLeavingEditor\}/);
  assert.match(editor, /await saveChainRef\.current/);
  assert.match(editor, /onDownload\?\.\(packageRef\.current\)/);
  assert.match(editor, /下载 TXT/);
  assert.doesNotMatch(editor, /下载 JSON|机器可读 Prompt Package/);
});

test("direction A uses independent collapsed rows and one continuous editor", async () => {
  const editor = await readFile(EDITOR_URL, "utf8");
  const shot = await readFile(SHOT_URL, "utf8");
  const richEditor = await readFile(RICH_EDITOR_URL, "utf8");
  const css = await readFile(CSS_URL, "utf8");

  assert.match(editor, /<h2>提示词文档<\/h2>/);
  assert.match(editor, /key=\{`\$\{analysisId\}:\$\{shot\.shot_id\}`\}/);
  assert.match(editor, /默认使用简体中文/);
  assert.match(shot, /const \[isOpen, setIsOpen\] = useState\(false\)/);
  assert.match(shot, /aria-expanded=\{isOpen\}/);
  assert.match(shot, /onClick=\{\(\) => setIsOpen\(\(current\) => !current\)\}/);
  assert.match(shot, /className="prompt-document-shot-summary"/);
  assert.match(shot, /promptShotCharacterCount\(shot\)/);
  assert.match(shot, /<PromptRichTextEditor/);
  assert.match(shot, /promptDocumentTextToDraft\(nextText, draft\)/);
  assert.doesNotMatch(shot, /<textarea|<input|<select|<details/);
  assert.doesNotMatch(shot, /PromptDocumentField|PromptTimelineEditor|PromptSectionView|模型输入/);
  assert.doesNotMatch(editor, /activeShot|expandedShot|openShot/);

  assert.match(richEditor, /contentEditable=\{!disabled\}/);
  assert.match(richEditor, /role="textbox"/);
  assert.match(richEditor, /event\.clipboardData\.getData\("text\/plain"\)/);
  assert.match(richEditor, /deleteAtomicPromptDecoration/);
  assert.match(richEditor, /decoration\.textContent = range\.text/);

  assert.match(css, /\.prompt-document-shot-list\s*\{[^}]*border-block:\s*1px solid var\(--border-default\)/s);
  assert.match(css, /\.prompt-document-shot \+ \.prompt-document-shot\s*\{[^}]*border-top:/s);
  assert.match(css, /\.prompt-document-surface\s*\{[^}]*padding:\s*var\(--space-4\)/s);
  assert.doesNotMatch(css, /\.prompt-document-surface > \*|width:\s*min\(100%, 84ch\)/);
  assert.doesNotMatch(css, /calc\(var\(--space-(?:4|6)\) \+ var\(--space-3\)\)/);
  assert.match(css, /\.prompt-document-shot-body-toolbar\s*\{[^}]*width:\s*100%/s);
  assert.match(css, /\.prompt-document-warning\s*\{[^}]*width:\s*100%/s);
  assert.match(css, /\.prompt-rich-editor\s*\{[^}]*width:\s*100%[^}]*font-size:\s*var\(--type-body-size\)[^}]*line-height:\s*var\(--type-leading-editor\)/s);
  assert.doesNotMatch(css, /width:\s*min\(100%, 72ch\)/);
  assert.match(css, /\.prompt-rich-token-label,[\s\S]*background:\s*var\(--surface-hover\)/);
  assert.match(css, /\.prompt-rich-token-mention\s*\{[^}]*color:\s*var\(--accent\)/s);
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.prompt-rich-editor\s*\{[^}]*font-size:\s*var\(--type-subheading-size\)/s);
  assert.doesNotMatch(css, /\.prompt-document-field|\.prompt-document-phase|\.prompt-document-compiled/);
});

test("continuous prompt text round-trips to the structured draft", async () => {
  const {
    deleteAtomicPromptDecoration,
    deleteAtomicPromptReference,
    findPromptDecorationRanges,
    findPromptReferenceRanges,
    promptDocumentTextToDraft,
    promptDraftToDocumentText,
    promptPackageToPlainText,
    promptTextFilename,
  } = await import(DOCUMENT_URL);
  const draft = sampleDraft();
  const documentText = promptDraftToDocumentText(draft);

  assert.match(documentText, /^【基础画面】\n【主体与服装】 @托管角色\/小喵酱 站在公园中\n【场景】 户外公园/m);
  assert.match(documentText, /【时序运镜】\n【0\.00–3\.00s】\n【主体动作】 右臂前伸\n【镜头运动】 固定机位/);
  assert.match(documentText, /【出场转场】\n【类型】 前景遮挡\n【时间】 2\.60–3\.00s/);
  assert.match(documentText, /【负面约束】\n- 不要改变动作顺序/);
  assert.match(documentText, /【补充说明】\n保持原节奏$/);
  assert.doesNotMatch(documentText, /phase_1|[{}]/);

  const multiPhaseText = promptDraftToDocumentText({
    ...draft,
    phases: [
      ...draft.phases,
      {
        ...draft.phases[0],
        id: "phase_2",
        start_seconds: 3,
        end_seconds: 4,
        subject_motion: "转身停顿",
      },
    ],
  });
  assert.match(multiPhaseText, /【焦点变化】 焦点保持在人物面部\n\n【3\.00–4\.00s】\n【主体动作】 转身停顿/);
  assert.match(
    promptDraftToDocumentText({ ...draft, transition: { kind: "none" } }),
    /【出场转场】\n无转场/,
  );

  const parsed = promptDocumentTextToDraft(documentText, draft);
  assert.deepEqual(parsed.visual, draft.visual);
  assert.deepEqual(parsed.phases, draft.phases);
  assert.deepEqual(parsed.transition, draft.transition);
  assert.deepEqual(parsed.continuity_refs, draft.continuity_refs);
  assert.deepEqual(parsed.negative_constraints, draft.negative_constraints);
  assert.equal(parsed.custom_notes, draft.custom_notes);

  const edited = documentText
    .replace("户外公园", "湖边公园")
    .replace("右臂前伸", "右臂缓慢前伸");
  const editedDraft = promptDocumentTextToDraft(edited, draft);
  assert.equal(editedDraft.visual.scene, "湖边公园");
  assert.equal(editedDraft.phases[0].subject_motion, "右臂缓慢前伸");

  const promptPackage = {
    version: 3,
    revision_id: "internal-revision",
    target_model: "seedance",
    global_prompt: "同一人物与场景贯穿全片",
    continuity_locks: ["人物身份保持一致"],
    negative_constraints: ["不要新增人物"],
    shots: [{
      shot_id: "shot_001",
      duration_seconds: 3,
      draft,
    }],
  };
  const plainText = promptPackageToPlainText(promptPackage);
  assert.match(plainText, /^全局视觉路径\n\n同一人物与场景贯穿全片/m);
  assert.match(plainText, /分镜 01 · 3\.0 秒/);
  assert.match(plainText, /【主体与服装】 @托管角色\/小喵酱/);
  assert.doesNotMatch(plainText, /shot_001|revision_id|internal-revision|[{}]/);
  assert.equal(promptTextFilename(promptPackage), "viral-dna-prompts-v3.txt");

  const decorations = findPromptDecorationRanges(documentText);
  assert.ok(decorations.some((range) => range.type === "section"));
  assert.ok(decorations.some((range) => range.type === "label"));
  assert.ok(decorations.some((range) => range.type === "time"));
  assert.ok(decorations.some((range) => range.type === "mention"));

  const reference = "@托管角色/小喵酱";
  const prompt = "替换为 " + reference + "，然后抬手。";
  const [range] = findPromptReferenceRanges(prompt);
  assert.deepEqual(
    deleteAtomicPromptReference(prompt, { key: "Backspace", selectionStart: range.end }),
    { value: "替换为 ，然后抬手。", caret: range.start },
  );
  const semanticText = "【主体与服装】 人物抬手";
  const semanticRange = findPromptDecorationRanges(semanticText)[0];
  assert.deepEqual(
    deleteAtomicPromptDecoration(semanticText, {
      key: "Delete",
      selectionStart: semanticRange.start,
    }),
    { value: " 人物抬手", caret: 0 },
  );
});

test("removing all phase labels keeps valid timing slots without restoring copy", async () => {
  const { promptDocumentTextToDraft } = await import(DOCUMENT_URL);
  const draft = sampleDraft();
  const parsed = promptDocumentTextToDraft("【补充说明】 仅保留这句话", draft);

  assert.equal(parsed.phases.length, 1);
  assert.equal(parsed.phases[0].id, "phase_1");
  assert.equal(parsed.phases[0].start_seconds, 0);
  assert.equal(parsed.phases[0].end_seconds, 3);
  assert.equal(parsed.phases[0].subject_motion, "");
  assert.equal(parsed.custom_notes, "仅保留这句话");
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
