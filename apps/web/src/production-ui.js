export const PRODUCTION_STEPS = Object.freeze([
  { id: "project_setup", label: "创作方案", description: "画幅、尺寸和预算" },
  { id: "reference_assets", label: "参考资产", description: "人物、产品和场景" },
  { id: "shot_images", label: "分镜图片", description: "逐镜头生成和审核" },
  { id: "shot_videos", label: "分段视频", description: "图片转视频", locked: true },
  { id: "editing", label: "剪辑合成", description: "排序、音轨和字幕", locked: true },
  { id: "export", label: "导出成片", description: "渲染和归档", locked: true },
]);

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
  image_approved: "确认分镜图片",
  image_approval_revoked: "取消采用分镜图片",
  image_rejected: "退回图片候选",
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

export const SHOT_LOCK_OPTIONS = Object.freeze([
  { id: "timing", label: "时间" },
  { id: "camera", label: "运镜" },
  { id: "composition", label: "构图" },
  { id: "action", label: "动作" },
  { id: "lighting", label: "灯光" },
  { id: "audio", label: "声音" },
]);

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

export function generationFailureGuidance(run) {
  const code = String(run?.error_code || "");
  const message = String(run?.error_message || "");
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
    return "当前引擎不支持纯文生图，请改用关键帧编辑或选择支持文生图的引擎。";
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
