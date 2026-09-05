import assert from "node:assert/strict";
import test from "node:test";
import { createStoryboardDraftSession, newStoryboardShot, storyboardDraftIssues, storyboardDraftShots } from "../src/skill-workflow/storyboard-draft.js";

const initial = () => ({ id: "revision-1", revision_number: 1, shots: [{ stable_shot_key: "shot_12345678", image_prompt_body: "产品静态近景", video_prompt_body: "镜头缓慢推进", image_prompt: "隐藏的公共规范\n产品静态近景" }] });
const response = (payload, revision = 2) => ({ ...initial(), id: `revision-${revision}`, revision_number: revision, shots: payload.shots });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test("shows bodies rather than full compiled prompts, including intentionally empty bodies", () => {
  assert.equal(storyboardDraftShots(initial())[0].image_prompt_body, "产品静态近景");
  const draft = initial();
  draft.shots[0].image_prompt_body = "";
  assert.equal(storyboardDraftShots(draft)[0].image_prompt_body, "");
});

test("image and video edits are independent and no-op flush creates no revision", async () => {
  const calls = [];
  const session = createStoryboardDraftSession(initial(), { save: async (payload) => { calls.push(payload); return response(payload); } });
  assert.equal(await session.flush(), true);
  assert.equal(calls.length, 0);
  session.edit((shots) => shots.map((shot) => ({ ...shot, image_prompt_body: "更换产品，保持侧光" })));
  assert.equal(await session.flush(), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].shots[0].video_prompt_body, "镜头缓慢推进");
  assert.equal(session.snapshot().status, "saved");
});

test("a flush waits for edits made while a save is running and uses the returned revision", async () => {
  const first = deferred();
  const second = deferred();
  const calls = [];
  const session = createStoryboardDraftSession(initial(), { save: (payload) => { calls.push(payload); return calls.length === 1 ? first.promise : second.promise; } });
  session.edit((shots) => shots.map((shot) => ({ ...shot, image_prompt_body: "第一笔修改" })));
  const saving = session.flush();
  await new Promise((resolve) => setImmediate(resolve));
  session.edit((shots) => shots.map((shot) => ({ ...shot, video_prompt_body: "保存期间的第二笔修改" })));
  assert.equal(session.flush(), saving);
  first.resolve(response(calls[0]));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls[1].expected_revision_id, "revision-2");
  assert.equal(calls[1].shots[0].video_prompt_body, "保存期间的第二笔修改");
  assert.equal(session.snapshot().status, "saving");
  second.resolve(response(calls[1], 3));
  assert.equal(await saving, true);
  assert.equal(session.snapshot().manifest.id, "revision-3");
  assert.equal(session.snapshot().dirty, false);
});

test("a failed save preserves edits, blocks navigation and retries against its original base", async () => {
  const calls = [];
  const session = createStoryboardDraftSession(initial(), { save: async (payload) => { calls.push(payload); if (calls.length === 1) throw new Error("连接中断"); return response(payload); } });
  session.edit((shots) => shots.map((shot) => ({ ...shot, video_prompt_body: "手写 ARRI Alexa 35 @asset/id" })));
  assert.equal(await session.flush(), false);
  assert.equal(calls.length, 1);
  assert.equal(session.snapshot().shots[0].video_prompt_body, "手写 ARRI Alexa 35 @asset/id");
  assert.equal(session.snapshot().status, "error");
  assert.equal(await session.flush(), true);
  assert.equal(calls[1].expected_revision_id, "revision-1");
});

test("background responses cannot overwrite a dirty draft or a newer saved revision", async () => {
  const session = createStoryboardDraftSession(initial(), { save: async (payload) => response(payload, 3) });
  session.edit((shots) => [...shots, newStoryboardShot()]);
  session.hydrate(response({ shots: [] }, 2));
  assert.equal(session.snapshot().shots.length, 2);
  await session.flush();
  session.hydrate(response({ shots: [] }, 2));
  assert.equal(session.snapshot().shots.length, 2);
});

test("empty and all-deleted drafts persist; completeness is checked separately at confirmation", async () => {
  const calls = [];
  const session = createStoryboardDraftSession(initial(), { save: async (payload) => { calls.push(payload); return response(payload, calls.length + 1); } });
  const added = newStoryboardShot();
  assert.match(added.stable_shot_key, /^shot_[a-z0-9]{32}$/);
  session.edit((shots) => [...shots, added]);
  assert.equal(await session.flush(), true);
  assert.equal(storyboardDraftIssues(session.snapshot().shots).length, 2);
  session.edit([]);
  assert.equal(await session.flush(), true);
  assert.deepEqual(storyboardDraftIssues(session.snapshot().shots), ["请至少添加一个分镜"]);
  session.edit([added]);
  await session.flush();
  assert.equal(session.snapshot().shots[0].stable_shot_key, added.stable_shot_key);
});

test("synchronous transport failures release the save queue for an explicit retry", async () => {
  let calls = 0;
  const session = createStoryboardDraftSession(initial(), { save: (draft) => {
    calls += 1;
    if (calls === 1) throw new Error("请求未发出");
    return response(draft);
  } });
  session.edit((shots) => [...shots, newStoryboardShot()]);
  assert.equal(await session.flush(), false);
  assert.equal(await session.flush(), true);
  assert.equal(calls, 2);
});
