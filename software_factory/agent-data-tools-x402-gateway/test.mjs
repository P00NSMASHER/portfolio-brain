import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';

const port='4173';
const child=spawn(process.execPath,['server.mjs'],{env:{...process.env,PORT:port},stdio:['ignore','pipe','pipe']});
const base='http://127.0.0.1:'+port;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function waitReady(){
  for(let i=0;i<30;i++){
    try{const r=await fetch(base+'/healthz');if(r.ok)return;}catch{}
    await sleep(250);
  }
  throw new Error('gateway did not become ready');
}

try{
  await waitReady();
  const health=await (await fetch(base+'/healthz')).json();
  assert.equal(health.ok,true);
  assert.equal(health.routes,8);

  const spec=await (await fetch(base+'/openapi.json')).json();
  assert.equal(Object.keys(spec.paths).length,8);
  for(const path of Object.keys(spec.paths)){
    const op=spec.paths[path].get;
    assert.equal(op.responses['402'].description,'Payment Required');
    assert.equal(op['x-payment-info'].protocols[0].x402.constructor,Object);
  }

  const agent=await (await fetch(base+'/.well-known/agent.json')).json();
  assert.equal(agent.version,'1.3');
  assert.equal(agent.intents.length,8);

  const treasury=await fetch(base+'/api/treasury-average-rates?security=Total%20Marketable');
  assert.equal(treasury.status,402);
  const treasuryHeader=treasury.headers.get('payment-required');
  assert.ok(treasuryHeader,'native Treasury route should emit PAYMENT-REQUIRED');
  const treasuryDoc=JSON.parse(Buffer.from(treasuryHeader,'base64').toString('utf8'));
  assert.equal(treasuryDoc.x402Version,2);
  assert.equal(treasuryDoc.accepts[0].network,'eip155:8453');
  assert.equal(treasuryDoc.accepts[0].amount,'5000');
  assert.equal(treasuryDoc.accepts[0].asset,'0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913');
  assert.equal(treasuryDoc.accepts[0].extra.name,'USD Coin');
  assert.equal(treasuryDoc.accepts[0].extra.version,'2');

  const badPayment=await fetch(base+'/api/treasury-average-rates',{
    headers:{'PAYMENT-SIGNATURE':'not-base64-json'}
  });
  assert.equal(badPayment.status,402);
  assert.ok(badPayment.headers.get('payment-required'));
  const badBody=await badPayment.json();
  assert.equal(badBody.error,'invalid_payment_header');

  const census=await fetch(base+'/api/us-address-geocode?address=4600%20Silver%20Hill%20Rd%2C%20Washington%2C%20DC%2020233');
  assert.equal(census.status,402);
  const censusHeader=census.headers.get('payment-required');
  assert.ok(censusHeader,'native Census route should emit PAYMENT-REQUIRED');
  const censusDoc=JSON.parse(Buffer.from(censusHeader,'base64').toString('utf8'));
  assert.equal(censusDoc.resource.url.endsWith('/api/us-address-geocode'),true);
  assert.equal(censusDoc.accepts[0].amount,'5000');
  assert.equal(censusDoc.accepts[0].asset,'0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913');
  assert.equal(censusDoc.accepts[0].extra.name,'USD Coin');
  assert.equal(censusDoc.resource.serviceName,'Census Address Geocoder');

  const badCensus=await fetch(base+'/api/us-address-geocode?address=x',{
    headers:{'PAYMENT-SIGNATURE':Buffer.from(JSON.stringify({x402Version:2}),'utf8').toString('base64')}
  });
  assert.equal(badCensus.status,400);

  const rdap=await fetch(base+'/api/domain-rdap?domain=example.com');
  assert.equal(rdap.status,402);
  const rdapHeader=rdap.headers.get('payment-required');
  assert.ok(rdapHeader,'native RDAP route should emit PAYMENT-REQUIRED');
  const rdapDoc=JSON.parse(Buffer.from(rdapHeader,'base64').toString('utf8'));
  assert.equal(rdapDoc.resource.url.endsWith('/api/domain-rdap'),true);
  assert.equal(rdapDoc.accepts[0].amount,'5000');
  assert.equal(rdapDoc.accepts[0].extra.name,'USD Coin');
  assert.equal(rdapDoc.resource.serviceName,'Domain RDAP Lookup');

  const badRdap=await fetch(base+'/api/domain-rdap?domain=bad_domain',{
    headers:{'PAYMENT-SIGNATURE':Buffer.from(JSON.stringify({x402Version:2}),'utf8').toString('base64')}
  });
  assert.equal(badRdap.status,400);

  for(const path of ['/api/pa-entity-one?q=OpenAI','/api/pa-business?q=OpenAI&limit=1']){
    const r=await fetch(base+path,{redirect:'manual'});
    assert.equal(r.status,402,path+' should return 402 unpaid');
    assert.ok(r.headers.get('payment-required'),path+' should preserve PAYMENT-REQUIRED');
  }
  console.log('x402 gateway smoke tests passed');
} finally {
  child.kill('SIGTERM');
}
