import test from "node:test";
import assert from "node:assert/strict";
import { formatStorage, historyOffset, quotaBytes, storageRatio } from "../src/accounts/storage-ui.js";

test("storage uses one decimal-byte definition for default limits and admin input", () => {
  assert.equal(formatStorage(2_000_000_000), "2 GB");
  assert.equal(formatStorage(10_000_000_000), "10 GB");
  assert.equal(quotaBytes("2.5"), 2_500_000_000);
  assert.equal(formatStorage(0), "0 B");
  for (const value of ["", "-1", "NaN", "Infinity", "100001"]) assert.throws(() => quotaBytes(value));
});

test("capacity gauge includes reservations and safely caps overage", () => {
  assert.equal(storageRatio({ limit_bytes: 100, used_bytes: 70, reserved_bytes: 20 }), 90);
  assert.equal(storageRatio({ limit_bytes: 100, used_bytes: 110, reserved_bytes: 0 }), 100);
  assert.equal(storageRatio(null), 0);
});

test("removing the last row on a page returns to existing history", () => {
  assert.equal(historyOffset(31, 30), 30);
  assert.equal(historyOffset(30, 30), 0);
  assert.equal(historyOffset(0, 60), 0);
  assert.equal(historyOffset(61, 90), 60);
});
