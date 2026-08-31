import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const thumbnailSource = readFileSync(
  new URL("../src/ShotNavigationThumbnail.jsx", import.meta.url),
  "utf8",
);
const imageWorkspaceSource = readFileSync(
  new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
  "utf8",
);
const videoWorkspaceSource = readFileSync(
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

test("shows complete lazy-loaded shot thumbnails with a stable fallback", () => {
  assert.match(thumbnailSource, /loading="lazy"/);
  assert.match(thumbnailSource, /decoding="async"/);
  assert.match(thumbnailSource, /alt=""/);
  assert.match(thumbnailSource, /setSourceIndex\(\(current\) => current \+ 1\)/);
  assert.match(thumbnailSource, /shot-navigation-thumbnail-fallback/);

  const thumbnailRule = cssRule(".shot-navigation-thumbnail");
  const imageRule = cssRule(".shot-navigation-thumbnail img");
  assert.match(thumbnailRule, /width:\s*52px/);
  assert.match(thumbnailRule, /height:\s*52px/);
  assert.match(imageRule, /object-fit:\s*contain/);
});

test("uses phase-aware thumbnail fallback order in both shot lists", () => {
  const imagePreviewPosition = imageWorkspaceSource.indexOf("item.image_preview");
  const imageSourcePosition = imageWorkspaceSource.indexOf("shot.source_keyframe_url");
  assert.ok(imagePreviewPosition >= 0);
  assert.ok(imageSourcePosition > imagePreviewPosition);

  const videoPreviewPosition = videoWorkspaceSource.indexOf("item.video_preview");
  const approvedImagePosition = videoWorkspaceSource.indexOf("item.image_preview");
  const videoSourcePosition = videoWorkspaceSource.indexOf("plan.source_keyframe_url");
  assert.ok(videoPreviewPosition >= 0);
  assert.ok(approvedImagePosition > videoPreviewPosition);
  assert.ok(videoSourcePosition > approvedImagePosition);
});

test("overlays the shot number instead of consuming another list column", () => {
  assert.match(thumbnailSource, /shot-navigation-index-badge/);
  assert.doesNotMatch(imageWorkspaceSource, /<span className="shot-navigation-index">/);
  assert.doesNotMatch(videoWorkspaceSource, /<span className="shot-video-index">/);
  assert.match(
    cssRule(".shot-navigation-main"),
    /grid-template-columns:\s*52px minmax\(0, 1fr\)/,
  );
  assert.match(
    cssRule(".shot-navigation-item"),
    /grid-template-columns:\s*auto minmax\(0, 1fr\) auto/,
  );
});
