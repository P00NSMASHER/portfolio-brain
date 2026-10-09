"""Offline proof of source-switch scheduling invariants for a future V5 cutover.

Exercises the reviewed Cloudflare Worker itself with fake provider replies and
a throwaway P-256 test key. NEVER contacts GitHub/Cloudflare or handles actual
secrets. Green tests do not constitute a real deployed V5 scheduled cycle.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "reliability" / "cloudflare" / "worker.mjs"
CYCLE = ROOT / ".github" / "workflows" / "brain-cycle.yml"
WATCHDOG = ROOT / ".github" / "workflows" / "brain-clock.yml"

class V5SwitchSafety(unittest.TestCase):
    def test_worker_pivots_to_new_main_without_laundering_v4_success(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed; JS cutover simulation unavailable")
        js = r"""
import {tick} from './reliability/cloudflare/worker.mjs';
import {webcrypto} from 'node:crypto';
import assert from 'node:assert/strict';

Object.defineProperty(globalThis, 'crypto', {value:webcrypto, configurable:true});
const OLD='9fc08c72e2d050359e7f119bfcbfb82b23f95b5b';
const NEW='a'.repeat(40);
const OTHER='b'.repeat(40);
const now=Date.now();
const controller={scheduledTime:Math.floor(now/600000)*600000,cron:'*/10 * * * *'};
const signing=await webcrypto.subtle.generateKey(
    {name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const privateBytes=await webcrypto.subtle.exportKey('pkcs8',signing.privateKey);
const env={GITHUB_ACTIONS_TOKEN:'fake-test-token-not-a-secret',
           SIGNING_KEY_PKCS8:Buffer.from(privateBytes).toString('base64')};

let main=OLD;
let runs=[];
const posts=[];
const gets=[];
function run(sha,id,ageMin=2,status='completed',conclusion='success'){
 const completed=new Date(now-ageMin*60000).toISOString();
 return {id,head_sha:sha,head_branch:'main',event:'schedule',
         path:'.github/workflows/brain-cycle.yml',created_at:completed,
         updated_at:completed,status,conclusion};
}
function reply(doc){return {ok:true,status:200,json:async()=>doc};}
globalThis.fetch=async (url, options) => {
 assert.equal(options.redirect,'manual');
 const path=new URL(url).pathname;
 if (path.endsWith('/branches/main')){
   gets.push('main');
   return reply({commit:{sha:main}});
 }
 if (path.endsWith('/actions/workflows/brain-cycle.yml/runs')){
   gets.push('runs');
   return reply({total_count:runs.length,workflow_runs:runs});
 }
 if (path.endsWith('/actions/workflows/brain-cycle.yml/dispatches')){
   assert.equal(options.method,'POST');
   assert.equal(options.headers.Authorization,'Bearer '+env.GITHUB_ACTIONS_TOKEN);
   const body=JSON.parse(options.body);
   assert.equal(body.ref,'main');
   assert.deepEqual(Object.keys(body.inputs).sort(),['cloudflare_attestation','cloudflare_signature']);
   posts.push(body);
   return {status:204};
 }
 throw new Error('MOCK_NETWORK_OUTSIDE_APPROVED_GITHUB_PATH: '+path);
};

runs=[run(OLD,1,1)];
assert.equal((await tick(controller,env)).status,'FRESH');
assert.equal(posts.length,0);

// A green OLD-source job cannot satisfy the newly promoted source; the
// worker chooses main dynamically and signs the NEW source from this slot.
main=NEW;
let outcome=await tick(controller,env);
assert.equal(outcome.status,'DISPATCH_ACCEPTED_NOT_COMPLETED');
assert.equal(outcome.source_sha,NEW);
assert.equal(posts.length,1);
const body=posts[0];
const payloadBytes=Buffer.from(body.inputs.cloudflare_attestation,'base64url');
const sigBytes=Buffer.from(body.inputs.cloudflare_signature,'base64url');
const payload=JSON.parse(payloadBytes.toString('utf8'));
assert.equal(payload.worker,'portfolio-brain-recovery');
assert.equal(payload.kind,'cloudflare_cron_v1');
assert.equal(payload.source_sha,NEW);
assert.equal(payload.cron,'*/10 * * * *');
assert.equal(payload.slot,Math.floor(controller.scheduledTime/600000));
assert.equal(sigBytes.length,64);
assert.equal(await webcrypto.subtle.verify(
 {name:'ECDSA',hash:'SHA-256'}, signing.publicKey, sigBytes, payloadBytes
),true);

// A NEW-source accepted run is NOT equivalent to successful completion;
// once an actual NEW-source core finishes, prevent duplicate dispatch.
runs=[run(OLD,1,1),run(NEW,2,1)];
assert.equal((await tick(controller,env)).status,'FRESH');
assert.equal(posts.length,1);

// Active NEW-source writer blocks a competing dispatch, regardless of
// successful older-source history.
runs=[run(OLD,1,1),run(NEW,3,1,'in_progress',null)];
assert.equal((await tick(controller,env)).status,'ACTIVE');
assert.equal(posts.length,1);

// Stale NEW-source queue blocks instead of creating concurrent writers.
runs=[run(OLD,1,1),run(NEW,4,24,'queued',null)];
assert.equal((await tick(controller,env)).status,'STALE_ACTIVE_BLOCKED');
assert.equal(posts.length,1);

// On a controlled rollback the Worker dynamically follows the restored
// OLD source; a recent NEW-source success is not a v4 recovery receipt.
main=OLD;
runs=[run(NEW,7,1),run(OLD,6,48)];
outcome=await tick(controller,env);
assert.equal(outcome.status,'DISPATCH_ACCEPTED_NOT_COMPLETED');
const reverted=JSON.parse(Buffer.from(posts.at(-1).inputs.cloudflare_attestation,'base64url').toString('utf8'));
assert.equal(reverted.source_sha,OLD);
assert.equal(posts.length,2);

// Source identity is never inferred from another repository.
assert(!gets.some(x=>x!=='main'&&x!=='runs'));
console.log('V5_CLOUDFLARE_DYNAMIC_MAIN_SWITCH_AND_ROLLBACK_PASS');
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", js],
            cwd=ROOT, capture_output=True, text=True, timeout=25, check=False,
        )
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertIn("V5_CLOUDFLARE_DYNAMIC_MAIN_SWITCH_AND_ROLLBACK_PASS",
                      completed.stdout)

    def test_protected_native_and_cloudflare_workflow_boundaries_remain(self):
        worker = WORKER.read_text(encoding="utf-8")
        core = CYCLE.read_text(encoding="utf-8")
        watchdog = WATCHDOG.read_text(encoding="utf-8")
        self.assertIn('githubGet("/branches/main",token)', worker)
        self.assertIn('const result=decide(runs,sha,nowMs)', worker)
        self.assertIn('source_sha:sha', worker)
        self.assertNotIn("9fc08c72e2d050359e7f119bfcbfb82b23f95b5b",worker)
        self.assertIn("async fetch() { return new Response(\"Not Found\",{status:404}); }",worker)
        self.assertIn('- cron: "7,27,47 * * * *"', core)
        self.assertIn('- cron: "16,36,56 * * * *"', watchdog)
        self.assertIn("group: brain-v2-state",core)
        self.assertIn("cancel-in-progress: false",core)
        self.assertIn("MAIN_DRIFT:",core)
        self.assertIn("STATE_CONFLICT:",core)
        self.assertIn("Verify independently signed Cloudflare Cron provenance",core)
        self.assertIn("push origin HEAD:refs/heads/brain-state-v2",core)
        self.assertNotIn("git push --force",core)
        self.assertIn("BRAIN_STATE_PARENT",core)

if __name__=="__main__":
    unittest.main()
