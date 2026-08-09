import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  forgetRecordThumbnailLoaded,
  recordThumbnailInitialState,
  rememberRecordThumbnailLoaded,
} from "../src/record-thumbnail-ui.js";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const appStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("remembers loaded thumbnails across record-page remounts", () => {
  const imageUrl = "/api/v1/records/example/thumbnail?v=1";

  assert.equal(recordThumbnailInitialState(""), "missing");
  assert.equal(recordThumbnailInitialState(imageUrl), "loading");
  rememberRecordThumbnailLoaded(imageUrl);
  assert.equal(recordThumbnailInitialState(imageUrl), "loaded");
  forgetRecordThumbnailLoaded(imageUrl);
  assert.equal(recordThumbnailInitialState(imageUrl), "loading");
});

test("keeps existing rows mounted during a background record refresh", () => {
  assert.match(appSource, /loading && records\.length === 0 \? \(/);
  assert.match(appSource, /useLayoutEffect\(\(\) => \{/);
  assert.match(appSource, /aria-busy=\{loading\}/);
});

test("crossfades the thumbnail skeleton instead of exposing the empty background", () => {
  assert.match(
    appStyles,
    /\.record-thumbnail-skeleton\s*\{[\s\S]*?transition:\s*opacity 180ms ease/,
  );
  assert.match(appStyles, /\.record-thumbnail\.loaded \.record-thumbnail-skeleton\s*\{\s*opacity:\s*0/);
});
