import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { artifactKey, folderPreferenceKey, promotionPayload } from "../src/generated-assets/asset-promotion-ui.js";

test("promotion targets and directory preferences are independently scoped", () => {
  assert.notEqual(artifactKey("image_candidate", "a"), artifactKey("image_candidate", "b"));
  assert.notEqual(artifactKey("image_candidate", "a"), artifactKey("video_candidate", "a"));
  const context = { account: { id: "a" }, active_workspace: { id: "w" } };
  const key = folderPreferenceKey(context, { projectId: "p", shotPlanId: "one" });
  assert.equal(key, folderPreferenceKey(context, { projectId: "p", shotPlanId: "two" }));
  assert.notEqual(key, folderPreferenceKey(context, { projectId: "other" }));
  assert.notEqual(key, folderPreferenceKey({ ...context, account: { id: "b" } }, { projectId: "p" }));
  assert.notEqual(key, folderPreferenceKey({ ...context, active_workspace: { id: "z" } }, { projectId: "p" }));
});

test("promotion payload uses the frozen candidate and all editable metadata", () => {
  const target = { artifactKind: "image_candidate", sourceEntityId: "a", shotPlanId: "shot" };
  const draft = { name: " 空气滤芯细节 ", folderId: "folder", assetType: "product", description: "侧逆光", tags: "滤芯，产品,滤芯" };
  assert.deepEqual(promotionPayload(target, draft), {
    kind: "image_candidate", source_entity_id: "a", shot_plan_id: "shot",
    name: "空气滤芯细节", folder_id: "folder", asset_type: "product", description: "侧逆光", tags: ["滤芯", "产品"],
  });
  assert.equal(promotionPayload(target, { ...draft, folderId: "" }).folder_id, null);
  assert.throws(() => promotionPayload(target, { ...draft, name: "  " }), /名称/);
  assert.throws(() => promotionPayload(target, { ...draft, name: "x".repeat(121) }), /名称/);
  assert.throws(() => promotionPayload(target, { ...draft, assetType: "invalid" }), /类型/);
  assert.throws(() => promotionPayload(target, { ...draft, tags: Array.from({ length: 21 }, (_, i) => `tag${i}`).join(",") }), /20/);
});

test("image previews omit selected badges without removing adopted state or selection styling", () => {
  const source = readFileSync(new URL("../src/ShotImageWorkspace.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /<span>\{(?:approvedIsSource|displayedCandidateIsApproved) \? "已采用" : "已选择"\}<\/span>/);
  assert.match(source, /displayedCandidateIsApproved && <span>已采用<\/span>/);
  assert.match(source, /visualChoice === "candidate" \? "selected"/);
  assert.match(source, /点击缩略图切换预览/);
});
