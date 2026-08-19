import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assetMentionLabel,
  assetMentionToken,
  isVisibleImageCandidate,
  normalizePromptMentionDraft,
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

test("progressively reveals optional image negative constraints", () => {
  assert.match(
    shotImageSource,
    /<details[\s\S]*className="production-field shot-image-negative-constraints"/,
  );
  assert.match(shotImageSource, /<summary>负面约束（可选）<\/summary>/);
  assert.match(shotImageSource, /aria-label="图片负面约束"/);
  assert.doesNotMatch(
    shotImageSource,
    /<details[\s\S]{0,240}className="production-field shot-image-negative-constraints"[^>]*\sopen(?:=|>)/,
  );
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
