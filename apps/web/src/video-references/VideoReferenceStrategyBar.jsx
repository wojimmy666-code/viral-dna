import { useMemo, useState } from "react";
import {
  ArrowsOutSimple,
  CheckCircle,
  DownloadSimple,
  IdentificationCard,
  ImageSquare,
  PersonSimpleRun,
  ShieldCheck,
  Trash,
  VideoCamera,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { MediaLightbox } from "../MediaLightbox.jsx";

function policyOf(model) {
  return model?.capabilities?.person_references || {};
}

function proxyUrl(resolveUrl, shotPlanId, proxyId, options = {}) {
  const query = new URLSearchParams();
  if (options.thumbnail) query.set("thumbnail", "true");
  if (options.download) query.set("download", "true");
  if (options.version) query.set("v", options.version);
  const suffix = query.size ? `?${query.toString()}` : "";
  const path = `/api/v1/video-references/shots/${shotPlanId}/proxies/${proxyId}/content${suffix}`;
  return resolveUrl?.(path) || path;
}

function proxyCreatedAt(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function proxyUsable(item) {
  return Boolean(
    item?.status === "ready"
    && item?.identity_removed
    && item?.validation_status === "passed"
    && item?.semantic_validation_status === "passed"
    && item?.quality_score != null
    && item?.relative_path
    && item?.sha256
    && item?.manifest_relative_path
    && item?.quality_report_relative_path
    && item?.model_sha256,
  );
}

function proxyQualityLabel(item) {
  if (item?.semantic_validation_status === "passed") return "姿态通过";
  if (item?.semantic_validation_status === "review_required") return "姿态需复核";
  if (item?.semantic_validation_status === "failed") return "姿态不合格";
  return "旧版未校验";
}

function proxyQualityScore(item) {
  const score = Number(item?.quality_score);
  return Number.isFinite(score) ? `${Math.round(score * 100)} 分` : "";
}

function installBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  return `${(bytes / (1024 * 1024)).toFixed(bytes >= 100 * 1024 * 1024 ? 0 : 1)} MB`;
}

export function VideoReferenceStrategyBar({
  busy,
  managedAssetBinding,
  model,
  onCreateImageProxy,
  onCreateVideoProxy,
  onDisableProxy,
  onDeleteProxy,
  onEnableProxy,
  onInstallProxyEngine,
  onOpenManagedAssets,
  onRefreshProxyEngines,
  plan,
  proxyEngineCapabilities = [],
  proxyEngineInstallError = "",
  proxyEngineInstallJob = null,
  proxyEngineLoadError = "",
  referenceFrames,
  resolveUrl,
  strategy,
  strategyError = "",
}) {
  const [lightboxProxyId, setLightboxProxyId] = useState(null);
  const capability = policyOf(model);
  const policy = capability.policy || "unknown";
  const routeCapability = model?.capabilities?.reference_route || {};
  const routeWantsProxy = Boolean(routeCapability.show_motion_proxy_controls);
  const boundProxyIds = new Set(
    (plan?.video_reference_bindings || [])
      .filter((item) => item.enabled && item.source_kind === "generated_proxy")
      .map((item) => item.proxy_asset_id),
  );
  const allProxies = useMemo(() => (
    [...(plan?.reference_proxy_assets || [])]
      .filter((item) => item.status === "ready" && item.identity_removed)
      .sort((left, right) => (
        new Date(right.created_at || 0).getTime()
        - new Date(left.created_at || 0).getTime()
      ))
  ), [plan?.reference_proxy_assets]);
  const proxies = allProxies.filter(
    (item) => boundProxyIds.has(item.id) && proxyUsable(item),
  );
  const imageProxy = proxies.find((item) => item.media_type === "image");
  const videoProxy = proxies.find((item) => item.media_type === "video");
  const firstImageSource = referenceFrames.find((item) => item.candidate);
  const availableProxyKinds = new Set(
    proxyEngineCapabilities
      .filter((item) => item.available && item.production_ready)
      .flatMap((item) => item.kinds || []),
  );
  const imageProxyEngineReady = availableProxyKinds.has("pose_proxy_image");
  const videoProxyEngineReady = availableProxyKinds.has("motion_proxy_video");
  const wholeBodyEngine = proxyEngineCapabilities.find(
    (item) => item.engine === "dwpose_wholebody_mannequin",
  );
  const installationActive = ["queued", "running"].includes(
    proxyEngineInstallJob?.status,
  );
  const installationProgress = Number(proxyEngineInstallJob?.progress_percent || 0);
  const imageProxyCount = allProxies.filter((item) => item.media_type === "image").length;
  const videoProxyCount = allProxies.filter((item) => item.media_type === "video").length;
  const identityReady = policy === "managed_required"
    ? Boolean(managedAssetBinding)
    : Boolean(firstImageSource?.candidate);
  const lightboxItems = allProxies
    .filter((item) => item.media_type === "image")
    .map((item, index) => ({
      id: item.id,
      src: proxyUrl(resolveUrl, plan?.id, item.id, { version: item.sha256 }),
      title: `图片白模 ${index + 1}`,
      meta: [proxyCreatedAt(item.created_at), item.engine].filter(Boolean).join(" · "),
      alt: "去除人物身份后的图片白模",
    }));

  if (policy !== "managed_required" && !routeWantsProxy) {
    return (
      <section className="video-reference-strategy raw" aria-label="人物参考策略">
        <span className="video-reference-strategy-icon"><ShieldCheck size={20} /></span>
        <div className="video-reference-strategy-copy">
          <strong>人物与动作来源 · {strategy?.route_label || routeCapability.label || "原始素材"}</strong>
          <small>
            {strategy?.description
              || `${model?.label || "当前模型"} 会直接使用已确认的目标人物画面；视频白模不会提交。`}
          </small>
          {strategy?.fallback_applied && (
            <span className="video-reference-route-badge fallback">已安全回退</span>
          )}
        </div>
        <span className={`video-reference-strategy-state${strategy?.generation_allowed === false ? " blocked" : " ready"}`}>
          {strategy?.generation_allowed === false ? "未就绪" : "可生成"}
        </span>
        {(strategy?.plan_steps?.length > 0 || strategyError) && (
          <details className="video-reference-route-details">
            <summary>查看生成输入计划</summary>
            {strategyError ? (
              <p className="video-reference-route-error">{strategyError}</p>
            ) : (
              <ul>
                {strategy.plan_steps.map((step) => (
                  <li data-status={step.status} key={`${step.kind}-${step.source}`}>
                    <strong>{step.label}</strong>
                    <span>{step.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </details>
        )}
      </section>
    );
  }

  return (
    <section className="video-reference-strategy managed" aria-label="人物参考策略">
      <span className="video-reference-strategy-icon"><PersonSimpleRun size={20} /></span>
      <div className="video-reference-strategy-copy">
        <strong>人物与动作来源 · {strategy?.route_label || routeCapability.label || "托管演员 + 无身份动作"}</strong>
        <small>
          {strategy?.description || (
            policy === "managed_required"
              ? managedAssetBinding
                ? `${managedAssetBinding.name} 是唯一身份来源；${referenceFrames.length} 张原始人物关键帧不会提交给 Seedance。`
                : "Seedance 不接收原始真人身份素材；生成前必须绑定 Provider 托管演员。"
              : "目标人物参考图提供身份；白模只提供动作、姿态、位置和镜头运动。"
          )}
        </small>
        <div className="video-reference-route-badges">
          <span className="video-reference-route-badge">
            {strategy?.motion_semantics === "structural_control"
              ? "结构控制"
              : strategy?.motion_semantics === "guided_reference"
                ? "动作参考"
                : "提示词引导"}
          </span>
          {strategy?.fallback_applied && (
            <span className="video-reference-route-badge fallback">已回退 · 动作还原较弱</span>
          )}
          {routeCapability.support_level === "experimental" && (
            <span className="video-reference-route-badge experimental">实验能力</span>
          )}
        </div>
        {(imageProxy || videoProxy) && (
          <div className="video-reference-proxy-chips">
            {imageProxy && (
              <span>
                <ImageSquare size={14} />图片白模已启用
                <button
                  aria-label="停用图片白模"
                  disabled={busy}
                  onClick={() => onDisableProxy?.(imageProxy.id)}
                  title="停用但保留历史白模资产"
                  type="button"
                >
                  <X size={12} />
                </button>
              </span>
            )}
            {videoProxy && (
              <span>
                <VideoCamera size={14} />视频白模已启用
                <button
                  aria-label="停用视频白模"
                  disabled={busy}
                  onClick={() => onDisableProxy?.(videoProxy.id)}
                  title="停用但保留历史白模资产"
                  type="button"
                >
                  <X size={12} />
                </button>
              </span>
            )}
          </div>
        )}
      </div>
      <div className="video-reference-strategy-actions">
        {policy === "managed_required" && (
          <button className="secondary-button compact" disabled={busy} onClick={onOpenManagedAssets} type="button">
            <IdentificationCard size={16} />{managedAssetBinding ? "更换演员" : "绑定演员"}
          </button>
        )}
        {identityReady
          && capability.supports_pose_proxy_image
          && firstImageSource
          && !imageProxy
          && imageProxyEngineReady && (
          <button
            className="secondary-button compact"
            disabled={busy}
            onClick={() => onCreateImageProxy?.({
              sourceCandidateId: firstImageSource.candidate.id,
              visualBeatId: firstImageSource.beat.id,
            })}
            type="button"
          >
            <ImageSquare size={16} />生成图片白模
          </button>
        )}
        {identityReady
          && capability.supports_motion_proxy_video
          && !videoProxy
          && videoProxyEngineReady && (
          <button
            className="secondary-button compact"
            disabled={busy}
            onClick={() => onCreateVideoProxy?.({
              visualBeatId: plan?.visual_beats?.[0]?.id,
            })}
            type="button"
          >
            <VideoCamera size={16} />生成原视频白模
          </button>
        )}
      </div>
      {identityReady
        && capability.supports_pose_proxy_image
        && !imageProxyEngineReady
        && !videoProxyEngineReady && (
        <span className="video-reference-strategy-state setup">
          <WarningCircle size={14} />白模引擎未就绪
        </span>
      )}
      {wholeBodyEngine && !wholeBodyEngine.available && (
        <div className="video-reference-proxy-setup">
          <button
            className="secondary-button compact"
            disabled={busy}
            onClick={() => onInstallProxyEngine?.(wholeBodyEngine.engine)}
            type="button"
          >
            {installationActive ? "正在安装 DWPose WholeBody" : "安装 DWPose WholeBody（约 351 MB）"}
          </button>
          {installationActive ? (
            <div className="video-reference-install-progress" role="status">
              <div>
                <span>{proxyEngineInstallJob.message || "正在下载模型"}</span>
                <output>{installationProgress}%</output>
              </div>
              <progress
                aria-label="DWPose WholeBody 安装进度"
                max="100"
                value={installationProgress}
              />
              <small>
                {[installBytes(proxyEngineInstallJob.downloaded_bytes), installBytes(proxyEngineInstallJob.total_bytes)]
                  .filter(Boolean)
                  .join(" / ")}
              </small>
            </div>
          ) : (
            <small>{proxyEngineInstallError || wholeBodyEngine.availability_note}</small>
          )}
        </div>
      )}
      {!wholeBodyEngine && (
        <div className="video-reference-proxy-setup" role="status">
          <button
            className="secondary-button compact"
            disabled={busy}
            onClick={onRefreshProxyEngines}
            type="button"
          >
            重新检测 DWPose WholeBody
          </button>
          <small>
            {proxyEngineLoadError || "当前 API 未提供 DWPose 能力；请重启服务后重新检测。"}
          </small>
        </div>
      )}
      {strategy?.generation_allowed === false && (
        <span className="video-reference-strategy-state blocked">
          <WarningCircle size={14} weight="fill" />{strategy.blocker_message || "未就绪"}
        </span>
      )}
      {(strategy?.plan_steps?.length > 0 || strategyError) && (
        <details className="video-reference-route-details">
          <summary>生成依据与中间过程</summary>
          {strategyError ? (
            <p className="video-reference-route-error">{strategyError}</p>
          ) : (
            <ul>
              {strategy.plan_steps.map((step) => (
                <li data-status={step.status} key={`${step.kind}-${step.source}`}>
                  <strong>{step.label}</strong>
                  <span>{step.detail}</span>
                </li>
              ))}
            </ul>
          )}
          {(strategy?.warnings || []).map((warning) => (
            <p className="video-reference-route-warning" key={warning}>{warning}</p>
          ))}
        </details>
      )}
      {allProxies.length > 0 && (
        <details className="video-reference-proxy-preview">
          <summary>
            <span>
              <strong>白模预览</strong>
              <small>图片 {imageProxyCount} · 视频 {videoProxyCount}</small>
            </span>
            <span className="video-reference-proxy-preview-hint">历史白模可重新启用</span>
          </summary>
          <div className="video-reference-proxy-gallery">
            {allProxies.map((proxy) => {
              const usable = proxyUsable(proxy);
              const bound = boundProxyIds.has(proxy.id);
              const enabled = bound && usable;
              const invalidBinding = bound && !usable;
              const image = proxy.media_type === "image";
              const version = proxy.sha256 || proxy.updated_at || proxy.created_at;
              const contentUrl = proxyUrl(
                resolveUrl,
                plan?.id,
                proxy.id,
                { version },
              );
              const thumbnailUrl = proxyUrl(
                resolveUrl,
                plan?.id,
                proxy.id,
                { thumbnail: true, version },
              );
              return (
                <article
                  className={`video-reference-proxy-card${enabled ? " selected" : ""}${invalidBinding ? " invalid-binding" : ""}`}
                  key={proxy.id}
                >
                  <div className="video-reference-proxy-media">
                    {image ? (
                      <button
                        aria-label="放大查看图片白模"
                        onClick={() => setLightboxProxyId(proxy.id)}
                        type="button"
                      >
                        <img alt="图片白模预览" loading="lazy" src={thumbnailUrl} />
                        <span><ArrowsOutSimple size={16} />放大</span>
                      </button>
                    ) : (
                      <video
                        controls
                        playsInline
                        poster={thumbnailUrl}
                        preload="metadata"
                        src={contentUrl}
                      >
                        当前浏览器无法播放视频白模。
                      </video>
                    )}
                    {enabled && (
                      <span className="video-reference-proxy-active">
                        <CheckCircle size={14} weight="fill" />当前启用
                      </span>
                    )}
                    {invalidBinding && (
                      <span className="video-reference-proxy-active invalid">
                        <WarningCircle size={14} weight="fill" />旧绑定不可提交
                      </span>
                    )}
                  </div>
                  <footer>
                    <div>
                      <strong>{image ? "图片白模" : "视频白模"}</strong>
                      <small>
                        {[
                          proxyCreatedAt(proxy.created_at),
                          proxy.identity_removed ? "身份已去除" : "身份未验证",
                          proxyQualityLabel(proxy),
                          proxyQualityScore(proxy),
                          proxy.engine,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </div>
                    <div className="video-reference-proxy-actions">
                      <a
                        aria-label={`下载${image ? "图片" : "视频"}白模`}
                        href={proxyUrl(
                          resolveUrl,
                          plan?.id,
                          proxy.id,
                          { download: true, version },
                        )}
                        title="下载白模"
                      >
                        <DownloadSimple size={17} />
                      </a>
                      <button
                        disabled={busy || (!bound && !usable)}
                        onClick={() => (
                          bound
                            ? onDisableProxy?.(proxy.id)
                            : onEnableProxy?.(proxy.id)
                        )}
                        title={!usable ? "姿态质量未通过，只能预览或下载" : undefined}
                        type="button"
                      >
                        {bound
                          ? (usable ? "停用" : "解除旧绑定")
                          : (usable ? "启用" : "不可启用")}
                      </button>
                      {!bound && (
                        <button
                          aria-label={`删除${image ? "图片" : "视频"}白模`}
                          className="danger"
                          disabled={busy}
                          onClick={async () => {
                            const deleted = await onDeleteProxy?.(proxy.id);
                            if (deleted && lightboxProxyId === proxy.id) {
                              setLightboxProxyId(null);
                            }
                          }}
                          title="永久删除白模及其本地文件"
                          type="button"
                        >
                          <Trash size={17} />
                        </button>
                      )}
                    </div>
                  </footer>
                </article>
              );
            })}
          </div>
        </details>
      )}
      <MediaLightbox
        activeId={lightboxProxyId}
        items={lightboxItems}
        onActiveChange={setLightboxProxyId}
        onClose={() => setLightboxProxyId(null)}
      />
    </section>
  );
}
