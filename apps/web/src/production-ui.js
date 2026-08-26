export const PRODUCTION_STEPS = Object.freeze([
  { id: "project_setup", label: "创作方案", description: "画幅、尺寸和预算" },
  { id: "reference_assets", label: "参考资产（可选）", description: "可跳过 · 人物、产品和场景" },
  { id: "shot_images", label: "分镜图片", description: "逐镜头生成和审核" },
  { id: "shot_videos", label: "分段视频", description: "图片转视频" },
  { id: "editing", label: "视频剪辑", description: "裁剪、轨道和字幕" },
  { id: "export", label: "导出成片", description: "高清渲染和归档" },
]);

const SHOT_IMAGE_STEP_INDEX = PRODUCTION_STEPS.findIndex(
  (step) => step.id === "shot_images",
);

export function productionUnlockedStepIndex(activeStep) {
  const activeIndex = PRODUCTION_STEPS.findIndex((step) => step.id === activeStep);
  return Math.max(SHOT_IMAGE_STEP_INDEX, activeIndex);
}

export function referenceAssetsContinueLabel(referenceCount) {
  return Number(referenceCount || 0) > 0
    ? "继续到分镜图片"
    : "跳过，进入分镜图片";
}

export const REFERENCE_TYPE_OPTIONS = Object.freeze([
  { id: "person", label: "人物" },
  { id: "product", label: "产品" },
  { id: "wardrobe", label: "服装" },
  { id: "scene", label: "场景" },
  { id: "prop", label: "道具" },
  { id: "style", label: "风格" },
]);

export const PRODUCTION_CHANGE_LABELS = Object.freeze({
  project_created: "创建方案",
  project_settings_changed: "更新方案设置",
  reference_changed: "更新参考资产",
  shot_plan_changed: "更新分镜计划",
  shot_structure_changed: "调整分镜结构",
  source_keyframe_changed: "更换分镜关键帧",
  image_candidate_selected: "选择图片候选",
  image_candidates_archived: "删除图片候选",
  image_candidates_restored: "恢复图片候选",
  image_approved: "确认分镜图片",
  image_approval_revoked: "取消采用分镜图片",
  image_rejected: "退回图片候选",
  video_candidates_created: "生成视频候选",
  video_candidates_archived: "视频候选移入回收站",
  video_candidates_restored: "恢复视频候选",
  video_candidate_selected: "选择视频候选",
  video_approved: "确认分镜视频",
  video_approval_revoked: "取消采用分镜视频",
  video_rejected: "退回视频候选",
  video_preparation_changed: "更新视频剪辑准备",
  analysis_prompts_synced: "同步分析提示词",
  workflow_advanced: "推进工作流",
  branch_created: "创建版本分支",
});

export const REFERENCE_ROLE_OPTIONS = Object.freeze([
  { id: "identity", label: "人物身份" },
  { id: "product", label: "产品" },
  { id: "scene", label: "场景" },
  { id: "wardrobe", label: "服装" },
  { id: "style", label: "风格" },
  { id: "layout", label: "构图" },
]);

const IMAGE_REFERENCE_ROLE_ORDER = Object.freeze({
  identity: 0,
  product: 1,
  wardrobe: 2,
  scene: 3,
  style: 4,
  layout: 5,
});

export function imageIdentityPolicy(referenceBindings = [], assets = []) {
  const assetsById = new Map((assets || []).map((asset) => [asset.id, asset]));
  const identityBindings = (referenceBindings || []).filter(
    (binding) => binding.role === "identity",
  );
  const primaryBinding = identityBindings.length === 1 ? identityBindings[0] : null;
  const primaryAsset = primaryBinding
    ? assetsById.get(primaryBinding.reference_asset_id) || null
    : null;
  let blocker = "";
  if (identityBindings.length > 1) {
    blocker = "每个分镜只能指定一个人物身份资产";
  } else if (primaryBinding && !primaryAsset) {
    blocker = "人物身份资产不存在或已不可用";
  } else if (primaryAsset && primaryAsset.type !== "person") {
    blocker = "人物身份来源必须使用人物类型资产";
  }
  return {
    enabled: identityBindings.length > 0,
    valid: !blocker,
    blocker,
    identityCount: identityBindings.length,
    primaryBinding,
    primaryAsset,
  };
}

export function imageGenerationInputManifest({
  inputMode = "keyframe_edit",
  sourceUrl = "",
  referenceBindings = [],
  assets = [],
} = {}) {
  if (inputMode === "text_to_image") return [];
  const assetsById = new Map((assets || []).map((asset) => [asset.id, asset]));
  const references = [...(referenceBindings || [])]
    .sort((left, right) => (
      (IMAGE_REFERENCE_ROLE_ORDER[left.role] ?? 99)
      - (IMAGE_REFERENCE_ROLE_ORDER[right.role] ?? 99)
      || Number(right.weight || 0) - Number(left.weight || 0)
    ));
  const manifest = sourceUrl ? [{
    input_index: 1,
    kind: "source_keyframe",
    label: "原视频关键帧",
    responsibility: "composition_pose_action_camera",
    identity_source: false,
    thumbnail_url: sourceUrl,
  }] : [];
  const startIndex = sourceUrl ? 2 : 1;
  references.forEach((binding, offset) => {
    const asset = assetsById.get(binding.reference_asset_id);
    manifest.push({
      input_index: startIndex + offset,
      kind: "reference_asset",
      asset_id: binding.reference_asset_id,
      label: asset?.name || "参考资产",
      role: binding.role,
      responsibility: binding.role === "identity"
        ? "exclusive_person_identity_source"
        : `${binding.role}_reference`,
      identity_source: binding.role === "identity",
      thumbnail_url: asset?.thumbnail_url || asset?.content_url || "",
    });
  });
  return manifest;
}

export function workflowStatusLabel(value) {
  return {
    draft: "待配置",
    ready: "可生成",
    generating: "生成中",
    review_required: "待确认",
    approved: "已确认",
    stale: "已过期",
    failed: "失败",
  }[value] || "待配置";
}

export function workflowStatusClass(value) {
  if (value === "approved") return "positive";
  if (value === "review_required") return "review";
  if (value === "stale" || value === "failed") return "warning";
  return "neutral";
}

export function videoCandidatePlaybackUrl(candidate, enhancementPreview) {
  if (!candidate) return "";
  if (
    enhancementPreview?.candidateId === candidate.id
    && enhancementPreview.url
  ) {
    return enhancementPreview.url;
  }
  return candidate.content_url || "";
}

export function duplicateVisualBeatSourceIds(beats = []) {
  const firstByFingerprint = new Map();
  const duplicates = new Set();
  for (const beat of beats) {
    if (beat?.source_frame_warning === "duplicate_frame") duplicates.add(beat.id);
    const fingerprint = beat?.source_frame_sha256 || beat?.source_frame_url || "";
    if (!fingerprint) continue;
    const firstId = firstByFingerprint.get(fingerprint);
    if (firstId) {
      duplicates.add(firstId);
      duplicates.add(beat.id);
    } else {
      firstByFingerprint.set(fingerprint, beat.id);
    }
  }
  return [...duplicates];
}

export function normalizedImageCandidateCount(settings) {
  const value = Number(settings?.default_candidate_count ?? 1);
  if (!Number.isFinite(value)) return 1;
  return Math.min(4, Math.max(1, Math.trunc(value)));
}

export function imageGenerationModeLabel(settings) {
  if (!settings?.enabled) return "未配置生图模型";
  if (settings.execution_mode === "source_frame") return "源视频关键帧";
  if (settings.execution_mode === "simulated") return "模拟占位图（非 AI）";
  return settings.execution_mode === "local_tool" ? "本机工具" : "国内大模型 API";
}

export function isAiImageGenerationRun(run) {
  return Boolean(
    run
    && run.provider !== "simulated"
    && ["remote_api", "local_tool"].includes(run.execution_mode),
  );
}

export function isVideoGenerationRun(run) {
  return run?.kind === "video";
}

export function latestRunByKind(runs, kind) {
  return (runs || []).find((run) => run?.kind === kind) || null;
}

export function videoGenerationRunLabel(run) {
  if (!run) return "尚未生成";
  if (run.execution_mode === "simulated" || run.provider === "simulated") {
    return "流程模拟视频（非 AI）";
  }
  if (run.execution_mode === "remote_api") {
    const provider = {
      bailian: "百炼",
      volc_ark: "火山方舟",
      minimax: "MiniMax",
    }[run.provider] || run.provider || "国内 API";
    return `${provider} · ${run.model_display_name || run.model_alias || run.model || "视频模型"}`;
  }
  return run.provider || "视频生成任务";
}

const VIDEO_FAILURE_PRESENTATIONS = Object.freeze({
  video_provider_inference_limit: {
    category: "inference_limit",
    title: "视频模型已暂停生成",
    message: "该模型已达到 Provider 设置的推理上限。请调整模型额度后再试，或切换其他视频模型。",
    action: "open_model_settings",
    retryable: false,
  },
  video_provider_balance_insufficient: {
    category: "balance",
    title: "Provider 余额或配额不足",
    message: "请充值对应 Provider 账户，或切换其他已配置的视频模型。",
    action: "open_model_settings",
    retryable: false,
  },
  video_provider_auth_invalid: {
    category: "authentication",
    title: "视频模型认证失败",
    message: "当前 API Key 无效、已失效或与所选区域不匹配。请重新配置并校验。",
    action: "open_model_settings",
    retryable: false,
  },
  video_provider_rate_limited: {
    category: "rate_limit",
    title: "Provider 请求过于频繁",
    message: "Provider 暂时限制了请求频率。请稍后重试。",
    action: "retry",
    retryable: true,
  },
  video_provider_task_timeout: {
    category: "timeout",
    title: "等待视频生成结果超时",
    message: "上游任务可能仍在运行。稍后重试查询不会重新提交，也不会重复计费。",
    action: "retry",
    retryable: true,
  },
  video_provider_content_rejected: {
    category: "content_policy",
    title: "提示词或参考画面未通过审核",
    message: "请调整可能涉及敏感内容的提示词或参考图片后重新生成。",
    action: "edit_prompt",
    retryable: false,
  },
});

function legacyVideoFailureCode(run, task) {
  const code = String(run?.error_code || task?.error_code || "");
  const message = String(
    run?.error_technical_message
    || task?.error_technical_message
    || run?.error_message
    || task?.error_message
    || "",
  );
  const evidence = `${code} ${message}`.toLowerCase();
  if (evidence.includes("setlimitexceeded") || evidence.includes("safe experience mode")) {
    return "video_provider_inference_limit";
  }
  if (/insufficient balance|accountoverdue|arrearage|quotaexhausted/.test(evidence)) {
    return "video_provider_balance_insufficient";
  }
  if (/invalid api key|unauthorized|authentication/.test(evidence)) {
    return "video_provider_auth_invalid";
  }
  if (/rate.?limit|too many requests/.test(evidence)) {
    return "video_provider_rate_limited";
  }
  if (/timeout|超时/.test(evidence)) return "video_provider_task_timeout";
  return code;
}

export function videoGenerationFailureDetails(run) {
  if (!run || !["failed", "blocked"].includes(run.status)) return null;
  const task = (run.provider_tasks || []).find(
    (item) => item.error_code || item.error_message || item.error_technical_message,
  ) || null;
  const code = legacyVideoFailureCode(run, task) || "video_provider_request_failed";
  const sourceCode = String(run.error_code || task?.error_code || "");
  const mappedLegacyFailure = Boolean(sourceCode && sourceCode !== code);
  const fallback = VIDEO_FAILURE_PRESENTATIONS[code] || {
    category: "unknown",
    title: "视频生成未完成",
    message: "Provider 没有完成本次生成。请查看技术详情，调整设置后再试。",
    action: "inspect_details",
    retryable: false,
  };
  const modelLabel = run.model_display_name || run.model_alias || run.model || "视频模型";
  const category = run.error_category || task?.error_category || fallback.category;
  const title = category === "inference_limit"
    ? `${modelLabel} 已暂停生成`
    : run.error_title || task?.error_title || fallback.title;
  return {
    code,
    category,
    title,
    message: mappedLegacyFailure
      ? fallback.message
      : run.error_message || task?.error_message || fallback.message,
    action: run.error_action || task?.error_action || fallback.action,
    retryable: Boolean(
      run.error_retryable
      || task?.retryable
      || fallback.retryable,
    ),
    providerCode: run.provider_error_code
      || task?.provider_error_code
      || (String(task?.error_code || "").startsWith("video_") ? "" : task?.error_code)
      || "",
    providerRequestId: run.provider_request_id || task?.provider_task_id || "",
    provider: run.provider || task?.provider || "",
    modelLabel,
    technicalMessage: run.error_technical_message || task?.error_technical_message || "",
    occurredAt: run.completed_at || run.updated_at || task?.completed_at || "",
  };
}

export function videoGenerationDiagnosticText(details) {
  if (!details) return "";
  return [
    `错误：${details.title}`,
    `错误码：${details.code}`,
    details.providerCode ? `Provider 错误码：${details.providerCode}` : "",
    details.provider ? `Provider：${details.provider}` : "",
    details.modelLabel ? `模型：${details.modelLabel}` : "",
    details.providerRequestId ? `任务编号：${details.providerRequestId}` : "",
    details.occurredAt ? `发生时间：${details.occurredAt}` : "",
    details.technicalMessage ? `技术信息：${details.technicalMessage}` : "",
  ].filter(Boolean).join("\n");
}

const FALLBACK_VIDEO_DURATIONS = Object.freeze(
  Array.from({ length: 13 }, (_, index) => index + 3),
);

function normalizedDurationNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function roundedDuration(value) {
  return Number(Number(value).toFixed(6));
}

export function preferredVideoResolution(model, currentResolution = "720P") {
  const capabilities = model?.capabilities || model || {};
  const supported = capabilities.supported_resolutions || [];
  const current = String(currentResolution || "").trim().toUpperCase();
  if (supported.includes(current)) return current;
  const declaredDefault = String(
    capabilities.default_resolution || "",
  ).trim().toUpperCase();
  if (supported.includes(declaredDefault)) return declaredDefault;
  if (supported.includes("720P")) return "720P";
  return supported[0] || current || "720P";
}

export function videoDurationOptions(model) {
  const capabilities = model?.capabilities || model || {};
  const supported = [...new Set(
    (capabilities.supported_durations || [])
      .map(normalizedDurationNumber)
      .filter(Boolean)
      .map(roundedDuration),
  )].sort((left, right) => left - right);
  if (supported.length > 0) return supported;

  const minimum = normalizedDurationNumber(
    capabilities.minimum_duration_seconds,
  );
  const maximum = normalizedDurationNumber(
    capabilities.maximum_duration_seconds,
  );
  const step = normalizedDurationNumber(
    capabilities.duration_step_seconds,
  ) || 1;
  if (minimum == null || maximum == null || maximum < minimum) {
    return [...FALLBACK_VIDEO_DURATIONS];
  }

  const values = [];
  const maximumStops = 600;
  for (
    let index = 0;
    index < maximumStops && minimum + index * step <= maximum + 0.000001;
    index += 1
  ) {
    values.push(roundedDuration(minimum + index * step));
  }
  return values.length > 0 ? values : [...FALLBACK_VIDEO_DURATIONS];
}

export function normalizeVideoDuration(value, model) {
  const options = videoDurationOptions(model);
  const capabilities = model?.capabilities || model || {};
  const requested = normalizedDurationNumber(value)
    ?? normalizedDurationNumber(capabilities.default_duration_seconds)
    ?? options[0];
  return options.reduce((closest, candidate) => {
    const candidateDistance = Math.abs(candidate - requested);
    const closestDistance = Math.abs(closest - requested);
    if (candidateDistance < closestDistance) return candidate;
    if (candidateDistance === closestDistance && candidate > closest) return candidate;
    return closest;
  }, options[0]);
}

export function formatVideoDuration(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number)
    ? String(number)
    : String(roundedDuration(number));
}

export function videoDurationConstraintLabel(model) {
  const capabilities = model?.capabilities || model || {};
  const options = videoDurationOptions(model);
  const explicitDurations = (capabilities.supported_durations || []).length > 0;
  const differences = options.slice(1).map((item, index) => (
    roundedDuration(item - options[index])
  ));
  const uniformStep = differences.length > 0
    && differences.every((item) => item === differences[0]);
  const isSparse = explicitDurations
    && (options.length <= 5 || !uniformStep || differences[0] > 1);
  if (isSparse) {
    return `仅支持 ${options.map(formatVideoDuration).join("、")} 秒`;
  }
  if (options.length === 1) return `固定 ${formatVideoDuration(options[0])} 秒`;
  const step = differences[0]
    || normalizedDurationNumber(capabilities.duration_step_seconds)
    || 1;
  return (
    `支持 ${formatVideoDuration(options[0])}–${formatVideoDuration(options.at(-1))} 秒`
    + `，按 ${formatVideoDuration(step)} 秒调整`
  );
}

export function imageGenerationIntentForShot(shotDetail) {
  const hasPriorAiCandidate = (shotDetail?.generation_runs || []).some(
    (run) => isAiImageGenerationRun(run) && (run.candidates || []).length > 0,
  );
  return hasPriorAiCandidate ? "new_variation" : "standard";
}

export function imageGenerationRunLabel(run) {
  if (!run) return "未生成";
  if (run.provider === "simulated" || run.execution_mode === "simulated") {
    return "模拟占位图（非 AI）";
  }
  if (run.execution_mode === "source_frame") return "源视频关键帧";
  return run.execution_mode === "local_tool" ? "本机工具" : "国内大模型 API";
}

export function resolveImageExecutionMode(settings, selection = "default") {
  if (!settings?.enabled) return null;
  if (selection === "remote_api" || selection === "local_tool") return selection;
  return settings.execution_mode === "local_tool" ? "local_tool" : "remote_api";
}

export function isImageEngineConfigured(settings, executionMode) {
  if (!settings?.enabled) return false;
  if (executionMode === "remote_api") return Boolean(settings.api_key_configured);
  if (executionMode === "local_tool") {
    return Boolean(settings.local_executable_path && settings.local_tool_id);
  }
  return false;
}

export function isRecoverableImageGenerationRun(run) {
  return Boolean(
    run?.recovery_available
    && Number(run?.recovery_candidate_count || 0) > 0,
  );
}

export function generationFailureGuidance(run) {
  const code = String(run?.error_code || "");
  const message = String(run?.error_message || "");
  if (isRecoverableImageGenerationRun(run)) {
    return "图片已经生成，只是尚未导入当前任务。点击“恢复图片”即可继续，不会再次消耗生成额度。";
  }
  if (code === "codex_windows_sandbox_setup_failed") {
    return (
      "Codex Windows 沙箱未能启动。请到“模型与设置 → Windows 沙箱”执行无费用预检；"
      + "若自动/增强模式仍失败，请手动选择兼容模式（unelevated）后再生成。"
    );
  }
  if (
    code === "local_tool_timeout"
    || /执行超过|timed?\s*out/i.test(message)
  ) {
    return "本机工具执行超时。确认网络稳定后可以直接重试，必要时提高本机工具超时。";
  }
  if (
    code === "local_tool_failed"
    && /chatgpt\.com|websocket|不知道这样的主机|dns|name resolution/i.test(message)
  ) {
    return "Codex 未能连接 ChatGPT。请先到“模型与设置”检查命令行代理并运行网络测试，然后重试。";
  }
  if (code === "text_to_image_unsupported") {
    return "当前引擎不支持纯文生图，请改用图生图或选择支持文生图的引擎。";
  }
  if (code.startsWith("local_tool")) {
    return "本机工具没有完成生成。请检查模型与设置中的工具、代理和登录状态后重试。";
  }
  return "修正模型配置或提示词后可以直接重试，本次失败不会产生可确认候选。";
}

export function estimateImageGenerationCostMicros(
  settings,
  candidateCount = normalizedImageCandidateCount(settings),
) {
  if (!settings?.enabled) return 0;
  const count = Math.min(4, Math.max(1, Math.trunc(Number(candidateCount) || 1)));
  if (settings.execution_mode === "local_tool") {
    if (settings.local_cost_source === "unmetered") return 0;
    if (
      settings.local_cost_source === "configured_rate"
      && Number.isFinite(Number(settings.local_unit_cost_micros))
    ) {
      return Math.max(0, Math.trunc(Number(settings.local_unit_cost_micros))) * count;
    }
    return null;
  }
  const selected = (settings.models || []).find(
    (item) => item.alias === settings.remote_model_alias,
  );
  if (!selected || !Number.isFinite(Number(selected.unit_cost_micros))) return null;
  return Math.max(0, Math.trunc(Number(selected.unit_cost_micros))) * count;
}

export function imageQualityLabel(report) {
  if (!report?.status) return "未自动质检 · 请人工核对";
  const semanticStatus = report.semantic_quality?.status;
  if (semanticStatus === "warning") return "VLM 发现语义风险 · 请人工核对";
  if (semanticStatus === "uncertain") return "VLM 证据不足 · 请人工核对";
  if (semanticStatus === "passed" && report.status === "warning") {
    return "尺寸有提示 · VLM 未发现明显语义问题 · 请人工核对";
  }
  if (semanticStatus === "passed") {
    return "VLM 未发现明显语义问题 · 请人工核对";
  }
  if (report.status === "warning") return "尺寸有提示 · 请人工核对";
  if (report.status === "manual_review_required") return "基础质检通过 · 请人工核对";
  if (report.status === "passed") return "自动质检通过";
  return "请人工核对";
}

export function constraintsFromText(value) {
  return [...new Set(String(value || "").split(/[\n，]/).map((item) => item.trim()).filter(Boolean))].slice(0, 40);
}

const RATIO_DIMENSIONS = Object.freeze({
  "9:16": { width: 1080, height: 1920 },
  "16:9": { width: 1920, height: 1080 },
  "1:1": { width: 1080, height: 1080 },
  "4:5": { width: 1080, height: 1350 },
});

const PRODUCTION_ASPECT_RATIOS = Object.freeze(Object.keys(RATIO_DIMENSIONS));

function positiveDimension(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function parseRatio(value) {
  const match = String(value || "").match(
    /^\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*$/,
  );
  if (!match) return null;
  const width = positiveDimension(match[1]);
  const height = positiveDimension(match[2]);
  return width && height ? { width, height } : null;
}

function ratioOrientation(value) {
  if (Math.abs(1 - value) <= 0.06) return "square";
  return value > 1 ? "landscape" : "portrait";
}

export function closestProductionAspectRatio({ width, height, aspectRatio } = {}) {
  const parsed = parseRatio(aspectRatio);
  const sourceWidth = positiveDimension(width) || parsed?.width;
  const sourceHeight = positiveDimension(height) || parsed?.height;
  if (!sourceWidth || !sourceHeight) return "9:16";

  const sourceRatio = sourceWidth / sourceHeight;
  const sourceOrientation = ratioOrientation(sourceRatio);
  return PRODUCTION_ASPECT_RATIOS
    .map((ratio, index) => {
      const dimensions = RATIO_DIMENSIONS[ratio];
      const candidateRatio = dimensions.width / dimensions.height;
      return {
        ratio,
        index,
        distance: Math.round(Math.abs(Math.log(sourceRatio / candidateRatio)) * 1e12),
        orientationMismatch: ratioOrientation(candidateRatio) === sourceOrientation ? 0 : 1,
      };
    })
    .sort((left, right) => (
      left.distance - right.distance
      || left.orientationMismatch - right.orientationMismatch
      || left.index - right.index
    ))[0].ratio;
}

export function productionDefaultsForSource(source = {}) {
  const outputAspectRatio = closestProductionAspectRatio(source);
  const dimensions = dimensionsForRatio(outputAspectRatio);
  return {
    outputAspectRatio,
    outputWidth: dimensions.width,
    outputHeight: dimensions.height,
  };
}

export function productionPreviewLayout(project = {}) {
  const parsed = parseRatio(project.output_aspect_ratio);
  const width = positiveDimension(project.output_width) || parsed?.width || 9;
  const height = positiveDimension(project.output_height) || parsed?.height || 16;
  const ratio = width / height;
  return {
    aspectRatio: `${width} / ${height}`,
    maxWidth: ratio < 1 ? `${Math.round(640 * ratio)}px` : "100%",
    orientation: ratioOrientation(ratio),
  };
}

export function dimensionsForRatio(ratio) {
  return RATIO_DIMENSIONS[ratio] || RATIO_DIMENSIONS["9:16"];
}

export function budgetMicrosFromYuan(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const yuan = Number(text);
  if (!Number.isFinite(yuan) || yuan <= 0 || yuan > 100000) {
    throw new Error("预算上限必须大于 0 且不超过 ¥100000");
  }
  return Math.round(yuan * 1_000_000);
}

export function budgetYuanFromMicros(value) {
  if (!Number.isFinite(Number(value)) || Number(value) <= 0) return "";
  const yuan = Number(value) / 1_000_000;
  return yuan.toFixed(yuan >= 100 ? 0 : 2);
}

export function normalizeReferenceTags(value) {
  const values = Array.isArray(value) ? value : String(value || "").split(/[,，\n]/);
  return [...new Set(values.map((item) => String(item).trim()).filter(Boolean))].slice(0, 20);
}

export function referenceTypeLabel(value) {
  return REFERENCE_TYPE_OPTIONS.find((item) => item.id === value)?.label || "参考图";
}

export function productionChangeLabel(value) {
  return PRODUCTION_CHANGE_LABELS[value] || "方案更新";
}

export function formatProductionDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
