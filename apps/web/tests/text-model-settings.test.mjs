import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  TEXT_MODEL_PURPOSES,
  effectiveTextModelAlias,
  effectiveTextModelLabel,
  normalizeTextModelOverrides,
} from "../src/settings/text-model-settings.js";

const SETTINGS_URL = new URL("../src/settings/UserSettingsPage.jsx", import.meta.url);
const APP_URL = new URL("../src/App.jsx", import.meta.url);
const REPLICATION_URL = new URL(
  "../src/viral-report/ReplicationWorkspace.jsx",
  import.meta.url,
);
const IMAGE_WORKSPACE_URL = new URL("../src/ShotImageWorkspace.jsx", import.meta.url);
const INTENT_PANEL_URL = new URL(
  "../src/video-intents/CreativeIntentPanel.jsx",
  import.meta.url,
);

test("resolves the account default and per-task text model labels", () => {
  const preferences = {
    settings: {
      text_model_alias: "qwen37",
      text_model_task_overrides: { video_prompt: "qwen36flash" },
    },
    text_models: [
      { alias: "qwen37", label: "Qwen3.7 Plus" },
      { alias: "qwen36flash", label: "Qwen3.6 Flash" },
    ],
  };

  assert.equal(
    effectiveTextModelAlias(preferences, TEXT_MODEL_PURPOSES.shotImagePrompt),
    "qwen37",
  );
  assert.equal(
    effectiveTextModelLabel(preferences, TEXT_MODEL_PURPOSES.replicationPlan),
    "Qwen3.7 Plus",
  );
  assert.equal(
    effectiveTextModelLabel(preferences, TEXT_MODEL_PURPOSES.videoPrompt),
    "Qwen3.6 Flash",
  );
  assert.deepEqual(
    normalizeTextModelOverrides({ video_prompt: "qwen37", replication_plan: "" }),
    { video_prompt: "qwen37" },
  );
});

test("settings expose one default, fallback control, and collapsed task overrides", async () => {
  const source = await readFile(SETTINGS_URL, "utf8");

  assert.match(source, /文案与提示词模型/);
  assert.match(source, /默认文案模型/);
  assert.match(source, /不影响图片生成模型和视频生成模型。/);
  assert.match(source, /text_model_fallback_enabled/);
  assert.match(source, /<details className="text-model-task-overrides">/);
  assert.match(source, /按任务分别设置/);
  assert.match(source, /项已覆盖/);
  assert.doesNotMatch(source, /在设置中修改/);
});

test("copy-generation model indicators stay off image and video prompt editors", async () => {
  const [app, replication, imageWorkspace, intentPanel] = await Promise.all([
    readFile(APP_URL, "utf8"),
    readFile(REPLICATION_URL, "utf8"),
    readFile(IMAGE_WORKSPACE_URL, "utf8"),
    readFile(INTENT_PANEL_URL, "utf8"),
  ]);

  assert.match(app, /TEXT_MODEL_PURPOSES\.replicationPlan/);
  assert.match(app, /TEXT_MODEL_PURPOSES\.shotImagePrompt/);
  assert.match(app, /TEXT_MODEL_PURPOSES\.videoPrompt/);
  assert.match(replication, /<TextModelIndicator label=\{textModelLabel\}/);
  assert.doesNotMatch(imageWorkspace, /TextModelIndicator|文案模型：/);
  assert.doesNotMatch(intentPanel, /TextModelIndicator|文案模型：/);
  assert.doesNotMatch(`${replication}${imageWorkspace}${intentPanel}`, /在设置中修改/);
});
