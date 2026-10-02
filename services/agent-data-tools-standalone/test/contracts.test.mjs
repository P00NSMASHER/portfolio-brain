import test from 'node:test';
import assert from 'node:assert/strict';
import { app } from '../src/server.mjs';
import { ROUTES } from '../src/x402.mjs';

let server;
let base;

test.before(async () => {
  server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const address = server.address();
  base = 'http://127.0.0.1:' + address.port;
});

test.after(async () => {
  await new Promise(resolve => server.close(resolve));
});

test('discovery surfaces stay free', async () => {
  for (const path of ['/.well-known/x402', '/openapi.json', '/.well-known/agent.json', '/skill.md', '/llms.txt', '/robots.txt', '/sitemap.xml']) {
    const res = await fetch(base + path);
    assert.equal(res.status, 200, path + ' should be public');
  }
});

test('all paid routes challenge before input validation', async () => {
  for (const [path, cfg] of Object.entries(ROUTES)) {
    const res = await fetch(base + path);
    assert.equal(res.status, 402, path + ' should challenge without payment');
    const encoded = res.headers.get('payment-required');
    assert.ok(encoded, path + ' missing PAYMENT-REQUIRED');
    const doc = JSON.parse(Buffer.from(encoded, 'base64').toString('utf8'));
    assert.equal(doc.x402Version, 2);
    assert.equal(doc.resource.url, base + path);
    assert.equal(doc.accepts[0].scheme, 'exact');
    assert.equal(doc.accepts[0].network, 'eip155:8453');
    assert.equal(doc.accepts[0].amount, cfg.amount);
    assert.equal(doc.accepts[0].extra.name, 'USD Coin');
    assert.equal(doc.accepts[0].extra.version, '2');
    assert.ok(/^[\x20-\x7E]{1,32}$/.test(doc.resource.serviceName), path + ' serviceName must be printable ASCII <=32');
    assert.ok(doc.resource.tags.length <= 5, path + ' must have <=5 resource tags');
  }
});

test('OpenAPI pricing mirrors runtime pricing', async () => {
  const res = await fetch(base + '/openapi.json');
  const doc = await res.json();
  assert.equal(doc.openapi, '3.1.0');
  assert.equal(doc.info.contact.email, 'jayp19386@gmail.com');
  for (const [path, cfg] of Object.entries(ROUTES)) {
    const op = doc.paths[path].get;
    assert.equal(op['x-payment-info'].price.amount, cfg.decimal);
    assert.deepEqual(op['x-payment-info'].protocols, [{ x402: {} }]);
    assert.ok(op.responses['200'].content['application/json'].schema);
    assert.ok(op.responses['402']);
  }
});

test('x402 discovery lists exactly the eight paid routes', async () => {
  const res = await fetch(base + '/.well-known/x402');
  const doc = await res.json();
  assert.equal(doc.resources.length, 8);
  const paths = doc.resources.map(x => new URL(x.resource).pathname).sort();
  assert.deepEqual(paths, Object.keys(ROUTES).sort());
});
