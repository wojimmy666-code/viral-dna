import { useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise,
  CaretDown,
  CheckCircle,
  CircleNotch,
  DownloadSimple,
  MagicWand,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useVideoEnhancement } from "./useVideoEnhancement.js";
import "./video-enhancement.css";

const TARGETS = [
  { id: "1080p", label: "1080p", note: "推荐", shortEdge: 1080 },
  { id: "4k", label: "4K", note: "更慢", shortEdge: 2160 },
];

function formatRemaining(seconds) {
  if (!Number.isFinite(Number(seconds))) return "";
  const value = Math.max(0, Number(seconds));
  if (value < 60) return `预计剩余 ${Math.ceil(value)} 秒`;
  return `预计剩余 ${Math.ceil(value / 60)} 分钟`;
}

function originalMedia(candidate) {
  const original = candidate?.quality_report?.video_enhancement?.original;
  return original?.relative_path
    ? original
    : {
        width: candidate?.width,
        height: candidate?.height,
      };
}

export function VideoEnhancementPanel({
  candidate,
  expectedRevisionId,
  onChanged,
  onNotificationsChanged,
  onPreviewChange,
  request,
  resolveUrl,
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("1080p");
  const [previewVersion, setPreviewVersion] = useState("current");
  const enhancement = useVideoEnhancement({
    candidateId: candidate?.id,
    enabled: Boolean(candidate?.id && expectedRevisionId),
    expectedRevisionId,
    onChanged,
    onNotificationsChanged,
    request,
  });
  const original = originalMedia(candidate);
  const sourceShortEdge = Math.min(
    Number(original.width) || 0,
    Number(original.height) || 0,
  );
  const sourceResolutionLabel = original.width && original.height
    ? `${original.width}×${original.height}`
    : "低清视频";
  const availableTargets = TARGETS.filter(
    (item) => !sourceShortEdge || sourceShortEdge < item.shortEdge,
  );
  const successfulViews = useMemo(
    () => enhancement.jobs
      .filter((item) => item.job.status === "succeeded" && item.content_url)
      .sort((left, right) => new Date(left.job.created_at) - new Date(right.job.created_at)),
    [enhancement.jobs],
  );
  const activeResult = successfulViews.find((item) => item.job.active_for_final) || null;
  const effectivePreviewVersion = previewVersion === "current"
    ? activeResult?.job.id || "original"
    : previewVersion;
  const selectedResult = successfulViews.find(
    (item) => item.job.id === effectivePreviewVersion,
  ) || null;
  const runningJob = enhancement.activeView?.job || null;
  const latestFailure = [...enhancement.jobs].reverse().find(
    (item) => ["failed", "interrupted", "cancelled"].includes(item.job.status),
  )?.job || null;

  useEffect(() => {
    setOpen(false);
    setPreviewVersion("current");
    onPreviewChange?.(null);
  }, [candidate?.id, onPreviewChange]);

  useEffect(() => {
    if (runningJob) setOpen(true);
  }, [runningJob?.id]);

  useEffect(() => {
    const preferred = enhancement.settings?.default_target;
    const selected = availableTargets.some((item) => item.id === preferred)
      ? preferred
      : availableTargets[0]?.id;
    if (selected) setTarget(selected);
  }, [enhancement.settings?.default_target, sourceShortEdge]);

  function previewOriginal() {
    setPreviewVersion("original");
    onPreviewChange?.({
      candidateId: candidate.id,
      key: "original",
      label: `原始 ${original.width || ""} × ${original.height || ""}`,
      url: `/api/v1/generation-candidates/${candidate.id}/content?variant=original`,
    });
  }

  function previewResult(item) {
    setPreviewVersion(item.job.id);
    onPreviewChange?.({
      candidateId: candidate.id,
      key: item.job.id,
      label: `${item.job.target === "4k" ? "4K" : "1080p"} 清晰版`,
      url: item.content_url,
    });
  }

  async function start() {
    const created = await enhancement.start(target);
    if (created) setOpen(true);
  }

  const installed = enhancement.settings?.capability?.available;
  const canInstall = enhancement.settings?.capability?.installable;
  const installActive = ["queued", "running"].includes(enhancement.installation?.status);
  const selectedIsActive = selectedResult?.job.active_for_final;
  const originalIsActive = !activeResult;

  return (
    <section className={`video-enhancement${open ? " open" : ""}`} aria-labelledby="video-enhancement-title">
      <button
        aria-expanded={open}
        className="video-enhancement-summary"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className="video-enhancement-summary-icon"><MagicWand size={18} weight="duotone" /></span>
        <span>
          <strong id="video-enhancement-title">AI 清晰化</strong>
          <small>
            {runningJob
              ? runningJob.progress_message
              : activeResult
                ? `${activeResult.job.target === "4k" ? "4K" : "1080p"} 版本用于成片`
                : "Real-ESRGAN 本地处理，不消耗视频生成额度"}
          </small>
        </span>
        {runningJob && <em>{runningJob.progress_percent}%</em>}
        <CaretDown className="video-enhancement-caret" size={17} />
      </button>

      {open && (
        <div className="video-enhancement-body">
          <div className="video-enhancement-flow" aria-label="清晰化输出设置">
            <span className="video-enhancement-source">
              <small>原视频</small>
              <strong>{original.width || "—"} × {original.height || "—"}</strong>
            </span>
            <span aria-hidden="true">→</span>
            <div className="video-enhancement-targets" role="radiogroup" aria-label="目标清晰度">
              {TARGETS.map((item) => {
                const reached = Boolean(
                  sourceShortEdge && sourceShortEdge >= item.shortEdge,
                );
                return (
                  <button
                    aria-checked={target === item.id}
                    className={target === item.id ? "selected" : ""}
                    disabled={Boolean(runningJob) || reached}
                    key={item.id}
                    onClick={() => setTarget(item.id)}
                    role="radio"
                    type="button"
                  >
                    <strong>{item.label}</strong>
                    <small>{reached ? "已达到" : item.note}</small>
                  </button>
                );
              })}
            </div>
            <span aria-hidden="true">→</span>
            <span className="video-enhancement-engine">
              <small>处理引擎</small>
              <strong>Real-ESRGAN 快速</strong>
            </span>
          </div>

          {target === "4k" && !runningJob && (
            <p className="video-enhancement-warning">
              <WarningCircle size={16} />{sourceResolutionLabel} 提升到 4K 主要改善边缘与观感，不等于获得原生 4K 细节。
            </p>
          )}

          {availableTargets.length === 0 && !runningJob && (
            <p className="video-enhancement-reached">
              <CheckCircle size={16} weight="fill" />当前视频已达到 4K，无需再次放大。
            </p>
          )}

          {!installed && (
            <div className="video-enhancement-install">
              <div>
                <strong>首次使用需安装本地引擎</strong>
                <span>{enhancement.settings?.capability?.availability_note || "正在检测本地环境"}</span>
                {enhancement.settings?.capability?.installation_path && (
                  <span
                    className="video-enhancement-install-path"
                    title={enhancement.settings.capability.installation_path}
                  >安装位置：<code>{enhancement.settings.capability.installation_path}</code></span>
                )}
              </div>
              <button
                className="secondary-button compact"
                disabled={!canInstall || installActive || Boolean(enhancement.busy)}
                onClick={enhancement.install}
                type="button"
              >
                {installActive ? <CircleNotch className="spin" size={16} /> : <DownloadSimple size={16} />}
                {installActive ? "安装中" : "安装引擎"}
              </button>
            </div>
          )}

          {enhancement.installation && (
            <div className={`video-enhancement-progress ${enhancement.installation.status}`} role="status">
              <div><span>{enhancement.installation.message}</span><strong>{enhancement.installation.progress_percent}%</strong></div>
              <progress max="100" value={enhancement.installation.progress_percent} />
            </div>
          )}

          {runningJob && (
            <div className="video-enhancement-progress running" role="status" aria-live="polite">
              <div>
                <span>{runningJob.progress_message}</span>
                <strong>{runningJob.progress_percent}%</strong>
              </div>
              <progress max="100" value={runningJob.progress_percent} />
              <footer>
                <span>{formatRemaining(runningJob.estimated_seconds_remaining) || "可以离开此页面，任务将在后台继续"}</span>
                <button
                  className="secondary-button compact"
                  disabled={enhancement.busy === "cancelling"}
                  onClick={() => enhancement.cancel(runningJob.id)}
                  type="button"
                ><X size={15} />取消任务</button>
              </footer>
            </div>
          )}

          {successfulViews.length > 0 && (
            <div className="video-enhancement-versions">
              <div className="video-enhancement-version-switch" role="radiogroup" aria-label="预览视频版本">
                <button
                  aria-checked={effectivePreviewVersion === "original"}
                  className={effectivePreviewVersion === "original" ? "selected" : ""}
                  onClick={previewOriginal}
                  role="radio"
                  type="button"
                >原始 {original.width} × {original.height}</button>
                {successfulViews.map((item) => (
                  <button
                    aria-checked={effectivePreviewVersion === item.job.id}
                    className={effectivePreviewVersion === item.job.id ? "selected" : ""}
                    key={item.job.id}
                    onClick={() => previewResult(item)}
                    role="radio"
                    type="button"
                  >
                    {item.job.target === "4k" ? "4K" : "1080p"}
                    {item.job.active_for_final && <CheckCircle size={14} weight="fill" />}
                  </button>
                ))}
              </div>
              <div className="video-enhancement-version-actions">
                {selectedResult && (
                  <a
                    className="secondary-button compact"
                    download={`video-${candidate.id}-${selectedResult.job.target}.mp4`}
                    href={resolveUrl(selectedResult.content_url)}
                  ><DownloadSimple size={15} />下载此版本</a>
                )}
                {selectedResult ? (
                  selectedIsActive ? (
                    <span className="video-enhancement-active"><CheckCircle size={16} weight="fill" />成片使用中</span>
                  ) : (
                    <button
                      className="primary-button compact"
                      disabled={enhancement.busy === "activating"}
                      onClick={() => enhancement.useForFinal(selectedResult.job.id)}
                      type="button"
                    >用于成片</button>
                  )
                ) : effectivePreviewVersion === "original" && (
                  originalIsActive ? (
                    <span className="video-enhancement-active"><CheckCircle size={16} weight="fill" />成片使用中</span>
                  ) : (
                    <button
                      className="secondary-button compact"
                      disabled={enhancement.busy === "activating"}
                      onClick={enhancement.useOriginal}
                      type="button"
                    >成片改用原始版</button>
                  )
                )}
              </div>
            </div>
          )}

          {(enhancement.error || latestFailure?.error_message) && !runningJob && (
            <div className="video-enhancement-error" role="alert">
              <WarningCircle size={17} />
              <span>{enhancement.error || latestFailure.error_message}</span>
              {latestFailure && latestFailure.status !== "cancelled" && (
                <button
                  className="secondary-button compact"
                  disabled={Boolean(enhancement.busy)}
                  onClick={() => enhancement.retry(latestFailure.id)}
                  type="button"
                ><ArrowClockwise size={15} />重试</button>
              )}
            </div>
          )}

          {installed && !runningJob && availableTargets.length > 0 && (
            <footer className="video-enhancement-actions">
              <span>本地处理，不消耗模型额度；原视频始终保留。</span>
              <button
                className="primary-button compact"
                disabled={Boolean(enhancement.busy)}
                onClick={start}
                type="button"
              >
                {enhancement.busy === "starting" ? <CircleNotch className="spin" size={16} /> : <MagicWand size={16} />}
                {successfulViews.some((item) => item.job.target === target) ? "重新清晰化" : "开始清晰化"}
              </button>
            </footer>
          )}
        </div>
      )}
    </section>
  );
}
