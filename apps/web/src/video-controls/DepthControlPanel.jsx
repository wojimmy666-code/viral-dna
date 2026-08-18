import { useMemo } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  IdentificationCard,
  ImageSquare,
  ShieldCheck,
  Stack,
  Trash,
  VideoCamera,
  WarningCircle,
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

function RoutePlan({ error, strategy }) {
  if (!error && !strategy?.plan_steps?.length) return null;
  return (
    <details className="depth-route-plan">
      <summary>查看生成输入计划</summary>
      {error ? (
        <p className="depth-control-error"><WarningCircle size={18} />{error}</p>
      ) : (
        <div className="depth-route-plan-grid">
          {strategy.plan_steps.map((step) => (
            <article data-status={step.status} key={`${step.kind}-${step.source}`}>
              <strong>{step.label}</strong>
              <span>{step.detail}</span>
            </article>
          ))}
        </div>
      )}
    </details>
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
  managedAssetBinding,
  model,
  onCreate,
  onCancelGeneration,
  onDelete,
  onInstall,
  onNotice,
  onOpenManagedAssets,
  onToggle,
  onRetryGeneration,
  plan,
  referenceFrames = [],
  request,
  resolveUrl,
  sourceVideoUrl,
  strategy,
  strategyError = "",
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
  const supportsDepth = Boolean(strategy?.depth_control_supported);
  const showsDepthControls = Boolean(strategy?.show_depth_control_controls);
  const identityReady = strategy?.managed_identity_required
    ? Boolean(managedAssetBinding)
    : referenceFrames.some((item) => item.candidate);
  const appearanceCount = (plan?.video_reference_bindings || []).filter(
    (item) => item.enabled && item.source_kind === "project_asset",
  ).length;

  if (!showsDepthControls) {
    return (
      <section className="depth-reference-summary compact" aria-label="视频参考策略">
        <span className="depth-reference-icon"><ShieldCheck size={21} /></span>
        <div className="depth-reference-copy">
          <strong>{strategy?.title || "人物与画面资产参考"}</strong>
          <small>{strategy?.description || `${model?.label || "当前模型"} 不接收深度控制视频。`}</small>
        </div>
        <span className={`depth-reference-state${strategy?.generation_allowed === false ? " blocked" : ""}`}>
          {strategy?.generation_allowed === false ? "未就绪" : "可生成"}
        </span>
        <RoutePlan error={strategyError} strategy={strategy} />
      </section>
    );
  }

  return (
    <section className="depth-reference-summary" aria-label="全场景深度控制">
      <header className="depth-reference-header">
        <span className="depth-reference-icon"><Stack size={21} /></span>
        <div className="depth-reference-copy">
          <strong>{strategy?.title || "资产外观 + 全场景深度控制"}</strong>
          <small>{strategy?.description || "深度视频只提供动作、空间关系、遮挡与镜头，不提供人物或场景外观。"}</small>
        </div>
        <span className={`depth-reference-state${strategy?.generation_allowed === false ? " blocked" : ""}`}>
          {strategy?.generation_allowed === false ? "未就绪" : "可生成"}
        </span>
      </header>

      <div className="depth-source-grid">
        <article data-ready={identityReady}>
          <IdentificationCard size={20} />
          <div><strong>人物身份</strong><span>{managedAssetBinding?.name || (identityReady ? "已确认人物资产" : "尚未选择")}</span></div>
        </article>
        <article data-ready={appearanceCount > 0 || referenceFrames.length > 0}>
          <ImageSquare size={20} />
          <div><strong>外观资产</strong><span>{appearanceCount > 0 ? `${appearanceCount} 项项目资产` : "使用已确认画面"}</span></div>
        </article>
        <article data-ready={Boolean(activeDepth)}>
          <VideoCamera size={20} />
          <div><strong>动作与空间</strong><span>{activeDepth ? "全场景深度已启用" : "尚未生成深度视频"}</span></div>
        </article>
      </div>

      {strategy?.managed_identity_required && !managedAssetBinding && (
        <button className="secondary-button compact" disabled={busy} onClick={onOpenManagedAssets} type="button">
          <IdentificationCard size={17} />选择托管演员
        </button>
      )}

      {(strategyError || strategy?.blocker_message) && (
        <p className="depth-control-error">
          <WarningCircle size={18} />{strategyError || strategy.blocker_message}
        </p>
      )}

      <DepthGenerationStatus
        error={generationError}
        job={generationJob}
        onCancel={onCancelGeneration}
        onRetry={onRetryGeneration}
      />

      <details className="depth-control-advanced">
        <summary>
          <span>深度控制（高级）</span>
          <small>默认由系统生成和路由，需要时可预览、重建或停用</small>
        </summary>
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
      </details>

      <RoutePlan error="" strategy={strategy} />
    </section>
  );
}
