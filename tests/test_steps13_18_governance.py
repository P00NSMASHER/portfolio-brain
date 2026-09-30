import unittest
from adapters.project_forwarder import ProjectForwardingError,forward_observation,load_seed_state as forwarding_seed
from adapters.abvm_observer import ABVMObservationError,build_abvm_evidence
from governance.authority import BoundaryError,project_capability,require_project_capability,validate_boundaries
from governance.evidence_semantics import semantics,source_projection
from hunting.autonomous_hunter import load_seed_state as hunter_seed
from hunting.repo_scout_intake import ingest_queue,load_seed_state as intake_seed
SHA="a"*40
def receipt(adapter_id="ADP-008",repository_id="REPO-008",repository_full_name="P00NSMASHER/portfolio-brain"):
 return {"adapter_id":adapter_id,"repository_id":repository_id,"repository_full_name":repository_full_name,"source_ref":"main","status":"INITIALIZED","current_sha":SHA,"receipt_hash":"sha256:"+"b"*64}
class FakeProvider:
 def __init__(self):self.metadata_calls=0;self.inspect_calls=0
 def repository_metadata(self,full_name):self.metadata_calls+=1;return {"id":123,"full_name":full_name,"private":False}
 def inspect_revision(self,candidate,revision):self.inspect_calls+=1;return {"revision":revision,"tree_sha":revision,"truncated":False,"paths":["src/roblox_framework.lua","tests/test_roblox_framework.lua","README.md"]}
def scout():
 return {"schema_version":2,"authority":"PRE_VERIFICATION_DISCOVERY_ONLY","worker_id":"HUNTER-01","candidate_count":2,"candidates":[{"repository":"example/eligible","exact_revision":"c"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":55,"root_code_signals":["src","tests"]},{"repository":"example/low","exact_revision":"d"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":1,"root_code_signals":["src"]}]}
class RemediationGovernanceTests(unittest.TestCase):
 def test_boundary_matrix(self):
  self.assertEqual(validate_boundaries()["projects"],12);self.assertTrue(project_capability("PRJ-000","CANDIDATE_PR"));self.assertFalse(project_capability("PRJ-006","DEPLOY"))
  with self.assertRaises(BoundaryError):require_project_capability("PRJ-006","DEPLOY")
 def test_forward_exact_once(self):
  d=[];s,a=forward_observation("PRJ-000",receipt(),forwarding_seed(),d.append);s,b=forward_observation("PRJ-000",receipt(),s,d.append);self.assertEqual(len(d),1);self.assertEqual(a["status"],"FORWARDED");self.assertEqual(b["status"],"DUPLICATE_SUPPRESSED");self.assertFalse(d[0]["deployment_authority"])
 def test_forward_wrong_project(self):
  with self.assertRaises(ProjectForwardingError):forward_observation("PRJ-005",receipt("ADP-003","REPO-003","P00NSMASHER/abvmschoolstarworld"),forwarding_seed(),lambda _:None)
 def test_repo001_intake_and_dedupe(self):
  p=FakeProvider();s,a=ingest_queue(queue=scout(),source_revision="e"*40,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=p,intake_state=intake_seed(),at="2026-09-30T14:00:00Z");self.assertEqual(a["inspected_candidates"],1);self.assertEqual(len(a["admitted"]),1);self.assertIsNotNone(a["admitted"][0]["proposal"]);self.assertFalse(a["reuse_rights_granted"])
  _,b=ingest_queue(queue=scout(),source_revision="e"*40,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=p,intake_state=s,at="2026-09-30T14:01:00Z");self.assertEqual(b["inspected_candidates"],0);self.assertEqual(len(b["duplicates"]),1);self.assertEqual(p.inspect_calls,1)
 def test_source_revision_in_dedupe(self):
  p=FakeProvider();s,_=ingest_queue(queue=scout(),source_revision="e"*40,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=p,intake_state=intake_seed(),at="2026-09-30T14:00:00Z");_,b=ingest_queue(queue=scout(),source_revision="f"*40,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=p,intake_state=s,at="2026-09-30T14:01:00Z");self.assertEqual(b["inspected_candidates"],1)
 def test_abvm_constrained(self):
  r=receipt("ADP-003","REPO-003","P00NSMASHER/abvmschoolstarworld");o=build_abvm_evidence(r,automation_health="HEALTHY",progress={"latest_run_id":1,"latest_run_status":"completed","latest_run_conclusion":"success","source_sequence":1,"source_revision":SHA});self.assertEqual(o["evidence_scope"],"AUTOMATION_HEALTH_AND_PROGRESS_ONLY");self.assertFalse(o["child_facing_mutation_authority"]);self.assertFalse(o["deployment_authority"])
  with self.assertRaises(ABVMObservationError):build_abvm_evidence(r,automation_health="HEALTHY",progress={"school_content":"secret"})
 def test_nonproof_semantics(self):
  for k in ("HEARTBEAT","NOTIFICATION","PAGES_PUBLICATION"):
   s=semantics(k);self.assertFalse(s["technical_verification"]);self.assertFalse(s["market_verification"]);self.assertFalse(s["revenue_verification"]);self.assertEqual(s["verification_credit"],[])
 def test_source_projection(self):
  p=source_projection("runtime",{"status":"STALE","age_minutes":90,"stale_after_minutes":60,"state_sequence":12,"state_hash":"sha256:"+"1"*64,"source_head_sha":"2"*40,"source_run_id":"9","source_ref":"artifact","error_class":"TimeoutError"});self.assertEqual(p["status"],"STALE");self.assertEqual(p["state_sequence"],12);self.assertTrue(p["state_hash"].startswith("sha256:"));self.assertEqual(p["blocked_reason"],"TimeoutError")
if __name__=="__main__":unittest.main()
