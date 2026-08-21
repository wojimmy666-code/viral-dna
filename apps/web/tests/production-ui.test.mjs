import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  PRODUCTION_STEPS,
  budgetMicrosFromYuan,
  budgetYuanFromMicros,
  closestProductionAspectRatio,
  constraintsFromText,
  dimensionsForRatio,
  duplicateVisualBeatSourceIds,
  estimateImageGenerationCostMicros,
  generationFailureGuidance,
  imageGenerationIntentForShot,
  imageGenerationInputManifest,
  imageIdentityPolicy,
  imageGenerationModeLabel,
  imageGenerationRunLabel,
  imageQualityLabel,
  isAiImageGenerationRun,
  isImageEngineConfigured,
  isVideoGenerationRun,
  latestRunByKind,
  normalizeReferenceTags,
  normalizedImageCandidateCount,
  preferredVideoResolution,
  productionDefaultsForSource,
  productionChangeLabel,
  productionPreviewLayout,
  productionUnlockedStepIndex,
  referenceAssetsContinueLabel,
  referenceTypeLabel,
  resolveImageExecutionMode,
  formatVideoDuration,
  normalizeVideoDuration,
  videoDurationConstraintLabel,
  videoDurationOptions,
  videoGenerationDiagnosticText,
  videoGenerationFailureDetails,
  videoGenerationRunLabel,
  workflowStatusClass,
  workflowStatusLabel,
} from "../src/production-ui.js";

test("locks one person asset as the second and exclusive identity input", () => {
  const assets = [
    { id: "person-1", name: "Betty", type: "person", thumbnail_url: "/betty.webp" },
    { id: "scene-1", name: "庭院", type: "scene", thumbnail_url: "/scene.webp" },
  ];
  const bindings = [
    { reference_asset_id: "scene-1", role: "scene", weight: 2 },
    { reference_asset_id: "person-1", role: "identity", weight: 0.1 },
  ];
  const policy = imageIdentityPolicy(bindings, assets);
  const manifest = imageGenerationInputManifest({
    sourceUrl: "/source.webp",
    referenceBindings: bindings,
    assets,
  });

  assert.equal(policy.enabled, true);
  assert.equal(policy.valid, true);
  assert.equal(policy.primaryAsset.name, "Betty");
  assert.equal(manifest[0].responsibility, "composition_pose_action_camera");
  assert.equal(manifest[0].identity_source, false);
  assert.equal(manifest[1].input_index, 2);
  assert.equal(manifest[1].asset_id, "person-1");
  assert.equal(manifest[1].responsibility, "exclusive_person_identity_source");
  assert.equal(manifest[2].asset_id, "scene-1");
});

test("blocks ambiguous or invalid identity assets in the image workspace", () => {
  const person = { id: "person-1", name: "人物", type: "person" };
  const scene = { id: "scene-1", name: "场景", type: "scene" };
  assert.match(
    imageIdentityPolicy([
      { reference_asset_id: person.id, role: "identity" },
      { reference_asset_id: "person-2", role: "identity" },
    ], [person]).blocker,
    /只能指定一个人物身份/,
  );
  assert.match(
    imageIdentityPolicy([
      { reference_asset_id: scene.id, role: "identity" },
    ], [scene]).blocker,
    /必须使用人物类型资产/,
  );
});

test("does not present image inputs for pure text generation", () => {
  assert.deepEqual(imageGenerationInputManifest({
    inputMode: "text_to_image",
    sourceUrl: "/source.webp",
    referenceBindings: [
      { reference_asset_id: "person-1", role: "identity", weight: 1 },
    ],
    assets: [
      { id: "person-1", name: "人物", type: "person", thumbnail_url: "/person.webp" },
    ],
  }), []);
});

const productionWorkflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const productionWorkflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);

test("detects analysis updates and synchronizes only selected prompt fields", () => {
  assert.equal(productionChangeLabel("analysis_prompts_synced"), "同步分析提示词");
  assert.match(productionWorkflowSource, /\/analysis-update`/);
  assert.match(productionWorkflowSource, /\/analysis-update\/sync-prompts/);
  assert.match(productionWorkflowSource, /function AnalysisUpdateBanner/);
  assert.match(productionWorkflowSource, /function AnalysisUpdatePanel/);
  assert.match(productionWorkflowSource, /使用新分析/);
  assert.match(productionWorkflowSource, /保留当前/);
  assert.match(productionWorkflowSource, /同步所选提示词并创建 Revision/);
  assert.match(productionWorkflowStyles, /\.analysis-update-diff-grid/);
  assert.match(productionWorkflowStyles, /grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
});

test("supports recoverable production project deletion", () => {
  assert.match(productionWorkflowSource, /function ProductionLifecycleDialog/);
  assert.match(productionWorkflowSource, /productions\?lifecycle=trashed/);
  assert.match(productionWorkflowSource, /\/productions\/\$\{project\.id\}\/restore/);
  assert.match(productionWorkflowSource, /\/productions\/\$\{project\.id\}\/permanent/);
  assert.match(productionWorkflowSource, /actionLabel:\s*"撤销"/);
  assert.match(productionWorkflowSource, /className="production-project-menu"/);
  assert.match(productionWorkflowSource, /className="production-workspace-menu"/);
  assert.match(productionWorkflowStyles, /\.production-project-menu/);
  assert.match(productionWorkflowStyles, /\.production-lifecycle-dialog-copy/);
});

test("labels video candidate recycle-bin revisions", () => {
  assert.equal(productionChangeLabel("image_candidates_archived"), "删除图片候选");
  assert.equal(productionChangeLabel("image_candidates_restored"), "恢复图片候选");
  assert.equal(productionChangeLabel("video_candidates_archived"), "视频候选移入回收站");
  assert.equal(productionChangeLabel("video_candidates_restored"), "恢复视频候选");
});

test("keeps a compatible video resolution and otherwise prefers 720P", () => {
  const flagship = {
    capabilities: { supported_resolutions: ["480P", "720P", "1080P"] },
  };
  const mini = {
    capabilities: { supported_resolutions: ["480P", "720P"] },
  };

  assert.equal(preferredVideoResolution(flagship, "1080P"), "1080P");
  assert.equal(preferredVideoResolution(flagship, "720p"), "720P");
  assert.equal(preferredVideoResolution(mini, "1080P"), "720P");
  assert.equal(
    preferredVideoResolution({ capabilities: { supported_resolutions: ["2K"] } }, "1080P"),
    "2K",
  );
});

test("maps legacy Seedance limit failures to safe actionable details", () => {
  const details = videoGenerationFailureDetails({
    status: "failed",
    provider: "volc_ark",
    model_display_name: "Seedance 2.0 Fast",
    error_code: "SetLimitExceeded",
    error_message: "Your account [2102003413] reached the Safe Experience Mode limit",
    provider_tasks: [{
      provider_task_id: "task-123",
      error_code: "SetLimitExceeded",
      error_message: "Your account [2102003413] reached the Safe Experience Mode limit",
      retryable: false,
    }],
  });

  assert.equal(details.category, "inference_limit");
  assert.equal(details.title, "Seedance 2.0 Fast 已暂停生成");
  assert.equal(details.retryable, false);
  assert.equal(details.action, "open_model_settings");
  assert.doesNotMatch(details.message, /2102003413|Your account/i);
  assert.match(videoGenerationDiagnosticText(details), /任务编号：task-123/);
});

test("only recommends direct retry for retryable video failures", () => {
  const details = videoGenerationFailureDetails({
    status: "failed",
    error_code: "video_provider_rate_limited",
    error_retryable: true,
  });
  assert.equal(details.retryable, true);
  assert.equal(details.action, "retry");
});

test("maps supported ratios to their default output dimensions", () => {
  assert.deepEqual(dimensionsForRatio("9:16"), { width: 1080, height: 1920 });
  assert.deepEqual(dimensionsForRatio("16:9"), { width: 1920, height: 1080 });
  assert.deepEqual(dimensionsForRatio("1:1"), { width: 1080, height: 1080 });
  assert.deepEqual(dimensionsForRatio("4:5"), { width: 1080, height: 1350 });
  assert.deepEqual(dimensionsForRatio("unknown"), { width: 1080, height: 1920 });
});

test("defaults production output to the closest supported source-video ratio", () => {
  assert.equal(
    closestProductionAspectRatio({ width: 1920, height: 1080 }),
    "16:9",
  );
  assert.equal(
    closestProductionAspectRatio({ width: 1080, height: 1920 }),
    "9:16",
  );
  assert.equal(
    closestProductionAspectRatio({ width: 1080, height: 1350 }),
    "4:5",
  );
  assert.equal(
    closestProductionAspectRatio({ aspectRatio: "1:1" }),
    "1:1",
  );
  assert.equal(
    closestProductionAspectRatio({ width: 1440, height: 1080 }),
    "16:9",
  );
  assert.deepEqual(
    productionDefaultsForSource({ width: 1920, height: 1080 }),
    {
      outputAspectRatio: "16:9",
      outputWidth: 1920,
      outputHeight: 1080,
    },
  );
});

test("sizes shot-image preview canvases from the project output ratio", () => {
  assert.deepEqual(
    productionPreviewLayout({
      output_aspect_ratio: "16:9",
      output_width: 1920,
      output_height: 1080,
    }),
    {
      aspectRatio: "1920 / 1080",
      maxWidth: "100%",
      orientation: "landscape",
    },
  );
  assert.deepEqual(
    productionPreviewLayout({ output_aspect_ratio: "9:16" }),
    {
      aspectRatio: "9 / 16",
      maxWidth: "360px",
      orientation: "portrait",
    },
  );
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

test("exposes stable simplified-Chinese labels and all implemented workflow steps", () => {
  assert.equal(referenceTypeLabel("wardrobe"), "服装");
  assert.equal(referenceTypeLabel("unknown"), "参考图");
  assert.equal(productionChangeLabel("branch_created"), "创建版本分支");
  assert.equal(productionChangeLabel("shot_structure_changed"), "调整分镜结构");
  assert.equal(PRODUCTION_STEPS.filter((step) => step.locked).length, 0);
  assert.deepEqual(
    PRODUCTION_STEPS.map((step) => step.id),
    ["project_setup", "reference_assets", "shot_images", "shot_videos", "editing", "export"],
  );
  assert.equal(PRODUCTION_STEPS[1].label, "参考资产（可选）");
});

test("keeps optional preparation views from locking the shot-image workspace", () => {
  assert.equal(productionUnlockedStepIndex("project_setup"), 2);
  assert.equal(productionUnlockedStepIndex("reference_assets"), 2);
  assert.equal(productionUnlockedStepIndex("shot_images"), 2);
  assert.equal(productionUnlockedStepIndex("shot_videos"), 3);
  assert.equal(referenceAssetsContinueLabel(0), "跳过，进入分镜图片");
  assert.equal(referenceAssetsContinueLabel(2), "继续到分镜图片");
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
  assert.equal(productionChangeLabel("image_approval_revoked"), "取消采用分镜图片");
});

test("flags duplicate visual-beat source frames by hash or explicit warning", () => {
  assert.deepEqual(
    duplicateVisualBeatSourceIds([
      { id: "beat-1", source_frame_sha256: "a".repeat(64) },
      { id: "beat-2", source_frame_sha256: "b".repeat(64) },
      { id: "beat-3", source_frame_sha256: "a".repeat(64) },
      { id: "beat-4", source_frame_warning: "duplicate_frame" },
    ]).sort(),
    ["beat-1", "beat-3", "beat-4"],
  );
});

test("requests a fresh variation only after a real AI candidate exists", () => {
  assert.equal(imageGenerationIntentForShot(null), "standard");
  assert.equal(
    imageGenerationIntentForShot({
      generation_runs: [
        {
          execution_mode: "source_frame",
          provider: "source_video",
          candidates: [{ id: "source" }],
        },
      ],
    }),
    "standard",
  );
  assert.equal(
    imageGenerationIntentForShot({
      generation_runs: [
        {
          execution_mode: "local_tool",
          provider: "codex_imagegen",
          candidates: [{ id: "candidate-1" }],
        },
      ],
    }),
    "new_variation",
  );
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

test("labels video runs and selects the latest run by media kind", () => {
  const imageRun = { id: "image-1", kind: "image" };
  const videoRun = {
    id: "video-1",
    kind: "video",
    provider: "simulated",
    execution_mode: "simulated",
  };
  assert.equal(isVideoGenerationRun(videoRun), true);
  assert.equal(isVideoGenerationRun(imageRun), false);
  assert.equal(latestRunByKind([videoRun, imageRun], "image"), imageRun);
  assert.equal(latestRunByKind([videoRun, imageRun], "video"), videoRun);
  assert.equal(videoGenerationRunLabel(null), "尚未生成");
  assert.equal(videoGenerationRunLabel(videoRun), "流程模拟视频（非 AI）");
  assert.equal(
    videoGenerationRunLabel({
      kind: "video",
      execution_mode: "remote_api",
      provider: "bailian",
      model_display_name: "百炼 Wan 2.7 图生视频",
    }),
    "百炼 · 百炼 Wan 2.7 图生视频",
  );
});

test("maps source-shot decimals to the nearest duration supported by the video model", () => {
  const wan = {
    label: "百炼 Wan 2.7",
    capabilities: {
      minimum_duration_seconds: 2,
      maximum_duration_seconds: 15,
      duration_step_seconds: 1,
      default_duration_seconds: 5,
      supported_durations: Array.from({ length: 14 }, (_, index) => index + 2),
    },
  };
  assert.deepEqual(videoDurationOptions(wan), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]);
  assert.equal(normalizeVideoDuration(6.567, wan), 7);
  assert.equal(normalizeVideoDuration(null, wan), 5);
  assert.equal(formatVideoDuration(7), "7");
  assert.equal(videoDurationConstraintLabel(wan), "支持 2–15 秒，按 1 秒调整");
});

test("uses discrete slider stops for video models with fixed durations", () => {
  const hailuo = {
    capabilities: {
      minimum_duration_seconds: 6,
      maximum_duration_seconds: 10,
      duration_step_seconds: 1,
      default_duration_seconds: 6,
      supported_durations: [6, 10],
    },
  };
  assert.deepEqual(videoDurationOptions(hailuo), [6, 10]);
  assert.equal(normalizeVideoDuration(8, hailuo), 10);
  assert.equal(videoDurationConstraintLabel(hailuo), "仅支持 6、10 秒");
});

test("builds range-model slider stops from minimum, maximum and step", () => {
  const ranged = {
    capabilities: {
      minimum_duration_seconds: 5,
      maximum_duration_seconds: 15,
      duration_step_seconds: 2,
      default_duration_seconds: 9,
      supported_durations: [],
    },
  };
  assert.deepEqual(videoDurationOptions(ranged), [5, 7, 9, 11, 13, 15]);
  assert.equal(normalizeVideoDuration(undefined, ranged), 9);
  assert.equal(videoDurationConstraintLabel(ranged), "支持 5–15 秒，按 2 秒调整");
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
  assert.equal(
    imageQualityLabel({
      status: "warning",
      semantic_quality: { status: "warning" },
    }),
    "VLM 发现语义风险 · 请人工核对",
  );
  assert.equal(
    imageQualityLabel({
      status: "manual_review_required",
      semantic_quality: { status: "passed" },
    }),
    "VLM 未发现明显语义问题 · 请人工核对",
  );
});

test("explains proxy-related local ImageGen failures with a retry path", () => {
  assert.match(
    generationFailureGuidance({
      error_code: "codex_windows_sandbox_setup_failed",
    }),
    /Windows 沙箱.*无费用预检.*unelevated/,
  );
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
