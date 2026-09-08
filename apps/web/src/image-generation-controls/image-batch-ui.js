export const activeImageBatch = (batch) => ["running", "stopping"].includes(batch?.status);
export function imageBatchCounts(batch) {
  const items = batch?.items || [];
  const count = (status) => items.filter((item) => item.status === status).length;
  return { total: items.length, completed: count("completed"), skipped: count("skipped"),
    running: count("running"), pending: count("pending"), failed: count("failed") + count("unknown"),
    cancelled: count("cancelled"), done: items.filter((item) => !["pending", "running"].includes(item.status)).length };
}
const imageStateTime = value => Date.parse(value || "") || 0;

export function shotImageStatus(plan, items = [], { imagePreview, visualBeatCount, generationRuns = [] } = {}) {
  const latestByBeat = new Map();
  const beatCount = visualBeatCount ?? plan.visual_beats?.length ?? 1;
  for (const run of generationRuns) {
    if (run.kind !== "image" || !["local_tool", "remote_api"].includes(run.execution_mode) || run.provider === "simulated") continue;
    const key = run.visual_beat_id || plan.visual_beats?.[0]?.id || "single";
    const previous = latestByBeat.get(key);
    if (!previous || imageStateTime(run.created_at) > imageStateTime(previous.created_at)) latestByBeat.set(key, run);
  }
  const latestRuns = [...latestByBeat.values()].filter(run => !items.some(item => (
    item.shot_plan_id === plan.id && item.status === "completed" && item.run_id && item.run_id !== run.id
    && (item.visual_beat_id === run.visual_beat_id || beatCount === 1)
    && imageStateTime(item.batch_created_at) > imageStateTime(run.created_at)
  )));
  const relevant = items.filter((item) => {
    if (item.shot_plan_id !== plan.id) return false;
    const latest = latestByBeat.get(item.visual_beat_id) || (beatCount === 1 ? latestRuns[0] : null);
    const batchTime = imageStateTime(item.batch_completed_at || item.batch_updated_at || item.batch_created_at);
    // A batch is an immutable attempt, not the current state of a shot. A later
    // single-shot run or successful image can supersede that attempt's outcome.
    if (latest?.id && latest.id !== item.run_id && batchTime && imageStateTime(latest.created_at) > batchTime) return false;
    if (["failed", "unknown", "cancelled"].includes(item.status) && beatCount === 1 && batchTime && imageStateTime(imagePreview?.updated_at) > batchTime) return false;
    return true;
  });
  if (latestRuns.some(run => ["running", "cancellation_requested"].includes(run.status)) || plan.image_status === "generating" || relevant.some(item => item.status === "running")) return "生成中";
  if (latestRuns.some(run => run.status === "queued") || relevant.some(item => item.status === "pending")) return "排队中";
  if (plan.image_status === "approved") return "已采用";
  if (plan.image_status === "stale") return "输入已更新";
  if (latestRuns.some(run => run.status === "failed")) return "失败";
  if (relevant.some((item) => item.status === "unknown")) return "需核对";
  if (relevant.some((item) => item.status === "failed")) return "失败";
  if (plan.image_status === "failed") return "失败";
  if (imagePreview?.candidate_id || imagePreview?.thumbnail_url || relevant.some(item => item.status === "completed") || plan.image_status === "review_required") return "待采用";
  return "待生成";
}
export function changedBatchShots(previous, next) {
  const seen = new Map((previous?.items || []).map((item) => [item.visual_beat_id, `${item.run_id}:${item.status}:${item.candidate_ids?.join(",")}`]));
  return [...new Set((next?.items || []).filter((item) =>
    (["completed", "failed", "unknown"].includes(item.status) || item.candidate_ids?.length > 0)
      && seen.get(item.visual_beat_id) !== `${item.run_id}:${item.status}:${item.candidate_ids?.join(",")}`
  ).map((item) => item.shot_plan_id))];
}
