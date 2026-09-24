import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parse } from "@babel/parser";
import { imageGenerationInputManifest } from "../src/production-ui.js";
import { globalPromptWasEdited } from "../src/prompt-context/input-freshness.js";
import { restoreGenerationPreferences } from "../src/image-generation-controls/generation-preferences.js";
import { imageBindingsForDraft, resolveImageInputMode, imageBaseCandidateId } from "../src/image-generation-controls/image-input.js";

test("shot images default to one, migrate only old counts and retain later explicit choices", () => {
  const defaults = {count:1, model:"default", inputMode:"text_to_image"};
  const legacy = {count:2, model:"chosen", resolution:"1280x720", inputMode:"keyframe_edit"};
  const policy = {count:1};
  assert.equal(restoreGenerationPreferences(null, defaults, policy).count, 1);
  assert.deepEqual(restoreGenerationPreferences(legacy, defaults, policy), {...legacy, count:1});
  assert.equal(legacy.count, 2); // Reading never rewrites the stored selection.
  assert.deepEqual(restoreGenerationPreferences({...legacy, _defaultVersions:policy}, defaults, policy), legacy);
  assert.equal(restoreGenerationPreferences(legacy, defaults).count, 2); // Other stages unchanged.
  assert.equal(restoreGenerationPreferences({count:4, _defaultVersions:null}, defaults, policy).count, 1);
  assert.equal(restoreGenerationPreferences("invalid", defaults, policy).count, 1);
});

test("global prompt notices are part-specific and do not flag hydration or a reverted edit", () => {
  const detail = { current_global_prompts: { common_image_prompt: "柔光", common_video_prompt: "慢推" } };
  assert.equal(globalPromptWasEdited(detail, {}, "image"), false);
  assert.equal(globalPromptWasEdited({}, { common_image_prompt: "暖光" }, "image"), false);
  assert.equal(globalPromptWasEdited(detail, { common_image_prompt: "暖光", common_video_prompt: "慢推" }, "image"), true);
  assert.equal(globalPromptWasEdited(detail, { common_image_prompt: "暖光", common_video_prompt: "慢推" }, "video"), false);
  assert.equal(globalPromptWasEdited(detail, { common_image_prompt: "柔光" }, "image"), false);
});

import {
  assetMentionLabel,
  assetMentionToken,
  ensurePromptMentionTokens,
  isVisibleImageCandidate,
  normalizePromptMentionDraft,
  reconcilePromptReferenceRemoval,
  removeMentionFromPrompt,
} from "../src/shot-image-ui.js";
import {
  LOCAL_IMAGE_MODEL_ALIAS,
  imageGenerationSummary,
  imageModelCompatibility,
  imageModelOptions,
} from "../src/image-generation-controls/image-generation-ui.js";

const shotImageSource = readFileSync(
  new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
  "utf8",
);
const productionWorkflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);

test("both image workflows use the single-picture default with the same cache policy", () => {
  const choices = productionWorkflowSource.slice(productionWorkflowSource.indexOf("const [imageChoices"), productionWorkflowSource.indexOf("const { engine: generationEngine"));
  assert.match(choices, /count: 1,/);
  assert.match(choices, /defaultVersions: \{ count: 1 \}/);
  assert.doesNotMatch(choices, /default_candidate_count/);
});
const productionWorkflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);
const imageCommandBarSource = readFileSync(
  new URL("../src/image-generation-controls/ImageGenerationCommandBar.jsx", import.meta.url),
  "utf8",
);
const imageControlStyles = readFileSync(
  new URL("../src/image-generation-controls/image-generation-controls.css", import.meta.url),
  "utf8",
);

test("image entry is a one-adopted-picture action without a required-shot checkbox", () => {
  assert.doesNotMatch(shotImageSource, /必需分镜|未确认时阻止|shot-required-check|draft\.required/);
  assert.match(shotImageSource, /已采用 \{gate\?\.approved_image_count \|\| 0\} 张/);
  assert.match(shotImageSource, /disabled=\{busy \|\| !gate\?\.allowed\}/);
  assert.doesNotMatch(shotImageSource, /确认图片，进入|advanced/);
  assert.match(productionWorkflowSource, /gate=\{gate\?\.current_step === "shot_images" \? gate : null\}/);
});

test("shows directory and asset name while keeping the reference id stable", () => {
  const asset = {
    id: "asset-1",
    folder_name: "人物",
    name: "面部",
  };
  assert.equal(assetMentionLabel(asset), "人物/面部");
  assert.equal(assetMentionToken(asset), "@人物/面部");

  const normalized = normalizePromptMentionDraft(
    "中景镜头，@面部 站在栏杆前",
    [{ reference_asset_id: asset.id, label: "面部" }],
    [asset],
  );
  assert.equal(normalized.imagePrompt, "中景镜头，@人物/面部 站在栏杆前");
  assert.deepEqual(normalized.imagePromptMentions, [
    { reference_asset_id: asset.id, label: "人物/面部" },
  ]);
  assert.equal(
    removeMentionFromPrompt(
      normalized.imagePrompt,
      normalized.imagePromptMentions[0],
      asset,
    ),
    "中景镜头， 站在栏杆前",
  );
});

test("restores missing @ tokens from saved asset bindings without duplicates", () => {
  const asset = {
    id: "asset-1",
    folder_name: "托管角色",
    name: "小喵酱",
  };
  const normalized = normalizePromptMentionDraft(
    "双马尾女性站在画面中央。",
    [],
    [asset],
    [{ reference_asset_id: asset.id, role: "identity", weight: 1 }],
  );
  assert.equal(
    normalized.imagePrompt,
    "@托管角色/小喵酱\n双马尾女性站在画面中央。",
  );
  assert.deepEqual(normalized.imagePromptMentions, [
    { reference_asset_id: asset.id, label: "托管角色/小喵酱" },
  ]);
  assert.equal(
    ensurePromptMentionTokens(
      normalized.imagePrompt,
      normalized.imagePromptMentions,
      [asset],
    ),
    normalized.imagePrompt,
  );
  assert.equal(
    normalizePromptMentionDraft(
      normalized.imagePrompt,
      normalized.imagePromptMentions,
      [asset],
      [{ reference_asset_id: asset.id, role: "identity", weight: 1 }],
    ).changed,
    false,
  );
});

test("deleting an @ token removes its mention and matching binding together", () => {
  const asset = { id: "asset-1", folder_name: "人物", name: "面部" };
  const unrelatedBinding = {
    reference_asset_id: "asset-without-mention",
    role: "scene",
    weight: 1,
  };
  const reconciled = reconcilePromptReferenceRemoval(
    "中景镜头，人物站在栏杆前",
    [{ reference_asset_id: asset.id, label: "人物/面部" }],
    [
      { reference_asset_id: asset.id, role: "identity", weight: 1 },
      unrelatedBinding,
    ],
    [asset],
  );
  assert.deepEqual(reconciled.imagePromptMentions, []);
  assert.deepEqual(reconciled.referenceBindings, [unrelatedBinding]);
});

test("routes image prompt references and bindings through one visual-beat save", () => {
  assert.match(
    productionWorkflowSource,
    /visualBeatChanges\.reference_bindings = remainingShotChanges\.reference_bindings/,
  );
  assert.match(
    productionWorkflowSource,
    /\/visual-beats\/\$\{pending\.visualBeatId\}[\s\S]*confirm_stale: true[\s\S]*\.\.\.visualBeatChanges/,
  );
  assert.match(shotImageSource, /<ImageAssetPromptEditor/);
});

test("auto-saves image prompt edits without a manual save action", () => {
  assert.match(shotImageSource, /<PromptSectionHeader[^>]*state=\{saveState\}/);
  assert.match(shotImageSource, /<ImageAssetPromptEditor[\s\S]*onBlur=\{onFlushDraft\}/);
  assert.doesNotMatch(shotImageSource, /保存草稿不会自动生成|type="submit">[\s\S]{0,120}保存/);
  assert.match(productionWorkflowSource, /const SHOT_IMAGE_AUTOSAVE_DELAY_MS = 700/);
  assert.match(productionWorkflowSource, /function useShotImageDraftAutosave/);
  assert.match(productionWorkflowSource, /setTargetSaveState\(target\.key, "dirty"\)/);
  assert.match(productionWorkflowSource, /const persistedShotDetail = await flushShotDraft\(\)/);
  assert.match(productionWorkflowSource, /onRetryDraftSave=\{retryShotDraftSave\}/);
});

test("hides the ready badge without hiding generation and failure states", () => {
  assert.match(shotImageSource, /!sourceVideoMode && plan.image_status !== "ready" &&/);
  assert.match(shotImageSource, /workflowStatusLabel\(plan.image_status\)/);
});

test("single visual beat is compact in the shared image workspace, independent of project origin", () => {
  const heading = shotImageSource.slice(shotImageSource.indexOf('<div className="shot-canvas-heading">'), shotImageSource.indexOf('<article className="shot-source-video-passthrough">'));
  assert.match(heading, /!sourceVideoMode && visualBeats.length === 1 \? \(\s*<strong>分镜 \{plan.index\}<\/strong>/);
  assert.match(heading, /!sourceVideoMode && visualBeats.length === 1 && \([\s\S]*onClick=\{onCreateVisualBeat\}/);
  assert.doesNotMatch(heading, /isSkillMode|generationRuns|candidate_count/);
  assert.match(shotImageSource, /activeVisualBeat && visualBeats.length > 1 && \(\s*<section className="visual-beat-editor"/);
  assert.match(productionWorkflowSource, /beats\[index \+ 1\] \|\| beats\[index - 1\] \|\| null/);
  assert.match(productionWorkflowSource, /refreshProject\(detail.project.id, shotDetail.plan.id, nextSelected\?\.id\)/);
});

test("passes the selected visual beat into the image workspace", () => {
  assert.match(
    productionWorkflowSource,
    /<ShotImageWorkspace[\s\S]*selectedVisualBeatId=\{selectedVisualBeatId\}/,
  );
  assert.match(
    shotImageSource,
    /visualBeats\.find\(\(item\) => item\.id === selectedVisualBeatId\)/,
  );
});

test("keeps legacy history visible but hides user-deleted image candidates", () => {
  assert.equal(isVisibleImageCandidate({ status: "archived" }), true);
  assert.equal(isVisibleImageCandidate({
    status: "archived",
    archive_reason: "user_deleted",
  }), false);
  assert.equal(isVisibleImageCandidate({ status: "rejected" }), false);
});

test("image workspace exposes zoom and reversible deletion without lock controls", () => {
  assert.match(shotImageSource, /MediaLightbox/);
  assert.match(shotImageSource, /onArchiveCandidate/);
  assert.match(shotImageSource, /<ImageAssetPromptEditor/);
  assert.doesNotMatch(shotImageSource, /锁定原视频要素|SHOT_LOCK_OPTIONS/);
  assert.match(productionWorkflowSource, /actionLabel:\s*"撤销"/);
  assert.match(productionWorkflowSource, /archiveImageCandidate/);
  assert.match(productionWorkflowSource, /restoreImageCandidate/);
});

test("image workspace omits the redundant engine banner and ready labels in the shot list", () => {
  assert.doesNotMatch(shotImageSource, /shot-generation-context|shot-generation-mode/);
  assert.doesNotMatch(productionWorkflowStyles, /\.shot-generation-context|\.shot-generation-mode/);
  assert.doesNotMatch(shotImageSource, /className=\{"shot-status-badge/);
  assert.match(shotImageSource, /const approvedImageLabel = shot\.image_status === "approved"/);
  assert.match(
    shotImageSource,
    /const latestRunBusy = \["queued", "running", "cancellation_requested"\]\.includes\(/,
  );
});

test("removes secondary candidate metadata and the visible generation manifest", () => {
  assert.doesNotMatch(
    shotImageSource,
    /选择此图|最近批次|历史批次|基础质检通过|请人工核对|本次参考|生成时按编号顺序提交|待采用/,
  );
  assert.doesNotMatch(shotImageSource, /shot-input-manifest|shot-candidate-quality/);
  assert.doesNotMatch(shotImageSource, /TextModelIndicator/);
  assert.match(shotImageSource, /<span>\{displayedCandidateModelLabel\}<\/span>/);
  assert.match(shotImageSource, /inputCount=\{generationInputManifest\.length\}/);
  assert.doesNotMatch(shotImageSource, /输入 @ 选择资产；系统会保存资产 ID|shot-prompt-help/);
  assert.doesNotMatch(productionWorkflowStyles, /\.shot-prompt-help/);
});

test("recovers already generated Codex images without submitting another generation", () => {
  assert.match(shotImageSource, /图片待恢复/);
  assert.match(shotImageSource, /onRecoverRun\?\.\(latestRun\.id\)/);
  assert.match(productionWorkflowSource, /\/generation-runs\/\$\{runId\}\/recover-output/);
  assert.match(productionWorkflowSource, /本次未重新调用 ImageGen/);
});

test("removes image negative constraints from the image workspace", () => {
  assert.doesNotMatch(shotImageSource, /shot-image-negative-constraints/);
  assert.doesNotMatch(shotImageSource, /<summary>负面约束（可选）<\/summary>/);
  assert.doesNotMatch(shotImageSource, /aria-label="图片负面约束"/);
});

test("uses one persistent per-shot retain checkbox for the two output routes", () => {
  assert.match(shotImageSource, /className=\{`shot-navigation-keep \$\{pendingOutputMode \? "pending" : ""\}`\}/);
  assert.match(shotImageSource, /<span>保留<\/span>/);
  assert.match(shotImageSource, /event\.target\.checked \? "source_video" : "image_to_video"/);
  assert.match(shotImageSource, /const \[pendingOutputModes, setPendingOutputModes\] = useState\(\{\}\)/);
  assert.match(shotImageSource, /await onSetOutputMode\?\.\(\{/);
  assert.match(shotImageSource, /loadedShotPlan\.id === selectedShotId/);
  assert.match(shotImageSource, /selectedShotSummary\?\.output_mode/);
  assert.match(shotImageSource, /data-output-mode=\{outputMode\}/);
  assert.match(shotImageSource, /sourceVideoMode \? \(/);
  assert.match(shotImageSource, /\{detailReady && plan && !sourceVideoMode && \(\s*<aside className="shot-inspector-panel">/);
  assert.match(productionWorkflowSource, /\/shot-output-mode/);
  assert.match(productionWorkflowSource, /onSetOutputMode=\{setShotOutputMode\}/);
  assert.match(productionWorkflowSource, /setShots\(\(current\) => current\.map/);
  assert.match(productionWorkflowSource, /setShotDetail\(\(current\) => \(/);
  assert.doesNotMatch(shotImageSource, /批量设置未处理分镜|shot-output-mode-selector/);
  assert.match(
    productionWorkflowStyles,
    /\.shot-image-workspace\[data-output-mode="source_video"\] \.shot-workspace-grid\s*\{[\s\S]*?grid-template-columns:\s*clamp\(300px, 23%, 380px\) minmax\(0, 1fr\)/,
  );
  assert.doesNotMatch(productionWorkflowStyles, /output-mode-source-video/);
  assert.doesNotMatch(shotImageSource, /分析默认帧|原视频已就绪/);
  assert.doesNotMatch(shotImageSource, /"尚未生成"/);
  assert.doesNotMatch(shotImageSource, /visual-beat-copy/);
});

test("image generation uses a compact command bar with upward popovers", () => {
  assert.match(shotImageSource, /ImageGenerationCommandBar/);
  assert.doesNotMatch(shotImageSource, /className="shot-generation-controls"/);
  assert.match(imageCommandBarSource, /ImageModelPopover/);
  assert.match(imageCommandBarSource, /ImageGenerationSettingsPopover/);
  assert.match(imageCommandBarSource, /function submit\(\) \{\s*onGenerate\(\);/);
  assert.match(imageCommandBarSource, /aria-label=\{`生成 \$\{candidateCount\} 张图片`\}/);
  assert.match(imageCommandBarSource, /:\s*"生成"\}/);
  assert.match(imageCommandBarSource, /estimatedCostLabel\s*&&/);
  assert.doesNotMatch(imageCommandBarSource, /selectedModel\?\.providerLabel\s*\|\|\s*compatibility\.reason/);
  assert.match(imageControlStyles, /\.shot-image-command-bar\s*\{/);
  assert.match(imageControlStyles, /\.shot-image-command-bar\s*\{[\s\S]*?display:\s*flex;[\s\S]*?flex-wrap:\s*nowrap;/);
  assert.doesNotMatch(imageControlStyles, /grid-template-areas:\s*"model summary cost actions"/);
  assert.doesNotMatch(imageControlStyles, /@container \(max-width: 560px\)/);
  assert.match(imageControlStyles, /@container \(max-width: 440px\)/);
  assert.match(imageControlStyles, /button\.active:disabled\s*\{[\s\S]*?opacity:\s*1;/);
  assert.match(imageControlStyles, /\.image-settings-scroll-region\s*\{[\s\S]*overflow-y:\s*auto/);
});

test("image model choices support per-run routing and compatibility checks", () => {
  const models = imageModelOptions({
    api_key_configured: true,
    local_executable_path: "imagegen.exe",
    models: [{
      alias: "remote-model",
      label: "Remote model",
      capabilities: {
        text_to_image: true,
        image_to_image: true,
        multi_reference: true,
        max_input_images: 2,
      },
    }],
  });
  assert.deepEqual(models.map((model) => model.alias), ["remote-model", LOCAL_IMAGE_MODEL_ALIAS]);
  assert.equal(imageModelCompatibility(models[0], { inputCount: 2 }).compatible, true);
  assert.equal(imageModelCompatibility(models[0], { inputCount: 3 }).compatible, false);
  assert.match(
    imageGenerationSummary({ aspectRatio: "9:16", candidateCount: 2, inputMode: "text_to_image" }),
    /9:16.*2/,
  );
  assert.match(
    imageGenerationSummary({ aspectRatio: "16:9", candidateCount: 1, inputMode: "keyframe_edit" }),
    /^底图编辑/,
  );
});

test("reference creation needs no original frame and never silently drops assets", () => {
  assert.equal(resolveImageInputMode({ inputMode: "keyframe_edit", referenceCount: 1 }), "reference_to_image");
  assert.equal(resolveImageInputMode({ inputMode: "text_to_image", referenceCount: 3 }), "reference_to_image");
  assert.equal(resolveImageInputMode({ inputMode: "reference_to_image", referenceCount: 0 }), "text_to_image");
  assert.equal(resolveImageInputMode({ inputMode: "text_to_image", sourceUrl: "/original", referenceCount: 1 }), "reference_to_image");
  assert.equal(resolveImageInputMode({ inputMode: "keyframe_edit", sourceUrl: "/original", referenceCount: 1 }), "keyframe_edit");
  assert.equal(resolveImageInputMode({ inputMode: "keyframe_edit", baseImageId: "missing-image", referenceCount: 1 }), "keyframe_edit");
  assert.equal(imageBaseCandidateId("reference_to_image", "previous-image"), null);
  assert.equal(imageBaseCandidateId("keyframe_edit", "previous-image"), "previous-image");
  assert.equal(imageBaseCandidateId("keyframe_edit", "source"), null);
  assert.doesNotMatch(shotImageSource, /人物身份替换需要先选择原视频关键帧|identityLocked|setGenerationInputMode\("keyframe_edit"\)/);
  assert.match(productionWorkflowSource, /base_image_candidate_id: baseCandidateId/);
  assert.match(imageGenerationSummary({ inputMode: "reference_to_image", candidateCount: 1 }), /^参考图创作/);
});

test("reference scope matches the active visual beat for both creation workflows", () => {
  const draft = { referenceBindings: [{ reference_asset_id: "person" }, { reference_asset_id: "scene" }], imagePromptMentions: [{ reference_asset_id: "scene" }] };
  assert.deepEqual(imageBindingsForDraft({ source_kind: "blank", visual_beats: [{}] }, {}, draft), draft.referenceBindings);
  assert.deepEqual(imageBindingsForDraft({ source_kind: "blank", visual_beats: [{}, {}] }, {}, draft), [draft.referenceBindings[1]]);
  assert.deepEqual(imageBindingsForDraft({ source_kind: "skill_generated", visual_beats: [{}] }, {}, draft), [draft.referenceBindings[1]]);
});

test("reference and base image capabilities are checked independently without model fallback", () => {
  const model = { configured: true, capabilities: { text_to_image: false, image_to_image: true, multi_reference: false, max_input_images: 3, max_reference_images: 2 } };
  assert.equal(imageModelCompatibility(model, { inputMode: "reference_to_image", inputCount: 1 }).compatible, true);
  assert.equal(imageModelCompatibility(model, { inputMode: "text_to_image", inputCount: 0 }).compatible, false);
  assert.match(imageModelCompatibility(model, { inputMode: "reference_to_image", inputCount: 2 }).reason, /多图/);
  model.capabilities.multi_reference = true;
  assert.equal(imageModelCompatibility(model, { inputMode: "keyframe_edit", inputCount: 3 }).compatible, true);
  assert.match(imageModelCompatibility(model, { inputMode: "reference_to_image", inputCount: 3 }).reason, /2 张参考/);
});

test("reference manifests number every input and distinguish an explicitly chosen base", () => {
  const bindings = [{ reference_asset_id: "person", role: "identity" }, { reference_asset_id: "scene", role: "scene" }];
  const reference = imageGenerationInputManifest({ inputMode: "reference_to_image", sourceUrl: "/unused-original", referenceBindings: bindings });
  assert.deepEqual(reference.map(item => item.input_index), [1, 2]);
  assert.ok(reference.every(item => item.kind === "reference_asset"));
  const edit = imageGenerationInputManifest({ inputMode: "keyframe_edit", sourceUrl: "/selected-base", baseImageCandidateId: "chosen", referenceBindings: bindings });
  assert.deepEqual(edit.map(item => item.input_index), [1, 2, 3]);
  assert.equal(edit[0].kind, "generated_image");
  assert.equal(edit[0].candidate_id, "chosen");
  assert.equal(edit[0].thumbnail_url, "/selected-base");
});

test("the real submit handler sends the visible mode and base, and protects against an outdated backend", async () => {
  const ast = parse(productionWorkflowSource, { sourceType: "module", plugins: ["jsx"] });
  const component = ast.program.body.find(node => node.declaration?.id?.name === "ProductionHub").declaration;
  const handler = component.body.body.find(node => node.id?.name === "generateShotCandidates");
  assert.ok(handler);
  const createHandler = new Function("scope", `with (scope) { return (${productionWorkflowSource.slice(handler.start, handler.end)}); }`);
  async function submit({ bindings = [], source = "", inputMode = "keyframe_edit", base = "", supportsBase = true, saveError = false } = {}) {
    const requests = [];
    const beat = { id: "beat", index: 1, source_frame_url: source };
    const shot = { plan: { id: "shot", index: 1, source_kind: "blank", visual_beats: [beat] }, current_revision_id: "saved-revision" };
    const scope = {
      shotDetail: shot, selectedVisualBeatId: beat.id,
      shotDraft: { referenceBindings: bindings }, workflow: null,
      generationResolution: "", generationCandidateCount: 1,
      generationEngine: "remote_api", generationModelAlias: "chosen-model",
      generationSettings: { enabled: true, supports_candidate_base_image: supportsBase },
      generationInputMode: inputMode, generationBaseImageId: base,
      detail: { project: { current_revision_id: "old-revision" } },
      shotDraftPatch: () => ({ activeBeat: beat, beatChanges: {}, shotChanges: {} }),
      resolveImageExecutionMode: () => "remote_api", executeAction: callback => callback(),
      flushGlobalPrompts: async () => {},
      flushShotDraft: async () => { if (saveError) throw new Error("保存失败"); return shot; },
      visualBeatFromDetail: item => item.plan.visual_beats[0],
      imageBindingsForDraft, resolveImageInputMode, imageBaseCandidateId,
      imageGenerationIntentForShot: () => "standard",
      request: async (url, options) => { requests.push({ url, ...JSON.parse(options.body) }); return { id: "run" }; },
      setShotDetail: () => {}, onProjectsChanged: async () => {}, onNotice: () => {},
      setActionError: message => { throw new Error(message); },
    };
    try { await createHandler(scope)(); } catch (error) { return { requests, error }; }
    return { requests };
  }
  const cases = [
    [{ bindings: [{ reference_asset_id: "person", role: "identity" }] }, "reference_to_image", null],
    [{ bindings: [{ reference_asset_id: "product", role: "product" }], inputMode: "text_to_image" }, "reference_to_image", null],
    [{}, "text_to_image", null],
    [{ base: "chosen-candidate" }, "keyframe_edit", "chosen-candidate"],
    [{ source: "/source", base: "source" }, "keyframe_edit", null],
    [{ source: "/source", inputMode: "text_to_image" }, "text_to_image", null],
  ];
  for (const [input, mode, base] of cases) {
    const result = await submit(input);
    assert.equal(result.error, undefined);
    assert.equal(result.requests.length, 1);
    assert.equal(result.requests[0].input_mode, mode);
    assert.equal(result.requests[0].base_image_candidate_id, base);
    assert.equal(result.requests[0].model_alias, "chosen-model");
    assert.equal(result.requests[0].expected_revision_id, "saved-revision");
  }
  for (const [input, message] of [
    [{ base: "chosen-candidate", supportsBase: false }, /重启后端/],
    [{ base: "select" }, /选择编辑底图/],
    [{ saveError: true }, /保存失败/],
  ]) {
    const result = await submit(input);
    assert.match(result.error.message, message);
    assert.equal(result.requests.length, 0);
  }
});
