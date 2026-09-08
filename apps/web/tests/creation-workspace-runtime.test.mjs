import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parse } from "@babel/parser";
import { SKILL_WORKFLOW_STAGES, stageState } from "../src/skill-workflow/skill-workflow-ui.js";
import { readOnce } from "../src/creation-workspace/read-request.js";
import { productionGateStatusPath } from "../src/production-ui.js";

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
    productionGateStatusPath,
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

for (const skill of [false, true]) {
  test(`${skill ? "Skill" : "analysis"} advances only the selected video subset after flushing`, async () => {
    const scope = productionScope(), events = [];
    scope.detail = { project: { id: "p" } };
    scope.workflow = skill ? { videosApproved: false, onAdvance: async () => { events.push("skill-approve"); } } : null;
    scope.executeAction = action => action();
    scope.flushWorkspace = async () => { events.push("save"); };
    scope.request = async (path, options) => {
      if (path.endsWith("gate-status?step=shot_videos")) {
        events.push("video-gate"); return {allowed: true, selected_video_count: 1};
      }
      if (options?.method === "POST") { events.push("advance"); return {}; }
      return {project: {current_revision_id: "latest", active_step: "shot_videos"}};
    };
    scope.refreshProject = scope.onProjectsChanged = async () => {};
    scope.setActiveSection = section => { scope.activeSection = section; };
    scope.onNotice = () => {};
    await productionHandler("advanceToEditing", scope)();
    assert.deepEqual(events, ["save", "video-gate", ...(skill ? ["skill-approve"] : []), "advance"]);
    assert.equal(scope.activeSection, "editing");
  });
  test(`${skill ? "Skill" : "analysis"} zero selected videos cannot bypass a past approval`, async () => {
    const scope = productionScope();
    scope.detail = {project: {id:"p",active_step:"editing"}};
    scope.workflow = skill ? {videosApproved:true} : null;
    scope.executeAction = action => action();
    scope.request = async path => {
      assert.ok(path.endsWith("?step=shot_videos"));
      return {allowed:false,selected_video_count:0,blocker_messages:["请至少选择一个视频"]};
    };
    await assert.rejects(productionHandler("advanceToEditing", scope)(), /至少选择一个/);
    assert.equal(scope.activeSection,"shot_images");
  });
}

test("reordering and editing selection flush drafts and use the saved revision", async () => {
  for (const [name,args,pathKey] of [["reorderShots",[["b","a"]],"/shots/order"],["changeEditingSelection",["b",false],"/editing-selection"]]) {
    const scope = productionScope(), events = [];
    scope.detail = {project:{id:"p",current_revision_id:"old"}};
    scope.executeAction = action => action();
    scope.flushWorkspace = async () => events.push("save");
    scope.request = async (path,options) => {
      if (!options) { events.push("revision"); return {project:{current_revision_id:"saved"}}; }
      assert.ok(path.endsWith(pathKey));
      assert.equal(JSON.parse(options.body).expected_revision_id,"saved");
      events.push("update");
    };
    scope.refreshProject = async () => events.push("refresh"); scope.onNotice = () => {};
    await productionHandler(name,scope)(...args);
    assert.deepEqual(events,["save","revision","update","refresh"]);
    scope.flushWorkspace = async () => { throw new Error("save failed"); };
    scope.request = () => assert.fail("must not mutate after a failed save");
    await assert.rejects(productionHandler(name,scope)(...args), /save failed/);
  }
});

for (const skill of [false, true]) {
  test(`${skill ? "Skill" : "analysis"} advances with one adopted picture and checks the image gate after saving`, async () => {
    const scope = productionScope();
    const events = [];
    scope.detail = { project: { id: "p" } };
    scope.workflow = skill ? { imagesApproved: false, onAdvance: async () => { events.push("skill-approve"); } } : null;
    scope.executeAction = (action) => action();
    scope.flushWorkspace = async () => { events.push("save"); };
    scope.request = async (path, options) => {
      if (path.endsWith("gate-status?step=shot_images")) {
        events.push("image-gate");
        return { allowed: true, approved_image_count: 1, required_shot_count: 15 };
      }
      if (options?.method === "POST") { events.push("advance"); return {}; }
      return { project: { current_revision_id: "latest", active_step: "shot_images" } };
    };
    scope.refreshProject = async (...args) => { assert.equal(args[3], "shot_videos"); };
    scope.onProjectsChanged = async () => {};
    scope.setActiveSection = (section) => { scope.activeSection = section; };
    scope.onNotice = () => {};
    await productionHandler("advanceWorkflow", scope)();
    assert.deepEqual(events, ["save", "image-gate", ...(skill ? ["skill-approve"] : []), "advance"]);
    assert.equal(scope.activeSection, "shot_videos");
  });

  test(`${skill ? "Skill" : "analysis"} refuses zero adopted pictures even when a prior stage approval exists`, async () => {
    const scope = productionScope();
    scope.detail = { project: { id: "p", active_step: "shot_videos" } };
    scope.workflow = skill ? { imagesApproved: true, onAdvance: async () => assert.fail("must not approve") } : null;
    scope.executeAction = (action) => action();
    scope.request = async (path, options) => {
      assert.ok(path.endsWith("gate-status?step=shot_images"));
      assert.equal(options, undefined);
      return { allowed: false, approved_image_count: 0, blocker_messages: ["请至少采用一张分镜图"] };
    };
    await assert.rejects(productionHandler("advanceWorkflow", scope)(), /请至少采用一张分镜图/);
    assert.equal(scope.activeSection, "shot_images");
  });
}

test("batch refresh uses verified picture counts rather than aggregate shot status", async () => {
  const scope = productionScope();
  const nextGate = { project_id: "p", current_step: "shot_images", allowed: true, approved_image_count: 1 };
  scope.request = async (path) => path.endsWith("/navigation")
    ? [{ plan: { id: "a", image_status: "ready", required: false } }]
    : nextGate;
  await productionHandler("refreshImageBatchResults", scope)([]);
  assert.deepEqual(scope.gate, nextGate);
});

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
    draftChoice: null, setChoice: () => {}, setDialogOpen: () => {},
    pendingRequest: { current: null }, callbacks: { current: { onFlush: async () => {} } },
    setWorking: () => {}, setError: () => {}, setPreview: () => {}, accept: async () => {},
    imageChoicePayload: (_settings, _ratio, value) => ({ model_alias: value.model, resolution: value.resolution, candidate_count: 4 }),
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
  assert.equal(first.candidate_count, 1);
  scope.choice = { model: "qwen_image_2", resolution: "1080x1920" };
  await prepare();
  assert.deepEqual(calls.at(-1).body, first);
  assert.equal(calls.filter(c => c.path.endsWith("/preview")).length, 1);
  await prepare();
  assert.notEqual(calls.at(-1).body.request_id, first.request_id);
  assert.equal(calls.at(-1).body.model_alias, "qwen_image_2");
  assert.equal(calls.at(-1).body.mode, "all");
  assert.equal(calls.at(-1).body.candidate_count, 1);
});

test("selecting an image refreshes selection without a toast or implicit approval", async () => {
  const calls = [];
  let refreshed = false;
  let projectsChanged = false;
  const scope = {
    detail: { project: { id: "p", current_revision_id: "revision" } }, selectedShotId: "s",
    executeAction: (action) => action(),
    request: async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); },
    refreshProject: async () => { refreshed = true; },
    onProjectsChanged: async () => { projectsChanged = true; },
    onNotice: () => assert.fail("selection must not raise a success toast"),
  };
  await productionHandler("selectCandidate", scope)("candidate");
  assert.deepEqual(calls, [{ path: "/generation-candidates/candidate/select", body: { expected_revision_id: "revision" } }]);
  assert.ok(refreshed && projectsChanged);
});

test("running-image polling updates each candidate and thumbnail without resetting prompt drafts", async () => {
  const source = readFileSync(new URL("../src/ProductionWorkflow.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const declarations = ast.program.body.map(node => node.declaration || node);
  const owner = declarations.find(node => node.id?.name === "ProductionHub");
  const call = owner.body.body.find(node => node.expression?.callee?.name === "useEffect"
    && source.slice(node.start, node.end).includes("async function pollGenerationRun"));
  const effect = call.expression.arguments[0];
  const upsert = declarations.find(node => node.id?.name === "upsertGenerationRun");
  const scheduled = [];
  const requests = [];
  const plan = { id: "s", image_prompt: "局部提示词原文" };
  const scope = {
    activeGenerationRun: { id: "run", status: "running", candidates: [] },
    selectedProjectId: "p", selectedShotId: "s",
    ACTIVE_GENERATION_RUN_STATUSES: new Set(["running"]), readOnce,
    upsertGenerationRun: new Function(`return (${source.slice(upsert.start, upsert.end)});`)(),
    shotDetail: { plan, generation_runs: [] }, shots: [{ plan }, { plan: { id: "other" } }],
    window: { setTimeout: fn => scheduled.push(fn), clearTimeout: () => {} },
    refreshProject: () => assert.fail("partial images must not reload the project"),
    hydrateShotDraft: () => assert.fail("partial images must not overwrite prompt drafts"),
    request: async path => {
      requests.push(path);
      if (path === "/generation-runs/run") return { id: "run", kind: "image", status: "running",
        shot_plan_id: "s", candidates: [{ id: "first-image" }] };
      assert.equal(path, "/productions/p/shots/navigation");
      return [{ plan, image_preview: { candidate_id: "first-image", thumbnail_url: "/first.webp" } }];
    },
  };
  scope.setShotDetail = update => { scope.shotDetail = update(scope.shotDetail); };
  scope.setShots = update => { scope.shots = update(scope.shots); };
  const start = new Function("scope", `with (scope) { return (${source.slice(effect.start, effect.end)}); }`)(scope);
  const dispose = start();
  await scheduled.shift()();
  assert.equal(scope.shotDetail.generation_runs[0].candidates[0].id, "first-image");
  assert.equal(scope.shots[0].image_preview.candidate_id, "first-image");
  assert.equal(scope.shots[0].plan, plan);
  assert.equal(scope.shotDetail.plan, plan);
  await scheduled.shift()();
  assert.equal(requests.filter(path => path.endsWith("/navigation")).length, 1,
    "unchanged heartbeats must not refresh thumbnails again");
  dispose();
});
