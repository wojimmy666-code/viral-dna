import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  filterNotifications,
  notificationToastPayload,
} from "../src/notification-ui.js";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const centerSource = readFileSync(
  new URL("../src/NotificationCenter.jsx", import.meta.url),
  "utf8",
);
const appStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

const notifications = [
  { id: "1", status: "in_progress", level: "info" },
  { id: "2", status: "succeeded", level: "success" },
  { id: "3", status: "failed", level: "error" },
];

test("filters the account feed into all, in-progress and failed views", () => {
  assert.equal(filterNotifications(notifications, "all").length, 3);
  assert.deepEqual(filterNotifications(notifications, "in_progress").map((item) => item.id), ["1"]);
  assert.deepEqual(filterNotifications(notifications, "failed").map((item) => item.id), ["3"]);
});

test("maps persisted failures to alert toasts without exposing raw response fields", () => {
  assert.deepEqual(
    notificationToastPayload({
      status: "failed",
      level: "error",
      title: "视频生成失败",
      message: "请检查模型设置。",
    }),
    {
      type: "error",
      title: "视频生成失败",
      message: "请检查模型设置。",
    },
  );
  assert.match(centerSource, /toast\.type === "error" \? "alert" : "status"/);
  assert.doesNotMatch(centerSource, /api[_-]?key|authorization|provider_response/i);
});

test("wires the top-bar bell to an account notification drawer and a three-toast stack", () => {
  assert.match(appSource, /notificationUnreadCount/);
  assert.match(appSource, /<NotificationDrawer/);
  assert.match(centerSource, /toasts\.slice\(-3\)/);
  assert.match(appStyles, /\.notification-drawer\s*\{/);
  assert.match(appStyles, /width:\s*min\(390px/);
});
