// Private subprocess protocol for the offline supplement tool. No network/dependencies.
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, lstatSync, openSync, readFileSync, writeSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const MAGIC = Buffer.from('ViralDNA model keys v1\0');
const LIMIT = 1024 * 1024;

export function seal(plaintext, key) {
  if (key.length !== 32 || plaintext.length > LIMIT) throw new Error('invalid_input');
  const nonce = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, nonce, { authTagLength: 16 });
  cipher.setAAD(MAGIC);
  const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([MAGIC, nonce, cipher.getAuthTag(), encrypted]);
}

export function unseal(container, key) {
  if (key.length !== 32 || container.length < MAGIC.length + 28
      || container.length > LIMIT + MAGIC.length + 28
      || !container.subarray(0, MAGIC.length).equals(MAGIC)) throw new Error('invalid_input');
  const offset = MAGIC.length;
  const decipher = createDecipheriv('aes-256-gcm', key, container.subarray(offset, offset + 12),
    { authTagLength: 16 });
  decipher.setAAD(MAGIC);
  decipher.setAuthTag(container.subarray(offset + 12, offset + 28));
  // Never release unauthenticated plaintext before final() succeeds.
  return Buffer.concat([decipher.update(container.subarray(offset + 28)), decipher.final()]);
}

function protectEmptyFile(file) {
  if (process.platform !== 'win32') return;
  const system = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32');
  const identity = spawnSync(path.join(system, 'whoami.exe'), ['/user', '/fo', 'csv', '/nh'],
    { encoding: 'utf8', windowsHide: true });
  const sid = identity.status === 0 && identity.stdout.match(/S-1-5-\d+(?:-\d+)+/)?.[0];
  if (!sid) throw new Error('identity_failed');
  const acl = spawnSync(path.join(system, 'icacls.exe'),
    [file, '/inheritance:r', '/grant:r', `*${sid}:F`, '*S-1-5-18:F'], { windowsHide: true });
  if (acl.status !== 0) throw new Error('permissions_failed');
}

function unlockKey(file, create) {
  if (!path.isAbsolute(file) || !file.endsWith('.vdna-unlock')) throw new Error('invalid_key_path');
  if (create) {
    const descriptor = openSync(file, 'wx', 0o600);
    try {
      protectEmptyFile(file);
      writeSync(descriptor, randomBytes(32));
      fsyncSync(descriptor);
    } finally { closeSync(descriptor); }
  }
  if (!existsSync(file) || !lstatSync(file).isFile() || lstatSync(file).isSymbolicLink()) {
    throw new Error('invalid_key_file');
  }
  const key = readFileSync(file);
  if (key.length !== 32) throw new Error('invalid_key_file');
  return key;
}

async function main() {
  const [command, keyFile] = process.argv.slice(2);
  if (!['seal-new', 'seal', 'open'].includes(command) || !keyFile || process.argv.length !== 4) {
    throw new Error('invalid_arguments');
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > LIMIT + MAGIC.length + 28) throw new Error('input_too_large');
    chunks.push(chunk);
  }
  const input = Buffer.concat(chunks);
  const key = unlockKey(keyFile, command === 'seal-new');
  try { process.stdout.write(command === 'open' ? unseal(input, key) : seal(input, key)); }
  finally { key.fill(0); input.fill(0); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    // Inputs may contain credentials. Do not print exception details or stacks.
    process.stderr.write('Secret processing failed: check the unlock file, integrity and permissions.\n');
    process.exitCode = 1;
  });
}
