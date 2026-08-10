import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspaceSource = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
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
const preparationSource = readFileSync(
  new URL("../src/VideoPreparationPanel.jsx", import.meta.url),
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

function cssRule(selector) {
  const start = workflowStyles.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS rule for ${selector}`);
  const end = workflowStyles.indexOf("}", start);
  return workflowStyles.slice(start, end + 1);
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
  assert.match(readableSection, /\.video-preparation-status,/);
  assert.match(
    readableSection,
    /\.production-workspace :is\([\s\S]*?\.video-preparation-status,[\s\S]*?\)\s*\{[\s\S]*?font-size:\s*var\(--production-type-caption\)/,
  );
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
  assert.match(workspaceSource, /historicalCandidateGroups/);
  assert.match(workspaceSource, /className="shot-candidate-library shot-video-candidate-library"/);
  assert.match(workspaceSource, /历史 \{historicalCandidateCount\} 个/);
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

test("requires approved videos to complete an explicit editing preparation", () => {
  assert.match(workspaceSource, /<VideoPreparationPanel/);
  assert.match(workspaceSource, /gate\?\.prepared_shot_count/);
  assert.match(preparationSource, /trim_in_seconds:\s*draft\.trimIn/);
  assert.match(preparationSource, /trim_out_seconds:\s*draft\.trimOut/);
  assert.match(preparationSource, /cover_timestamp_seconds:\s*draft\.cover/);
  assert.match(preparationSource, /audio_mode:\s*draft\.audioMode/);
  assert.match(preparationSource, /className="video-preparation-audio"/);

  const bodyRule = cssRule(".video-preparation-body");
  const coverRule = cssRule(".video-preparation-cover-frame");
  assert.match(bodyRule, /grid-template-columns:/);
  assert.match(coverRule, /overflow:\s*hidden/);
});

test("shows duration alignment risk as a non-blocking preparation warning", () => {
  assert.match(preparationSource, /preparation\?\.warning_messages\?\.length/);
  assert.match(preparationSource, /可交接 · 有提示/);
  assert.match(preparationSource, /className="video-preparation-warnings"/);
  assert.match(workflowStyles, /\.video-preparation-warnings/);
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
