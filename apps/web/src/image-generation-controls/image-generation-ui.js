export const LOCAL_IMAGE_MODEL_ALIAS = "local_tool";

export function imageModelOptions(settings = {}) {
  const remoteConfigured = Boolean(settings.api_key_configured);
  const remoteModels = (settings.models || []).map((model) => ({
    ...model,
    configured: remoteConfigured,
    executionMode: "remote_api",
    providerLabel: "阿里百炼",
  }));
  const localCapability = settings.execution_mode === "local_tool"
    ? settings.selected_capabilities
    : null;
  return [
    ...remoteModels,
    {
      alias: LOCAL_IMAGE_MODEL_ALIAS,
      provider: "local_tool",
      providerLabel: "本机工具",
      model: settings.local_model || settings.local_tool_id || "imagegen",
      label: settings.local_model || settings.local_tool_id || "本机 ImageGen",
      description: "使用当前设备中已配置的 ImageGen 工具生成图片。",
      unit_cost_micros: settings.local_unit_cost_micros,
      recommended: false,
      configured: Boolean(settings.local_executable_path),
      executionMode: "local_tool",
      capabilities: localCapability || {
        text_to_image: true,
        image_to_image: true,
        multi_reference: true,
        max_reference_images: 4,
        max_input_images: 5,
        max_candidates: 4,
      },
    },
  ];
}

export function imageModelCompatibility(model, { inputCount = 0, inputMode = "keyframe_edit" } = {}) {
  if (!model?.configured) return { compatible: false, reason: "尚未配置" };
  const capability = model.capabilities || {};
  if (inputMode === "text_to_image" && !capability.text_to_image) {
    return { compatible: false, reason: "不支持纯文生图" };
  }
  if (inputMode === "keyframe_edit" && !capability.image_to_image) {
    return { compatible: false, reason: "不支持图生图" };
  }
  const maximumInputs = Number(capability.max_input_images || 1);
  if (inputCount > maximumInputs) {
    return { compatible: false, reason: `最多接收 ${maximumInputs} 张图片` };
  }
  return { compatible: true, reason: "" };
}

export function imageGenerationSummary({ aspectRatio, candidateCount, inputMode }) {
  const mode = inputMode === "text_to_image" ? "纯文生图" : "图生图";
  return `${mode} · ${aspectRatio || "跟随方案"} · 自适应 · ${candidateCount}张`;
}

export function imageModelCapabilitySummary(model) {
  const capability = model?.capabilities || {};
  const modes = [];
  if (capability.text_to_image) modes.push("文生图");
  if (capability.image_to_image) modes.push("图生图");
  if (capability.multi_reference) modes.push("多图参考");
  return modes.length > 0 ? modes.join(" · ") : model?.description || "能力未声明";
}
