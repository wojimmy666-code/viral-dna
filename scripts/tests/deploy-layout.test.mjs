import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServicePlan } from '../dev/managed-launcher.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = relative => readFileSync(path.join(root, relative), 'utf8');

test('scripts root exposes only the two stable batch entries', () => {
  assert.deepEqual(readdirSync(path.join(root, 'scripts'), { withFileTypes: true })
    .filter(item => item.isFile()).map(item => item.name).sort(), ['deploy-server.bat', 'start.bat']);
  const entry = read('scripts/start.bat');
  assert.match(entry, /call "%~dp0dev\\start-dev\.bat" %\*/);
  assert.match(entry, /exit \/b %errorlevel%/);
  const deploy = read('scripts/deploy-server.bat');
  assert.match(deploy, /deploy\\deploy-server\.ps1" %\*/);
  assert.doesNotMatch(deploy, /start "|\/k |EnableDelayedExpansion/);
});

test('moved launch helper still resolves the actual repository root', () => {
  const plan = createServicePlan();
  assert.equal(plan[0].cwd, root);
  assert.equal(plan[1].cwd, path.join(root, 'apps', 'web'));
  assert.match(read('scripts/dev/start-dev.bat'), /%~dp0\.\.\\\.\./);
});

test('deployment has no global process kill, forced Git update, or automatic push', () => {
  const core = read('scripts/deploy/Deploy.Core.psm1');
  assert.doesNotMatch(core, /taskkill|Stop-Process|Stop-Service|reset.+--hard|git push|git clean/i);
  assert.match(core, /merge', '--ff-only'/);
  assert.match(core, /git@github\.com:wojimmy666-code\/viral-dna\.git/);
  assert.match(core, /StrictHostKeyChecking=yes/);
  assert.match(core, /FileShare\]::None/);
});

test('production serves static output and one API worker, not Vite dev', () => {
  const core = read('scripts/deploy/Deploy.Core.psm1');
  const host = read('scripts/deploy/api-host.py');
  assert.match(core, /apps\\web\\dist\\client/);
  assert.doesNotMatch(core, /npm.+run.+dev|vite.+preview/i);
  assert.match(host, /workers=1/);
  assert.match(host, /host="127\.0\.0\.1"/);
  assert.match(host, /forwarded_allow_ips="127\.0\.0\.1"/);
});
