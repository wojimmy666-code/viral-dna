import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildRecordListParams,
  normalizeRecordLifecycle,
  recordActionSuccessMessage,
  recordBatchActions,
} from "../src/record-lifecycle-ui.js";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const appStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("record lifecycle falls back to active and is sent to the list API", () => {
  assert.equal(normalizeRecordLifecycle("unknown"), "active");
  const params = buildRecordListParams({
    query: "  演示视频  ",
    folder: "unfiled",
    status: "completed",
    lifecycle: "archived",
    page: 2,
    pageSize: 50,
  });
  assert.equal(params.get("q"), "演示视频");
  assert.equal(params.get("folder_id"), "unfiled");
  assert.equal(params.get("status"), "completed");
  assert.equal(params.get("lifecycle"), "archived");
  assert.equal(params.get("page"), "2");
  assert.equal(params.get("page_size"), "50");
});

test("each lifecycle exposes the correct batch actions", () => {
  assert.deepEqual(
    recordBatchActions("active").map((item) => item.action),
    ["archive", "trash"],
  );
  assert.deepEqual(
    recordBatchActions("archived").map((item) => item.action),
    ["activate", "trash"],
  );
  assert.deepEqual(
    recordBatchActions("trashed").map((item) => item.action),
    ["restore", "purge"],
  );
});

test("record actions return concise account-notification copy", () => {
  assert.equal(recordActionSuccessMessage("archive", 2), "2 条记录已归档");
  assert.equal(recordActionSuccessMessage("trash", 1), "1 条记录已移入回收站");
  assert.equal(recordActionSuccessMessage("purge", 3), "3 条记录已永久删除");
});

test("keeps the dense list count in the page title without a duplicate result heading", () => {
  assert.match(appSource, /className="history-title-line"/);
  assert.match(appSource, /className="history-scope-filter"/);
  assert.doesNotMatch(appSource, /history-result-heading/);
  assert.match(appStyles, /\.record-table-row\s*\{[\s\S]*?min-height:\s*96px/);
});
