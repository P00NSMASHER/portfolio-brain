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
