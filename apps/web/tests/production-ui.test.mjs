import assert from "node:assert/strict";
import test from "node:test";

import {
  PRODUCTION_STEPS,
  budgetMicrosFromYuan,
  budgetYuanFromMicros,
  constraintsFromText,
  dimensionsForRatio,
  estimateImageGenerationCostMicros,
  generationFailureGuidance,
  imageGenerationModeLabel,
  imageGenerationRunLabel,
  imageQualityLabel,
  isAiImageGenerationRun,
  isImageEngineConfigured,
  normalizeReferenceTags,
  normalizedImageCandidateCount,
  productionChangeLabel,
  referenceTypeLabel,
  resolveImageExecutionMode,
  workflowStatusClass,
  workflowStatusLabel,
} from "../src/production-ui.js";

test("maps supported ratios to their default output dimensions", () => {
  assert.deepEqual(dimensionsForRatio("9:16"), { width: 1080, height: 1920 });
  assert.deepEqual(dimensionsForRatio("16:9"), { width: 1920, height: 1080 });
  assert.deepEqual(dimensionsForRatio("1:1"), { width: 1080, height: 1080 });
  assert.deepEqual(dimensionsForRatio("unknown"), { width: 1080, height: 1920 });
});

test("converts production budgets between yuan and integer micros", () => {
  assert.equal(budgetMicrosFromYuan("1.25"), 1_250_000);
  assert.equal(budgetMicrosFromYuan(""), null);
  assert.equal(budgetYuanFromMicros(1_250_000), "1.25");
  assert.equal(budgetYuanFromMicros(100_000_000), "100");
  assert.equal(budgetYuanFromMicros(null), "");
});

test("rejects invalid production budgets before sending an API request", () => {
  assert.throws(() => budgetMicrosFromYuan("0"), /预算上限/);
  assert.throws(() => budgetMicrosFromYuan("-1"), /预算上限/);
  assert.throws(() => budgetMicrosFromYuan("not-a-number"), /预算上限/);
  assert.throws(() => budgetMicrosFromYuan("100001"), /预算上限/);
});

test("normalizes, deduplicates and caps reference tags", () => {
  assert.deepEqual(
    normalizeReferenceTags("人物，正面, 人物\n棚拍"),
    ["人物", "正面", "棚拍"],
  );
  assert.equal(
    normalizeReferenceTags(Array.from({ length: 25 }, (_, index) => "标签" + index)).length,
    20,
  );
});

test("exposes stable simplified-Chinese labels and locks future stages", () => {
  assert.equal(referenceTypeLabel("wardrobe"), "服装");
  assert.equal(referenceTypeLabel("unknown"), "参考图");
  assert.equal(productionChangeLabel("branch_created"), "创建版本分支");
  assert.equal(productionChangeLabel("shot_structure_changed"), "调整分镜结构");
  assert.equal(PRODUCTION_STEPS.filter((step) => step.locked).length, 3);
  assert.deepEqual(
    PRODUCTION_STEPS.slice(0, 3).map((step) => step.id),
    ["project_setup", "reference_assets", "shot_images"],
  );
});

test("normalizes shot constraints and exposes approval status labels", () => {
  assert.deepEqual(
    constraintsFromText("不要乱码\n保持人物一致，不要乱码"),
    ["不要乱码", "保持人物一致"],
  );
  assert.equal(workflowStatusLabel("review_required"), "待确认");
  assert.equal(workflowStatusLabel("stale"), "已过期");
  assert.equal(workflowStatusClass("approved"), "positive");
  assert.equal(workflowStatusClass("stale"), "warning");
});

test("normalizes image generation settings and never treats unknown cost as zero", () => {
  const remote = {
    enabled: true,
    execution_mode: "remote_api",
    default_candidate_count: 9,
    remote_model_alias: "qwen_image_2",
    models: [{ alias: "qwen_image_2", unit_cost_micros: 200_000 }],
  };
  assert.equal(normalizedImageCandidateCount(remote), 4);
  assert.equal(imageGenerationModeLabel(remote), "国内大模型 API");
  assert.equal(estimateImageGenerationCostMicros(remote), 800_000);

  const localUnknown = {
    enabled: true,
    execution_mode: "local_tool",
    default_candidate_count: 2,
    local_cost_source: "unknown",
  };
  assert.equal(imageGenerationModeLabel(localUnknown), "本机工具");
  assert.equal(estimateImageGenerationCostMicros(localUnknown), null);
  assert.equal(
    estimateImageGenerationCostMicros({
      ...localUnknown,
      local_cost_source: "subscription_quota",
    }),
    null,
  );
  assert.equal(
    estimateImageGenerationCostMicros({
      ...localUnknown,
      local_cost_source: "configured_rate",
      local_unit_cost_micros: 125_000,
    }),
    250_000,
  );
  assert.equal(estimateImageGenerationCostMicros({ enabled: false }), 0);
  assert.equal(normalizedImageCandidateCount({}), 1);
});

test("resolves per-run image engines without changing the global default", () => {
  const settings = {
    enabled: true,
    execution_mode: "local_tool",
    api_key_configured: true,
    local_executable_path: "C:/tools/imagegen.exe",
    local_tool_id: "openai-codex-imagegen",
  };
  assert.equal(resolveImageExecutionMode(settings, "default"), "local_tool");
  assert.equal(resolveImageExecutionMode(settings, "remote_api"), "remote_api");
  assert.equal(resolveImageExecutionMode(settings, "local_tool"), "local_tool");
  assert.equal(resolveImageExecutionMode({ enabled: false }, "remote_api"), null);
  assert.equal(isImageEngineConfigured(settings, "remote_api"), true);
  assert.equal(isImageEngineConfigured(settings, "local_tool"), true);
  assert.equal(
    isImageEngineConfigured({ ...settings, local_executable_path: "" }, "local_tool"),
    false,
  );
});

test("never presents simulated or source-frame runs as AI generated images", () => {
  const simulated = {
    provider: "simulated",
    execution_mode: "simulated",
  };
  const sourceFrame = {
    provider: "source_video",
    execution_mode: "source_frame",
  };
  const localTool = {
    provider: "local_tool",
    execution_mode: "local_tool",
  };

  assert.equal(imageGenerationModeLabel({ enabled: false }), "未配置生图模型");
  assert.equal(imageGenerationRunLabel(simulated), "模拟占位图（非 AI）");
  assert.equal(imageGenerationRunLabel(sourceFrame), "源视频关键帧");
  assert.equal(isAiImageGenerationRun(simulated), false);
  assert.equal(isAiImageGenerationRun(sourceFrame), false);
  assert.equal(isAiImageGenerationRun(localTool), true);
});

test("labels automated image quality without replacing manual review", () => {
  assert.equal(
    imageQualityLabel({ status: "manual_review_required" }),
    "基础质检通过 · 请人工核对",
  );
  assert.equal(
    imageQualityLabel({ status: "warning" }),
    "尺寸有提示 · 请人工核对",
  );
  assert.equal(imageQualityLabel({}), "未自动质检 · 请人工核对");
});

test("explains proxy-related local ImageGen failures with a retry path", () => {
  assert.match(
    generationFailureGuidance({
      error_code: "local_tool_failed",
      error_message: "failed to connect to websocket at chatgpt.com: DNS error",
    }),
    /检查命令行代理.*网络测试.*重试/,
  );
  assert.match(
    generationFailureGuidance({ error_code: "local_tool_timeout" }),
    /超时.*重试/,
  );
});
