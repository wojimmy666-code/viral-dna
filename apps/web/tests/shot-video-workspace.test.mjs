import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  videoCandidateCountOptions,
  videoModelCatalogUiState,
  videoOutputSummary,
} from "../src/video-generation-controls/video-generation-ui.js";
import {
  videoCandidatePlaybackUrl,
} from "../src/production-ui.js";
import {
  videoDraftFromDetail,
  videoDraftParameters,
} from "../src/video-generation-controls/useShotVideoGenerationDraft.js";
import {
  buildVideoPromptHighlightSegments,
  buildManagedAssetReferenceOption,
  buildVideoReferenceSystemConstraints,
  buildVideoReferenceOptions,
  compileVideoPromptWithReferences,
  deleteVideoMentionAtSelection,
  ensureVideoGenerationReference,
  insertVideoMentionIntoPrompt,
  normalizeVideoPromptMentions,
  reconcileVideoDraftReferences,
  selectedVideoReferenceOptions,
  removeVideoMentionFromPrompt,
  requiredSourceForVideoMention,
  stripLegacyVideoReferencePolicies,
  synchronizeAutomaticVideoPrompt,
  videoMentionToken,
  videoReferenceConflictPriority,
} from "../src/video-inputs/video-prompt-references.js";

const workspaceSource = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const productionWorkflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const generationControlsSource = readFileSync(
  new URL("../src/ShotVideoGenerationControls.jsx", import.meta.url),
  "utf8",
);
const generationDraftSource = readFileSync(
  new URL(
    "../src/video-generation-controls/useShotVideoGenerationDraft.js",
    import.meta.url,
  ),
  "utf8",
);
const videoPromptReferenceEditorSource = readFileSync(
  new URL("../src/video-inputs/VideoPromptReferenceEditor.jsx", import.meta.url),
  "utf8",
);
const creativeIntentPanelSource = readFileSync(
  new URL("../src/video-intents/CreativeIntentPanel.jsx", import.meta.url),
  "utf8",
);
const creativeIntentMentionEditorSource = readFileSync(
  new URL("../src/video-intents/CreativeIntentMentionEditor.jsx", import.meta.url),
  "utf8",
);
const videoPromptReferencePolicySource = readFileSync(
  new URL("../src/video-inputs/VideoPromptReferencePolicy.jsx", import.meta.url),
  "utf8",
);
const videoPromptReferencePolicyStyles = readFileSync(
  new URL("../src/video-inputs/video-prompt-reference-policy.css", import.meta.url),
  "utf8",
);
const generationReferenceComposerSource = readFileSync(
  new URL(
    "../src/video-inputs/reference-composer/GenerationReferenceComposer.jsx",
    import.meta.url,
  ),
  "utf8",
);
const referencePickerSource = readFileSync(
  new URL(
    "../src/video-inputs/reference-composer/ReferencePickerPopover.jsx",
    import.meta.url,
  ),
  "utf8",
);
const referenceComposerStyles = readFileSync(
  new URL(
    "../src/video-inputs/reference-composer/reference-composer.css",
    import.meta.url,
  ),
  "utf8",
);
const generationControlsStyles = readFileSync(
  new URL("../src/shot-video-generation-controls.css", import.meta.url),
  "utf8",
);
const modelPopoverSource = readFileSync(
  new URL("../src/video-generation-controls/VideoModelPopover.jsx", import.meta.url),
  "utf8",
);
const settingsPopoverSource = readFileSync(
  new URL("../src/video-generation-controls/VideoGenerationSettingsPopover.jsx", import.meta.url),
  "utf8",
);
const anchoredPopoverSource = readFileSync(
  new URL("../src/video-generation-controls/AnchoredPopover.jsx", import.meta.url),
  "utf8",
);
const candidateLibrarySource = readFileSync(
  new URL("../src/VideoCandidateLibrary.jsx", import.meta.url),
  "utf8",
);
const candidateLibraryStyles = readFileSync(
  new URL("../src/video-candidate-library.css", import.meta.url),
  "utf8",
);
const workflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);
const baseStyles = readFileSync(
  new URL("../src/styles.css", import.meta.url),
  "utf8",
);
const videoEditorSource = readFileSync(
  new URL("../src/video-editor/VideoEditorWorkspace.jsx", import.meta.url),
  "utf8",
);
const timelineCanvasSource = readFileSync(
  new URL("../src/video-editor/TimelineCanvas.jsx", import.meta.url),
  "utf8",
);
const videoEditorStyles = readFileSync(
  new URL("../src/video-editor/video-editor.css", import.meta.url),
  "utf8",
);
const imageWorkspaceSource = readFileSync(
  new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
  "utf8",
);
const appSource = readFileSync(
  new URL("../src/App.jsx", import.meta.url),
  "utf8",
);

function cssRule(selector, source = workflowStyles) {
  const start = source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS rule for ${selector}`);
  const end = source.indexOf("}", start);
  return source.slice(start, end + 1);
}

test("keeps the production workspace on a readable semantic type ramp", () => {
  const readableSection = workflowStyles.slice(
    workflowStyles.indexOf("/* Production consumes the global ViralDNA UI System"),
  );

  assert.match(baseStyles, /--type-caption-size:\s*0\.75rem/);
  assert.match(baseStyles, /--type-label-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-body-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-heading-size:\s*1rem/);
  assert.match(baseStyles, /--type-page-size:\s*1\.25rem/);
  assert.match(readableSection, /\.production-workspace\s*\{/);
  assert.match(readableSection, /font-size:\s*var\(--type-body-size\)/);
  assert.match(readableSection, /\.production-workspace \.prompt-editor-textarea\s*\{[^}]*font-size:\s*var\(--type-body-size\)/s);
  assert.match(readableSection, /\.production-export-status/);
  assert.doesNotMatch(readableSection, /--production-(?:type|text|leading)-/);
  assert.doesNotMatch(readableSection, /font-size:\s*(?:7|8|9|10|11)px/);
});

test("keeps video candidates usable when the shot input has changed", () => {
  assert.match(workspaceSource, /status === "stale" \? "旧输入"/);
  assert.match(workspaceSource, /分镜输入已更新/);
  assert.match(workspaceSource, /当前候选基于修改前的输入生成，仍可继续使用/);
  assert.match(workspaceSource, /plan\.video_status === "stale"/);
  assert.match(candidateLibrarySource, /const oldInput = plan\?\.video_status === "stale"/);
  assert.match(candidateLibrarySource, /可采用.*旧输入/s);
  assert.match(productionWorkflowSource, /基于修改前的分镜输入生成。确认仍采用当前画面吗/);
  assert.match(productionWorkflowSource, /confirm_stale_input: usesOldInput/);
  assert.match(workflowStyles, /\.shot-video-input-version-notice\s*\{/);
  assert.match(workflowStyles, /\.shot-candidate-current-detail > em\.old-input\s*\{/);
});

test("keeps the segmented video stage renderable before a candidate exists", () => {
  const candidate = { id: "video-1", content_url: "/original.mp4" };

  assert.equal(videoCandidatePlaybackUrl(null, null), "");
  assert.equal(videoCandidatePlaybackUrl(candidate, null), "/original.mp4");
  assert.equal(
    videoCandidatePlaybackUrl(candidate, {
      candidateId: "video-1",
      url: "/enhanced.mp4",
    }),
    "/enhanced.mp4",
  );
  assert.equal(
    videoCandidatePlaybackUrl(candidate, {
      candidateId: "video-2",
      url: "/other.mp4",
    }),
    "/original.mp4",
  );
  assert.match(workspaceSource, /videoCandidatePlaybackUrl\(/);
});

test("adopts a video candidate in one step without a selected intermediate state", () => {
  assert.match(workspaceSource, /"采用此视频"/);
  assert.match(workspaceSource, /"仍然采用"/);
  assert.doesNotMatch(workspaceSource, /选择此候选|确认采用|onSelectCandidate/);
  assert.doesNotMatch(productionWorkflowSource, /async function selectVideoCandidate/);
  assert.doesNotMatch(candidateLibrarySource, /"已选择"/);
  assert.match(productionWorkflowSource, /async function approveVideoCandidate/);
});

test("keeps rejected videos visible until the user explicitly deletes them", () => {
  assert.match(workspaceSource, /function isUserDeletedVideoCandidate/);
  assert.match(workspaceSource, /filter\(\(candidate\) => !isUserDeletedVideoCandidate\(candidate\)\)/);
  assert.match(workspaceSource, /displayedCandidate\.status === "rejected"/);
  assert.match(workspaceSource, />重新采用</);
  assert.match(candidateLibrarySource, /shot-candidate-review-state rejected/);
  assert.match(candidateLibrarySource, /"已退回"/);
  assert.match(productionWorkflowSource, /已退回并保留在历史中，可随时重新采用/);
  assert.match(candidateLibraryStyles, /\.shot-candidate-review-state\.rejected\s*\{/);
  assert.match(workflowStyles, /\.shot-candidate-tile\.rejected\s*\{/);
  assert.doesNotMatch(workspaceSource, /!\["rejected", "archived"\]\.includes/);
});

test("uses a compact generation command bar with upward anchored model and setting popovers", () => {
  const commandRule = cssRule(".shot-video-generation-command", generationControlsStyles);
  const barRule = cssRule(".shot-video-command-bar", generationControlsStyles);
  const popoverRule = cssRule(".video-generation-popover", generationControlsStyles);

  assert.match(workspaceSource, /<ShotVideoGenerationControls/);
  assert.match(generationControlsSource, /<VideoModelPopover/);
  assert.match(generationControlsSource, /<VideoGenerationSettingsPopover/);
  assert.match(generationControlsSource, /aria-expanded=\{modelOpen\}/);
  assert.match(generationControlsSource, /aria-expanded=\{settingsOpen\}/);
  assert.match(generationControlsSource, /className=\"shot-video-model-trigger/);
  assert.match(generationControlsSource, /className="shot-video-output-summary"/);
  assert.doesNotMatch(generationControlsSource, /shot-video-capability-badge|>有序多图</);
  assert.match(settingsPopoverSource, /生成前自动保存提示词/);
  assert.doesNotMatch(settingsPopoverSource, /提示词与负面约束/);
  assert.match(commandRule, /--video-command-control:\s*48px/);
  assert.match(commandRule, /container-type:\s*inline-size/);
  assert.match(barRule, /grid-template-areas:\s*"model summary cost actions"/);
  assert.match(popoverRule, /position:\s*fixed/);
  assert.match(popoverRule, /z-index:\s*60/);
  assert.match(anchoredPopoverSource, /createPortal/);
  assert.match(anchoredPopoverSource, /placeAbove/);
  assert.match(anchoredPopoverSource, /contains\(event\.target\)/);
  assert.doesNotMatch(anchoredPopoverSource, /Math\.max\(180, placeAbove/);
  assert.match(settingsPopoverSource, /className="video-settings-scroll-region"/);
  assert.match(generationControlsStyles, /\.video-settings-scroll-region\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(generationControlsStyles, /\.video-settings-footer\s*\{[\s\S]*flex:\s*0 0 auto/);
  assert.match(modelPopoverSource, /尚未配置/);
  assert.doesNotMatch(modelPopoverSource, /预计生成时间|约\d+分钟/);
  assert.match(generationControlsStyles, /@container \(max-width: 680px\)/);
  assert.match(generationControlsStyles, /@media \(max-width: 620px\)/);
});

test("derives compact output summaries and candidate choices from model capabilities", () => {
  assert.equal(videoOutputSummary({
    aspectRatio: "9:16",
    candidateCount: 2,
    duration: 5,
    resolution: "720P",
  }), "9:16 · 720P · 5秒 · 2个");
  assert.deepEqual(
    videoCandidateCountOptions({ capabilities: { max_candidates: 3 } }),
    [1, 2, 3],
  );
  assert.deepEqual(
    videoCandidateCountOptions({ capabilities: { max_candidates: 9 } }),
    [1, 2, 3, 4],
  );
});

test("distinguishes a model catalog outage from a real empty catalog or missing key", () => {
  const loading = videoModelCatalogUiState({ status: "loading" });
  assert.equal(loading.loading, true);
  assert.equal(loading.missingProviderKey, false);
  assert.equal(loading.title, "正在读取视频模型");

  const failed = videoModelCatalogUiState({
    error: "API 暂时不可用",
    status: "error",
  });
  assert.equal(failed.failed, true);
  assert.equal(failed.missingProviderKey, false);
  assert.equal(failed.subtitle, "API 暂时不可用");

  const selectedModel = { alias: "seedance", label: "Seedance", provider: "volc_ark" };
  const cached = videoModelCatalogUiState({
    models: [selectedModel],
    providers: [{ provider: "volc_ark", api_key_configured: true }],
    selectedModel,
    status: "error",
  });
  assert.equal(cached.usingCachedCatalog, true);
  assert.equal(cached.providerReady, true);
  assert.equal(cached.failed, false);

  const missingKey = videoModelCatalogUiState({
    models: [selectedModel],
    providers: [{ provider: "volc_ark", api_key_configured: false }],
    selectedModel,
    status: "ready",
  });
  assert.equal(missingKey.missingProviderKey, true);
  assert.match(missingKey.subtitle, /Key 未配置/);

  const unavailable = videoModelCatalogUiState({
    models: [selectedModel],
    providers: [{ provider: "volc_ark", api_key_configured: true }],
    selectedAlias: "minimax_h3",
    selectedModel: null,
    status: "ready",
  });
  assert.equal(unavailable.unavailableSelection, true);
  assert.equal(unavailable.title, "minimax_h3");
  assert.match(unavailable.subtitle, /已保存模型当前不可用/);
});

test("persists each shot video model instead of reapplying the global default", () => {
  const detail = {
    plan: {
      duration_seconds: 4,
      video_prompt: "测试提示词",
      video_negative_constraints: ["不要抖动"],
    },
  };
  const settings = {
    default_model_alias: "bailian_wan_2_7_r2v",
    default_resolution: "720P",
    models: [{ alias: "bailian_wan_2_7_r2v" }],
  };
  const persisted = {
    model_alias: "seedance_2_0_fast",
    resolution: "1080P",
    duration_seconds: 5,
    candidate_count: 2,
    draft_version: 3,
  };

  const restored = videoDraftFromDetail(detail, settings, persisted);
  assert.equal(restored.modelAlias, "seedance_2_0_fast");
  assert.equal(restored.resolution, "1080P");
  assert.equal(restored.durationSeconds, "5");
  assert.equal(restored.candidateCount, 2);
  assert.deepEqual(videoDraftParameters(restored), {
    model_alias: "seedance_2_0_fast",
    resolution: "1080P",
    duration_seconds: 5,
    candidate_count: 2,
    input_plan: {
      schema_version: "viral-dna-video-input-plan/v1",
      sources: [],
      references: [],
    },
    video_prompt: "测试提示词",
    video_prompt_mentions: [],
    video_negative_constraints: ["不要抖动"],
    intent_text: "",
    intent_mentions: [],
    locked_reference_keys: [],
    removed_intent_reference_keys: [],
    prompt_manually_modified: false,
    reference_sync_mode: "auto",
    auto_reference_exclusions: [],
    reference_order_override: [],
  });

  assert.match(productionWorkflowSource, /useShotVideoGenerationDraft/);
  assert.match(productionWorkflowSource, /video-generation-draft/);
  assert.match(
    productionWorkflowSource,
    /flushVideoDraft\(shotDetail\.plan\.id\)[\s\S]*\/video-runs/,
  );
  assert.match(generationDraftSource, /expected_draft_version/);
  assert.match(generationDraftSource, /window\.setTimeout\([\s\S]*400/);
  assert.match(generationDraftSource, /pendingRef\.current/);
  assert.doesNotMatch(workspaceSource, /compatibleVideoModels\[0\]/);
  assert.doesNotMatch(
    workspaceSource,
    /managedAssetCompatible[\s\S]{0,500}selectVideoModel\(fallback\.alias\)/,
  );
  assert.doesNotMatch(
    productionWorkflowSource,
    /modelAlias:\s*"bailian_wan_2_7_r2v"/,
  );
});

test("persists creative-intent mentions as stable asset ids", () => {
  const mention = {
    reference_kind: "project_asset",
    reference_id: "9a0cadbc-22c0-43cf-bfb4-ae37c50ee09d",
    label: "资产/服装/白色睡衣",
    role: "wardrobe",
    order: 1,
  };
  const restored = videoDraftFromDetail({
    plan: { duration_seconds: 3, video_prompt: "" },
  }, {
    default_model_alias: "minimax_h3",
    default_resolution: "720P",
    models: [{ alias: "minimax_h3" }],
  }, {
    schema_version: "viral-dna-shot-video-draft/v2",
    model_alias: "minimax_h3",
    resolution: "720P",
    duration_seconds: 3,
    candidate_count: 1,
    video_prompt: "",
    video_prompt_mentions: [],
    video_negative_constraints: [],
    input_plan: { sources: [], references: [] },
    intent: {
      text: "服装换成 @资产/服装/白色睡衣",
      mentions: [mention],
    },
  });

  assert.equal(restored.intentText, "服装换成 @资产/服装/白色睡衣");
  assert.deepEqual(restored.intentMentions, [mention]);
  assert.deepEqual(videoDraftParameters(restored).intent_mentions, [mention]);
});

test("blocks video generation until a stale creative intent is regenerated", () => {
  assert.match(
    workspaceSource,
    /videoDraft\.intent\?\.status === "stale"[\s\S]*重新生成引用与提示词/,
  );
});

test("automatically binds approved visual beats to prompt mentions", () => {
  const visualBeatId = "46bc61aa-e6f1-4a9d-bf84-81f85be1e6f9";
  const reference = {
    reference_kind: "approved_image",
    reference_id: "5e098a85-7bd7-4b35-97bc-17397a3f1f48",
    label: "分镜图/图1",
    role: "composition",
    order: 1,
    visual_beat_id: visualBeatId,
    automatic: true,
    scope: {
      kind: "visual_beats",
      visual_beat_ids: [visualBeatId],
      start_ratio: 0,
      end_ratio: 1,
    },
    origin: "visual_beat_auto",
  };
  const detail = {
    plan: {
      duration_seconds: 3,
      video_prompt: "保持构图和动作。",
      video_prompt_mentions: [],
      visual_beats: [{
        id: visualBeatId,
        index: 1,
        title: "动作",
        required: true,
        start_ratio: 0,
        end_ratio: 1,
        approved_image_candidate_id: reference.reference_id,
      }],
    },
    generation_runs: [{
      kind: "image",
      visual_beat_id: visualBeatId,
      candidates: [{ id: reference.reference_id }],
    }],
  };
  const settings = {
    default_model_alias: "bailian_wan_2_7_r2v",
    default_resolution: "720P",
    models: [{ alias: "bailian_wan_2_7_r2v" }],
  };
  const restored = videoDraftFromDetail(detail, settings, {
    input_plan: { sources: ["approved_images"] },
  });

  assert.deepEqual(restored.selectedReferences, [reference]);
  assert.equal(restored.videoPrompt, "@分镜图/图1\n\n保持构图和动作。");
  assert.deepEqual(restored.videoPromptMentions, [reference]);
  assert.deepEqual(videoDraftParameters(restored).input_plan.references, [reference]);
  assert.deepEqual(restored.inputSources, ["approved_images"]);
});

test("keeps automatic frame references at their semantic positions", () => {
  const references = [
    {
      reference_kind: "approved_image",
      reference_id: "5e098a85-7bd7-4b35-97bc-17397a3f1f48",
      label: "分镜图/图1",
      role: "composition",
      order: 1,
      automatic: true,
    },
    {
      reference_kind: "approved_image",
      reference_id: "03ae3d8d-de44-455d-9931-b495474964b7",
      label: "分镜图/图2",
      role: "composition",
      order: 2,
      automatic: true,
    },
    {
      reference_kind: "project_asset",
      reference_id: "02f03a76-8603-48d3-b51e-df1b7ade3200",
      label: "资产/小喵酱/面部",
      role: "actor_identity",
      order: 3,
    },
  ];
  const prompt = [
    "@分镜图/图1 @分镜图/图2 @资产/小喵酱/面部",
    "",
    "【分段画面】",
    "画面以 @分镜图/图1 为准。",
    "@分镜图/图1 到 @分镜图/图2 由视频模型生成连续转场。",
  ].join("\n");

  const synchronized = synchronizeAutomaticVideoPrompt({
    prompt,
    mentions: references,
    selectedReferences: references,
  });

  assert.equal(synchronized.videoPrompt, prompt);
  assert.match(synchronized.videoPrompt, /画面以 @分镜图\/图1 为准/);
  assert.match(synchronized.videoPrompt, /@分镜图\/图1 到 @分镜图\/图2/);
  assert.equal(synchronized.videoPromptMentions.length, 3);
});

test("remembers removed automatic references by stable visual beat id", () => {
  const frame = (beatId, index, candidateId) => ({
    beat: {
      id: beatId,
      index,
      title: `画面${index}`,
      start_ratio: (index - 1) / 2,
      end_ratio: index / 2,
    },
    candidate: { id: candidateId },
  });
  const frames = [
    frame("fe9af5cf-8293-4a37-a38c-c0fc827906de", 1, "9ea90c3c-f451-4b83-a5dc-a0709d2a90e5"),
    frame("af462b21-9c5d-4668-b43f-4265b52c1ca1", 2, "03ae3d8d-de44-455d-9931-b495474964b7"),
  ];
  const automatic = reconcileVideoDraftReferences({
    videoPrompt: "人物连续完成动作。",
    videoPromptMentions: [],
    selectedReferences: [],
    inputSources: [],
    autoReferenceExclusions: [],
    referenceOrderOverride: [],
  }, {}, frames);
  assert.equal(automatic.selectedReferences.length, 2);
  assert.equal(automatic.videoPrompt, "@分镜图/图1 @分镜图/图2\n\n人物连续完成动作。");

  const reversedReferences = [...automatic.selectedReferences].reverse();
  const reordered = reconcileVideoDraftReferences(automatic, {
    selectedReferences: reversedReferences,
    referenceOrderOverride: reversedReferences.map(
      (item) => `approved_image:visual_beat:${item.visual_beat_id}`,
    ),
  }, frames);
  assert.deepEqual(
    reordered.selectedReferences.map((item) => item.label),
    ["分镜图/图2", "分镜图/图1"],
  );
  assert.equal(reordered.videoPrompt, "@分镜图/图2 @分镜图/图1\n\n人物连续完成动作。");

  const removed = reordered.selectedReferences[1];
  const excluded = reconcileVideoDraftReferences(reordered, {
    selectedReferences: reordered.selectedReferences.slice(0, 1),
    removedReference: removed,
  }, frames);
  assert.deepEqual(excluded.autoReferenceExclusions, [frames[0].beat.id]);
  assert.equal(excluded.videoPrompt, "@分镜图/图2\n\n人物连续完成动作。");

  const changedFrames = [
    frame(frames[0].beat.id, 1, "b894f4dd-99af-4f45-af99-a4b94cda4b89"),
    frames[1],
  ];
  const stillExcluded = reconcileVideoDraftReferences(excluded, {}, changedFrames);
  assert.equal(stillExcluded.selectedReferences.length, 1);
  const restored = reconcileVideoDraftReferences(stillExcluded, {
    restoreAutomaticReferences: true,
  }, changedFrames);
  assert.deepEqual(restored.autoReferenceExclusions, []);
  assert.equal(restored.selectedReferences[0].reference_id, changedFrames[0].candidate.id);
  assert.equal(restored.videoPrompt, "@分镜图/图1 @分镜图/图2\n\n人物连续完成动作。");
});

test("remembers removed intent references and clears the exclusion after a manual re-add", () => {
  const intentReference = {
    reference_kind: "project_asset",
    reference_id: "02f03a76-8603-48d3-b51e-df1b7ade3200",
    label: "资产/服装/白色睡衣",
    role: "appearance",
    order: 1,
    origin: "intent_explicit",
  };
  const removed = reconcileVideoDraftReferences({
    videoPrompt: "@资产/服装/白色睡衣\n替换服装。",
    videoPromptMentions: [intentReference],
    selectedReferences: [intentReference],
    inputSources: ["project_assets"],
    removedIntentReferenceKeys: [],
  }, {
    selectedReferences: [],
    removedReference: intentReference,
  });

  assert.deepEqual(removed.removedIntentReferenceKeys, [
    `project_asset:${intentReference.reference_id}`,
  ]);

  const manuallyReadded = reconcileVideoDraftReferences(removed, {
    selectedReferences: [{ ...intentReference, origin: "manual" }],
    addedReference: { ...intentReference, origin: "manual" },
  });
  assert.deepEqual(manuallyReadded.removedIntentReferenceKeys, []);
});

test("composes optional video inputs without exposing audio as a generation input", () => {
  assert.match(workspaceSource, /<GenerationReferenceComposer/);
  assert.match(generationReferenceComposerSource, /ReferencePickerPopover/);
  assert.doesNotMatch(workspaceSource, /image_prompt_mentions/);
  assert.match(generationReferenceComposerSource, /selectedReferenceItems/);
  assert.doesNotMatch(generationReferenceComposerSource, /已自动加入.*张分镜图.*与画面轨道同步/);
  assert.match(generationReferenceComposerSource, /恢复默认/);
  assert.match(generationReferenceComposerSource, /尚无生成参考/);
  assert.match(workspaceSource, /maximum_reference_images/);
  assert.match(workspaceSource, /不会自动丢弃参考/);
  assert.match(referencePickerSource, /选择托管人物/);
  assert.match(referencePickerSource, /创建或管理深度视频/);
  assert.match(referencePickerSource, /preferredWidth=\{480\}/);
  assert.match(referenceComposerStyles, /\.generation-reference-picker \.generation-reference-picker-heading h4\s*\{[^}]*font-size:\s*var\(--type-subheading-size\)/s);
  assert.doesNotMatch(referenceComposerStyles, /--reference-picker-(?:title|body|meta)-size/);
  assert.match(referenceComposerStyles, /grid-template-columns:\s*44px minmax\(0, 1fr\) 22px/);
  assert.match(referenceComposerStyles, /min-height:\s*56px/);
  assert.doesNotMatch(generationReferenceComposerSource, /id:\s*"audio"/);
  assert.doesNotMatch(workspaceSource, /shot-video-foundation-note/);
  assert.doesNotMatch(workspaceSource, /可组合生成输入/);
  assert.match(productionWorkflowSource, /input_plan:\s*\{/);
  assert.match(productionWorkflowSource, /sources:\s*Array\.from/);
});

test("recovers the video model catalog and exposes an actionable retry state", () => {
  assert.match(appSource, /videoSettingsLoadedRef/);
  assert.match(appSource, /async function loadVideoGenerationSettings/);
  assert.match(appSource, /retryCount = 2/);
  assert.match(appSource, /window\.addEventListener\("online", recoverVideoSettings\)/);
  assert.match(appSource, /videoSettingsLoadState !== "error"[\s\S]*5000/);
  assert.match(appSource, /videoGenerationSettingsStatus=\{videoSettingsLoadState\}/);
  assert.match(productionWorkflowSource, /onReloadVideoGenerationSettings/);
  assert.match(workspaceSource, /modelCatalogFailed/);
  assert.match(workspaceSource, /onReloadModels=\{onReloadVideoGenerationSettings\}/);
  assert.match(generationControlsSource, /modelCatalog\.missingProviderKey/);
  assert.match(modelPopoverSource, /data-model-retry/);
  assert.match(modelPopoverSource, /模型目录读取失败/);
  assert.match(modelPopoverSource, /模型目录刷新失败/);
});

test("uses one prompt editor role in image and video workspaces", () => {
  assert.match(videoPromptReferenceEditorSource, /className="prompt-editor-textarea"/);
  assert.match(imageWorkspaceSource, /className="prompt-editor-textarea"/);
  assert.match(workflowStyles, /\.production-workspace \.prompt-editor-textarea\s*\{[^}]*font-weight:\s*var\(--type-weight-regular\)/s);
});

test("distills candidate metadata and removes video negative-constraint editing", () => {
  assert.doesNotMatch(workspaceSource, /shot-video-negative-constraints|视频负面约束/);
  assert.doesNotMatch(workflowStyles, /\.shot-video-negative-constraints/);

  assert.doesNotMatch(workspaceSource, /Math\.round\(beat\.start_ratio \* 100\)/);
  assert.doesNotMatch(candidateLibrarySource, /<span>\{group\.candidates\.length\} 个<\/span>/);
  assert.match(candidateLibrarySource, /<strong>当前预览<\/strong>/);
  assert.match(candidateLibrarySource, /<span>\{generationRunCostLabel\(displayedRun\)\}<\/span>/);
  assert.doesNotMatch(candidateLibrarySource, /candidateModelLabel\(displayedRun\)|formatCandidateBatchTime\(displayedRun|formatVideoDuration\(displayedCandidate/);
  assert.doesNotMatch(candidateLibrarySource, /当前预览 · 视频 #/);
  assert.doesNotMatch(imageWorkspaceSource, /<span>\{group\.candidates\.length\} 张<\/span>/);
  assert.match(imageWorkspaceSource, /<strong>当前预览<\/strong>/);
  assert.doesNotMatch(imageWorkspaceSource, /当前预览 · 候选/);
});

test("associates the duration label, output and help text with the range input", () => {
  assert.match(settingsPopoverSource, /<label htmlFor=\{durationControlId\}>视频时长<\/label>/);
  assert.match(settingsPopoverSource, /<output htmlFor=\{durationControlId\}>/);
  assert.match(settingsPopoverSource, /id=\{durationControlId\}/);
  assert.match(settingsPopoverSource, /aria-describedby=\{durationHelpId\}/);
  assert.match(settingsPopoverSource, /className="video-duration-help"/);
});

test("constrains portrait media inside the preview so native video controls stay visible", () => {
  const frameRule = cssRule(".shot-video-media-frame");
  const mediaRule = workflowStyles.match(
    /\.shot-video-media-frame img,\s*\.shot-video-media-frame video\s*\{[^}]+\}/,
  )?.[0] || "";

  assert.match(frameRule, /grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(frameRule, /grid-template-rows:\s*minmax\(0, 1fr\)/);
  assert.match(frameRule, /overflow:\s*hidden/);
  assert.match(mediaRule, /min-width:\s*0/);
  assert.match(mediaRule, /min-height:\s*0/);
  assert.match(mediaRule, /max-width:\s*100%/);
  assert.match(mediaRule, /max-height:\s*100%/);
  assert.match(mediaRule, /object-fit:\s*contain/);
});

test("keeps candidate actions compact and overlays download on the video", () => {
  assert.match(workspaceSource, /className="shot-video-download-button"/);
  assert.match(generationControlsSource, /className="shot-video-command-cost"/);
  assert.doesNotMatch(workspaceSource, /className=\{`shot-video-run-card/);
  assert.doesNotMatch(workspaceSource, />下载<\/a>/);

  const downloadRule = cssRule(".shot-video-download-button");
  const actionRule = cssRule(".shot-video-command-actions", generationControlsStyles);
  assert.match(downloadRule, /position:\s*absolute/);
  assert.match(downloadRule, /top:\s*9px/);
  assert.match(downloadRule, /right:\s*9px/);
  assert.match(actionRule, /display:\s*flex/);
  assert.match(actionRule, /justify-content:\s*flex-end/);
});

test("auto-saves changed prompts with the returned revision before generating", () => {
  assert.match(productionWorkflowSource, /function videoPromptChangesFromDraft/);
  assert.match(
    productionWorkflowSource,
    /persistedShotDetail = await request\(`\/production-shots\/\$\{shotDetail\.plan\.id\}`[\s\S]*expectedRevisionId = persistedShotDetail\.current_revision_id[\s\S]*\/video-runs/,
  );
  assert.match(generationControlsSource, /生成前会自动保存当前提示词/);
  assert.doesNotMatch(generationControlsSource, /保存提示词/);
  assert.doesNotMatch(workspaceSource, /onSave/);
  assert.doesNotMatch(productionWorkflowSource, /async function saveVideoPrompt/);
  assert.match(productionWorkflowSource, /changes\.video_prompt_mentions/);
  assert.match(generationDraftSource, /videoPromptMentions/);
  assert.match(generationDraftSource, /setSaveState\("dirty"\)/);
  assert.match(workspaceSource, /<AutosaveStatus/);
  assert.match(workspaceSource, /draftSaveState/);
  assert.match(workspaceSource, /<small>\{videoDraft\.videoPrompt\.length\} 字<\/small>/);
  assert.match(videoPromptReferenceEditorSource, /onBlur=\{onBlur\}/);
  assert.doesNotMatch(workspaceSource, /含人工修改/);
});

test("binds readable prompt mentions to stable multimodal reference ids", () => {
  const projectAssetId = "0e65c993-3487-4ec6-9801-c9de5d72f4bb";
  const options = buildVideoReferenceOptions({
    assets: [{
      id: projectAssetId,
      name: "面部",
      folder_name: "小喵酱",
      type: "person",
      rights_confirmed: true,
      thumbnail_url: "/asset.jpg",
    }],
    managedAssetBinding: {
      id: "08c760fc-f454-41b0-b074-aa3895537a88",
      asset_id: "managed-person-1",
      name: "演员A",
      provider: "volc_ark",
      project_name: "default",
    },
  });
  const asset = options.find((item) => item.reference_kind === "project_asset");
  assert.equal(asset.label, "资产/小喵酱/面部");
  assert.equal(asset.role, "actor_identity");
  assert.equal(videoMentionToken(asset), "@资产/小喵酱/面部");
  assert.equal(requiredSourceForVideoMention(asset), "project_assets");
  const managed = options.find((item) => item.reference_kind === "provider_managed_asset");
  assert.deepEqual(buildManagedAssetReferenceOption(null), null);
  assert.equal(buildManagedAssetReferenceOption({
    id: "08c760fc-f454-41b0-b074-aa3895537a88",
    asset_id: "managed-person-1",
    name: "演员A",
    provider: "volc_ark",
    project_name: "default",
  }).reference_id, managed.reference_id);
  assert.deepEqual(selectedVideoReferenceOptions(options, [asset]), [asset]);
  assert.equal(
    managed.preview_url,
    "/api/v1/managed-assets/providers/volc_ark/assets/managed-person-1/preview",
  );
  assert.deepEqual(ensureVideoGenerationReference([], managed), [{
    reference_kind: "provider_managed_asset",
    reference_id: managed.reference_id,
    label: managed.label,
    role: "actor_identity",
    order: 1,
  }]);
  assert.equal(
    ensureVideoGenerationReference([managed], managed).length,
    1,
  );

  const prompt = "保持 @资产/小喵酱/面部 的身份，动作参考深度视频。";
  const normalized = normalizeVideoPromptMentions(prompt, [{
    reference_kind: asset.reference_kind,
    reference_id: asset.reference_id,
    label: asset.label,
    role: asset.role,
    order: 8,
  }], options);
  assert.equal(normalized.length, 1);
  assert.equal(normalized[0].reference_id, projectAssetId);
  assert.equal(normalized[0].order, 1);
  const detached = normalizeVideoPromptMentions("不显式书写引用别名", normalized, options);
  assert.equal(detached.length, 0);
  assert.equal(
    removeVideoMentionFromPrompt(prompt, normalized[0]),
    "保持 的身份，动作参考深度视频。",
  );

  const inserted = insertVideoMentionIntoPrompt("浅黄色短袖上衣@", {
    start: "浅黄色短袖上衣".length,
    end: "浅黄色短袖上衣@".length,
  }, asset);
  assert.equal(inserted.value, "浅黄色短袖上衣 @资产/小喵酱/面部 ");
  const highlighted = buildVideoPromptHighlightSegments(inserted.value, [asset]);
  assert.deepEqual(highlighted.map((item) => item.type), ["text", "mention", "text"]);
  assert.equal(highlighted[1].text, "@资产/小喵酱/面部");

  const atomicPrompt = "替换为 @托管角色/小喵酱，然后抬手。";
  const atomicMention = {
    reference_kind: managed.reference_kind,
    reference_id: managed.reference_id,
    label: "托管角色/小喵酱",
    role: managed.role,
    order: 1,
  };
  const tokenStart = atomicPrompt.indexOf("@托管角色/小喵酱");
  const tokenEnd = tokenStart + "@托管角色/小喵酱".length;
  assert.deepEqual(
    deleteVideoMentionAtSelection(atomicPrompt, [atomicMention], {
      key: "Backspace",
      selectionStart: tokenEnd,
      selectionEnd: tokenEnd,
    }),
    { value: "替换为，然后抬手。", cursor: tokenStart - 1 },
  );
  assert.deepEqual(
    deleteVideoMentionAtSelection(atomicPrompt, [atomicMention], {
      key: "Delete",
      selectionStart: tokenStart + 2,
      selectionEnd: tokenStart + 2,
    }),
    { value: "替换为，然后抬手。", cursor: tokenStart - 1 },
  );
  assert.deepEqual(
    deleteVideoMentionAtSelection(atomicPrompt, [atomicMention], {
      key: "Delete",
      selectionStart: tokenStart + 2,
      selectionEnd: tokenEnd - 2,
    }),
    { value: "替换为，然后抬手。", cursor: tokenStart - 1 },
  );
  assert.equal(
    deleteVideoMentionAtSelection(atomicPrompt, [atomicMention], {
      key: "Backspace",
      selectionStart: 2,
      selectionEnd: 2,
    }),
    null,
  );

  const depthReference = {
    reference_kind: "depth_control",
    reference_id: "77efbb39-8414-496d-bcd7-705482f36f25",
    label: "深度视频/分镜动作1",
    role: "depth",
    order: 1,
  };
  const managedReference = {
    reference_kind: managed.reference_kind,
    reference_id: managed.reference_id,
    label: "托管角色/小喵酱",
    role: managed.role,
    order: 2,
  };
  const systemConstraints = buildVideoReferenceSystemConstraints([
    depthReference,
    managedReference,
  ]);
  assert.equal(systemConstraints.length, 2);
  assert.match(systemConstraints[0].text, /保留强度以创作意图中的明确要求为准/);
  assert.match(systemConstraints[0].text, /未要求逐帧复刻时允许模型自然调整/);
  assert.match(systemConstraints[1].text, /唯一的人物身份来源/);
  assert.match(systemConstraints[1].text, /不得继承深度视频或其他参考画面中的人物身份/);
  assert.match(
    videoReferenceConflictPriority([depthReference, managedReference]),
    /人物身份以托管角色为准.*镜头关系以深度视频为准/,
  );
  const compiledPrompt = compileVideoPromptWithReferences(
    "人物在公园中抬手调整口罩。",
    [depthReference, managedReference],
  );
  assert.match(compiledPrompt, /用户视频提示词/);
  assert.match(compiledPrompt, /@深度视频\/分镜动作1/);
  assert.match(compiledPrompt, /@托管角色\/小喵酱/);
  assert.equal(
    stripLegacyVideoReferencePolicies(
      "@托管角色/小喵酱 是画面中唯一的人物身份来源。 人物的面部、年龄、发型、体型和身份特征必须来自该托管角色，不继承深度视频或其他参考画面中的人物身份。 @深度视频/分镜动作1 是唯一的动作、姿态、运动节奏、空间位置、镜头关系和遮挡转场来源。严格逐帧遵循深度视频中的身体姿态、手臂轨迹、动作顺序、速度、停顿、主体位置、景别变化和镜头运动。不得重新设计、简化、增加、删除、交换或提前任何动作。 【目标画面】 公园中的人物。",
    ),
    "【目标画面】 公园中的人物。",
  );

  assert.match(workspaceSource, /<VideoPromptReferenceEditor/);
  assert.match(workspaceSource, /<VideoPromptReferencePolicy/);
  assert.match(workspaceSource, /<GenerationReferenceComposer/);
  assert.match(workspaceSource, /<CreativeIntentPanel/);
  assert.match(workspaceSource, /compile-intent/);
  assert.match(workspaceSource, /intent_mentions:\s*videoDraft\.intentMentions/);
  assert.match(workspaceSource, /merge_strategy:\s*"replace_all"/);
  assert.match(workspaceSource, /restore-intent-baseline/);
  assert.match(workspaceSource, /className="shot-video-config-disclosure"/);
  assert.match(workspaceSource, /open=\{referenceSettingsOpen\}/);
  assert.match(workspaceSource, /open=\{promptSettingsOpen\}/);
  assert.match(workspaceSource, /reconcileVideoDraftReferences/);
  assert.match(workspaceSource, /videoPromptMentions/);
  assert.match(workspaceSource, /selectedReferences/);
  assert.match(videoPromptReferenceEditorSource, /className="video-prompt-highlight"/);
  assert.match(videoPromptReferenceEditorSource, /document\.addEventListener\("pointerdown"/);
  assert.match(videoPromptReferenceEditorSource, /aria-activedescendant/);
  assert.match(videoPromptReferenceEditorSource, /selectionActive \? " selecting"/);
  assert.match(videoPromptReferenceEditorSource, /onSelect=\{updateSelectionState\}/);
  assert.match(videoPromptReferenceEditorSource, /new ResizeObserver/);
  assert.match(videoPromptReferenceEditorSource, /textarea\.clientWidth \+ horizontalBorder/);
  assert.match(videoPromptReferenceEditorSource, /视频提示词快捷引用/);
  assert.match(videoPromptReferenceEditorSource, /aria-label="视频提示词"/);
  assert.doesNotMatch(videoPromptReferenceEditorSource, /<label[^>]*>视频提示词<\/label>/);
  assert.match(videoPromptReferenceEditorSource, /加入生成参考并插入提示词/);
  assert.match(videoPromptReferenceEditorSource, /deleteVideoMentionAtSelection/);
  assert.match(videoPromptReferenceEditorSource, /removedReferences/);
  assert.match(videoPromptReferenceEditorSource, /event\.nativeEvent\?\.isComposing/);
  assert.match(creativeIntentPanelSource, /<CreativeIntentMentionEditor/);
  assert.doesNotMatch(creativeIntentPanelSource, /说明要保留|输入 @ 可精确指定资产|TextModelIndicator|尚未生成/);
  assert.match(creativeIntentPanelSource, /video_intent_model_validation_failed/);
  assert.match(creativeIntentPanelSource, /提示词校验失败/);
  assert.match(creativeIntentPanelSource, /需要确认意图/);
  assert.doesNotMatch(creativeIntentPanelSource, /建议模型|creative-intent-model-note/);
  assert.match(workspaceSource, /intentRequirementsNeedAssets/);
  assert.match(workspaceSource, /仍有创作意图需要人工确认/);
  assert.match(creativeIntentMentionEditorSource, /buildVideoReferenceOptions/);
  assert.match(creativeIntentMentionEditorSource, /从托管资产目录选择/);
  assert.match(creativeIntentMentionEditorSource, /onRequestManagedAssetMention/);
  assert.match(workspaceSource, /buildManagedAssetReferenceOption\(savedBinding\)/);
  assert.match(workspaceSource, /pendingManagedAssetMentionRef/);
  assert.doesNotMatch(creativeIntentPanelSource, /interpretation\.summary/);
  assert.doesNotMatch(creativeIntentPanelSource, /creative-intent-result-copy/);
  assert.match(creativeIntentMentionEditorSource, /deleteVideoMentionAtSelection/);
  assert.match(creativeIntentMentionEditorSource, /event\.nativeEvent\?\.isComposing/);
  assert.match(creativeIntentMentionEditorSource, /createPortal\(menu, document\.body\)/);
  assert.match(creativeIntentMentionEditorSource, /explicit|失效|invalidMentions/);
  assert.match(generationDraftSource, /intent_mentions/);
  assert.match(videoPromptReferencePolicySource, /复制可编辑提示词/);
  assert.match(videoPromptReferencePolicySource, /复制模型输入/);
  assert.match(
    videoPromptReferencePolicyStyles,
    /\.video-reference-policy-actions button\.primary\s*\{[^}]*color:\s*var\(--text-on-accent\)/s,
  );
  assert.match(
    workflowStyles,
    /\.production-workspace \.video-reference-policy-actions button:not\(\.primary\)\s*\{[^}]*color:\s*var\(--text-primary\)/s,
  );
});

test("keeps provider failures in notifications and scopes model warnings", () => {
  assert.match(workspaceSource, /const latestFailedVideoRun = useMemo/);
  assert.match(workspaceSource, /failureAlias=\{latestFailedVideoRun\?\.model_alias \|\| ""\}/);
  assert.match(generationControlsSource, /failureAlias=\{failureAlias\}/);
  assert.match(generationControlsSource, /latestRun\?\.status === "cancelled"/);
  assert.doesNotMatch(workspaceSource, /videoGenerationFailureDetails\(latestRun\)/);
  assert.doesNotMatch(workspaceSource, /className="shot-video-generation-error"/);
  assert.doesNotMatch(workflowStyles, /\.shot-video-generation-error\s*\{/);
});

test("keeps video candidates from every generation batch selectable", () => {
  assert.match(workspaceSource, /const videoRuns = useMemo/);
  assert.match(workspaceSource, /const candidateGroups = useMemo/);
  assert.match(workspaceSource, /<VideoCandidateLibrary/);
  assert.match(candidateLibrarySource, /className="shot-candidate-library shot-video-candidate-library"/);
  assert.match(candidateLibrarySource, /历史 \{historicalCount\} 个/);
  assert.doesNotMatch(candidateLibrarySource, /可用 \{activeCandidates\.length\} 个|点击缩略图切换预览/);
  assert.doesNotMatch(candidateLibrarySource, /个批次/);
  assert.match(workspaceSource, /改用此视频/);
  assert.match(workspaceSource, /displayedCandidateRun\?\.model_display_name/);
  assert.doesNotMatch(
    workspaceSource,
    /\(latestRun\?\.candidates \|\| \[\]\)\.filter/,
  );
  assert.doesNotMatch(
    workspaceSource,
    /plan\.video_status === "approved" \|\| Boolean\(generationBlockedReason\)/,
  );
  assert.match(workspaceSource, /plan\.video_status !== "ready"/);
  assert.doesNotMatch(workspaceSource, /videoGenerationRunLabel|可人工调整/);
  assert.match(workspaceSource, /<strong>资产引用与控制<\/strong><small>\{selectedVideoReferences\.length\} 项<\/small>/);

  const libraryRule = cssRule(".shot-video-candidate-library");
  const thumbRule = cssRule(".shot-video-candidate-library .shot-candidate-thumb");
  assert.match(libraryRule, /margin-top:\s*10px/);
  assert.match(thumbRule, /position:\s*relative/);
  assert.match(thumbRule, /background:\s*#19191e/);
});

test("manages video candidate history through a recoverable recycle bin", () => {
  assert.match(workspaceSource, /const archivedCandidateGroups = useMemo/);
  assert.match(workspaceSource, /candidate\.archive_reason === "user_deleted"/);
  assert.match(candidateLibrarySource, /管理/);
  assert.match(candidateLibrarySource, /移入回收站/);
  assert.match(candidateLibrarySource, /回收站 \{archivedCandidates\.length\}/);
  assert.match(candidateLibrarySource, /恢复所选/);
  assert.match(candidateLibrarySource, /approved_video_candidate_id/);
  assert.match(candidateLibrarySource, /已采用，请先取消采用或改用其他视频/);
  assert.match(candidateLibrarySource, /候选文件会保留，可随时恢复/);
  assert.match(candidateLibrarySource, /全选可删除/);
  assert.match(candidateLibrarySource, /全选可恢复/);
  assert.match(candidateLibrarySource, /清空选择/);
  assert.doesNotMatch(candidateLibrarySource, /candidate-batch-selector/);
  assert.match(candidateLibraryStyles, /\.candidate-lifecycle-confirm\s*\{/);
  assert.match(candidateLibraryStyles, /\.shot-candidate-tile\.lifecycle-locked\s*\{/);
  assert.doesNotMatch(candidateLibraryStyles, /\.candidate-batch-selector/);
  assert.match(candidateLibraryStyles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(candidateLibrarySource, /window\.confirm|window\.prompt/);
});

test("lazy-loads one muted hover preview without changing candidate selection", () => {
  assert.match(candidateLibrarySource, /HOVER_PREVIEW_DELAY_MS = 180/);
  assert.match(candidateLibrarySource, /\(hover: hover\) and \(pointer: fine\)/);
  assert.match(candidateLibrarySource, /prefers-reduced-motion: reduce/);
  assert.match(candidateLibrarySource, /candidate\.content_url/);
  assert.match(candidateLibrarySource, /onPointerEnter=\{schedulePreview\}/);
  assert.match(candidateLibrarySource, /onPointerLeave=\{stopPreview\}/);
  assert.match(candidateLibrarySource, /className="shot-candidate-hover-video"/);
  assert.match(candidateLibrarySource, /loop\s+muted/);
  assert.match(candidateLibrarySource, /playsInline/);
  assert.match(candidateLibrarySource, /preload="auto"/);
  assert.match(candidateLibrarySource, /renderThumbnail\(candidate, !interactionBusy\)/);
  assert.match(candidateLibrarySource, /renderThumbnail\(candidate\)/);

  const hoverVideoRule = cssRule(".shot-candidate-hover-video", candidateLibraryStyles);
  assert.match(hoverVideoRule, /position:\s*absolute/);
  assert.match(hoverVideoRule, /object-fit:\s*contain/);
  assert.match(hoverVideoRule, /opacity:\s*0/);
  assert.match(hoverVideoRule, /pointer-events:\s*none/);
});

test("advances after approval and keeps editing controls in the video editor module", () => {
  assert.doesNotMatch(workspaceSource, /VideoPreparationPanel/);
  assert.doesNotMatch(workspaceSource, /gate\?\.prepared_shot_count/);
  assert.match(workspaceSource, /gate\?\.approved_shot_count/);
  assert.match(workspaceSource, /进入视频剪辑/);
  assert.match(videoEditorSource, /trim_in_seconds/);
  assert.match(videoEditorSource, /trim_out_seconds/);
  assert.match(videoEditorSource, /cover_timestamp_seconds/);
  assert.match(videoEditorSource, /audio_mode/);
  assert.match(videoEditorSource, /background_audio_track/);
  assert.match(timelineCanvasSource, /V1 视频/);
  assert.match(timelineCanvasSource, /A1 原音/);
  assert.match(timelineCanvasSource, /A2 附加/);
  assert.match(timelineCanvasSource, /T1 字幕/);
  assert.match(videoEditorSource, /timeline\/background-audio/);
});

test("removes automated continuity checks from entry to the editor", () => {
  assert.doesNotMatch(workspaceSource, /ContinuityQualityPanel/);
  assert.doesNotMatch(workspaceSource, /进入剪辑前，请人工检查/);
  assert.doesNotMatch(productionWorkflowSource, /continuity-reports/);
  assert.doesNotMatch(productionWorkflowSource, /ContinuityReport/);
  assert.doesNotMatch(productionWorkflowSource, /runContinuityCheck/);
  assert.doesNotMatch(productionWorkflowSource, /decideContinuityFinding/);
  assert.match(
    productionWorkflowSource,
    /async function advanceToEditing\(\)[\s\S]*target_step: "editing"/,
  );
  assert.doesNotMatch(workflowStyles, /\.shot-video-gate-summary\s*\{/);
});

test("shows clip quality warnings inside the independent editor inspector", () => {
  assert.match(videoEditorSource, /clip\.warning_messages/);
  assert.match(videoEditorSource, /timeline-quality-summary/);
  assert.match(videoEditorSource, /重新质检/);
  assert.doesNotMatch(videoEditorSource, /timeline-cover-field|封面帧必须位于入点和出点之间/);
  assert.match(videoEditorStyles, /\.timeline-quality-summary/);
});

test("submits approved visual beats without a duplicate storyboard preview", () => {
  assert.match(workspaceSource, /approvedVisualBeatFramesFromDetail/);
  assert.match(workspaceSource, /referenceFrames=\{referenceFrames\}/);
  assert.match(workspaceSource, /请先确认全部必需画面（\$\{approvedReferenceCount\}\/\$\{referenceFrames\.length\}）/);
  assert.match(workspaceSource, /!allReferencesApproved/);
  assert.doesNotMatch(workspaceSource, /function approvedImageCandidate/);
  assert.doesNotMatch(workspaceSource, /className="shot-video-preview-grid"/);
  assert.doesNotMatch(workspaceSource, /有序参考画面|有序多图参考故事板|shot-video-storyboard/);
  assert.doesNotMatch(workflowStyles, /\.shot-video-preview-stack|\.shot-video-storyboard/);
});

test("offers only models that declare an enabled reference route", () => {
  assert.match(workspaceSource, /capability\?\.image_to_video/);
  assert.match(workspaceSource, /capability\?\.reference_route\?\.enabled !== false/);
  assert.match(workspaceSource, /videoModels\.filter\(supportsReferenceRoute\)/);
  assert.match(modelPopoverSource, /configuredModels\.map/);
  assert.match(modelPopoverSource, /unconfiguredModels\.map/);
  assert.doesNotMatch(workspaceSource, /\{videoModels\.map\(/);
  assert.match(workspaceSource, /preferredVideoResolution\(model, current\.resolution\)/);
});

test("uses the same reference-route gate in model settings", () => {
  assert.match(appSource, /function supportsProductionVideoWorkflow/);
  assert.match(appSource, /model\.capabilities\?\.image_to_video/);
  assert.match(appSource, /model\.capabilities\?\.reference_route\?\.enabled !== false/);
  assert.match(appSource, /videoModelOptions\.filter\(/);
  assert.match(appSource, /selectableVideoModelOptions\.map/);
});

test("keeps visual beats compact while the system manages names and transitions", () => {
  assert.match(imageWorkspaceSource, /className="visual-beat-rail"/);
  assert.match(imageWorkspaceSource, /onReorderVisualBeats/);
  assert.match(imageWorkspaceSource, /onCreateVisualBeat/);
  assert.match(imageWorkspaceSource, /onDeleteVisualBeat/);
  assert.doesNotMatch(imageWorkspaceSource, /transition_to_next_type/);
  assert.doesNotMatch(imageWorkspaceSource, /transition_to_next_duration_seconds/);
  assert.doesNotMatch(imageWorkspaceSource, /画面名称|到下一画面|转场秒数/);

  const railRule = cssRule(".visual-beat-rail");
  assert.match(railRule, /display:\s*flex/);
  assert.match(railRule, /overflow-x:\s*auto/);
});

test("source-video shots bypass generation controls and remain reversible", () => {
  assert.match(workspaceSource, /plan\?\.output_mode === "source_video"/);
  assert.match(workspaceSource, /已沿用原视频/);
  assert.match(workspaceSource, /改为重新生成/);
  assert.match(workspaceSource, /!sourceVideoMode && <VideoCandidateLibrary/);
  assert.match(workspaceSource, /outputMode: "image_to_video"/);
});
