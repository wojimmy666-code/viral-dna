export function storyboardProgressState(step, now = Date.now(), manifest = null) {
  const running = step?.execution_status === "running";
  const failed = step?.execution_status === "failed";
  const progress = Math.max(0, Math.min(100, Number(step?.progress) || 0));
  const start = Date.parse(step?.started_at || "");
  const end = Date.parse(step?.completed_at || "");
  const elapsedMs = running
    ? (Number.isFinite(start) ? Math.max(0, now - start) : 0)
    : Math.max(0, Number(step?.total_ms) || (Number.isFinite(start) && Number.isFinite(end) ? end - start : 0));
  const legacyModel = step?.error_code === "storyboard_model_failed"
    ? step.error_message?.match(/^([\w.:-]+)：/)?.[1] : null;
  const resumeConflict = Boolean(manifest && step?.resumable
    && manifest.id !== step.checkpoint_manifest_revision_id);
  const resumable = Boolean(step?.resumable && !resumeConflict);
  const phase = progress < 18 ? "整理品牌、品类和素材事实"
    : progress < 55 ? "正在生成大纲与镜头"
      : progress < 90 ? "编译逐镜头图片与视频提示词" : "检查连续性与提示词质量";
  return {
    running, failed, progress, elapsedMs,
    title: running ? phase : failed ? "大纲与分镜处理失败" : "大纲与分镜处理已停止",
    model: step?.model || legacyModel || (running ? "正在准备文案模型" : "模型信息未记录"),
    endedAt: Number.isFinite(end) ? new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(end) : "",
    resumable, resumeConflict,
    retryLabel: resumable ? "继续处理" : "重新生成",
    canRetry: !running && step?.retryable !== false && !resumeConflict && (!manifest || resumable),
    savedLabel: step?.total_shots > 0 ? `已保留 ${step.total_shots} 个镜头 · 已编译 ${step.completed_shots || 0} 个` : "",
    error: step?.error_message || (failed ? "处理未完成，请重试；如再次失败，请检查文案模型连接。" : ""),
  };
}
