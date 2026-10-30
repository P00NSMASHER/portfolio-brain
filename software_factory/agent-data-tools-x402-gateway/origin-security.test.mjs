// Production discovery and x402 challenges must never trust forwarded Host headers.
// Entirely offline: VM stubs the HTTP server and all network activity.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code = fs.readFileSync(new URL('./server.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '');
function start(env) {
  const context = vm.createContext({
    URL, Buffer, console, process: {env},
    fetchWithTimeout: () => {throw new Error('NETWORK_NOT_ALLOWED');},
    http: {createServer: () => ({listen() {}})},
  });
  vm.runInContext(code, context, {filename: 'server.mjs'});
  context.spoofedRequest = {headers: {
    host: 'attacker.example',
    'x-forwarded-host': 'attacker.example, trusted.example',
    'x-forwarded-proto': 'http',
  }};
  return vm.runInContext('origin(spoofedRequest)', context);
}

test('production payment resource origin ignores forged forwarded host and scheme', () => {
  assert.equal(start({NODE_ENV: 'production', PUBLIC_ORIGIN: 'https://trusted.example'}),
    'https://trusted.example');
});

test('production requires explicit public origin before starting HTTP server', () => {
  assert.throws(() => start({NODE_ENV: 'production'}), /PUBLIC_ORIGIN_REQUIRED/);
  assert.throws(() => start({NODE_ENV: 'production', PUBLIC_ORIGIN: ' '}),
    /PUBLIC_ORIGIN_REQUIRED/);
});

test('invalid, attacker-controlled and noncanonical public origins are rejected', () => {
  for (const candidate of [
    'http://trusted.example', 'https://trusted.example/path',
    'https://trusted.example/?redirect=1', 'https://user:pass@trusted.example',
    'https://trusted.example#fragment',
  ]) {
    assert.throws(() => start({NODE_ENV: 'production', PUBLIC_ORIGIN: candidate}),
      /PUBLIC_ORIGIN_INVALID/, candidate);
  }
});

test('local-only smoke without production origin remains runnable', () => {
  assert.equal(start({}), 'http://attacker.example');
});
