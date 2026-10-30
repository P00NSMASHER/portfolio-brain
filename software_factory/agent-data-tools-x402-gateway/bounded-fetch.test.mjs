import {test} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {fetchWithTimeout} from './bounded-fetch.mjs';
async function serve(handler, run) {
  const server = http.createServer(handler);
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  try { await run(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
test('valid JSON and HTTP failure status preserved', async () => {
  await serve((q,r)=>{r.writeHead(503);r.end('{"ok":false}');},async url=>{
    const r=await fetchWithTimeout(url);assert.equal(r.status,503);assert.equal(r.ok,false);
    assert.deepEqual(await r.json(),{ok:false});
  });
});
test('streamed body limit enforced without content-length',async()=>{
  await serve((q,r)=>{r.write('1234');r.end('5678');},async url=>{
    await assert.rejects(fetchWithTimeout(url,{},1000,4),/too_large/);
  });
});
test('deadline covers stalled body after headers',async()=>{
  await serve((q,r)=>{r.writeHead(200);r.write('x');},async url=>{
    const start=Date.now();await assert.rejects(fetchWithTimeout(url,{},100));
    assert.ok(Date.now()-start<1500);
  });
});
