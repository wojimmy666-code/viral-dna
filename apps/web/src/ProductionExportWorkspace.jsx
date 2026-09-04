import { useEffect, useState } from "react";
import {
  CircleNotch,
  DownloadSimple,
  FileVideo,
  FilmSlate,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

const RESOLUTION_OPTIONS = [
  { value: "720p", label: "720P", description: "快速交付" },
  { value: "1080p", label: "1080P", description: "推荐成片" },
  { value: "project", label: "方案尺寸", description: "保持原设置" },
];

const SUBTITLE_OPTIONS = [
  { value: "burned", label: "烧录字幕", description: "兼容主流短视频平台" },
  { value: "embedded", label: "内嵌字幕", description: "播放器可开关字幕轨" },
  { value: "none", label: "无字幕", description: "输出清洁版画面" },
];

function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "待生成";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusLabel(status) {
  return {
    queued: "排队中",
    running: "导出中",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status] || status;
}

function optionLabel(options, value) {
  return options.find((item) => item.value === value)?.label || value;
}

function normalizeLockedResolution(value) {
  const normalized = String(value || "").toLowerCase();
  return ["720p", "1080p"].includes(normalized) ? normalized : "project";
}

export function ProductionExportWorkspace({
  lockedResolution = null,
  project,
  request,
  resolveUrl,
  onNotice,
  onNotificationsChanged,
  onProjectChanged,
}) {
  const [timeline, setTimeline] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resolution, setResolution] = useState(() => (
    lockedResolution ? normalizeLockedResolution(lockedResolution) : "1080p"
  ));
  const [subtitleMode, setSubtitleMode] = useState("burned");
  const [quality, setQuality] = useState("high");

  const activeJob = jobs.find((item) => ACTIVE_STATUSES.has(item.status)) || null;
  const successfulJobs = jobs.filter((item) => item.status === "succeeded");
  const latestSuccess = successfulJobs[0] || null;
  const resolutionOptions = lockedResolution
    ? RESOLUTION_OPTIONS.filter((item) => item.value === normalizeLockedResolution(lockedResolution))
    : RESOLUTION_OPTIONS;
  useEffect(() => {
    if (lockedResolution) setResolution(normalizeLockedResolution(lockedResolution));
  }, [lockedResolution]);
  useEffect(() => {
    let disposed = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [nextTimeline, response] = await Promise.all([
          request(`/productions/${project.id}/timeline`),
          request(`/productions/${project.id}/timeline/final-renders`),
        ]);
        if (disposed) return;
        setTimeline(nextTimeline);
        setJobs(response.items || []);
      } catch (requestError) {
        if (!disposed) setError(requestError.message);
      } finally {
        if (!disposed) setLoading(false);
      }
    }
    load();
    return () => { disposed = true; };
  }, [project.id, request]);

  useEffect(() => {
    if (!activeJob?.id) return undefined;
    let disposed = false;
    let timer = null;
    async function poll() {
      try {
        const next = await request(`/productions/${project.id}/export-jobs/${activeJob.id}`);
        if (disposed) return;
        setJobs((items) => [next, ...items.filter((item) => item.id !== next.id)]);
        if (ACTIVE_STATUSES.has(next.status)) {
          timer = window.setTimeout(poll, 1000);
          return;
        }
        await onNotificationsChanged?.();
        if (next.status === "succeeded") {
          onNotice({
            type: "success",
            title: "高清成片已导出",
            message: "成片已归档，可以下载。",
          });
          await onProjectChanged?.();
        } else if (next.status === "failed") {
          onNotice({
            type: "error",
            title: "高清导出失败",
            message: next.error_message || "请检查导出设置后重试。",
          });
        }
      } catch (requestError) {
        if (!disposed) setError(requestError.message);
      }
    }
    timer = window.setTimeout(poll, 800);
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeJob?.id, onNotice, onNotificationsChanged, onProjectChanged, project.id, request]);

  async function startExport() {
    if (!timeline || activeJob) return;
    setBusy(true);
    setError("");
    try {
      const job = await request(`/productions/${project.id}/timeline/final-renders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: timeline.revision_id,
          resolution,
          subtitle_mode: subtitleMode,
          quality,
        }),
      });
      setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      onNotice({
        type: "info",
        title: "高清成片已排队",
        message: "可以继续留在页面查看进度。",
      });
      await onNotificationsChanged?.();
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "无法开始导出", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function cancelExport() {
    if (!activeJob) return;
    try {
      const next = await request(
        `/productions/${project.id}/export-jobs/${activeJob.id}/cancel`,
        { method: "POST" },
      );
      setJobs((items) => [next, ...items.filter((item) => item.id !== next.id)]);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  function download(job) {
    const anchor = document.createElement("a");
    anchor.href = resolveUrl(`/api/v1/productions/${project.id}/export-jobs/${job.id}/download`);
    anchor.download = job.output_filename || "成片.mp4";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  if (loading) {
    return <div className="production-export-loading"><CircleNotch className="spin" size={24} />正在读取导出工作区</div>;
  }

  return (
    <section className="production-export-workspace">
      <header className="production-export-toolbar">
        <div>
          <h3>导出成片</h3>
        </div>
        {activeJob && (
          <div className="production-export-progress" aria-live="polite">
            <CircleNotch className="spin" size={17} />
            <span>高清导出 {activeJob.progress_percent}%</span>
            <button onClick={cancelExport} type="button"><X size={14} />取消</button>
          </div>
        )}
      </header>

      {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}

      <div className="production-export-grid">
        <section className="production-export-settings">
          <div className="production-export-section-heading">
            <div><strong>导出设置</strong></div>
          </div>

          <fieldset className="production-export-option-group">
            <legend>{lockedResolution ? "清晰度（项目锁定）" : "清晰度"}</legend>
            <div className="production-export-option-row">
              {resolutionOptions.map((option) => (
                <button className={resolution === option.value ? "active" : ""} disabled={Boolean(lockedResolution)} key={option.value} onClick={() => setResolution(option.value)} type="button">
                  <strong>{option.label}</strong><small>{option.description}</small>
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="production-export-option-group">
            <legend>字幕</legend>
            <div className="production-export-option-column">
              {SUBTITLE_OPTIONS.map((option) => (
                <label className={subtitleMode === option.value ? "active" : ""} key={option.value}>
                  <input checked={subtitleMode === option.value} name="subtitle-mode" onChange={() => setSubtitleMode(option.value)} type="radio" />
                  <span><strong>{option.label}</strong><small>{option.description}</small></span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="production-export-option-group">
            <legend>编码质量</legend>
            <div className="production-export-quality">
              <button className={quality === "standard" ? "active" : ""} onClick={() => setQuality("standard")} type="button"><strong>标准</strong><small>文件更小</small></button>
              <button className={quality === "high" ? "active" : ""} onClick={() => setQuality("high")} type="button"><strong>高质量</strong><small>推荐交付</small></button>
            </div>
          </fieldset>

          <button className="primary-button production-export-submit" disabled={busy || Boolean(activeJob) || !timeline} onClick={startExport} type="button">
            {busy || activeJob ? <CircleNotch className="spin" size={18} /> : <FilmSlate size={18} weight="fill" />}
            {activeJob ? "正在导出" : successfulJobs.length ? "重新导出高清成片" : "开始高清导出"}
          </button>
        </section>

        <section className="production-export-preview">
          <div className="production-export-section-heading">
            <div><strong>最新成片</strong><small>{latestSuccess ? `${formatDate(latestSuccess.completed_at)} · ${formatBytes(latestSuccess.file_size_bytes)}` : "完成导出后可在这里播放和下载"}</small></div>
            {latestSuccess && <button aria-label="下载最新成片" onClick={() => download(latestSuccess)} type="button"><DownloadSimple size={18} /></button>}
          </div>
          {latestSuccess ? (
            <div
              className="production-export-video"
              style={{
                "--export-aspect": `${latestSuccess.preview_width} / ${latestSuccess.preview_height}`,
                "--export-ratio": latestSuccess.preview_width / latestSuccess.preview_height,
              }}
            >
              <video controls poster={resolveUrl(latestSuccess.cover_url)} preload="metadata" src={resolveUrl(latestSuccess.output_url)} />
            </div>
          ) : (
            <div className="production-export-empty"><FileVideo size={42} /><strong>尚未生成高清成片</strong><span>低清预览不会被当作最终交付文件。</span></div>
          )}
        </section>
      </div>

      <section className="production-export-history">
        <div className="production-export-section-heading"><div><strong>导出历史</strong></div></div>
        {jobs.length === 0 ? (
          <div className="production-export-history-empty">暂无导出记录</div>
        ) : (
          <div className="production-export-job-list">
            {jobs.map((job) => (
              <article className={`production-export-job ${job.status}`} key={job.id}>
                <div className="production-export-job-cover">
                  {job.cover_url ? <img alt="成片封面" src={resolveUrl(job.cover_url)} /> : <FileVideo size={22} />}
                </div>
                <div className="production-export-job-main">
                  <div><strong>{job.output_filename || "高清成片"}</strong><span className={`production-export-status ${job.status}`}>{statusLabel(job.status)}</span></div>
                  <small>{job.preview_width} × {job.preview_height} · {optionLabel(SUBTITLE_OPTIONS, job.subtitle_mode)} · {formatDate(job.created_at)}</small>
                  {job.error_message && <p>{job.error_message}</p>}
                </div>
                <div className="production-export-job-actions">
                  {job.status === "succeeded" && <button onClick={() => download(job)} type="button"><DownloadSimple size={16} />下载</button>}
                  {ACTIVE_STATUSES.has(job.status) && <span>{job.progress_percent}%</span>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
