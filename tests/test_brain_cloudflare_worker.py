"""Exercise Cloudflare scheduled health decisions without a network or credentials."""
from pathlib import Path
import shutil
import subprocess
import unittest

WORKER=Path(__file__).resolve().parents[1]/"reliability/cloudflare/worker.mjs"

class CloudflareDecisionTests(unittest.TestCase):
    def test_independent_fallback_health_and_source_identity(self):
        if not shutil.which("node"):self.skipTest("Node is unavailable")
        js="""
import {decide} from './reliability/cloudflare/worker.mjs';
import assert from 'node:assert/strict';
const sha='a'.repeat(40);
const now=Date.parse('2026-10-08T06:00:00Z');
function row(min,id,status='completed',conclusion='success',source=sha){
 const done=new Date(now-min*60000).toISOString();
 return {id,path:'.github/workflows/brain-cycle.yml',event:'schedule',
         head_sha:source,head_branch:'main',created_at:done,updated_at:done,
         status,conclusion};
}
const history=(...rows)=>({total_count:rows.length,workflow_runs:rows});
const fresh=decide(history(row(8,1)),sha,now);
assert.equal(fresh.status,'FRESH');
assert.equal(fresh.dispatch,false);
const due=decide(history(row(46,2)),sha,now);
assert.equal(due.status,'DUE');
assert.equal(due.dispatch,true);
const active=decide(history(row(2,3,'in_progress',null),row(50,4)),sha,now);
assert.equal(active.status,'ACTIVE');
assert.equal(active.dispatch,false);
const stale=decide(history(row(30,5,'queued',null)),sha,now);
assert.equal(stale.status,'STALE_ACTIVE_BLOCKED');
assert.equal(stale.dispatch,false);
const failed=decide(history(row(5,6,'completed','failure')),sha,now);
assert.equal(failed.status,'DUE');
assert.equal(failed.dispatch,true);
const otherSource=decide(history(row(1,7,'completed','success','b'.repeat(40))),sha,now);
assert.equal(otherSource.status,'DUE');
assert.throws(()=>decide({total_count:2,workflow_runs:[row(1,1)]},sha,now));
assert.throws(()=>decide(history(row(1,1),row(1,2,'completed','success','notsha')),sha,now));
console.log('WORKER_DECISIONS_PASS');
"""
        result=subprocess.run(["node","--input-type=module","-e",js],
                cwd=WORKER.parents[2],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("WORKER_DECISIONS_PASS",result.stdout)

if __name__=="__main__":unittest.main()
