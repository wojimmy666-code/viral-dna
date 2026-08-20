import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const sourceDirectory = path.resolve(testDirectory, "../src");
const baseStyles = readFileSync(path.join(sourceDirectory, "styles.css"), "utf8");
const workflowStyles = readFileSync(
  path.join(sourceDirectory, "production-workflow.css"),
  "utf8",
);
const videoGenerationStyles = readFileSync(
  path.join(sourceDirectory, "shot-video-generation-controls.css"),
  "utf8",
);
const imageWorkspace = readFileSync(
  path.join(sourceDirectory, "ShotImageWorkspace.jsx"),
  "utf8",
);
const videoWorkspace = readFileSync(
  path.join(sourceDirectory, "ShotVideoWorkspace.jsx"),
  "utf8",
);
const systemPrimitives = readFileSync(
  path.join(sourceDirectory, "ui/system/SystemPrimitives.jsx"),
  "utf8",
);
const designContract = readFileSync(
  path.resolve(testDirectory, "../DESIGN.md"),
  "utf8",
);

function cssFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return cssFiles(target);
    return entry.isFile() && entry.name.endsWith(".css") ? [target] : [];
  });
}

const stylesheets = cssFiles(sourceDirectory).map((file) => ({
  file: path.relative(sourceDirectory, file),
  source: readFileSync(file, "utf8"),
}));

function cssRule(source, selector, { last = false } = {}) {
  const start = last
    ? source.lastIndexOf(`${selector} {`)
    : source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS rule for ${selector}`);
  const end = source.indexOf("}", start);
  return source.slice(start, end + 1);
}

function declarations(source, property) {
  const pattern = new RegExp(`(?<![-\\w])${property}:\\s*([^;}]+)`, "g");
  return [...source.matchAll(pattern)].map((match) => match[1].trim());
}

test("defines the system-wide four-size and two-weight product scale", () => {
  assert.match(baseStyles, /--font-family-ui:/);
  assert.match(baseStyles, /--type-caption-size:\s*0\.75rem/);
  assert.match(baseStyles, /--type-label-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-body-size:\s*0\.875rem/);
  assert.match(baseStyles, /--type-subheading-size:\s*1rem/);
  assert.match(baseStyles, /--type-heading-size:\s*1rem/);
  assert.match(baseStyles, /--type-page-size:\s*1\.25rem/);
  assert.match(baseStyles, /--type-weight-regular:\s*400/);
  assert.match(baseStyles, /--type-weight-semibold:\s*600/);
  assert.match(baseStyles, /--type-weight-bold:\s*600/);
  assert.doesNotMatch(baseStyles, /font-family:\s*Inter/);
});

test("defines two ordinary text levels plus explicit state colors", () => {
  assert.match(baseStyles, /--text-primary:\s*#25232d/i);
  assert.match(baseStyles, /--text-secondary:\s*#6b6b76/i);
  assert.match(baseStyles, /--text-disabled:\s*#9b9ba5/i);
  assert.match(baseStyles, /--status-success-text:/);
  assert.match(baseStyles, /--status-warning-text:/);
  assert.match(baseStyles, /--status-danger-text:/);
  assert.match(baseStyles, /--status-info-text:/);
});

test("keeps every stylesheet on semantic typography and text-color tokens", () => {
  const allowedSizes = new Set([
    "0",
    "inherit",
    "var(--type-caption-size)",
    "var(--type-label-size)",
    "var(--type-body-size)",
    "var(--type-subheading-size)",
    "var(--type-heading-size)",
    "var(--type-page-size)",
  ]);
  const allowedWeights = new Set([
    "var(--type-weight-regular)",
    "var(--type-weight-semibold)",
    "var(--type-weight-bold)",
  ]);
  const allowedColors = new Set([
    "inherit",
    "transparent",
    "CanvasText",
    "HighlightText",
  ]);

  for (const { file, source } of stylesheets) {
    for (const value of declarations(source, "font-size")) {
      assert.ok(allowedSizes.has(value), `${file} uses non-system font-size: ${value}`);
    }
    for (const value of declarations(source, "font-weight")) {
      assert.ok(allowedWeights.has(value), `${file} uses non-system font-weight: ${value}`);
    }
    for (const value of declarations(source, "color")) {
      assert.ok(
        value.startsWith("var(") || allowedColors.has(value),
        `${file} uses a literal text color: ${value}`,
      );
    }
    assert.doesNotMatch(source, /(?<![-\w])font:\s*[^;]*(?:px|rem)/);
    for (const value of declarations(source, "letter-spacing")) {
      assert.equal(value, "normal", `${file} uses non-system letter-spacing: ${value}`);
    }
    for (const value of declarations(source, "text-transform")) {
      assert.notEqual(value, "uppercase", `${file} uses uppercase UI scaffolding`);
    }
    assert.doesNotMatch(
      source,
      /var\(--(?:purple|purple-dark|purple-soft|purple-border|ink|muted|faint|line|panel|canvas|green|orange|red|text-tertiary)\)/,
    );
    assert.doesNotMatch(source, /--production-(?:type|text|leading)-/);
  }
});

test("uses the same global prompt editor role for image and video", () => {
  assert.match(imageWorkspace, /className="prompt-editor-textarea"/);
  assert.match(videoWorkspace, /className="prompt-editor-textarea"/);

  const rule = cssRule(
    workflowStyles,
    ".production-workspace .prompt-editor-textarea",
  );
  assert.match(rule, /font-size:\s*var\(--type-body-size\)/);
  assert.match(rule, /font-weight:\s*var\(--type-weight-regular\)/);
  assert.match(rule, /line-height:\s*var\(--type-leading-editor\)/);
  assert.match(rule, /padding:\s*10px 12px/);
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

test("ships reusable system primitives and a durable design contract", () => {
  assert.match(systemPrimitives, /export function PageShell/);
  assert.match(systemPrimitives, /export function PageHeader/);
  assert.match(systemPrimitives, /export function SurfacePanel/);
  assert.match(systemPrimitives, /export function StatusBadge/);
  assert.match(systemPrimitives, /export function InlineMessage/);
  assert.match(designContract, /## Typography \/ 排版/);
  assert.match(designContract, /## Engineering rules \/ 工程约束/);
  assert.match(designContract, /1440\/1280\/1024\/768\/390px/);
});
