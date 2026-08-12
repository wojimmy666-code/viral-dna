import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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

test("keeps video generation fields on shared heading and control rows", () => {
  const optionsRule = cssRule(".shot-video-generation-options");
  const fieldRule = cssRule(".shot-video-generation-field");
  const durationRule = cssRule(".shot-video-duration-control");

  assert.match(optionsRule, /--shot-video-control-height:\s*48px/);
  assert.match(optionsRule, /--shot-video-heading-height:\s*24px/);
  assert.match(optionsRule, /align-items:\s*start/);
  assert.match(fieldRule, /grid-template-rows:\s*var\(--shot-video-heading-height\) var\(--shot-video-control-height\)/);
  assert.match(fieldRule, /align-content:\s*start/);
  assert.match(fieldRule, /align-self:\s*start/);
  assert.match(durationRule, /height:\s*var\(--shot-video-control-height\)/);
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
  assert.match(workspaceSource, /<label htmlFor=\{durationControlId\}>生成时长<\/label>/);
  assert.match(workspaceSource, /<output htmlFor=\{durationControlId\}>/);
  assert.match(workspaceSource, /id=\{durationControlId\}/);
  assert.match(workspaceSource, /aria-describedby=\{durationHelpId\}/);
  assert.match(workspaceSource, /className="shot-video-duration-meta"/);
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
  assert.match(workspaceSource, /className="shot-video-cost-summary"/);
  assert.doesNotMatch(workspaceSource, /className=\{`shot-video-run-card/);
  assert.doesNotMatch(workspaceSource, />下载<\/a>/);

  const downloadRule = cssRule(".shot-video-download-button");
  const actionRule = cssRule(".shot-video-prompt-actions");
  assert.match(downloadRule, /position:\s*absolute/);
  assert.match(downloadRule, /top:\s*9px/);
  assert.match(downloadRule, /right:\s*9px/);
  assert.match(actionRule, /flex-wrap:\s*wrap/);
});

test("shows actionable provider failures and hides unsafe direct retry", () => {
  assert.match(workspaceSource, /videoGenerationFailureDetails\(latestRun\)/);
  assert.match(workspaceSource, /className="shot-video-generation-error" role="alert"/);
  assert.match(workspaceSource, /打开模型设置/);
  assert.match(workspaceSource, /技术详情/);
  assert.match(workspaceSource, /复制诊断信息/);
  assert.match(workspaceSource, /latestFailure\.retryable/);
  assert.match(workspaceSource, /latestRun\?\.status === "cancelled"/);
  assert.match(workflowStyles, /\.shot-video-generation-error\s*\{/);
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

test("offers only models that declare ordered multi-image capability", () => {
  assert.match(workspaceSource, /capability\?\.multi_image_reference/);
  assert.match(workspaceSource, /capability\?\.ordered_reference_images/);
  assert.match(workspaceSource, /videoModels\.filter\(supportsOrderedMultiImage\)/);
  assert.match(workspaceSource, /compatibleVideoModels\.map/);
  assert.doesNotMatch(workspaceSource, /\{videoModels\.map\(/);
  assert.match(workspaceSource, /preferredVideoResolution\(model, current\.resolution\)/);
});

test("uses the same ordered multi-image gate in model settings", () => {
  assert.match(appSource, /function supportsProductionVideoWorkflow/);
  assert.match(appSource, /model\.capabilities\?\.multi_image_reference/);
  assert.match(appSource, /model\.capabilities\?\.ordered_reference_images/);
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
