import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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
  assert.match(shotImageSource, /reconcilePromptReferenceRemoval\(/);
});

test("auto-saves image prompt edits without a manual save action", () => {
  assert.match(shotImageSource, /<AutosaveStatus/);
  assert.match(shotImageSource, /onBlur=\{\(\) => Promise\.resolve\(onFlushDraft\?\.\(\)\)/);
  assert.doesNotMatch(shotImageSource, /保存草稿不会自动生成|type="submit">[\s\S]{0,120}保存/);
  assert.match(productionWorkflowSource, /const SHOT_IMAGE_AUTOSAVE_DELAY_MS = 700/);
  assert.match(productionWorkflowSource, /function useShotImageDraftAutosave/);
  assert.match(productionWorkflowSource, /setTargetSaveState\(target\.key, "dirty"\)/);
  assert.match(productionWorkflowSource, /const persistedShotDetail = await flushShotDraft\(\)/);
  assert.match(productionWorkflowSource, /onRetryDraftSave=\{retryShotDraftSave\}/);
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
  assert.match(shotImageSource, /assetMentionToken\(asset\)/);
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
    /^图生图/,
  );
});
