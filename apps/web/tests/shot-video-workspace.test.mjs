import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  videoCandidateCountOptions,
  videoModelCatalogUiState,
  videoOutputSummary,
} from "../src/video-generation-controls/video-generation-ui.js";
import {
  videoDraftFromDetail,
  videoDraftParameters,
} from "../src/video-generation-controls/useShotVideoGenerationDraft.js";
import {
  buildVideoPromptHighlightSegments,
  buildVideoReferenceOptions,
  insertVideoMentionIntoPrompt,
  normalizeVideoPromptMentions,
  selectedVideoReferenceOptions,
  removeVideoMentionFromPrompt,
  requiredSourceForVideoMention,
  videoMentionToken,
} from "../src/video-inputs/video-prompt-references.js";

const workspaceSource = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const continuityPanelSource = readFileSync(
  new URL("../src/ContinuityQualityPanel.jsx", import.meta.url),
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
    workflowStyles.indexOf("/* ViralDNA Typography System 1.0"),
  );

  assert.match(baseStyles, /--type-caption-size:\s*0\.75rem/);
  assert.match(baseStyles, /--type-label-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-body-size:\s*1rem/);
  assert.match(readableSection, /\.production-workspace\s*\{/);
  assert.match(readableSection, /font-size:\s*var\(--production-type-body\)/);
  assert.match(readableSection, /\.production-workspace \.prompt-editor-textarea\s*\{[^}]*font-size:\s*var\(--production-type-body\)/s);
  assert.match(readableSection, /\.production-export-status/);
  assert.doesNotMatch(readableSection, /font-size:\s*(?:7|8|9|10|11)px/);
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
  assert.match(settingsPopoverSource, /生成前自动保存提示词与负面约束/);
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

test("keeps selected generation references separate from prompt mentions", () => {
  const reference = {
    reference_kind: "approved_image",
    reference_id: "5e098a85-7bd7-4b35-97bc-17397a3f1f48",
    label: "分镜图/图1-动作",
    role: "composition",
    order: 1,
  };
  const detail = {
    plan: {
      duration_seconds: 3,
      video_prompt: "保持构图和动作。",
      video_prompt_mentions: [reference],
    },
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
  assert.deepEqual(restored.videoPromptMentions, []);
  assert.deepEqual(videoDraftParameters(restored).input_plan.references, [reference]);

  const mentioned = videoDraftFromDetail({
    plan: {
      ...detail.plan,
      video_prompt: "保持 @分镜图/图1-动作 的构图和动作。",
    },
  }, settings, { input_plan: { sources: ["approved_images"], references: [reference] } });
  assert.deepEqual(mentioned.videoPromptMentions, [reference]);
});

test("composes optional video inputs without exposing audio as a generation input", () => {
  assert.match(workspaceSource, /<GenerationReferenceComposer/);
  assert.match(generationReferenceComposerSource, /ReferencePickerPopover/);
  assert.match(generationReferenceComposerSource, /selectedReferenceItems/);
  assert.match(generationReferenceComposerSource, /未添加媒体参考，将按文生视频生成/);
  assert.match(referencePickerSource, /选择托管人物/);
  assert.match(referencePickerSource, /创建或管理深度视频/);
  assert.match(referencePickerSource, /preferredWidth=\{480\}/);
  assert.match(referenceComposerStyles, /--reference-picker-title-size:\s*0\.875rem/);
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
  assert.match(workspaceSource, /className="prompt-editor-textarea"/);
  assert.match(imageWorkspaceSource, /className="prompt-editor-textarea"/);
  assert.match(workflowStyles, /\.production-workspace \.prompt-editor-textarea\s*\{[^}]*font-weight:\s*var\(--type-weight-regular\)/s);
});

test("distills repeated candidate metadata and progressively reveals negative constraints", () => {
  assert.match(workspaceSource, /<details className="shot-video-negative-constraints">/);
  assert.match(workspaceSource, /<summary>视频负面约束（可选）<\/summary>/);
  assert.doesNotMatch(
    workspaceSource,
    /<details className="shot-video-negative-constraints"[^>]*\sopen(?:=|>)/,
  );
  assert.match(workspaceSource, /aria-label="视频负面约束"/);
  assert.match(workflowStyles, /\.shot-video-negative-constraints summary\s*\{/);

  assert.doesNotMatch(workspaceSource, /Math\.round\(beat\.start_ratio \* 100\)/);
  assert.doesNotMatch(candidateLibrarySource, /<span>\{group\.candidates\.length\} 个<\/span>/);
  assert.match(candidateLibrarySource, /<strong>当前预览<\/strong>/);
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
  assert.deepEqual(selectedVideoReferenceOptions(options, [asset]), [asset]);
  assert.equal(
    managed.preview_url,
    "/api/v1/managed-assets/providers/volc_ark/assets/managed-person-1/preview",
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

  assert.match(workspaceSource, /<VideoPromptReferenceEditor/);
  assert.match(workspaceSource, /<GenerationReferenceComposer/);
  assert.match(workspaceSource, /requiredInputSource/);
  assert.match(workspaceSource, /videoPromptMentions/);
  assert.match(workspaceSource, /selectedReferences/);
  assert.match(videoPromptReferenceEditorSource, /className="video-prompt-highlight"/);
  assert.match(videoPromptReferenceEditorSource, /document\.addEventListener\("pointerdown"/);
  assert.match(videoPromptReferenceEditorSource, /aria-activedescendant/);
  assert.match(videoPromptReferenceEditorSource, /selectionActive \? " selecting"/);
  assert.match(videoPromptReferenceEditorSource, /onSelect=\{updateSelectionState\}/);
  assert.match(videoPromptReferenceEditorSource, /new ResizeObserver/);
  assert.match(videoPromptReferenceEditorSource, /textarea\.clientWidth \+ horizontalBorder/);
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
  assert.match(videoEditorSource, /V1 视频/);
  assert.match(videoEditorSource, /A1 原音/);
  assert.match(videoEditorSource, /A2 附加/);
  assert.match(videoEditorSource, /T1 字幕/);
  assert.match(videoEditorSource, /timeline\/background-audio/);
});

test("checks adjacent-shot continuity before entering the editor", () => {
  assert.match(workspaceSource, /<ContinuityQualityPanel/);
  assert.match(continuityPanelSource, /跨分镜连续性/);
  assert.match(continuityPanelSource, /规则检查完成/);
  assert.match(continuityPanelSource, /尚未执行 VLM 视觉验证/);
  assert.match(continuityPanelSource, /标记为有意变化/);
  assert.match(continuityPanelSource, /重新打开/);
  assert.match(productionWorkflowSource, /continuity-reports\/latest/);
  assert.match(
    productionWorkflowSource,
    /async function loadContinuityReport[\s\S]*error\?\.status === 404[\s\S]*return null/,
  );
  assert.match(
    productionWorkflowSource,
    /Promise\.all\([\s\S]*loadContinuityReport\(projectId\)/,
  );
  assert.match(productionWorkflowSource, /async function runContinuityCheck/);
  assert.match(productionWorkflowSource, /async function decideContinuityFinding/);
  assert.match(
    productionWorkflowSource,
    /async function advanceToEditing\(\)[\s\S]*continuity-reports[\s\S]*target_step: "editing"/,
  );
  assert.match(workflowStyles, /\.continuity-quality-panel\s*\{/);
  assert.match(workflowStyles, /\.continuity-quality-findings\s*\{/);
});

test("shows clip quality warnings inside the independent editor inspector", () => {
  assert.match(videoEditorSource, /clip\.warning_messages/);
  assert.match(videoEditorSource, /timeline-quality-summary/);
  assert.match(videoEditorSource, /重新质检/);
  assert.doesNotMatch(videoEditorSource, /timeline-cover-field|封面帧必须位于入点和出点之间/);
  assert.match(videoEditorStyles, /\.timeline-quality-summary/);
});

test("submits approved visual beats as an explicit ordered storyboard", () => {
  assert.match(workspaceSource, /function approvedVisualBeatFrames/);
  assert.match(workspaceSource, /className="shot-video-preview-stack"/);
  assert.match(workspaceSource, /className="shot-video-storyboard"/);
  assert.match(workspaceSource, /图\{beat\.index\}/);
  assert.match(workspaceSource, /\{approvedReferenceCount\}\/\{referenceFrames\.length\}/);
  assert.match(workspaceSource, /!allReferencesApproved/);
  assert.doesNotMatch(workspaceSource, /function approvedImageCandidate/);
  assert.doesNotMatch(workspaceSource, /className="shot-video-preview-grid"/);

  const previewStackRule = cssRule(".shot-video-preview-stack");
  const storyboardRule = cssRule(".shot-video-storyboard");
  const figureRule = cssRule(".shot-video-storyboard figure");
  const imageRule = cssRule(".shot-video-storyboard-image");
  const transitionRule = cssRule(".shot-video-storyboard-transition");

  assert.match(previewStackRule, /grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(previewStackRule, /align-items:\s*start/);
  assert.match(previewStackRule, /gap:\s*16px/);
  assert.match(storyboardRule, /display:\s*flex/);
  assert.match(storyboardRule, /height:\s*auto/);
  assert.match(storyboardRule, /align-items:\s*flex-start/);
  assert.match(storyboardRule, /overflow-x:\s*auto/);
  assert.match(storyboardRule, /scroll-snap-type:\s*x proximity/);
  assert.match(figureRule, /width:\s*clamp\(108px, 11vw, 144px\)/);
  assert.match(imageRule, /height:\s*clamp\(128px, 14vw, 168px\)/);
  assert.match(transitionRule, /width:\s*32px/);
  assert.doesNotMatch(workflowStyles, /height:\s*min\(58vh, 360px\)/);
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

test("keeps visual beats compact, ordered and independently editable", () => {
  assert.match(imageWorkspaceSource, /className="visual-beat-rail"/);
  assert.match(imageWorkspaceSource, /onReorderVisualBeats/);
  assert.match(imageWorkspaceSource, /onCreateVisualBeat/);
  assert.match(imageWorkspaceSource, /onDeleteVisualBeat/);
  assert.match(imageWorkspaceSource, /transition_to_next_type/);
  assert.match(imageWorkspaceSource, /transition_to_next_duration_seconds/);

  const railRule = cssRule(".visual-beat-rail");
  assert.match(railRule, /display:\s*flex/);
  assert.match(railRule, /overflow-x:\s*auto/);
});
