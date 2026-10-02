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

  for(const path of ['/api/pa-entity-one?q=OpenAI','/api/sec-filings?ticker=AAPL&limit=1']){
    const r=await fetch(base+path,{redirect:'manual'});
    assert.equal(r.status,402,path+' should return 402 unpaid');
    assert.ok(r.headers.get('payment-required'),path+' should preserve PAYMENT-REQUIRED');
  }
  console.log('x402 gateway smoke tests passed');
} finally {
  child.kill('SIGTERM');
}
