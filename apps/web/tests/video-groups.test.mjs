import assert from "node:assert/strict";
import test from "node:test";
import { groupDefinition, groupModelOptions, suggestedGroups, plannedCuts, cutsValid } from "../src/video-groups/group-planning.js";
import { productionPromptsToText } from "../src/prompt-editor/prompt-sources.js";

const model = { available: true, capabilities: { multi_image_reference: true, ordered_reference_images: true, minimum_duration_seconds: 4, maximum_duration_seconds: 10, maximum_reference_images: 5 } };
const shots = Array.from({ length: 5 }, (_, i) => ({ id: `s${i}`, index: i + 1, duration_seconds: 1, visual_beats: [{ approved_image_candidate_id: `i${i}` }] }));

test("short-shot suggestions use model capabilities, never join across an existing group", () => {
  assert.deepEqual(suggestedGroups(shots, model), [["s0", "s1", "s2", "s3"]]);
  assert.deepEqual(suggestedGroups(shots, model, new Set(["s2"])), [["s0", "s1"], ["s3", "s4"]]);
  assert.deepEqual(groupModelOptions([model, { ...model, available: false }, { ...model, capabilities: { multi_image_reference: true } }]), [model]);
});
test("reviewed ranges reject empty inputs, overlaps, reversed or out-of-bounds cuts", () => {
  const cuts = plannedCuts(shots, 5);
  assert.equal(cutsValid(cuts, 5), true);
  assert.equal(plannedCuts(shots.slice(0,2),5)[1].trim_in_seconds, 2.5);
  for (const change of [{ trim_in_seconds: "" }, { trim_out_seconds: 0 }, { trim_out_seconds: 6 }]) {
    assert.equal(cutsValid([{ ...cuts[0], ...change }, ...cuts.slice(1)], 5), false);
  }
  assert.equal(cutsValid([cuts[0], { ...cuts[1], trim_in_seconds: .9 }], 5), false);
  assert.deepEqual(groupDefinition({ id: "g", shot_plan_ids: ["a", "b"], input_fingerprint: "derived" }), { id: "g", shot_plan_ids: ["a", "b"], video_prompt: "", transition: "cut" });
});
test("TXT exports a single group prompt, not multiple standalone video tasks", () => {
  const text = productionPromptsToText({ name: "世界地标", shots: shots.slice(0, 2).map(shot => ({ ...shot, images: [{ prompt: "场景图片", negative_constraints: [] }], video_group_id: "g", video_prompt: "不要重复独立任务", video_negative_constraints: [] })), video_groups: [{ shot_plan_ids: ["s0", "s1"], compiled_prompt: "巴黎硬切到京都" }] });
  assert.match(text, /2 个分镜 → 1 段视频/);
  assert.match(text, /巴黎硬切到京都/);
  assert.doesNotMatch(text, /不要重复独立任务/);
});
