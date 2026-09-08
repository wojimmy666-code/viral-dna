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

const previousBatchFailure = {shot_plan_id:"s",visual_beat_id:"b",status:"failed",run_id:null,
  batch_created_at:"2026-09-06T12:00:00Z",batch_completed_at:"2026-09-06T13:00:00Z"};
const recoveredPreview = {candidate_id:"new-image",thumbnail_url:"/new-image",updated_at:"2026-09-07T06:18:00Z"};
const imageRun = (status, extra = {}) => ({id:"retry",kind:"image",execution_mode:"local_tool",visual_beat_id:"b",created_at:"2026-09-07T06:01:00Z",status,...extra});

test("a running batch refreshes each newly published image without claiming completion", () => {
  const before = {items:[{shot_plan_id:"s",visual_beat_id:"b",run_id:"r",status:"running",candidate_ids:[]}]};
  const first = {items:[{...before.items[0],candidate_ids:["one"]}]};
  const second = {items:[{...before.items[0],candidate_ids:["one","two"]}]};
  assert.deepEqual(changedBatchShots(before,first),["s"]);
  assert.deepEqual(changedBatchShots(first,first),[]);
  assert.deepEqual(changedBatchShots(first,second),["s"]);
  assert.equal(imageBatchCounts(first).completed,0);
});

test("a later successful image supersedes an old batch failure even when the editable plan is ready", () => {
  const plan={id:"s",image_status:"ready"};
  assert.equal(shotImageStatus(plan,[previousBatchFailure],{imagePreview:recoveredPreview,visualBeatCount:1}),"待采用");
  assert.equal(previousBatchFailure.status,"failed","history is not rewritten");
});

test("single-shot retry moves through queued, running and review without reviving a prior batch failure", () => {
  const context={imagePreview:recoveredPreview,visualBeatCount:1};
  for(const [status,label] of [["queued","排队中"],["running","生成中"],["cancellation_requested","生成中"],["completed","待采用"]]) {
    assert.equal(shotImageStatus({id:"s",image_status:"ready"},[previousBatchFailure],{...context,generationRuns:[imageRun(status)]}),label);
  }
});

test("new failures and active batch attempts remain visible even when an older image is available", () => {
  const plan={id:"s",image_status:"ready"};
  const laterBatch={...previousBatchFailure,batch_created_at:"2026-09-07T07:00:00Z",batch_completed_at:"2026-09-07T07:10:00Z"};
  assert.equal(shotImageStatus(plan,[laterBatch],{imagePreview:recoveredPreview}),"失败");
  assert.equal(shotImageStatus(plan,[previousBatchFailure],{imagePreview:recoveredPreview,generationRuns:[imageRun("failed",{created_at:"2026-09-07T07:00:00Z"})]}),"失败");
  assert.equal(shotImageStatus(plan,[{...laterBatch,status:"running"}],{imagePreview:recoveredPreview}),"生成中");
});

test("only the latest real image run per beat contributes a state", () => {
  const older=imageRun("failed",{id:"old",created_at:"2026-09-06T12:00:00Z"});
  const completed=imageRun("completed");
  const other=[imageRun("running",{kind:"video"}),imageRun("failed",{execution_mode:"source_frame"}),imageRun("failed",{provider:"simulated"})];
  for(const runs of [[older,completed,...other],[completed,older,...other]]) {
    assert.equal(shotImageStatus({id:"s",image_status:"ready"},[previousBatchFailure],{imagePreview:recoveredPreview,generationRuns:runs}),"待采用");
  }
});

test("a fresh completed batch beats an older cached failure while the shot detail refresh is pending", () => {
  const completed={...previousBatchFailure,status:"completed",run_id:"new-batch-run",batch_created_at:"2026-09-07T07:00:00Z",batch_completed_at:"2026-09-07T07:10:00Z"};
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[completed],{imagePreview:recoveredPreview,generationRuns:[imageRun("failed")]}),"待采用");
});

test("one available image never hides another visual beat's unresolved failure", () => {
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[previousBatchFailure],{imagePreview:recoveredPreview,visualBeatCount:2}),"失败");
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[previousBatchFailure],{imagePreview:recoveredPreview,visualBeatCount:2,generationRuns:[imageRun("completed",{visual_beat_id:"other-beat"})]}),"失败");
});

test("adoption, stale content, unresolved results and missing images retain truthful labels", () => {
  assert.equal(shotImageStatus({id:"s",image_status:"approved"},[previousBatchFailure],{imagePreview:recoveredPreview}),"已采用");
  assert.equal(shotImageStatus({id:"s",image_status:"stale"},[previousBatchFailure],{imagePreview:recoveredPreview}),"输入已更新");
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[previousBatchFailure]),"失败");
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[{...previousBatchFailure,status:"unknown"}]),"需核对");
  assert.equal(shotImageStatus({id:"s",image_status:"ready"},[],{generationRuns:[imageRun("completed")]}),"待生成");
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
