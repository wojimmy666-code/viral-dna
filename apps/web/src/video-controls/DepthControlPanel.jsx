import { useMemo } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  Stack,
  Trash,
  VideoCamera,
} from "@phosphor-icons/react";
import { DepthGenerationStatus } from "./depth/DepthGenerationStatus.jsx";
import { AddToAssetsButton } from "../generated-assets/AddToAssetsButton.jsx";
import "./depth/depth-generation.css";

function createdAtLabel(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function depthUrl(resolveUrl, shotId, assetId, options = {}) {
  const query = new URLSearchParams();
  if (options.thumbnail) query.set("thumbnail", "true");
  if (options.download) query.set("download", "true");
  if (options.version) query.set("v", options.version);
  const suffix = query.size ? `?${query.toString()}` : "";
  const path = `/api/v1/depth-controls/shots/${shotId}/${assetId}/content${suffix}`;
  return resolveUrl?.(path) || path;
}

function usableDepth(item) {
  return Boolean(
    item?.status === "ready"
    && item?.validation_status === "passed"
    && item?.relative_path
    && item?.sha256,
  );
}

export function DepthControlPanel({
  busy,
  engineCapabilities = [],
  engineError = "",
  installation,
  installationError = "",
  generationError = "",
  generationJob,
  onCreate,
  onCancelGeneration,
  onDelete,
  onInstall,
  onNotice,
  onToggle,
  onRetryGeneration,
  plan,
  request,
  resolveUrl,
  sourceVideoUrl,
}) {
  const depthAssets = useMemo(() => (
    [...(plan?.depth_control_assets || [])].sort((left, right) => (
      new Date(right.created_at || 0).getTime()
      - new Date(left.created_at || 0).getTime()
    ))
  ), [plan?.depth_control_assets]);
  const activeDepth = depthAssets.find((item) => item.enabled && usableDepth(item)) || null;
  const engine = (
    engineCapabilities.find((item) => item.engine === generationJob?.engine)
    || engineCapabilities.find((item) => item.available)
    || engineCapabilities[0]
    || null
  );
  const installationRunning = ["queued", "running"].includes(installation?.status);
  const generationRunning = ["queued", "running", "cancellation_requested"].includes(
    generationJob?.status,
  );
  const stateLabel = generationRunning
    ? "生成中"
    : activeDepth
      ? "已启用"
      : engine?.available
        ? "可生成"
        : "引擎未就绪";
  const stateBlocked = !generationRunning && !activeDepth && !engine?.available;
  const shotRange = plan
    ? `分镜 ${plan.index} · ${Number(plan.start_seconds || 0).toFixed(1)}–${Number(plan.end_seconds || 0).toFixed(1)} 秒`
    : "当前分镜";

  return (
    <section className="depth-reference-summary" aria-label="深度视频生成">
      <header className="depth-reference-header">
        <span className="depth-reference-icon"><Stack size={21} /></span>
        <div className="depth-reference-copy">
          <strong>从原始分镜生成深度视频</strong>
          <small>只读取原始视频的当前分镜，提取动作、遮挡、空间层次和镜头轨迹；不使用人物身份或外观资产。</small>
        </div>
        <span className={`depth-reference-state${stateBlocked ? " blocked" : ""}`}>
          {stateLabel}
        </span>
      </header>

      <div className="depth-source-note">
        <VideoCamera size={20} />
        <div><strong>唯一输入：原始视频</strong><span>{shotRange}</span></div>
        <span><CheckCircle size={16} />无需人物或场景资产</span>
      </div>

      <DepthGenerationStatus
        error={generationError}
        job={generationJob}
        onCancel={onCancelGeneration}
        onRetry={onRetryGeneration}
      />

      <div className="depth-control-body">
        <div className="depth-control-media-grid">
          <article>
            <header><strong>原始分镜</strong><span>仅用于提取空间深度</span></header>
            <video controls playsInline preload="metadata" src={sourceVideoUrl} />
          </article>
          <article>
            <header><strong>全场景深度</strong><span>近白远黑 · 不含身份与纹理</span></header>
            {activeDepth ? (
              <video
                controls
                key={activeDepth.id}
                playsInline
                poster={depthUrl(resolveUrl, plan.id, activeDepth.id, { thumbnail: true, version: activeDepth.sha256 })}
                preload="metadata"
                src={depthUrl(resolveUrl, plan.id, activeDepth.id, { version: activeDepth.sha256 })}
              />
            ) : (
              <div className="depth-control-placeholder"><VideoCamera size={30} /><span>生成后可在这里检查空间深度</span></div>
            )}
          </article>
        </div>

        <div className="depth-control-toolbar">
          <div>
            <strong>{engine?.engine === "video_depth_anything" ? "Video Depth Anything Small" : "真实深度引擎"}</strong>
            <span>{engine?.available ? "引擎已就绪" : engine?.availability_note || engineError || "深度引擎状态未知"}</span>
          </div>
          <div className="depth-control-actions">
            {activeDepth && (
              <AddToAssetsButton
                artifactKind="depth_control"
                assetType="spatial_depth"
                disabled={busy}
                name={`分镜 ${plan.index} 深度视频`}
                onNotice={onNotice}
                request={request}
                shotPlanId={plan.id}
                sourceEntityId={activeDepth.id}
              />
            )}
            {activeDepth && (
              <button className="secondary-button compact" disabled={busy} onClick={() => onToggle?.(activeDepth.id, false)} type="button">停用</button>
            )}
            {engine?.available ? (
              <button className="secondary-button compact" disabled={busy || generationRunning} onClick={() => onCreate?.()} type="button">
                <ArrowClockwise size={17} />{generationRunning ? "正在生成" : activeDepth ? "重新生成" : "生成深度视频"}
              </button>
            ) : (
              <button
                className="secondary-button compact"
                disabled={busy || installationRunning || !engine}
                onClick={() => onInstall?.(engine?.engine)}
                type="button"
              >
                <ArrowClockwise size={17} />{installationRunning ? "正在安装" : "安装深度引擎"}
              </button>
            )}
            {activeDepth && (
              <button aria-label="删除当前深度视频" className="icon-button danger" disabled={busy} onClick={() => onDelete?.(activeDepth.id)} title="删除深度视频" type="button"><Trash size={17} /></button>
            )}
          </div>
        </div>

        {(installationRunning || installationError) && (
          <div className={`depth-engine-installation${installationError ? " failed" : ""}`} role="status">
            <div>
              <strong>{installationError ? "安装未完成" : installation?.message || "正在安装深度引擎"}</strong>
              <span>{installationError || `${installation?.progress_percent || 0}%`}</span>
            </div>
            {!installationError && (
              <progress
                aria-label="深度引擎安装进度"
                max="100"
                value={installation?.progress_percent || 0}
              >
                {installation?.progress_percent || 0}%
              </progress>
            )}
          </div>
        )}

        {depthAssets.length > 1 && (
          <div className="depth-control-history">
            <strong>历史深度</strong>
            <div>
              {depthAssets.map((item) => (
                <button disabled={busy || !usableDepth(item)} key={item.id} onClick={() => onToggle?.(item.id, true)} type="button">
                  <span>{item.enabled ? <CheckCircle size={16} weight="fill" /> : <VideoCamera size={16} />}</span>
                  <span>{createdAtLabel(item.created_at) || "历史版本"}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
