export const isCreativeRunning = (batch) => ["queued", "running"].includes(batch?.status);

export function visibleCreativeBatch(batch) {
  return batch?.status === "completed" || batch?.phase === "legacy"
    || (batch?.status === "failed" && batch.phase === "ideas" && batch.ideas?.length > 0) ? batch : null;
}

export function ideaReviewState(idea, brief) {
  if (idea.review_brief != null && idea.review_brief !== brief) return "needs_review";
  return idea.review_state && idea.review_state !== "unreviewed"
    ? idea.review_state : idea.review_issues?.length ? "needs_review" : "ready";
}

export function creativeRequirements(text) {
  const clauses = String(text || "").split(/[，,；;。\n]+/).map(value => value.trim()).filter(Boolean);
  const size = Math.max(1, Math.ceil(clauses.length / 24));
  return Array.from({ length: Math.ceil(clauses.length / size) }, (_, i) => ({ index: i + 1, text: clauses.slice(i * size, (i + 1) * size).join("；") }));
}

export function creativeBriefText(batch) {
  if (!batch || batch.phase === "legacy") return "";
  const frozen = batch.input_snapshot?.creative_brief?.text;
  if (typeof frozen === "string") return frozen;
  return batch.feedback || batch.input_snapshot?.original_creative_brief || "";
}

export function mergeCreativeBatch(items, batch) {
  return [batch, ...items.filter((item) => item.id !== batch.id)]
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

export function creativeTimingParts(batch, now = Date.now()) {
  if (!batch) return { total: 0, queue: 0, model: 0 };
  const end = batch.completed_at ? new Date(batch.completed_at).getTime() : now;
  const total = Math.max(0, (end - new Date(batch.created_at).getTime()) / 1000);
  const queue = batch.started_at
    ? Math.max(0, (new Date(batch.started_at) - new Date(batch.created_at)) / 1000) : total;
  const model = isCreativeRunning(batch) && batch.started_at
    ? Math.max((batch.model_elapsed_ms || 0) / 1000, (end - new Date(batch.started_at)) / 1000)
    : (batch.model_elapsed_ms || 0) / 1000;
  return { total: Math.round(total), queue: Math.round(queue), model: Math.round(model) };
}

export function creativeTiming(batch, now = Date.now()) {
  if (!batch) return "";
  const { total, queue, model } = creativeTimingParts(batch, now);
  return `总计 ${total} 秒 · 排队 ${queue} 秒 · 模型 ${model} 秒`;
}

export function creativeCost(batch) {
  if (batch.cost_status === "not_started") return "尚未调用模型";
  const cost = `¥${((batch.model_cost_micros || 0) / 1_000_000).toFixed(4)}`;
  return batch.cost_status === "measured" ? `已记录费用 ${cost}`
    : batch.model_cost_micros ? `已记录 ${cost}，另有请求费用未回报` : "费用未回报（不代表免费）";
}

export function batchLabel(batch) {
  const action = batch.phase === "legacy" ? "旧版完整方案" : batch.operation === "localize" ? "中文校正" : batch.operation === "edit" ? "人工修改"
    : batch.phase === "expanded" ? "展开分镜" : batch.operation === "regenerate" ? "单条重写" : "简短创意";
  const reviewCount = batch.phase === "ideas" ? batch.ideas?.filter(idea => ideaReviewState(idea, creativeBriefText(batch)) !== "ready").length : 0;
  const state = batch.status === "completed" && reviewCount ? "待修订"
    : { queued: "排队中", running: "生成中", failed: "失败", cancelled: "已取消", stale: "旧版" }[batch.status];
  return `${new Date(batch.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} · ${action}${state ? ` · ${state}` : ""}`;
}
