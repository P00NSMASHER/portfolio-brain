import copy,unittest
from repair.repair_engine import RepairError,apply_canary,apply_heldout,apply_independent_audit,compile_factory_work,failure_to_task,hashv,learning_alert_failures,record_factory_candidate,validate_history
H=lambda c:"sha256:"+c*64
def failure(source="FAILURE_PACKET",state="VERIFIED",**kw):
    x={"schema_version":"1.0.0","failure_id":"RFAIL-TEST-0001","source_type":source,"project_ids":["PRJ-000"],"target_repository_id":"REPO-008","target_paths":["learning/continuous_learning.py"],"failure_class":"REGRESSION","observation":"A reproducible regression changes the expected decision.","reproduction_steps":["Run the frozen fixture","Observe the wrong decision"],"evidence_refs":["evidence:failure"],"regression_test_requirement":"The frozen fixture must preserve the expected decision.","evidence_state":state,"sensitive_material_involved":False,"benchmark_contaminated":False,"reported_at":"2026-09-25T20:00:00Z"}
    x.update(kw);return x
def evalpkt(stage,actor,result="PASS",tests=3,passed=3,regs=0,viol=0):
    return {"schema_version":"1.0.0","evaluation_id":"REVAL-"+stage+"-0001","repair_task_id":"RTASK-"+__import__("hashlib").sha256(b"RFAIL-TEST-0001").hexdigest()[:20].upper(),"stage":stage,"actor_agent_id":actor,"candidate_commit_sha":"b"*40,"candidate_diff_hash":H("d"),"result":result,"tests_total":tests,"tests_passed":passed,"regressions":regs,"authority_violations":viol,"evidence_refs":["eval:"+stage],"report_hash":H("r")}
def candidate_task():
    t=failure_to_task(failure());t,p=compile_factory_work(t,"a"*40)
    rec={"work_id":p["factory_work_id"],"state":"PR_OPEN","builder_agent_id":"AGT-ENGINEER","verification_id":"SFV-1","commit_sha":"b"*40,"diff_hash":H("d"),"test_receipt_hashes":[H("t")],"pr_number":1,"pr_url":"https://example/pr/1"}
    return record_factory_candidate(t,rec)
class RepairTests(unittest.TestCase):
    def test_verified_reproducible_failure_becomes_ready(self):
        t=failure_to_task(failure());self.assertEqual(t["state"],"READY_FOR_REPAIR");self.assertTrue(validate_history(t))
    def test_learning_alert_is_reproduction_only(self):
        f=failure(source="LEARNING_ALERT",state="OBSERVED",reproduction_steps=[],regression_test_requirement=None);self.assertEqual(failure_to_task(f)["state"],"NEEDS_REPRODUCTION")
    def test_unverified_failure_cannot_authorize_repair(self):
        self.assertEqual(failure_to_task(failure(state="OBSERVED"))["state"],"NEEDS_REPRODUCTION")
    def test_sensitive_and_benchmark_failures_block(self):
        self.assertEqual(failure_to_task(failure(sensitive_material_involved=True))["state"],"BLOCKED");self.assertEqual(failure_to_task(failure(benchmark_contaminated=True))["state"],"BLOCKED")
    def test_protected_target_blocks(self):
        self.assertEqual(failure_to_task(failure(target_paths=[".github/workflows/x.yml"]))["state"],"BLOCKED")
    def test_other_repository_blocks(self):
        self.assertEqual(failure_to_task(failure(target_repository_id="REPO-002"))["state"],"BLOCKED")
    def test_only_ready_task_compiles_factory_work(self):
        with self.assertRaises(RepairError):compile_factory_work(failure_to_task(failure(state="OBSERVED")),"a"*40)
        t,p=compile_factory_work(failure_to_task(failure()),"a"*40);self.assertEqual(t["state"],"FACTORY_PENDING");self.assertEqual(p["repository_id"],"REPO-008");self.assertEqual(p["required_regression_test"],failure()["regression_test_requirement"])
    def test_factory_candidate_requires_pr_open_and_verification(self):
        t,p=compile_factory_work(failure_to_task(failure()),"a"*40)
        bad={"work_id":p["factory_work_id"],"state":"READY_FOR_PR","builder_agent_id":"AGT-ENGINEER","verification_id":"SFV-1","commit_sha":"b"*40,"diff_hash":H("d"),"test_receipt_hashes":[H("t")],"pr_number":None,"pr_url":None}
        with self.assertRaises(RepairError):record_factory_candidate(t,bad)
    def test_heldout_must_pass_exact_candidate(self):
        t=candidate_task();e=evalpkt("HELD_OUT","AGT-TESTER");t=apply_heldout(t,e);self.assertEqual(t["state"],"INDEPENDENT_AUDIT_PENDING")
        t2=candidate_task();bad=evalpkt("HELD_OUT","AGT-TESTER",passed=2);self.assertEqual(apply_heldout(t2,bad)["state"],"BLOCKED")
    def test_builder_cannot_run_heldout(self):
        with self.assertRaises(RepairError):apply_heldout(candidate_task(),evalpkt("HELD_OUT","AGT-ENGINEER"))
    def test_auditor_must_be_independent_of_builder_and_heldout_evaluator(self):
        t=apply_heldout(candidate_task(),evalpkt("HELD_OUT","AGT-TESTER"))
        with self.assertRaises(RepairError):apply_independent_audit(t,evalpkt("INDEPENDENT_AUDIT","AGT-TESTER"))
        t=apply_independent_audit(t,evalpkt("INDEPENDENT_AUDIT","AGT-AUDITOR"));self.assertEqual(t["state"],"CANARY_PENDING")
    def test_canary_requires_zero_regressions_and_authority_violations(self):
        t=apply_independent_audit(apply_heldout(candidate_task(),evalpkt("HELD_OUT","AGT-TESTER")),evalpkt("INDEPENDENT_AUDIT","AGT-AUDITOR"))
        bad=evalpkt("CANARY","AGT-RED-TEAM",regs=1);self.assertEqual(apply_canary(t,bad)["state"],"BLOCKED")
        t=apply_independent_audit(apply_heldout(candidate_task(),evalpkt("HELD_OUT","AGT-TESTER")),evalpkt("INDEPENDENT_AUDIT","AGT-AUDITOR"))
        good=apply_canary(t,evalpkt("CANARY","AGT-RED-TEAM"));self.assertEqual(good["state"],"PROMOTION_ELIGIBLE");self.assertFalse(good["promotion"]["automatic_promotion"]);self.assertEqual(good["promotion"]["required_approval"],"INTEGRATOR_APPROVAL")
    def test_tampered_history_is_rejected(self):
        t=failure_to_task(failure());bad=copy.deepcopy(t);bad["history"][0]["detail"]["state"]="BLOCKED"
        with self.assertRaises(RepairError):validate_history(bad)
    def test_learning_alert_conversion_does_not_invent_regression_test(self):
        rows=learning_alert_failures({"learning_alerts":[{"type":"overfit_signal","memory_key":"GLOBAL::SEARCH::*::x"}]},"2026-09-25T20:00:00Z")
        self.assertEqual(rows[0]["source_type"],"LEARNING_ALERT");self.assertIsNone(rows[0]["regression_test_requirement"]);self.assertEqual(failure_to_task(rows[0])["state"],"NEEDS_REPRODUCTION")
if __name__=="__main__":unittest.main()
