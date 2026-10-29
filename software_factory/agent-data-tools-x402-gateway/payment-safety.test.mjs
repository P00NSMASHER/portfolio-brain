// All payment, IANA, EDGAR, Census and OFAC responses are mocked.
// Never contacts a payment facilitator, a real upstream, or a deployed service.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('./server.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '');
const signature = Buffer.from(JSON.stringify({x402Version: 2, payload: {}})).toString('base64');

const json = (data, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
  text: async () => JSON.stringify(data),
});
const csv = value => ({ok: true, status: 200, text: async () => value});

async function request(path, {method = 'GET', sourceReply, paymentVerify = {isValid: true}} = {}) {
  const calls = [];
  let handler;
  const fetchWithTimeout = async (url) => {
    const address = String(url);
    if (address.startsWith('https://facilitator.payai.network/')) {
      const stage = address.endsWith('/verify') ? 'verify' : 'settle';
      calls.push(stage);
      return json(stage === 'verify' ? paymentVerify : {success: true});
    }
    calls.push('source:' + address);
    if (!sourceReply) throw new Error('UNEXPECTED_UPSTREAM_CALL');
    return sourceReply(address);
  };
  const context = vm.createContext({
    URL, Buffer, console, fetchWithTimeout, process: {env: {}},
    http: {createServer: fn => {handler = fn; return {listen() {}};}},
  });
  vm.runInContext(source, context, {filename: 'server.mjs'});
  const req = {
    method, url: path,
    headers: {host: 'test.invalid', 'payment-signature': signature},
  };
  const res = {
    statusCode: 200, headers: {}, destroyed: false, body: '',
    writeHead(status, headers) {
      this.statusCode = status;
      Object.assign(this.headers, headers);
      return this;
    },
    setHeader(name, value) {this.headers[name.toLowerCase()] = value;},
    end(body = '') {this.body = String(body); this.finished = true;},
  };
  await handler(req, res);
  assert.equal(res.finished, true, 'mock HTTP request should complete');
  return {status: res.statusCode, headers: res.headers, calls,
    body: res.body ? JSON.parse(res.body) : null};
}

const census = '/api/us-address-geocode?address=4600%20Silver%20Hill%20Road';
const rdap = '/api/domain-rdap?domain=example.com';
const sec = '/api/sec-filings?cik=320193&limit=1';
const ofac = '/api/ofac-sdn-screen?name=JANE%20DOE';
const treasury = '/api/treasury-average-rates';
const censusGood = {result: {addressMatches: [{
  matchedAddress: '4600 SILVER HILL RD', coordinates: {x: -76.93, y: 38.85},
  geographies: {},
}]}};
const rdapBootstrap = {services: [[['com'], ['https://rdap.test/']]]};
const rdapGood = {objectClassName: 'domain', ldhName: 'example.com'};
const secGood = {
  cik: 320193, name: 'Example Corp', filings: {recent: {
    form: ['10-K'], accessionNumber: ['0000320193-26-000001'],
    primaryDocument: ['example.htm'], filingDate: ['2026-10-01'],
  }},
};
const ofacSdn = (() => {
  const row = Array(12).fill('-0-');
  row[0] = '1'; row[1] = 'JANE DOE'; row[3] = 'SDGT';
  return row.join(',') + '\n';
})();
const ofacAlt = '1,-0-,aka,JANE A DOE,-0-\n';

const cases = [
  {name: 'Treasury', path: treasury, invalid: () => json({}), good: () =>
    json({data: [{record_date: '2026-09-30', security_desc: 'Total Marketable',
      security_type_desc: 'Marketable', avg_interest_rate_amt: '3.50'}]})},
  {name: 'Census', path: census, invalid: () => json({}), good: () => json(censusGood)},
  {name: 'RDAP', path: rdap,
    invalid: url => json(url.includes('dns.json') ? rdapBootstrap : {objectClassName: 'domain', ldhName: 'wrong.com'}),
    good: url => json(url.includes('dns.json') ? rdapBootstrap : rdapGood)},
  {name: 'SEC', path: sec,
    invalid: () => json({cik: 999999, filings: {recent: {form: []}}}),
    good: () => json(secGood)},
  {name: 'OFAC', path: ofac,
    invalid: url => csv(url.endsWith('SDN.CSV') ? 'corrupt\n' : ofacAlt),
    good: url => csv(url.endsWith('SDN.CSV') ? ofacSdn : ofacAlt)},
];

for (const scenario of cases) {
  test(scenario.name + ': malformed upstream never settles a payment', async () => {
    const out = await request(scenario.path, {sourceReply: scenario.invalid});
    assert.equal(out.status, 502);
    assert.equal(out.calls[0], 'verify');
    assert.ok(out.calls.some(x => x.startsWith('source:')));
    assert.equal(out.calls.includes('settle'), false);
    assert.equal(out.body.paid, undefined);
  });
  test(scenario.name + ': valid source has verify -> source -> settle order', async () => {
    const out = await request(scenario.path, {sourceReply: scenario.good});
    assert.equal(out.status, 200);
    assert.equal(out.body.paid, true);
    assert.equal(out.calls[0], 'verify');
    assert.ok(out.calls.slice(1, -1).every(x => x.startsWith('source:')));
    assert.equal(out.calls.at(-1), 'settle');
  });
  test(scenario.name + ': declined verify cannot call upstream or settle', async () => {
    const out = await request(scenario.path, {
      sourceReply: () => {throw new Error('upstream must not execute');},
      paymentVerify: {isValid: false, success: false},
    });
    assert.equal(out.status, 402);
    assert.deepEqual(out.calls, ['verify']);
  });
}
for (const path of [...cases.map(x => x.path), '/api/pa-business?q=hello', '/api/vendor-intake-gate?name=X']) {
  test('HEAD never starts a paid service: ' + path, async () => {
    const out = await request(path, {method: 'HEAD'});
    assert.equal(out.status, 405);
    assert.deepEqual(out.calls, []);
  });
}
for (const path of ['/api/us-address-geocode?address=x', '/api/domain-rdap?domain=bad_domain',
                    '/api/sec-filings', '/api/ofac-sdn-screen?name=x']) {
  test('invalid input rejected before verification: ' + path, async () => {
    const out = await request(path);
    assert.equal(out.status, 400);
    assert.deepEqual(out.calls, []);
  });
}
test('malformed Census match cannot be billed', async () => {
  const out = await request(census, {sourceReply: () => json({result: {addressMatches: [null]}})});
  assert.equal(out.status, 502);
  assert.equal(out.calls.includes('settle'), false);
});
test('authoritative RDAP 404 is a valid unregistered answer', async () => {
  const out = await request(rdap, {sourceReply: url =>
    url.includes('dns.json') ? json(rdapBootstrap) : json({}, 404)});
  assert.equal(out.status, 200);
  assert.equal(out.body.registered, false);
  assert.equal(out.calls.at(-1), 'settle');
});
