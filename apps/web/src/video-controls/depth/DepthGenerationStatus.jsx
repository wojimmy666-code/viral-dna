import {
  ArrowClockwise,
  CaretDown,
  CircleNotch,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";

const ACTIVE_STATUSES = new Set(["queued", "running", "cancellation_requested"]);

const STAGE_LABELS = {
  queued: "等待执行",
  validating_input: "检查输入",
  probing_media: "读取视频信息",
  clipping_source: "提取分镜",
  loading_model: "加载深度模型",
  inferring_depth: "推理空间深度",
  writing_depth: "写入深度帧",
  encoding_video: "编码深度视频",
  validating_output: "检查输出质量",
  persisting_asset: "保存深度资产",
  completed: "生成完成",
};

function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `约 ${Math.ceil(seconds)} 秒`;
  return `约 ${Math.ceil(seconds / 60)} 分钟`;
}

export function DepthGenerationStatus({ error = "", job, onCancel, onRetry }) {
  if (!job && !error) return null;
  const active = Boolean(job && ACTIVE_STATUSES.has(job.status));
  const failed = ["failed", "interrupted"].includes(job?.status);
  const cancelled = job?.status === "cancelled";
  const percent = Math.max(0, Math.min(100, Number(job?.progress_percent || 0)));
  const frameLabel = job?.total_frames
    ? `${job.processed_frames || 0}/${job.total_frames} 帧`
    : "";
  const etaLabel = durationLabel(job?.estimated_seconds_remaining);

  if (active) {
    return (
      <section className="depth-job-status running" aria-label="深度生成进度">
        <header>
          <span className="depth-job-status-icon"><CircleNotch className="spin" size={20} /></span>
          <div>
            <strong aria-live="polite">{STAGE_LABELS[job.stage] || "正在生成全场景深度"}</strong>
            <span>{job.progress_message || "深度任务正在后台执行"}</span>
          </div>
          <output>{percent}%</output>
        </header>
        <progress aria-label="全场景深度生成进度" max="100" value={percent}>{percent}%</progress>
        <footer>
          <span>{[frameLabel, etaLabel, job.device_name].filter(Boolean).join(" · ")}</span>
          <button className="secondary-button compact" disabled={job.status === "cancellation_requested"} onClick={onCancel} type="button">
            <XCircle size={16} />{job.status === "cancellation_requested" ? "正在停止" : "取消任务"}
          </button>
        </footer>
      </section>
    );
  }

  if (failed || cancelled || error) {
    return (
      <section className={`depth-job-status ${cancelled ? "cancelled" : "failed"}`} role={failed || error ? "alert" : "status"}>
        <header>
          <span className="depth-job-status-icon"><WarningCircle size={20} /></span>
          <div>
            <strong>{cancelled ? "深度生成已取消" : "深度生成未完成"}</strong>
            <span>{error || job?.error_message || "任务没有生成可用的深度视频。"}</span>
          </div>
          {onRetry && (
            <button className="secondary-button compact" onClick={onRetry} type="button">
              <ArrowClockwise size={16} />快速重试
            </button>
          )}
        </header>
        {job?.technical_detail && (
          <details>
            <summary><CaretDown size={14} />技术详情</summary>
            <pre>{job.technical_detail}</pre>
          </details>
        )}
      </section>
    );
  }

  return null;
}
