import assert from "node:assert/strict";
import test from "node:test";

import { inferVideoOrientation } from "../src/video-layout.js";

test("infers portrait and landscape from media dimensions", () => {
  assert.equal(inferVideoOrientation({ width: 720, height: 1280 }), "portrait");
  assert.equal(inferVideoOrientation({ width: 1920, height: 1080 }), "landscape");
});

test("treats near-square media as square", () => {
  assert.equal(inferVideoOrientation({ width: 1080, height: 1080 }), "square");
  assert.equal(inferVideoOrientation({ width: 1000, height: 1040 }), "square");
});

test("falls back to the report aspect ratio and then landscape", () => {
  assert.equal(inferVideoOrientation({ aspectRatio: "9:16" }), "portrait");
  assert.equal(inferVideoOrientation({ aspectRatio: "1 / 1" }), "square");
  assert.equal(inferVideoOrientation({ aspectRatio: "invalid" }), "landscape");
});
