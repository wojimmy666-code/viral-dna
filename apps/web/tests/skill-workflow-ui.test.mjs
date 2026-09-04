import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildCategoryProfileCreativeInputs,
  buildRunContractPayload,
  dimensionsForResolutionLabel,
  resolutionForRatio,
  resolutionLabelForDimensions,
  SKILL_WORKFLOW_STAGES,
  stageState,
  validateSkillStartDraft,
} from "../src/skill-workflow/skill-workflow-ui.js";

const videoModel = {
  alias: "video-explicit",
  provider: "provider-a",
  capabilities: {
    default_duration_seconds: 5,
    supported_durations: [5],
    supported_resolutions: ["720P", "1080P"],
  },
  pricing: {
    kind: "per_second_by_resolution",
    rates_micros: { "720P": 100_000, "1080P": 200_000 },
  },
};

const wizardSource = readFileSync(
  new URL("../src/skill-workflow/SkillExperience.jsx", import.meta.url),
  "utf8",
);

test("keeps the fixed eight-stage G0-G7 workflow explicit", () => {
  assert.equal(SKILL_WORKFLOW_STAGES.length, 8);
  assert.deepEqual(
    SKILL_WORKFLOW_STAGES.map((item) => item.gate),
    [
      "brief_approved",
      "style_approved",
      "storyboard_approved",
      "images_approved",
      "videos_approved",
      "picture_locked",
      "audio_caption_approved",
      "delivery_approved",
    ],
  );
});

test("projects provider resolution labels onto the selected aspect ratio", () => {
  assert.equal(resolutionForRatio("9:16", 1024), "576x1024");
  assert.equal(dimensionsForResolutionLabel("9:16", "1080P"), "1080x1920");
  assert.equal(resolutionLabelForDimensions(videoModel, "1080x1920"), "1080P");
});

test("requires explicit model, resolution and full-auto budget choices", () => {
  const skill = {
    duration_seconds: { min: 5, max: 30 },
    current_version: {
      manifest: {
        spec: {
          intake: {
            questions: [{ key: "message", label: "核心信息", required: true }],
          },
        },
      },
    },
  };
  const issues = validateSkillStartDraft({
    projectName: "项目",
    categoryProfileId: "profile-1",
    objective: "新品发布",
    aspectRatio: "9:16",
    durationSeconds: 15,
    skillAnswers: {},
    automationMode: "full_auto",
  }, skill);
  assert.ok(issues.includes("请回答：核心信息"));
  assert.ok(issues.includes("请主动选择图片模型"));
  assert.ok(issues.includes("请主动选择视频分辨率"));
  assert.ok(issues.includes("全自动模式必须设置预算上限"));
});

test("derives the removed intake fields from the category profile", () => {
  const skill = {
    supported_channels: ["douyin", "xiaohongshu"],
    current_version: {
      manifest: {
        spec: {
          intake: {
            creative_basis: { allowed: ["hybrid", "brand_led"], recommended: "hybrid" },
            questions: [{ key: "primary_message", required: true }],
          },
        },
      },
    },
  };
  const inputs = buildCategoryProfileCreativeInputs({
    objective: "发布秋季新品",
    profile: {
      display_name: "秋季通勤女装",
      category_name: "女装",
      brand_name: "示例品牌",
      brief: "面向城市通勤的克制高级感",
      audiences: ["25–35 岁通勤女性"],
      selling_points: ["抗皱", "一衣多穿"],
      scenes: ["通勤", "咖啡馆"],
      forbidden_claims: ["绝对显瘦"],
      visual_style: "自然光、低饱和",
      revision: 3,
    },
    skill,
  });
  assert.equal(inputs.brandName, "示例品牌");
  assert.equal(inputs.audience, "25–35 岁通勤女性");
  assert.equal(inputs.channel, "douyin");
  assert.equal(inputs.creativeBasis, "brand_led");
  assert.deepEqual(inputs.requiredMessages, ["抗皱", "一衣多穿"]);
  assert.deepEqual(inputs.forbiddenMessages, ["绝对显瘦"]);
  assert.equal(inputs.skillAnswers.primary_message, "抗皱；一衣多穿");
  assert.equal(inputs.visualIdentity.visual_style, "自然光、低饱和");
});

test("requires a category profile but derives the built-in primary message", () => {
  const skill = {
    duration_seconds: { min: 5, max: 30 },
    current_version: {
      manifest: { spec: { intake: { questions: [{ key: "primary_message", label: "记忆点", required: true }] } } },
    },
  };
  const draft = {
    projectName: "项目",
    objective: "新品发布",
    aspectRatio: "9:16",
    durationSeconds: 15,
    skillAnswers: {},
    imageModel: "image",
    imageResolution: "576x1024",
    videoModel: "video",
    videoResolution: "1080x1920",
    automationMode: "guided",
  };
  const missingProfile = validateSkillStartDraft(draft, skill);
  assert.ok(missingProfile.includes("请从品类库选择一份档案"));
  const complete = validateSkillStartDraft({ ...draft, categoryProfileId: "profile-1" }, skill);
  assert.ok(!complete.some((issue) => issue.includes("记忆点")));
});

test("keeps the first step focused on a category profile and creative objective", () => {
  assert.match(wizardSource, /<span>从品类库选择<em>必填<\/em><\/span>/);
  assert.match(wizardSource, /label="创作目标" required/);
  assert.doesNotMatch(wizardSource, /<WizardField label="品牌名称"/);
  assert.doesNotMatch(wizardSource, /<WizardField label="目标受众"/);
  assert.doesNotMatch(wizardSource, /<WizardField label="发布渠道"/);
  assert.doesNotMatch(wizardSource, /<WizardField label="创作依据"/);
  assert.doesNotMatch(wizardSource, /<WizardField label="品牌说明"/);
  assert.doesNotMatch(wizardSource, /<WizardField label="行动引导"/);
});

test("treats project assets as a pool instead of one generation request", () => {
  assert.doesNotMatch(wizardSource, /requiresReferenceImage/);
  assert.doesNotMatch(wizardSource, /requiresReferenceVideo/);
  assert.doesNotMatch(wizardSource, /参考视频的安全传输链路尚未启用，请先移除该素材/);
  assert.match(
    wizardSource,
    /text_to_image === true \|\| item\.capabilities\?\.image_to_image === true/,
  );
});

test("freezes explicit generation choices and reports unknown prices honestly", () => {
  const draft = {
    imageModel: "image-explicit",
    imageResolution: "576x1024",
    videoModel: "video-explicit",
    videoResolution: "1080x1920",
    durationSeconds: 15,
    fps: 30,
    generateVideoAudio: true,
    musicStrategy: "select",
    narrationStrategy: "none",
    subtitleStrategy: "final_speech",
    automationMode: "guided",
    budgetCny: "10",
  };
  const known = buildRunContractPayload({
    draft,
    imageModels: [{ alias: "image-explicit", provider: "provider-b", unit_cost_micros: 50_000 }],
    videoModels: [videoModel],
  });
  assert.equal(known.video_resolution_label, "1080P");
  assert.equal(known.allow_provider_fallback, false);
  assert.equal(known.estimate_status, "known");
  assert.ok(known.estimated_cost_micros > 0);

  const unknown = buildRunContractPayload({
    draft,
    imageModels: [{ alias: "image-explicit", provider: "provider-b" }],
    videoModels: [videoModel],
  });
  assert.equal(unknown.estimate_status, "unknown");
});

test("keeps execution, validation and human review as separate axes", () => {
  const stage = SKILL_WORKFLOW_STAGES[0];
  const state = stageState({
    run: {
      run: { current_stage: "creative_brief" },
      gates: [],
      steps: [{
        stage: "creative_brief",
        attempt: 1,
        execution_status: "succeeded",
        validation_status: "passed",
        review_status: "unreviewed",
      }],
    },
  }, stage);
  assert.equal(state.execution, "succeeded");
  assert.equal(state.validation, "passed");
  assert.equal(state.review, "unreviewed");
  assert.equal(state.approved, false);
});

test("keeps Look Test generation observable, incremental and cancellable", () => {
  assert.match(wizardSource, /setInterval\(refreshProgress, 2_000\)/);
  assert.match(wizardSource, /setInterval\(\(\) => setClockNow\(Date\.now\(\)\), 1_000\)/);
  assert.match(wizardSource, /<progress max="100" value=\{lookTest\?\.progress \|\| 0\}>/);
  assert.match(wizardSource, /已完成图片会即时保留/);
  assert.match(wizardSource, /继续生成未完成项/);
  assert.match(wizardSource, /look-test\/cancel/);
  assert.match(wizardSource, /modelOption\?\.label \|\| contract\?\.image_model_id/);
  assert.match(wizardSource, /status === "succeeded" && candidates\.length === 0/);
  assert.match(wizardSource, /上一轮没有生成有效图片，请重新生成/);
});

test("makes storyboard authoring observable, recoverable and model-auditable", () => {
  assert.match(wizardSource, /<StoryboardProgress/);
  assert.match(wizardSource, /storyboard\/cancel/);
  assert.match(wizardSource, /heartbeatLabel\(step\?\.last_heartbeat_at, clockNow\)/);
  assert.match(wizardSource, /文案模型 \{manifest\.authoring_model/);
  assert.match(wizardSource, /大纲与分镜已开始生成/);
});

test("reviews structured directing fields and auto-saves storyboard edits", () => {
  assert.match(wizardSource, /<ContinuitySummary manifest=\{manifest\}/);
  assert.match(wizardSource, /creative_spec/);
  assert.match(wizardSource, /prompt_quality/);
  assert.match(wizardSource, /AI 优化此镜头/);
  assert.match(wizardSource, /修改会自动保存/);
  assert.match(wizardSource, /<AutosaveStatus/);
  assert.match(wizardSource, /setTimeout\(\(\) => \{\s*void saveStoryboard\(\);\s*\}, 900\)/);
  assert.doesNotMatch(wizardSource, />保存大纲与分镜</);
});
