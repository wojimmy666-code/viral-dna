import {
  formatVideoDuration,
  videoDurationConstraintLabel,
} from "../production-ui.js";

const PROVIDER_LABELS = Object.freeze({
  bailian: "阿里云百炼",
  minimax: "MiniMax",
  volc_ark: "火山方舟",
});

export function providerSettingForModel(model, providers = []) {
  return providers.find((item) => item.provider === model?.provider) || null;
}

export function videoProviderLabel(model, providers = []) {
  const setting = providerSettingForModel(model, providers);
  return setting?.label || PROVIDER_LABELS[model?.provider] || model?.provider || "未设置 Provider";
}

export function isVideoModelConfigured(model, providers = []) {
  return Boolean(providerSettingForModel(model, providers)?.api_key_configured);
}

export function videoModelCatalogUiState({
  error = "",
  models = [],
  providers = [],
  selectedModel = null,
  status = "ready",
} = {}) {
  const hasModels = models.length > 0;
  const loading = ["idle", "loading"].includes(status) && !hasModels;
  const refreshing = status === "loading" && hasModels;
  const failed = status === "error" && !hasModels;
  const usingCachedCatalog = status === "error" && hasModels;
  const providerReady = Boolean(
    selectedModel && isVideoModelConfigured(selectedModel, providers),
  );
  const missingProviderKey = Boolean(selectedModel && !providerReady);

  let title = selectedModel?.label || "选择视频模型";
  let subtitle = "请选择一个可用模型";
  if (loading) {
    title = "正在读取视频模型";
    subtitle = "正在同步模型目录";
  } else if (failed) {
    title = "模型目录读取失败";
    subtitle = error || "请重新加载视频模型目录";
  } else if (selectedModel) {
    const providerLabel = videoProviderLabel(selectedModel, providers);
    subtitle = providerReady
      ? providerLabel
      : `${providerLabel} · Key 未配置`;
  } else if (!hasModels) {
    subtitle = "暂无具备可用参考素材路由的模型";
  } else if (usingCachedCatalog) {
    subtitle = "目录刷新失败，可继续使用上次结果";
  }

  return {
    failed,
    hasModels,
    loading,
    missingProviderKey,
    providerReady,
    refreshing,
    shouldReload: failed || usingCachedCatalog,
    subtitle,
    title,
    usingCachedCatalog,
  };
}

export function videoModelCapabilitySummary(model, providers = []) {
  const resolutions = model?.capabilities?.supported_resolutions || [];
  const resolutionLabel = resolutions.length > 0
    ? resolutions.join(" / ")
    : "分辨率待确认";
  return [
    videoProviderLabel(model, providers),
    model?.capabilities?.reference_route?.label || "参考路由待确认",
    videoDurationConstraintLabel(model),
    resolutionLabel,
  ].join(" · ");
}

export function videoCandidateCountOptions(model) {
  const maximum = Math.min(
    4,
    Math.max(1, Math.trunc(Number(model?.capabilities?.max_candidates) || 1)),
  );
  return Array.from({ length: maximum }, (_, index) => index + 1);
}

export function videoOutputSummary({ aspectRatio, candidateCount, duration, resolution }) {
  return [
    aspectRatio || "未设置画幅",
    resolution || "未设置分辨率",
    `${formatVideoDuration(duration)}秒`,
    `${Number(candidateCount) || 1}个`,
  ].join(" · ");
}
