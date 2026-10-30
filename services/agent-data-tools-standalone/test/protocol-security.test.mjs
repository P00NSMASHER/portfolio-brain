import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  requestOrigin, settlePayment, verifyPayment, paidRoute,
} from '../src/x402.mjs';

// No Express, network, real payment, server, or GitHub token is required.
const priorFetch = globalThis.fetch;
const priorOrigin = process.env.PUBLIC_ORIGIN;
afterEach(() => {
  globalThis.fetch = priorFetch;
  if (priorOrigin === undefined) delete process.env.PUBLIC_ORIGIN;
  else process.env.PUBLIC_ORIGIN = priorOrigin;
});

function req(headers = {}, peer = '127.0.0.1') {
  const normalized = Object.fromEntries(
    Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return {
    protocol: 'http',
    socket: { remoteAddress: peer },
    query: { q: 'Mock Company' },
    get(name) { return normalized[name.toLowerCase()]; },
  };
}

function reply() {
  return {
    code: 200, headers: {}, body: null,
    status(code) { this.code = code; return this; },
    set(key, value) {
      if (typeof key === 'object') Object.assign(this.headers, key);
      else this.headers[key] = value;
      return this;
    },
    json(body) { this.body = body; return this; },
  };
}

function signature() {
  return Buffer.from(JSON.stringify({
    x402Version: 2,
    payload: { authorization: { from: '0x0000000000000000000000000000000000000001' } },
  }), 'utf8').toString('base64');
}

test('loopback mode ignores forged proxy protocol and accepts only local peer/host', () => {
  delete process.env.PUBLIC_ORIGIN;
  assert.equal(requestOrigin(req({
    host: '127.0.0.1:3001', 'x-forwarded-proto': 'https,evil',
  })), 'http://127.0.0.1:3001');
  for (const [host, peer] of [
    ['attacker.invalid', '127.0.0.1'],
    ['127.0.0.1:3001', '203.0.113.4'],
    ['127.0.0.1:3001@attacker.invalid', '127.0.0.1'],
    ['localhost:3001\nX-injection:yes', '127.0.0.1'],
  ]) {
    assert.throws(() => requestOrigin(req({ host }, peer)),
      /public_origin_required/);
  }
});

test('public HTTPS origin is configured independently of attacker Host headers', () => {
  process.env.PUBLIC_ORIGIN = 'https://tools.example.com/';
  const inbound = req({host:'attacker.invalid','x-forwarded-proto':'http'}, '203.0.113.7');
  assert.equal(requestOrigin(inbound), 'https://tools.example.com');
  for (const bad of [
    'http://tools.example.com',
    'https://tools.example.com/redirect',
    'https://person:secret@tools.example.com/',
    'https://tools.example.com/?token=secret',
    'not a URL',
  ]) {
    process.env.PUBLIC_ORIGIN = bad;
    assert.throws(() => requestOrigin(inbound), /public_origin_invalid/);
  }
});

test('unpaid challenge requires no provider call or result', async () => {
  delete process.env.PUBLIC_ORIGIN;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error('network forbidden'); };
  const result = reply();
  await paidRoute(req({host:'localhost:3000'}), result, '/api/pa-business',
    () => ({q:'Test'}), async () => { throw new Error('no unpaid source call'); });
  assert.equal(result.code, 402);
  assert.equal(result.body.x402Version, 2);
  assert.equal(calls, 0);
});

test('failed HTTP verify with forged positive body cannot authorize settlement', async () => {
  delete process.env.PUBLIC_ORIGIN;
  const called = [];
  globalThis.fetch = async (url) => {
    called.push(String(url));
    return new Response(JSON.stringify({isValid:true,success:true}), {status:503});
  };
  const result = reply();
  await paidRoute(req({host:'127.0.0.1:3000','payment-signature':signature()}),
    result, '/api/pa-business', () => ({q:'Test'}),
    async () => { throw new Error('must not execute'); });
  assert.equal(result.code, 402);
  assert.equal(called.length, 1);
  assert.ok(called[0].endsWith('/verify'));
});

test('settlement timeout/HTTP unknown never submits a second financial POST', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('network timeout after potential write');
  };
  const settlement = await settlePayment('/api/pa-business', {x402Version:2});
  assert.equal(settlement.ok, false);
  assert.equal(settlement.unresolved, true);
  assert.equal(settlement.reason, 'settlement_transport_unknown');
  assert.equal(calls, 1);
});

test('HTTP 503 during settlement returns unresolved without serving paid result', async () => {
  delete process.env.PUBLIC_ORIGIN;
  const calls = [];
  globalThis.fetch = async (url) => {
    const path = String(url);
    calls.push(path);
    if (path.endsWith('/verify'))
      return new Response(JSON.stringify({isValid:true}), {status:200});
    if (path.endsWith('/settle'))
      return new Response(JSON.stringify({errorReason:'facilitator_unavailable'}), {status:503});
    throw new Error('unexpected outbound destination');
  };
  const result = reply();
  await paidRoute(req({host:'localhost:3000','payment-signature':signature()}),
    result, '/api/pa-business', () => ({q:'Test'}), async () => ({verified:'true'}));
  assert.equal(result.code, 503);
  assert.equal(result.body.paymentState, 'unresolved');
  assert.equal(result.body.retrySamePayment, false);
  assert.equal(result.body.action, 'reconcile_settlement_before_retry');
  assert.equal(result.body.verified, undefined);
  assert.equal(calls.filter(x => x.endsWith('/settle')).length, 1);
});

test('HTTP failure with fake settlement success cannot count as paid', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(JSON.stringify({success:true}), {status:500});
  };
  const settlement = await settlePayment('/api/pa-business', {x402Version:2});
  assert.equal(settlement.ok, false);
  assert.equal(settlement.unresolved, true);
  assert.equal(calls, 1);
});

test('successful paid flow verifies, calculates and settles once in that order', async () => {
  delete process.env.PUBLIC_ORIGIN;
  const calls = [];
  globalThis.fetch = async url => {
    const path = String(url);
    if (path.endsWith('/verify')) {
      calls.push('verify');
      return new Response(JSON.stringify({isValid:true}), {status:200});
    }
    if (path.endsWith('/settle')) {
      calls.push('settle');
      return new Response(JSON.stringify({success:true,transaction:'mocked'}), {status:200});
    }
    throw new Error('unreviewed destination');
  };
  const result = reply();
  await paidRoute(req({host:'127.0.0.1:3001','payment-signature':signature()}),
    result, '/api/pa-business',
    () => { calls.push('validate'); return {q:'Test'}; },
    async () => { calls.push('data'); return {verified:'mocked'}; });
  assert.deepEqual(calls, ['validate','verify','data','settle']);
  assert.equal(result.code, 200);
  assert.equal(result.body.paid, true);
  assert.equal(result.body.verified, 'mocked');
  assert.equal(result.headers['x402-settled'], 'true');
});

test('upstream error after verify does not settle or return private result', async () => {
  delete process.env.PUBLIC_ORIGIN;
  const calls = [];
  globalThis.fetch = async url => {
    calls.push(String(url));
    return new Response(JSON.stringify({isValid:true}), {status:200});
  };
  const result = reply();
  await paidRoute(req({host:'localhost:3000','payment-signature':signature()}),
    result, '/api/pa-business', () => ({q:'Test'}), async () => {
      const e = new Error('upstream temporarily unavailable');
      e.status=502;
      throw e;
    });
  assert.equal(result.code, 502);
  assert.equal(result.body.paymentSettled, false);
  assert.equal(calls.length, 1);
  assert.ok(calls[0].endsWith('/verify'));
});
