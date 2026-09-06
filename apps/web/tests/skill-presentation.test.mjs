import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { claimSkillPreview, releaseSkillPreview, resolveSkillMediaUrl, skillCoverSources, presentationPayload } from "../src/skill-workflow/skill-presentation-ui.js";
import { uploadFormWithProgress } from "../src/api-upload.js";

test("cover priority: chosen image, extracted video poster, legacy fallback", () => {
  assert.deepEqual(skillCoverSources({ presentation: {cover_url:"image",poster_url:"frame"}, cover_url:"old" }), ["image","frame","old"]);
  assert.deepEqual(skillCoverSources({ presentation: {cover_url:"frame",poster_url:"frame"}, cover_url:"frame" }), ["frame"]);
  assert.deepEqual(skillCoverSources({ cover_url:"old" }), ["old"]);
  assert.deepEqual(skillCoverSources({ presentation: {cover_url:"broken"}, cover_url:"broken", fallback_cover_url:"legacy" }), ["broken","legacy"]);
  assert.deepEqual(skillCoverSources({}), []);
});

test("platform media use API origin without moving bundled static covers", () => {
  assert.equal(resolveSkillMediaUrl("/api/v1/skill-media/id/content", "http://localhost:8000/api/v1"), "http://localhost:8000/api/v1/skill-media/id/content");
  assert.equal(resolveSkillMediaUrl("/skill-covers/old.svg", "http://localhost:8000/api/v1"), "/skill-covers/old.svg");
});

test("only one preview owns playback; stale cleanup cannot stop the next cover", () => {
  const stopped = [];
  claimSkillPreview("a", () => stopped.push("a"));
  claimSkillPreview("b", () => stopped.push("b"));
  releaseSkillPreview("a");
  claimSkillPreview("c", () => stopped.push("c"));
  assert.deepEqual(stopped, ["a", "b"]);
  releaseSkillPreview("c");
  claimSkillPreview("d", () => stopped.push("d"));
  assert.deepEqual(stopped, ["a", "b"]);
  releaseSkillPreview("d");
});

test("presentation submission reserves list contract and sends IDs, never manifests or private URLs", () => {
  const value = presentationPayload(4, "item", {id:"image",content_url:"secret"}, {id:"video",poster_asset_id:"derived"});
  assert.deepEqual(value, {expected_revision:4,primary_item_id:"item",items:[{id:"item",image_asset_id:"image",video_asset_id:"video",sort_order:0}]});
  assert.deepEqual(presentationPayload(4,"item",null,null), {expected_revision:4,primary_item_id:null,items:[]});
});

test("real upload progress and server errors are forwarded", async t => {
  let xhr;
  class FakeXHR {
    constructor() { xhr = this; this.upload = {}; }
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; }
    abort() { this.onabort(); }
  }
  const originalXHR = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = FakeXHR;
  t.after(() => { if (originalXHR) globalThis.XMLHttpRequest = originalXHR; else delete globalThis.XMLHttpRequest; });
  const seen = [];
  const pending = uploadFormWithProgress("/upload", "body", p=>seen.push(p), undefined, () => "素材太大");
  xhr.upload.onprogress({lengthComputable:true, loaded:2, total:8});
  xhr.upload.onprogress({lengthComputable:false});
  assert.deepEqual(seen,[25,null]);
  xhr.status=202; xhr.response={id:"asset"}; xhr.onload();
  assert.deepEqual(await pending,{id:"asset"});
  const failed = uploadFormWithProgress("/upload", "body", null, undefined, () => "素材太大");
  xhr.status=413; xhr.response={}; xhr.onload();
  await assert.rejects(failed, {message:"素材太大",status:413});
  const controller = new AbortController();
  const cancelled = uploadFormWithProgress("/upload", "body", null, controller.signal, () => "");
  controller.abort();
  await assert.rejects(cancelled, {name:"AbortError"});
});

test("cover defers video mounting, preserves poster until playing, and releases media", () => {
  const source = readFileSync(new URL("../src/skill-workflow/SkillCover.jsx", import.meta.url), "utf8");
  assert.match(source, /active && videoUrl && <video/);
  assert.match(source, /loop muted playsInline/);
  assert.match(source, /setTimeout\(start, 200\)/);
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /IntersectionObserver/);
  assert.match(source, /visibilitychange/);
  assert.match(source, /video\.removeAttribute\("src"\)/);
});

test("admin save waits for ready media, uploads use progress, and drafts can be restored or discarded", () => {
  const source = readFileSync(new URL("../src/admin/SkillPresentationEditor.jsx", import.meta.url), "utf8");
  assert.match(source, /!unresolved\(draft.image\) && !unresolved\(draft.video\)/);
  assert.match(source, /request\.upload/);
  assert.match(source, /localStorage\.getItem/);
  assert.match(source, /localStorage\.removeItem/);
  assert.match(source, /reloadSaved/);
  assert.match(source, /重试处理/);
});
