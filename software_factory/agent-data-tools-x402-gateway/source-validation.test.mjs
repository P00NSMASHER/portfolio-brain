import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./server.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
function context(doc){
 const c=vm.createContext({process:{env:{}},URL,Buffer,console,
 http:{createServer:()=>({listen:()=>{}})},
 fetchWithTimeout:async()=>({ok:true,status:200,json:async()=>doc,text:async()=>''})});
 vm.runInContext(source,c);return c;
}
test('Census malformed200 is rejected rather than billed no-match',async()=>{
 await assert.rejects(vm.runInContext("geocodeAddress('123 Main St')",context({})),/census_shape/);
});
test('SEC malformed200 is rejected rather than billed empty filings',async()=>{
 await assert.rejects(vm.runInContext("lookupSecFilings({cik:'123',limit:1})",context({})),/sec_identity/);
});
test('empty OFAC sources rejected',async()=>{
 await assert.rejects(vm.runInContext('loadOfacEntries()',context({})),/ofac_(empty|aliases_empty)/);
});
test('numbered Census geography matches digits',()=>{
 const c=context({});assert.equal(vm.runInContext("firstGeoByPattern({'2020 Census Blocks':[{BLOCK:'12'}]},/^\\d{4} Census Blocks$/i).BLOCK",c),'12');
});

test('null Census match rejected',async()=>{await assert.rejects(vm.runInContext("geocodeAddress('123 Main St')",context({result:{addressMatches:[null]}})),/census_match_invalid/);});

function rdapMockContext(base){
  const calls=[];
  const c=vm.createContext({process:{env:{}},URL,Buffer,console,
    http:{createServer:()=>({listen:()=>{}})},
    fetchWithTimeout:async(url,options={})=>{
      const target=String(url);
      calls.push({url:target,redirect:options.redirect});
      const data=target==='https://data.iana.org/rdap/dns.json'
        ? {services:[[['com'],[base]]]}
        : {objectClassName:'domain',ldhName:'example.com',entities:[],nameservers:[]};
      return {ok:true,status:200,json:async()=>data,text:async()=>JSON.stringify(data)};
    }});
  vm.runInContext(source,c);
  return {c,calls};
}
test('RDAP bootstrap rejects unsafe remote targets before a second request',async()=>{
  const unsafe=[
    'http://rdap.example.net/rdap/',
    'https://127.0.0.1/rdap/',
    'https://[::1]/',
    'https://localhost/rdap/',
    'https://rdap.internal/rdap/',
    'https://user:password@rdap.example.net/rdap/',
    'https://rdap.example.net:8443/rdap/',
    'https://rdap.example.net/rdap/?q=1',
    'https://rdap.example.net/rdap/#frag',
    'https://rdap.example.net./rdap/',
  ];
  for(const base of unsafe){
    const {c,calls}=rdapMockContext(base);
    await assert.rejects(vm.runInContext("lookupRdap('example.com')",c),/rdap_service_url_invalid/);
    assert.equal(calls.length,1,'unsafe base must not be fetched');
    assert.equal(calls[0].url,'https://data.iana.org/rdap/dns.json');
  }
});
test('valid public RDAP endpoint remains usable but forbids redirects',async()=>{
  const {c,calls}=rdapMockContext('https://rdap.example.net/rdap/');
  const result=await vm.runInContext("lookupRdap('example.com')",c);
  assert.equal(result.domain,'example.com');
  assert.equal(result.registered,true);
  assert.equal(result.authoritativeRdap,'https://rdap.example.net/rdap');
  assert.equal(calls.length,2);
  assert.equal(calls[1].url,'https://rdap.example.net/rdap/domain/example.com');
  assert.equal(calls[1].redirect,'error');
});
