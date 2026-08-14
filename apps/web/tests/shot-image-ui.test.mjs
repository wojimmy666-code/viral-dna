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

const shotImageSource = readFileSync(
  new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
  "utf8",
);
const productionWorkflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
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
