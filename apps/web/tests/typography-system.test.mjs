import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const baseStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const workflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);
const videoGenerationStyles = readFileSync(
  new URL("../src/shot-video-generation-controls.css", import.meta.url),
  "utf8",
);
const assetStyles = readFileSync(
  new URL("../src/asset-library.css", import.meta.url),
  "utf8",
);
const platformStyles = readFileSync(
  new URL("../src/platform-connections.css", import.meta.url),
  "utf8",
);
const imageWorkspace = readFileSync(
  new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
  "utf8",
);
const videoWorkspace = readFileSync(
  new URL("../src/ShotVideoWorkspace.jsx", import.meta.url),
  "utf8",
);
const typographyGuide = readFileSync(
  new URL("../../../docs/ViralDNA_UI字体与响应式布局规范.md", import.meta.url),
  "utf8",
);

function cssRule(source, selector, { last = false } = {}) {
  const start = last
    ? source.lastIndexOf(`${selector} {`)
    : source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS rule for ${selector}`);
  const end = source.indexOf("}", start);
  return source.slice(start, end + 1);
}

test("defines one rem-based semantic type system", () => {
  assert.match(baseStyles, /--font-family-ui:/);
  assert.match(baseStyles, /--type-caption-size:\s*0\.75rem/);
  assert.match(baseStyles, /--type-label-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-body-size:\s*1rem/);
  assert.match(baseStyles, /--type-subheading-size:\s*1\.125rem/);
  assert.match(baseStyles, /--type-heading-size:\s*1\.25rem/);
  assert.match(baseStyles, /--type-page-size:\s*1\.5rem/);
  assert.doesNotMatch(baseStyles, /font-family:\s*Inter/);
});

test("keeps every page stylesheet at or above the caption floor", () => {
  const stylesheets = [baseStyles, workflowStyles, assetStyles, platformStyles];

  for (const stylesheet of stylesheets) {
    assert.doesNotMatch(stylesheet, /font-size:\s*(?:7|8|9|10|11)px/);
    assert.doesNotMatch(
      stylesheet,
      /font-weight:\s*(?:500|650|730|750|800|850|900);/,
    );
  }
});

test("uses the same explicit prompt editor role for image and video", () => {
  assert.match(imageWorkspace, /className="prompt-editor-textarea"/);
  assert.match(videoWorkspace, /className="prompt-editor-textarea"/);

  const rule = cssRule(
    workflowStyles,
    ".production-workspace .prompt-editor-textarea",
  );
  assert.match(rule, /font-size:\s*var\(--production-type-body\)/);
  assert.match(rule, /font-weight:\s*var\(--type-weight-regular\)/);
  assert.match(rule, /line-height:\s*var\(--production-leading-editor\)/);
  assert.match(rule, /max-width:\s*100%/);
});

test("binds responsive video controls to the real editor pane", () => {
  const editorRule = cssRule(workflowStyles, ".shot-video-editor", { last: true });
  const commandRule = cssRule(videoGenerationStyles, ".shot-video-generation-command");
  const commandBarRule = cssRule(videoGenerationStyles, ".shot-video-command-bar");

  assert.match(editorRule, /container-type:\s*inline-size/);
  assert.match(commandRule, /container-type:\s*inline-size/);
  assert.match(commandBarRule, /grid-template-areas:\s*"model summary cost actions"/);
  assert.match(videoGenerationStyles, /@container \(max-width: 680px\)/);
  assert.match(videoGenerationStyles, /@container \(max-width: 480px\)/);
  assert.match(videoGenerationStyles, /@media \(max-width: 620px\)/);
});

test("keeps essential export values visible instead of ellipsizing them", () => {
  const summaryRule = cssRule(workflowStyles, ".production-export-summary");
  const valueRule = cssRule(workflowStyles, ".production-export-summary strong");

  assert.match(summaryRule, /repeat\(auto-fit, minmax\(min\(100%, 10rem\), 1fr\)\)/);
  assert.match(valueRule, /white-space:\s*normal/);
  assert.match(valueRule, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(valueRule, /text-overflow:\s*ellipsis/);
});

test("documents type roles, truncation policy and responsive acceptance", () => {
  assert.match(typographyGuide, /## 3\. 语义字阶/);
  assert.match(typographyGuide, /## 7\. 截断策略/);
  assert.match(typographyGuide, /浏览器 125%、150%、200% 缩放/);
  assert.match(typographyGuide, /不得使用低于 12px 的文字/);
});
