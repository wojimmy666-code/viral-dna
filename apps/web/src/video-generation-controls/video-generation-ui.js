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

export function videoModelCapabilitySummary(model, providers = []) {
  const resolutions = model?.capabilities?.supported_resolutions || [];
  const resolutionLabel = resolutions.length > 0
    ? resolutions.join(" / ")
    : "分辨率待确认";
  return [
    videoProviderLabel(model, providers),
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
