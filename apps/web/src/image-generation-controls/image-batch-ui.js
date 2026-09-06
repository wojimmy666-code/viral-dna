export const activeImageBatch = (batch) => ["running", "stopping"].includes(batch?.status);
export function imageBatchCounts(batch) {
  const items = batch?.items || [];
  const count = (status) => items.filter((item) => item.status === status).length;
  return { total: items.length, completed: count("completed"), skipped: count("skipped"),
    running: count("running"), pending: count("pending"), failed: count("failed") + count("unknown"),
    cancelled: count("cancelled"), done: items.filter((item) => !["pending", "running"].includes(item.status)).length };
}
export function shotImageStatus(plan, items = []) {
  const relevant = items.filter((item) => item.shot_plan_id === plan.id);
  if (relevant.some((item) => item.status === "running")) return "生成中";
  if (relevant.some((item) => item.status === "pending")) return "排队中";
  if (plan.image_status === "approved") return "已采用";
  if (relevant.some((item) => item.status === "unknown")) return "需核对";
  if (relevant.some((item) => item.status === "failed")) return "失败";
  if (relevant.some((item) => item.status === "completed") || plan.image_status === "review_required") return "待采用";
  if (plan.image_status === "stale") return "需更新";
  if (plan.image_status === "failed") return "失败";
  return "待生成";
}
export function changedBatchShots(previous, next) {
  const seen = new Map((previous?.items || []).map((item) => [item.visual_beat_id, `${item.run_id}:${item.status}:${item.candidate_ids?.join(",")}`]));
  return [...new Set((next?.items || []).filter((item) =>
    ["completed", "failed", "unknown"].includes(item.status)
      && seen.get(item.visual_beat_id) !== `${item.run_id}:${item.status}:${item.candidate_ids?.join(",")}`
  ).map((item) => item.shot_plan_id))];
}
