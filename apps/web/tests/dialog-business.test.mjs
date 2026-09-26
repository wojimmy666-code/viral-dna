import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parse } from '@babel/parser';
import traverseModule from '@babel/traverse';
import { createDialogController } from '../src/ui/system/dialog-state.js';

const traverse = traverseModule.default || traverseModule;
function handler(file, name, scope) {
  const source = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8'); let fn;
  traverse(parse(source, { sourceType: 'module', plugins: ['jsx'] }), { FunctionDeclaration(item) { if (item.node.id?.name === name) fn = item.node; } });
  assert.ok(fn, name);
  return new Function('scope', `with(scope) { return (${source.slice(fn.start, fn.end)}); }`)(scope);
}
function fixture() {
  const calls = [], notices = []; let decision = null;
  const controller = createDialogController({ getScope: () => 'project:shot', getInput: () => 'reviewed', captureAuthority: () => 'lease', checkAuthority: () => true, notify: value => { decision = value; } });
  const plan = { id: 'shot', index: 2, duration_seconds: 5, video_status: 'pending' }, beat = { id: 'beat', index: 3 };
  const scope = {
    shotDetail: { plan, generation_runs: [] }, detail: { project: { id: 'project', current_revision_id: 'rev-before' } },
    selectedVisualBeatId: 'beat', shotDraft: {}, workflow: null,
    shotDraftPatch: () => ({ activeBeat: beat, beatChanges: {}, shotChanges: {} }),
    generationSettings: { enabled: true, local_cost_source: 'unknown', allow_unknown_local_image_cost: false },
    generationResolution: '1536x864', generationCandidateCount: 2, generationEngine: 'local_tool', generationModelAlias: 'remote-image', generationBaseImageId: '', generationInputMode: 'text_to_image',
    videoDraft: { candidateCount: 2, durationSeconds: 5, modelAlias: 'video-model', resolution: '1080P', inputSources: ['shot_images'] },
    videoGenerationSettings: { models: [{ alias: 'video-model', label: '本次所选视频模型', pricing: { kind: 'provider_usage_tokens' } }] },
    videoPromptChangesFromDraft: () => ({}), videoInputModeFromDraft: () => 'image_to_video',
    resolveImageExecutionMode: () => scope.generationEngine,
    actionDialog: { open: options => controller.open(options) },
    flushGlobalPrompts: async () => { calls.push({ draft: 'global' }); },
    flushShotDraft: async () => ({ plan, current_revision_id: 'rev-saved' }),
    flushVideoDraft: async () => {},
    visualBeatFromDetail: () => beat, imageBindingsForDraft: () => [], resolveImageInputMode: () => 'text_to_image', imageBaseCandidateId: () => null, imageGenerationIntentForShot: () => 'standard',
    setShotDetail: () => {}, setDetail: () => {}, setShots: () => {}, upsertGenerationRun: value => value, setActionError: () => {},
    onProjectsChanged: async () => {}, onNotificationsChanged: async () => {}, onNotice: value => notices.push(value),
    request: async (url, options) => { calls.push({ url, body: JSON.parse(options.body), method: options.method }); return { id: 'run' }; },
    executeAction: async (action, throwOnError) => { try { await action(); } catch (error) { if (throwOnError) throw error; } },
  };
  return { scope, calls, notices, controller, decision: () => decision };
}
test('real image handler: open/cancel writes nothing in original-video and Skill workspaces', async () => {
  for (const workflow of [null, { section: 'shot_images' }]) {
    const f = fixture(); f.scope.workflow = workflow;
    const pending = handler('ProductionWorkflow.jsx', 'generateShotCandidates', f.scope)();
    assert.equal(f.calls.length, 0); assert.equal(f.decision().kind, 'generation');
    assert.match(f.decision().warning, /不代表免费/); assert.equal(f.decision().confirmLabel, '生成 2 张');
    f.controller.cancel(); assert.equal(await pending, false); assert.equal(f.calls.length, 0);
  }
});
test('real image handler: confirmed request uses reviewed count, size and saved revision exactly once', async () => {
  const f = fixture(); const pending = handler('ProductionWorkflow.jsx', 'generateShotCandidates', f.scope)();
  const work = f.controller.submit(); await f.controller.submit(); await work; await pending;
  const writes = f.calls.filter(item => item.url); assert.equal(writes.length, 1);
  assert.equal(writes[0].url, '/production-shots/shot/image-runs');
  assert.deepEqual(writes[0].body, { expected_revision_id: 'rev-saved', visual_beat_id: 'beat', candidate_count: 2, input_mode: 'text_to_image', base_image_candidate_id: null, execution_mode: 'local_tool', model_alias: 'local_tool', allow_unknown_cost: true, width: 1536, height: 864, generation_intent: 'standard' });
});
test('known image costs and explicit existing unknown-cost permission do not acquire extra dialogs', async () => {
  for (const settings of [{ local_cost_source: 'configured_rate' }, { allow_unknown_local_image_cost: true }]) {
    const f = fixture(); Object.assign(f.scope.generationSettings, settings);
    await handler('ProductionWorkflow.jsx', 'generateShotCandidates', f.scope)();
    assert.equal(f.decision(), null); assert.equal(f.calls.filter(item => item.url).length, 1);
  }
});
test('real video handler: usage pricing disclosure, reviewed parameters, and no confirmation on known price', async () => {
  const f = fixture(); const generate = handler('ProductionWorkflow.jsx', 'generateVideoCandidates', f.scope);
  const pending = generate({ type: 'click' }); assert.equal(f.calls.length, 0); assert.match(f.decision().warning, /实际用量/);
  assert.equal(f.decision().details.find(([name]) => name === '模型')[1], '本次所选视频模型');
  await f.controller.submit(); await pending;
  const writes = f.calls.filter(item => item.url); assert.equal(writes.length, 1);
  assert.equal(writes[0].body.candidate_count, 2); assert.equal(writes[0].body.model_alias, 'video-model'); assert.equal(writes[0].body.duration_seconds, 5); assert.equal(writes[0].body.resolution, '1080P'); assert.equal(writes[0].body.allow_unknown_cost, true);
  f.scope.videoGenerationSettings.models[0].pricing.kind = 'fixed'; await generate();
  assert.equal(f.decision(), null); assert.equal(f.calls.filter(item => item.url).length, 2);
});
test('unknown video price is not misrepresented as known provider usage pricing', async () => {
  const f = fixture(); f.scope.videoGenerationSettings.models = [];
  const pending = handler('ProductionWorkflow.jsx', 'generateVideoCandidates', f.scope)();
  assert.match(f.decision().warning, /暂无可靠/); assert.doesNotMatch(f.decision().warning, /该模型按供应商实际用量结算/);
  f.controller.cancel(); await pending;
});
test('accepted image run followed by refresh failure never resubmits; preflight failure has zero generation writes', async () => {
  const f = fixture(); f.scope.onProjectsChanged = async () => { throw new Error('刷新失败'); };
  const pending = handler('ProductionWorkflow.jsx', 'generateShotCandidates', f.scope)();
  await f.controller.submit(); await f.controller.submit(); await pending;
  assert.equal(f.calls.filter(item => item.url).length, 1);
  const p = fixture(); p.scope.flushGlobalPrompts = async () => { throw new Error('草稿未保存'); };
  const preparation = handler('ProductionWorkflow.jsx', 'generateShotCandidates', p.scope)();
  await p.controller.submit(); assert.equal(p.calls.length, 0); assert.match(p.decision().error, /草稿未保存/);
  p.controller.cancel(); await preparation;
});
test('real project rename uses the captured project ID and trimmed dialog value', async () => {
  const f = fixture(); Object.assign(f.scope, { apiRequest: f.scope.request, refreshHistory: async () => {}, showNotice: () => {}, setHistoryError: () => {} });
  const pending = handler('App.jsx', 'renameHistoryRecord', f.scope)({ id: 'original-project', name: '旧名称' });
  assert.equal(f.calls.length, 0); await f.controller.submit('新名称'); await pending;
  assert.deepEqual(f.calls, [{ url: '/projects/original-project', method: 'PATCH', body: { name: '新名称' } }]);
});
