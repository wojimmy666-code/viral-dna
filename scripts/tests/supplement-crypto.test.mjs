import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import test from 'node:test';
import { seal, unseal } from '../maintenance/supplement-crypto.mjs';

test('authenticated encryption roundtrip, randomized nonce, no plaintext', () => {
  const key = randomBytes(32);
  const payload = Buffer.from(JSON.stringify({ keys: { DASHSCOPE_API_KEY: 'test-secret-only' } }));
  const one = seal(payload, key), two = seal(payload, key);
  assert.deepEqual(unseal(one, key), payload);
  assert.notDeepEqual(one, two);
  assert.ok(!one.includes(Buffer.from('test-secret-only')));
});

test('wrong key, altered header/tag/ciphertext and truncation fail closed', () => {
  const key = randomBytes(32), encrypted = seal(Buffer.from('fixture-only'), key);
  assert.throws(() => unseal(encrypted, randomBytes(32)));
  for (const offset of [0, 23, 35, encrypted.length - 1]) {
    const damaged = Buffer.from(encrypted); damaged[offset] ^= 1;
    assert.throws(() => unseal(damaged, key));
  }
  assert.throws(() => unseal(encrypted.subarray(0, 25), key));
  assert.throws(() => seal(Buffer.alloc(0), Buffer.alloc(8)));
});
