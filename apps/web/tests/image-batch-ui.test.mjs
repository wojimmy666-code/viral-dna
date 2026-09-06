import assert from "node:assert/strict";
import test from "node:test";
import { activeImageBatch, imageBatchCounts, changedBatchShots, shotImageStatus } from "../src/image-generation-controls/image-batch-ui.js";
import { readOnce } from "../src/creation-workspace/read-request.js";

test("batch progress uses actual picture tasks and keeps human adoption separate", () => {
  const batch = { status: "running", items: ["completed", "running", "pending", "skipped", "failed"].map(status => ({status})) };
  assert.equal(activeImageBatch(batch), true);
  assert.deepEqual(imageBatchCounts(batch), { total: 5, completed: 1, running: 1, pending: 1, skipped: 1, failed: 1, cancelled: 0, done: 3 });
  assert.equal(shotImageStatus({id: "s", image_status: "ready"}, [{shot_plan_id: "s", status: "completed"}]), "待采用");
  assert.equal(shotImageStatus({id: "s", image_status: "approved"}), "已采用");
});
test("heartbeat changes do not trigger another candidate refresh", () => {
  const previous = { items: [{visual_beat_id: "b", shot_plan_id: "s", run_id: "r", status: "completed", candidate_ids: ["c"]}] };
  assert.deepEqual(changedBatchShots(previous, {...previous, last_heartbeat_at: "new"}), []);
  assert.deepEqual(changedBatchShots(null, previous), ["s"]);
});
test("concurrent GETs share only in-flight promises; subsequent reads stay fresh", async () => {
  let count = 0;
  const request = async () => ++count;
  assert.deepEqual(await Promise.all([readOnce(request, "/project"), readOnce(request, "/project")]), [1, 1]);
  assert.equal(await readOnce(request, "/project"), 2);
});
test("failed reads are not cached", async () => {
  let count = 0;
  const request = async () => { if (++count === 1) throw new Error("offline"); return count; };
  await assert.rejects(readOnce(request, "/project"));
  assert.equal(await readOnce(request, "/project"), 2);
});
