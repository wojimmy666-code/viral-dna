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

function cssRule(selector) {
  const start = workflowStyles.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS rule for ${selector}`);
  const end = workflowStyles.indexOf("}", start);
  return workflowStyles.slice(start, end + 1);
}

test("keeps video generation fields on shared heading and control rows", () => {
  const optionsRule = cssRule(".shot-video-generation-options");
  const fieldRule = cssRule(".shot-video-generation-field");
  const durationRule = cssRule(".shot-video-duration-control");

  assert.match(optionsRule, /--shot-video-control-height:\s*44px/);
  assert.match(optionsRule, /--shot-video-heading-height:\s*22px/);
  assert.match(optionsRule, /align-items:\s*start/);
  assert.match(fieldRule, /grid-template-rows:\s*var\(--shot-video-heading-height\) var\(--shot-video-control-height\)/);
  assert.match(fieldRule, /align-content:\s*start/);
  assert.match(fieldRule, /align-self:\s*start/);
  assert.match(durationRule, /height:\s*var\(--shot-video-control-height\)/);
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
