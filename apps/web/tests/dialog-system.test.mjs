import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { parse } from '@babel/parser';
import traverseModule from '@babel/traverse';
import postcss from 'postcss';
import { createDialogController } from '../src/ui/system/dialog-state.js';

const traverse = traverseModule.default || traverseModule;
const src = fileURLToPath(new URL('../src/', import.meta.url));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function harness(options = {}) {
  const state = { scope: 'project:shot', input: 'revision:settings', authority: 'lease', snapshot: null };
  const controller = createDialogController({ getScope: () => state.scope, getInput: () => state.input,
    captureAuthority: () => state.authority, checkAuthority: previous => previous === state.authority,
    notify: snapshot => { state.snapshot = snapshot; }, ...options });
  return { state, controller };
}
test('cancel has zero writes; repeated opens do not queue old decisions', async () => {
  const { controller, state } = harness(); let calls = 0;
  const first = controller.open({ onConfirm: ({ mutate }) => mutate(() => { calls++; }) });
  assert.equal(await controller.open({ onConfirm() { calls++; } }), false);
  controller.cancel(); assert.equal(await first, false); assert.equal(calls, 0); assert.equal(state.snapshot, null);
});
test('double-submit writes once and busy cannot close; successful acceptance closes', async () => {
  const { controller, state } = harness(), pending = deferred(); let calls = 0;
  const outcome = controller.open({ onConfirm: ({ mutate }) => mutate(() => { calls++; return pending.promise; }) });
  const submit = controller.submit(); await controller.submit(); controller.cancel();
  await Promise.resolve(); assert.equal(calls, 1); assert.equal(state.snapshot.busy, true);
  pending.resolve({ id: 'task' }); await submit; assert.deepEqual(await outcome, { id: 'task' }); assert.equal(state.snapshot, null);
});
test('explicit failure retains the input decision and allows corrected retry', async () => {
  const { controller, state } = harness(); let calls = 0;
  const outcome = controller.open({ initialValue: '原名称', onConfirm: ({ value, mutate }) => mutate(() => {
    calls++; if (calls === 1) throw Object.assign(new Error('名称重复'), { status: 409 }); return value;
  }) });
  await controller.submit('修改名称'); assert.equal(state.snapshot.error, '名称重复'); assert.equal(state.snapshot.busy, false); assert.equal(state.snapshot.uncertain, false);
  await controller.submit('新名称'); assert.equal(await outcome, '新名称'); assert.equal(calls, 2);
});
test('unknown transport/server outcome blocks a second write', async () => {
  for (const failure of [new TypeError('Failed to fetch'), Object.assign(new Error('服务器异常'), { status: 500 })]) {
    const { controller, state } = harness(); let calls = 0;
    controller.open({ onConfirm: ({ mutate }) => mutate(() => { calls++; throw failure; }) });
    await controller.submit(); await controller.submit(); assert.equal(calls, 1); assert.equal(state.snapshot.uncertain, true); controller.cancel();
  }
});
test('timeout does not spin forever, does not retry and ignores a late reply', async () => {
  const { controller, state } = harness({ timeoutMs: 5 }), pending = deferred(); let calls = 0;
  controller.open({ onConfirm: ({ mutate }) => mutate(() => { calls++; return pending.promise; }) });
  await controller.submit(); assert.equal(state.snapshot.busy, false); assert.equal(state.snapshot.uncertain, true);
  pending.resolve('late'); await Promise.resolve(); await controller.submit(); assert.equal(calls, 1); controller.cancel();
});
test('successful write followed by failed refresh is never replayed', async () => {
  const { controller, state } = harness(); let calls = 0, errors = 0;
  const outcome = controller.open({ onError() { errors++; }, onConfirm: async ({ mutate }) => { await mutate(() => { calls++; }); throw new Error('刷新失败'); } });
  await controller.submit(); await controller.submit(); assert.equal(await outcome, true); assert.equal(state.snapshot, null); assert.equal(calls, 1); assert.equal(errors, 1);
});
test('project, inputs, account and lease changes before submit prevent a write', async () => {
  for (const field of ['scope', 'input', 'authority']) {
    const { controller, state } = harness(); let calls = 0;
    controller.open({ onConfirm: ({ mutate }) => mutate(() => { calls++; }) }); state[field] = 'changed';
    await controller.submit(); assert.equal(calls, 0); assert.match(state.snapshot.error, /已变化/); controller.cancel();
  }
});
test('navigation while draft preparation is pending stops the eventual write', async () => {
  const { controller, state } = harness(), prep = deferred(); let calls = 0;
  controller.open({ onConfirm: async ({ mutate }) => { await prep.promise; await mutate(() => { calls++; }); } });
  const work = controller.submit(); state.scope = 'another-project'; prep.resolve(); await work; assert.equal(calls, 0); controller.cancel();
});
test('unmount settles outstanding caller and ignores late work', async () => {
  const { controller, state } = harness(), prep = deferred(); let calls = 0, errors = 0;
  const outcome = controller.open({ onError() { errors++; }, onConfirm: async ({ mutate }) => { await prep.promise; await mutate(() => { calls++; }); } });
  const work = controller.submit(); controller.dispose(); prep.resolve(); await work; assert.equal(await outcome, false); assert.equal(calls, 0); assert.equal(errors, 0);
  controller.activate(); const fresh = controller.open({ onConfirm: () => true }); await controller.submit(); assert.equal(await fresh, true); assert.equal(state.snapshot, null);
});
test('scope change while a write is pending stops stale UI continuation without repeating the accepted write', async () => {
  const { controller, state } = harness(), response = deferred(); let continued = 0;
  const outcome = controller.open({ onConfirm: async ({ mutate }) => { await mutate(() => response.promise); continued++; } });
  const work = controller.submit(); await Promise.resolve(); state.scope = 'other-project'; response.resolve({ id: 'accepted' }); await work;
  assert.equal(continued, 0); assert.equal(await outcome, true);
});

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? sourceFiles(path.join(dir, entry.name)) : /\.(jsx?|tsx?)$/.test(entry.name) ? [path.join(dir, entry.name)] : []);
}
function nativeCalls(source) {
  const issues = [], banned = new Set(['alert', 'confirm', 'prompt']);
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  function isWindow(node, scope, seen = new Set()) {
    if (node?.type !== 'Identifier') return false;
    const binding = scope.getBinding(node.name);
    if (!binding) return ['window', 'globalThis', 'self'].includes(node.name);
    if (seen.has(binding)) return false; seen.add(binding);
    return binding.path.isVariableDeclarator() && isWindow(binding.path.node.init, binding.path.scope, seen);
  }
  function nativeReference(node, scope, seen = new Set()) {
    if (!node) return false;
    if (['MemberExpression', 'OptionalMemberExpression'].includes(node.type)) {
      const key = node.computed ? node.property.value : node.property.name;
      return banned.has(key) && isWindow(node.object, scope);
    }
    if (node.type !== 'Identifier') return false;
    const binding = scope.getBinding(node.name);
    if (!binding) return banned.has(node.name);
    if (seen.has(binding)) return false; seen.add(binding);
    if (!binding.path.isVariableDeclarator()) return false;
    const declaration = binding.path.node;
    if (declaration.id.type === 'ObjectPattern' && isWindow(declaration.init, binding.path.scope)) {
      return declaration.id.properties.some(item => item.value?.name === node.name && banned.has(item.key?.name || item.key?.value));
    }
    return nativeReference(declaration.init, binding.path.scope, seen);
  }
  traverse(ast, { 'CallExpression|OptionalCallExpression'(item) {
    if (nativeReference(item.node.callee, item.scope)) issues.push(item.node.loc.start.line);
  } });
  return issues;
}
test('native-dialog guard covers direct, optional, computed and aliased calls without banning local confirm handlers', () => {
  for (const source of ['confirm("x")', 'window.alert("x")', 'window?.prompt?.("x")', 'globalThis["confirm"]("x")', 'const ask=window.confirm;ask("x")', 'const w=window; const {confirm:ask}=w;ask("x")']) assert.equal(nativeCalls(source).length, 1, source);
  for (const source of ['function confirm(){};confirm()', 'const confirm=()=>true;confirm()', 'function run(prompt){prompt()}', 'api.confirm()']) assert.equal(nativeCalls(source).length, 0, source);
});
test('all product business calls are free of native alert, confirm and prompt', () => {
  const violations = sourceFiles(src).flatMap(file => nativeCalls(readFileSync(file, 'utf8')).map(line => `${path.relative(src, file)}:${line}`));
  assert.deepEqual(violations, []);
});
test('business shells use Dialog; public dark dialogs, navigation/notification drawers and anchored menus are explicit exceptions', () => {
  const exceptions = new Set(['ui/system/Dialog.jsx', 'landing/LoginDialog.jsx', 'landing/HomePage.jsx', 'app-sidebar/AppSidebar.jsx', 'NotificationCenter.jsx', 'video-generation-controls/AnchoredPopover.jsx']);
  const violations = [];
  for (const file of sourceFiles(src)) {
    const relative = path.relative(src, file).replaceAll('\\', '/'); if (exceptions.has(relative)) continue;
    traverse(parse(readFileSync(file, 'utf8'), { sourceType: 'module', plugins: ['jsx'] }), { JSXOpeningElement(item) {
      const node = item.node, tag = node.name.name;
      if (tag === 'dialog' || (tag?.[0] === tag?.[0]?.toLowerCase() && node.attributes.some(attr => attr.name?.name === 'role' && ['dialog', 'alertdialog'].includes(attr.value?.value)))) violations.push(`${relative}:${node.loc.start.line}`);
    } });
  }
  assert.deepEqual(violations, []);
});
test('shared shell owns top-layer focus, scroll, IME and frozen-close behavior', () => {
  const shell = readFileSync(path.join(src, 'ui/system/Dialog.jsx'), 'utf8');
  for (const token of ['showModal()', 'dialog.close()', 'lockScroll()', 'isComposing', 'keyCode === 229', 'previous.focus', 'callbacks.current.busy', 'data-dialog-cancel']) assert.ok(shell.includes(token), token);
  const css = readFileSync(path.join(src, 'ui/system/dialogs.css'), 'utf8');
  for (const token of ['var(--overlay-backdrop)', 'var(--radius-overlay)', 'var(--shadow-overlay)', '440px', '480px', '560px', '960px', '1200px', '100dvh - 32px']) assert.ok(css.includes(token), token);
});
test('business dialogs cannot reintroduce private root skins or backdrops in page CSS', () => {
  const classes = new Set(), violations = [];
  for (const file of sourceFiles(src)) {
    traverse(parse(readFileSync(file, 'utf8'), { sourceType: 'module', plugins: ['jsx'] }), { JSXOpeningElement(item) {
      if (item.node.name.name !== 'Dialog') return;
      const value = item.node.attributes.find(attr => attr.name?.name === 'className')?.value?.value;
      if (typeof value === 'string') value.split(/\s+/).forEach(name => classes.add(name));
    } });
  }
  function scan(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) { scan(file); continue; }
      if (!file.endsWith('.css') || file === path.join(src, 'ui/system/dialogs.css')) continue;
      postcss.parse(readFileSync(file, 'utf8')).walkRules(rule => {
        const isRoot = rule.selectors.some(selector => !/[\s>+~]/.test(selector) && (selector.match(/\.[\w-]+/g) || []).some(token => classes.has(token.slice(1))));
        if (!isRoot) return;
        rule.walkDecls(decl => {
          if (/^(background(?:-color)?|border(?:-radius|-color)?|box-shadow|backdrop-filter|width|max-width|font(?:-family|-size)?|color)$/.test(decl.prop)) violations.push(`${path.relative(src, file)}:${rule.source.start.line} ${decl.prop}`);
        });
      });
    }
  }
  scan(src); assert.deepEqual(violations, []);
});
