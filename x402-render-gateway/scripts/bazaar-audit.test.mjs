// Offline contract tests. No real network, payment, verification, or settlement.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const script = fs.readFileSync(new URL('./bazaar-audit.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '');
const pa = 'https://pa-entity-x402.floot.app/_api/pa-entity-one';
const netlify = 'https://agent-data-tools-x402.netlify.app/api/pa-entity-one';
const requirements = {
  scheme: 'exact', network: 'eip155:8453', amount: '1000',
  asset: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  payTo: '0x708f7b52b56eafd7fc1de65fc7752ed732914021',
  extra: {name: 'USD Coin', version: '2'},
};
const challenge = {
  x402Version: 2, resource: {
    url: pa, serviceName: 'PA entity', tags: ['registry'], mimeType: 'application/json',
  },
  accepts: [requirements], extensions: {bazaar: {info: {input: {method: 'GET'}}}},
};
function reply(body, status=200, paymentRequired=null) {
  return {status, text: async () => JSON.stringify(body),
    headers: {get: key => key === 'payment-required' ? paymentRequired : null}};
}
async function exercise({missingCatalog = false, requireNetlify = false} = {}) {
  const calls = [], outputs = [], process = {
    env: {}, argv: requireNetlify ? ['node','audit','--require-netlify'] : ['node','audit'],
    exitCode: undefined,
  };
  const fetch = async (u, init) => {
    const url = String(u); calls.push({url, method:init?.method});
    if (url.startsWith(pa)) return reply(challenge, 402, Buffer.from(JSON.stringify(challenge)).toString('base64'));
    if (url.endsWith('/.well-known/x402.json'))
      return reply({resources: [{resource:pa, accepts:[requirements], extensions:challenge.extensions}]});
    if (url.includes('/discovery/listing-status?resource='))
      return reply({listed:url.includes(encodeURIComponent(pa)),hidden:false});
    if (url.includes('/discovery/resources?'))
      return reply({items: missingCatalog ? [] : [{resource:pa, serviceName:'PA entity',tags:['registry']}]});
    if (url.startsWith(netlify)||url.includes('agent-data-tools-x402.netlify.app'))
      return reply({error:'missing'},404);
    throw new Error('unexpected URL: ' + url);
  };
  const sandbox = vm.createContext({
    Buffer, fetch, AbortSignal, Date, process,
    console: {log: line => outputs.push(JSON.parse(line)), error: line => outputs.push({error:line})},
  });
  await vm.runInContext(script,sandbox,{filename:'bazaar-audit.mjs'});
  assert.equal(outputs.length,1);
  return {calls, report:outputs[0], process};
}
test('valid primary listing is healthy with 404 optional fallback',async()=>{
  const {calls,report,process}=await exercise();
  assert.equal(report.primaryHealthy,true);
  assert.equal(report.fallback.valid402,false);
  assert.equal(process.exitCode,undefined);
  assert.equal(calls.length,7);
  for(const call of calls){
    assert.equal(call.method,'GET');
    assert.doesNotMatch(call.url,/\/(?:verify|settle)\b|payment-signature|PAYMENT-SIGNATURE/i);
  }
});
test('unlisted primary fails closed without a payment',async()=>{
  const {report,process,calls}=await exercise({missingCatalog:true});
  assert.equal(report.primaryHealthy,false);
  assert.equal(process.exitCode,1);
  assert.equal(calls.length,7);
});
test('explicit Netlify requirement fails on undeployed fallback',async()=>{
  const {report,process}=await exercise({requireNetlify:true});
  assert.equal(report.primaryHealthy,true);
  assert.equal(report.fallbackRequired,true);
  assert.equal(process.exitCode,1);
});
