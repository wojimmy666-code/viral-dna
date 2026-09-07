import assert from "node:assert/strict";
import test from "node:test";
import { createGlobalPromptSession, combinePrompt } from "../src/prompt-context/global-prompt-session.js";
import { createStoryboardDraftSession, newStoryboardShot, storyboardDraftIssues, storyboardDraftShots } from "../src/skill-workflow/storyboard-draft.js";

const initial = () => ({ id: "revision-1", revision_number: 1, shots: [{ stable_shot_key: "shot_12345678", image_prompt_body: "产品静态近景", video_prompt_body: "镜头缓慢推进", image_prompt: "隐藏的公共规范\n产品静态近景" }] });
const response = (payload, revision = 2) => ({ ...initial(), id: `revision-${revision}`, revision_number: revision, shots: payload.shots });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test("global edits serialize independently, include the base revision, and retain edits during save", async () => {
  const first = deferred(); const calls = [];
  const session = createGlobalPromptSession({ id: "g1", common_image_prompt: "暖色", common_video_prompt: "缓慢推进" }, {
    save: async p => { calls.push(p); return calls.length === 1 ? first.promise : { ...p, id: "g3" }; },
  });
  session.edit("image", "冷色");
  const saving = session.flush();
  await new Promise(resolve => setImmediate(resolve));
  session.edit("video", "固定机位");
  first.resolve({ ...calls[0], id: "g2" });
  assert.equal(await saving, true);
  assert.equal(calls[1].expected_revision_id, "g2");
  assert.deepEqual(session.snapshot().values, { common_image_prompt: "冷色", common_video_prompt: "固定机位" });
  assert.equal(combinePrompt("冷色", "局部画面"), "冷色\n\n局部画面");
});

test("failed global save preserves the local draft; intentionally empty globals are valid", async () => {
  let fail = true;
  const session = createGlobalPromptSession({ id: "g1", common_image_prompt: "暖色", common_video_prompt: "" }, {
    save: async p => { if (fail) throw new Error("版本冲突"); return { ...p, id: "g2" }; },
  });
  session.edit("image", "");
  assert.equal(await session.flush(), false);
  assert.equal(session.snapshot().dirty, true);
  assert.equal(session.snapshot().values.common_image_prompt, "");
  fail = false;
  assert.equal(await session.flush(), true);
  assert.equal(combinePrompt("", "局部正文"), "局部正文");
});

test("outline hydration notices production-only edits and submits the corresponding conflict token", async () => {
  let submitted;
  const session = createStoryboardDraftSession({ ...initial(), production_prompt_token: "p1" }, {
    save: async payload => { submitted = payload; return response(payload); },
  });
  const next = { ...initial(), production_prompt_token: "p2", production_revision_id: "r2" };
  next.shots[0].video_prompt_body = "后续阶段修改";
  session.hydrate(next);
  assert.equal(session.snapshot().shots[0].video_prompt_body, "后续阶段修改");
  session.edit(shots => shots.map(shot => ({ ...shot, image_prompt_body: "新局部" })));
  await session.flush();
  assert.equal(submitted.expected_production_prompt_token, "p2");
});

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
