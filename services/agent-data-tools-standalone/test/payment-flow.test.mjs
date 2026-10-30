import test from 'node:test';
import assert from 'node:assert/strict';
import { app } from '../src/server.mjs';

let server;
let base;
const originalFetch = globalThis.fetch;

test.before(async () => {
  server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const address = server.address();
  base = 'http://127.0.0.1:' + address.port;
});

test.after(async () => {
  globalThis.fetch = originalFetch;
  await new Promise(resolve => server.close(resolve));
});

function paymentHeader() {
  return Buffer.from(JSON.stringify({
    x402Version: 2,
    payload: { authorization: { from: '0x0000000000000000000000000000000000000001' } },
  }), 'utf8').toString('base64');
}

test('successful paid call verifies, fetches data, then settles', async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.startsWith(base)) return originalFetch(url, options);

    calls.push(target);
    if (target === 'https://facilitator.payai.network/verify') {
      const posted = JSON.parse(options.body);
      assert.equal(posted.paymentRequirements.amount, '5000');
      assert.equal(posted.paymentRequirements.extra.name, 'USD Coin');
      return new Response(JSON.stringify({ isValid: true }), { status: 200 });
    }
    if (target.startsWith('https://api.fiscaldata.treasury.gov/')) {
      assert.deepEqual(calls, [
        'https://facilitator.payai.network/verify',
        target,
      ]);
      return new Response(JSON.stringify({
        data: [{
          record_date: '2026-08-31',
          security_type_desc: 'Marketable',
          security_desc: 'Total Marketable',
          avg_interest_rate_amt: '3.500',
        }],
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    }
    if (target === 'https://facilitator.payai.network/settle') {
      assert.equal(calls.length, 3, 'settle must occur only after the data fetch');
      return new Response(JSON.stringify({ success: true, transaction: '0xtest' }), { status: 200 });
    }
    throw new Error('unexpected fetch ' + target);
  };

  const res = await originalFetch(base + '/api/treasury-average-rates?security=Total%20Marketable', {
    headers: { 'PAYMENT-SIGNATURE': paymentHeader() },
  });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('x402-settled'), 'true');
  assert.ok(res.headers.get('payment-response'));
  const body = await res.json();
  assert.equal(body.paid, true);
  assert.equal(body.count, 1);
  assert.deepEqual(calls.map(url =>
    url.startsWith('https://api.fiscaldata.treasury.gov/') ? 'treasury' : url
  ), [
    'https://facilitator.payai.network/verify',
    'treasury',
    'https://facilitator.payai.network/settle',
  ]);
});

test('upstream failure does not settle', async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.startsWith(base)) return originalFetch(url, options);

    calls.push(target);
    if (target === 'https://facilitator.payai.network/verify') {
      return new Response(JSON.stringify({ isValid: true }), { status: 200 });
    }
    if (target.startsWith('https://api.fiscaldata.treasury.gov/')) {
      return new Response('upstream unavailable', { status: 503 });
    }
    if (target === 'https://facilitator.payai.network/settle') {
      throw new Error('settle must not be called after an upstream failure');
    }
    throw new Error('unexpected fetch ' + target);
  };

  const res = await originalFetch(base + '/api/treasury-average-rates', {
    headers: { 'PAYMENT-SIGNATURE': paymentHeader() },
  });
  assert.equal(res.status, 502);
  const body = await res.json();
  assert.equal(body.paymentSettled, false);
  assert.ok(!calls.includes('https://facilitator.payai.network/settle'));
});
