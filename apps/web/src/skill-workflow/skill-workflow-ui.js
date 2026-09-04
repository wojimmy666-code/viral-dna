export const SKILL_WORKFLOW_STAGES = Object.freeze([
  { id: "creative_brief", label: "创作简报", gate: "brief_approved", gateLabel: "批准简报" },
  { id: "style_confirmation", label: "风格确认", gate: "style_approved", gateLabel: "批准风格" },
  { id: "storyboard_design", label: "大纲与分镜", gate: "storyboard_approved", gateLabel: "批准分镜" },
  { id: "shot_images", label: "分镜图片", gate: "images_approved", gateLabel: "批准图片" },
  { id: "shot_videos", label: "分镜视频", gate: "videos_approved", gateLabel: "批准视频" },
  { id: "editing", label: "剪辑", gate: "picture_locked", gateLabel: "锁定画面" },
  { id: "audio_caption", label: "配乐与字幕", gate: "audio_caption_approved", gateLabel: "批准声音与字幕" },
  { id: "export", label: "导出交付", gate: "delivery_approved", gateLabel: "批准交付" },
]);

export const EXECUTION_LABELS = Object.freeze({
  pending: "等待中",
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
  blocked: "已暂停",
  skipped: "已跳过",
  stale: "需更新",
  cancelled: "已取消",
});

export const VALIDATION_LABELS = Object.freeze({
  unchecked: "未校验",
  passed: "校验通过",
  warning: "有提醒",
  failed: "校验失败",
});

export const REVIEW_LABELS = Object.freeze({
  unreviewed: "待审核",
  needs_revision: "需修改",
  approved: "已批准",
});

export function parseResolution(value, fallback = [1024, 1024]) {
  const match = String(value || "").trim().match(/^(\d{3,5})\s*[x×]\s*(\d{3,5})$/i);
  if (!match) return fallback;
  return [Number(match[1]), Number(match[2])];
}

export function resolutionForRatio(ratio, longEdge = 1024) {
  const [width, height] = String(ratio || "1:1").split(":").map(Number);
  if (!width || !height) return `${longEdge}x${longEdge}`;
  if (width >= height) {
    return `${longEdge}x${Math.max(256, Math.round((longEdge * height) / width / 8) * 8)}`;
  }
  return `${Math.max(256, Math.round((longEdge * width) / height / 8) * 8)}x${longEdge}`;
}

export function resolutionLabelShortEdge(label) {
  const normalized = String(label || "").toUpperCase();
  if (normalized === "2K") return 1440;
  if (normalized === "4K") return 2160;
  const match = normalized.match(/^(\d{3,4})P$/);
  return match ? Number(match[1]) : 0;
}

export function dimensionsForResolutionLabel(ratio, label) {
  const shortEdge = resolutionLabelShortEdge(label);
  const [widthRatio, heightRatio] = String(ratio || "").split(":").map(Number);
  if (!shortEdge || !widthRatio || !heightRatio) return "";
  if (widthRatio === heightRatio) return `${shortEdge}x${shortEdge}`;
  if (widthRatio > heightRatio) {
    return `${Math.round((shortEdge * widthRatio) / heightRatio / 8) * 8}x${shortEdge}`;
  }
  return `${shortEdge}x${Math.round((shortEdge * heightRatio) / widthRatio / 8) * 8}`;
}

export function resolutionLabelForDimensions(model, dimensions) {
  const [width, height] = parseResolution(dimensions, [0, 0]);
  const shortEdge = Math.min(width, height);
  return (model?.capabilities?.supported_resolutions || []).find(
    (item) => resolutionLabelShortEdge(item) === shortEdge,
  ) || "";
}

export function formatMicros(value) {
  const amount = Number(value || 0) / 1_000_000;
  return `¥${amount.toFixed(amount >= 10 ? 1 : 2)}`;
}

export function latestGateDecision(gates, gate) {
  return [...(gates || [])]
    .filter((item) => item.gate === gate)
    .sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)))[0] || null;
}

export function stageState(workspace, stage) {
  const runDetail = workspace?.run;
  const run = runDetail?.run;
  const stageIndex = SKILL_WORKFLOW_STAGES.findIndex((item) => item.id === stage.id);
  const currentIndex = SKILL_WORKFLOW_STAGES.findIndex((item) => item.id === run?.current_stage);
  const decision = latestGateDecision(runDetail?.gates, stage.gate);
  const step = [...(runDetail?.steps || [])]
    .filter((item) => item.stage === stage.id)
    .sort((left, right) => Number(right.attempt || 0) - Number(left.attempt || 0))[0];
  const approved = ["approve", "skip"].includes(decision?.decision);
  return {
    approved,
    current: stageIndex === currentIndex,
    complete: approved || (currentIndex > stageIndex && currentIndex >= 0),
    decision,
    execution: step?.execution_status || (approved ? "succeeded" : stageIndex === currentIndex ? "running" : "pending"),
    review: approved ? "approved" : step?.review_status || "unreviewed",
    validation: step?.validation_status || "unchecked",
    step,
  };
}

function compactStrings(values, limit = 30) {
  return [...new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean))]
    .slice(0, limit);
}

export function buildCategoryProfileCreativeInputs({
  objective,
  profile,
  skill,
  skillAnswers = {},
}) {
  const sellingPoints = compactStrings(profile?.selling_points, 16);
  const audiences = compactStrings(profile?.audiences, 12);
  const scenes = compactStrings(profile?.scenes, 16);
  const forbiddenClaims = compactStrings(profile?.forbidden_claims, 20);
  const intake = skill?.current_version?.manifest?.spec?.intake || {};
  const allowedBases = intake.creative_basis?.allowed || [];
  const recommendedBasis = intake.creative_basis?.recommended;
  const creativeBasis = allowedBases.includes("brand_led")
    ? "brand_led"
    : allowedBases.includes(recommendedBasis)
      ? recommendedBasis
      : allowedBases[0] || "brand_led";
  const primaryMessage = sellingPoints.join("；") || profile?.brief || String(objective || "").trim();
  const derivedAnswers = { ...skillAnswers };
  if ((intake.questions || []).some((question) => question.key === "primary_message")) {
    derivedAnswers.primary_message = primaryMessage;
  }
  const description = [
    profile?.brief,
    profile?.category_name && `所属品类：${profile.category_name}`,
    scenes.length && `适用场景：${scenes.join("、")}`,
    profile?.visual_style && `视觉风格：${profile.visual_style}`,
  ].filter(Boolean).join("\n").slice(0, 4000);

  return {
    audience: audiences.join("、"),
    brandDescription: description,
    brandName: profile?.brand_name || profile?.display_name || "",
    channel: skill?.supported_channels?.[0] || "internal",
    creativeBasis,
    forbiddenMessages: forbiddenClaims,
    requiredMessages: sellingPoints,
    skillAnswers: derivedAnswers,
    values: sellingPoints,
    visualIdentity: {
      source: "category_profile",
      profile_display_name: profile?.display_name || "",
      profile_revision: profile?.revision || 1,
      category_name: profile?.category_name || "",
      visual_style: profile?.visual_style || "",
      audiences,
      selling_points: sellingPoints,
      scenes,
      forbidden_claims: forbiddenClaims,
    },
  };
}

export function validateSkillStartDraft(draft, skill) {
  const issues = [];
  if (!draft.projectName?.trim()) issues.push("请填写项目名称");
  if (!draft.categoryProfileId) issues.push("请从品类库选择一份档案");
  if (!draft.objective?.trim()) issues.push("请填写创作目标");
  if (!draft.aspectRatio) issues.push("请选择画幅");
  for (const question of skill?.current_version?.manifest?.spec?.intake?.questions || []) {
    if (question.key === "primary_message") continue;
    const answer = draft.skillAnswers?.[question.key];
    if (question.required && (answer == null || answer === "" || answer.length === 0)) {
      issues.push(`请回答：${question.label}`);
    }
  }
  const range = skill?.duration_seconds;
  const duration = Number(draft.durationSeconds);
  if (!Number.isFinite(duration) || duration < Number(range?.min || 3) || duration > Number(range?.max || 600)) {
    issues.push(`成片时长需在 ${range?.min || 3}–${range?.max || 600} 秒之间`);
  }
  if (!draft.imageModel) issues.push("请主动选择图片模型");
  if (!draft.imageResolution) issues.push("请主动选择图片分辨率");
  if (!draft.videoModel) issues.push("请主动选择视频模型");
  if (!draft.videoResolution) issues.push("请主动选择视频分辨率");
  if (draft.automationMode === "full_auto" && !(Number(draft.budgetCny) > 0)) {
    issues.push("全自动模式必须设置预算上限");
  }
  return issues;
}

export function buildRunContractPayload({ draft, imageModels = [], videoModels = [] }) {
  const image = imageModels.find((item) => item.alias === draft.imageModel);
  const video = videoModels.find((item) => item.alias === draft.videoModel);
  const [imageWidth, imageHeight] = parseResolution(draft.imageResolution);
  const [videoWidth, videoHeight] = parseResolution(draft.videoResolution, [1280, 720]);
  const videoResolutionLabel = resolutionLabelForDimensions(video, draft.videoResolution);
  const videoDurations = video?.capabilities?.supported_durations?.length
    ? video.capabilities.supported_durations.map((item) => Math.round(Number(item)))
    : [Math.max(1, Math.round(Number(video?.capabilities?.default_duration_seconds || 5)))];
  const clipDuration = Math.max(1, videoDurations[0] || 5);
  const shotCount = Math.max(1, Math.ceil(Number(draft.durationSeconds || clipDuration) / clipDuration));
  const imageUnitCost = image?.unit_cost_micros == null
    ? null
    : Number(image.unit_cost_micros);
  const pricing = video?.pricing || {};
  const shortEdge = Math.min(videoWidth, videoHeight);
  const pricingResolution = pricing.rates_micros?.[draft.videoResolution] != null
    ? draft.videoResolution
    : videoResolutionLabel || `${shortEdge}P`;
  let videoUnitCost = null;
  if (pricing.kind === "per_second_by_resolution") {
    const rate = Number(pricing.rates_micros?.[pricingResolution]);
    if (Number.isFinite(rate)) videoUnitCost = rate * clipDuration;
  } else if (pricing.kind === "fixed_matrix") {
    const rate = Number(pricing.rates_micros?.[`${pricingResolution}:${clipDuration}`]);
    if (Number.isFinite(rate)) videoUnitCost = rate;
  } else {
    const rate = pricing.unit_cost_micros ?? pricing.cost_per_clip_micros;
    if (rate != null && Number.isFinite(Number(rate))) videoUnitCost = Number(rate);
  }
  const imageEstimate = Number.isFinite(imageUnitCost)
    ? Math.max(0, imageUnitCost) * (2 + shotCount * 2)
    : 0;
  const videoEstimate = Number.isFinite(videoUnitCost)
    ? Math.max(0, videoUnitCost) * shotCount
    : 0;
  const estimateKnown = image && video
    && Number.isFinite(imageUnitCost)
    && Number.isFinite(videoUnitCost);
  const estimatedCost = Math.round(imageEstimate + videoEstimate);
  return {
    image_provider_connection_id: image?.provider || "",
    image_model_id: draft.imageModel,
    image_width: imageWidth,
    image_height: imageHeight,
    video_provider_connection_id: video?.provider || "",
    video_model_id: draft.videoModel,
    video_width: videoWidth,
    video_height: videoHeight,
    video_resolution_label: videoResolutionLabel,
    video_fps: Number(draft.fps || 30),
    video_duration_capabilities_seconds: [...new Set(videoDurations.filter((item) => item > 0))],
    candidate_count_by_stage: { look_test: 2, shot_image: 2, shot_video: 1 },
    text_model_selection: draft.textModel || "workspace_default",
    audio_source_strategy: draft.generateVideoAudio ? "candidate" : "muted",
    generate_video_audio: Boolean(draft.generateVideoAudio),
    music_strategy: draft.musicStrategy || "none",
    narration_strategy: draft.narrationStrategy || "none",
    subtitle_strategy: draft.subtitleStrategy || "none",
    automation_mode: draft.automationMode || "guided",
    budget_limit_micros: Number(draft.budgetCny) > 0
      ? Math.round(Number(draft.budgetCny) * 1_000_000)
      : null,
    estimated_cost_micros: estimatedCost,
    estimate_status: estimateKnown ? "known" : "unknown",
    allow_provider_fallback: false,
    supports_exact_overlay: true,
  };
}
