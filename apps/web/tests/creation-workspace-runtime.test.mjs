import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parse } from "@babel/parser";
import { SKILL_WORKFLOW_STAGES, stageState } from "../src/skill-workflow/skill-workflow-ui.js";
import { readOnce } from "../src/creation-workspace/read-request.js";

// Execute the real event handlers with isolated state/network boundaries. This
// exercises async behavior, not screenshots or a substitute for browser QA.
function handler(file, component, name, scope) {
  const source = readFileSync(new URL(file, import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const owner = ast.program.body.map((node) => node.declaration || node).find((node) => node.id?.name === component);
  const fn = owner.body.body.find((node) => node.type === "FunctionDeclaration" && node.id.name === name);
  assert.ok(fn, `${component}.${name} must remain covered`);
  return new Function("scope", `with (scope) { return (${source.slice(fn.start, fn.end)}); }`)(scope);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function productionScope() {
  const scope = {
    shotRequestId: { current: 0 },
    projectRefreshRequestId: { current: 0 },
    shotSelectionPending: { current: false },
    selectedProjectId: "p",
    selectedShotId: "a",
    selectedVisualBeatId: "beat-a",
    focusedCandidateId: "candidate-a",
    activeSection: "shot_images",
    shotCache: { current: new Map() },
    shots: [],
    imageGenerationSettings: {},
    readOnce,
    actionError: "",
    shotDetail: { plan: { id: "a" } },
    workflow: null,
    videoGenerationSettings: {},
    flushWorkspace: async () => {},
    updateLocation: () => {},
    restoreLocation: () => {},
    settingsFromProject: () => ({}),
    visualBeatFromDetail: (detail) => ({ id: `beat-${detail.plan.id}` }),
    hydrateShotDraft: () => {}, hydrateVideoDraft: () => {}, resetShotDraft: () => {}, resetVideoDraft: () => {},
    refreshAnalysisUpdate: async () => {},
    request: async (path) => {
      if (path === "/productions/p") return { project: { id: "p" } };
      if (path === "/productions/p/shots") return ["a", "b", "c"].map((id) => ({ plan: { id } }));
      if (path.startsWith("/production-shots/") && !path.endsWith("draft")) return { plan: { id: path.split("/")[2] } };
      return {};
    },
  };
  for (const key of ["SelectedShotId", "FocusedCandidateId", "ActionError", "ImpactReview", "ShotDetail", "SelectedVisualBeatId", "Detail", "Assets", "Revisions", "Shots", "Gate", "GenerationSettings", "SettingsDraft"]) {
    scope[`set${key}`] = (value) => { scope[key[0].toLowerCase() + key.slice(1)] = value; };
  }
  return scope;
}

const productionHandler = (name, scope) => handler("../src/ProductionWorkflow.jsx", "ProductionHub", name, scope);
const skillHandler = (name, scope) => handler("../src/skill-workflow/SkillExperience.jsx", "SkillProjectWorkspace", name, scope);

test("a failed shot request retains the prior shot and preview", async () => {
  const scope = productionScope();
  scope.request = async () => { throw new Error("offline"); };
  await productionHandler("selectShot", scope)("b");
  assert.equal(scope.selectedShotId, "a");
  assert.equal(scope.shotDetail.plan.id, "a");
  assert.equal(scope.focusedCandidateId, "candidate-a");
  assert.equal(scope.actionError, "offline");
});

test("background refresh cannot cancel an in-flight user shot selection", async () => {
  const scope = productionScope();
  const secondShot = deferred();
  const originalRequest = scope.request;
  scope.request = (path) => path === "/production-shots/b" ? secondShot.promise : originalRequest(path);
  const selecting = productionHandler("selectShot", scope)("b");
  await Promise.resolve();
  await productionHandler("refreshProject", scope)("p", "a", "beat-a");
  secondShot.resolve({ plan: { id: "b" } });
  await selecting;
  assert.equal(scope.selectedShotId, "b");
  assert.equal(scope.shotDetail.plan.id, "b");
});

test("a late failure from an old selection cannot replace the current error state", async () => {
  const scope = productionScope();
  const secondShot = deferred();
  const originalRequest = scope.request;
  scope.request = (path) => path === "/production-shots/b" ? secondShot.promise : originalRequest(path);
  const select = productionHandler("selectShot", scope);
  const selectingB = select("b");
  await Promise.resolve();
  await select("c");
  secondShot.reject(new Error("old request failed"));
  await selectingB;
  assert.equal(scope.selectedShotId, "c");
  assert.equal(scope.actionError, "");
});

test("audio approval must finish pending timeline saves before deciding which revision to approve", async () => {
  const events = [];
  const scope = {
    workspace: { production_project_id: "p", timeline: { id: "old-skill", source_timeline_revision_id: "old" }, mix_revision: { id: "old-mix", validation_status: "passed" }, run: { run: { current_stage: "audio_caption" }, gates: [] } },
    productionTimeline: { revision_id: "old" },
    SKILL_WORKFLOW_STAGES, stageState,
    productionWorkspaceRef: { current: { flush: async () => { events.push("save"); return { revision_id: "new" }; } } },
    request: async () => ({ revision_id: "new" }),
    setProductionTimeline: () => {}, setError: () => {},
    finalizeAudioCaption: async () => { events.push("finalize-new"); return { timeline: { id: "new-skill" }, mix_revision: { id: "new-mix", validation_status: "passed" } }; },
    decideGate: async (_gate, _decision, ids) => { events.push(ids); },
  };
  await skillHandler("confirmAudioCaption", scope)();
  assert.deepEqual(events, ["save", "finalize-new", ["new-skill", "new-mix"]]);
});

test("batch retry reuses the submitted snapshot; a later explicit click starts a new full batch", async () => {
  const calls = [];
  let loseReply = true;
  const scope = {
    base: "/productions/p/image-batches", projectId: "p", settings: {}, aspectRatio: "9:16",
    choice: { model: "local_tool", resolution: "720x1280" },
    pendingRequest: { current: null }, callbacks: { current: { onFlush: async () => {} } },
    setWorking: () => {}, setError: () => {}, setPreview: () => {}, accept: async () => {},
    imageChoicePayload: (_settings, _ratio, value) => ({ model_alias: value.model, resolution: value.resolution }),
    request: async (path, options) => {
      calls.push({ path, body: options?.body && JSON.parse(options.body) });
      if (path.endsWith("/preview")) return { items: [] };
      if (path === "/productions/p") return { project: { current_revision_id: "revision" } };
      if (loseReply) { loseReply = false; throw new Error("reply lost"); }
      return { status: "completed" };
    },
  };
  const prepare = handler("../src/image-generation-controls/ImageBatchToolbar.jsx", "ImageBatchToolbar", "prepare", scope);
  await prepare();
  const first = calls.at(-1).body;
  assert.equal(first.mode, "all");
  scope.choice = { model: "qwen_image_2", resolution: "1080x1920" };
  await prepare();
  assert.deepEqual(calls.at(-1).body, first);
  assert.equal(calls.filter(c => c.path.endsWith("/preview")).length, 1);
  await prepare();
  assert.notEqual(calls.at(-1).body.request_id, first.request_id);
  assert.equal(calls.at(-1).body.model_alias, "qwen_image_2");
  assert.equal(calls.at(-1).body.mode, "all");
});
