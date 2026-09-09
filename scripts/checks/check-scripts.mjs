import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const directory = path.join(root, 'scripts');
const entries = readdirSync(directory, { withFileTypes: true });
assert.deepEqual(entries.filter(entry => entry.isFile()).map(entry => entry.name).sort(),
  ['deploy-server.bat', 'start.bat'], 'scripts/ must have exactly two public entry files');
for (const entry of ['start.bat', 'deploy-server.bat', 'dev/start-dev.bat']) {
  const contents = readFileSync(path.join(directory, entry), 'utf8');
  assert.doesNotMatch(contents, /(?<!\r)\n/, `${entry} must retain Windows CRLF line endings`);
  assert.ok(contents.startsWith('@echo off\r\n'), `${entry} must be BOM-free`);
}
for (const relative of ['deploy/deploy-server.ps1', 'deploy/Deploy.Core.psm1']) {
  assert.equal(readFileSync(path.join(directory, relative)).subarray(0, 3).toString('hex'),
    'efbbbf', `${relative} needs UTF-8 BOM for Windows PowerShell 5.1`);
}
console.log('Script layout and Windows entry encoding checks passed.');
