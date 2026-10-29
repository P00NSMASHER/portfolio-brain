"""Verify scheduled clock proof is not accepted from self-declared JSON."""
import copy
import unittest
from soak_v3.watchdog_probe import validate_link
from soak_v3.audit import EvidenceError

SHA="a"*40
def sample():
    core={"event":"workflow_dispatch","status":"completed","conclusion":"success",
          "run_attempt":1,"actor":{"login":"github-actions[bot]"},
          "head_sha":SHA,"head_branch":"main",
          "path":".github/workflows/brain-cycle.yml",
          "created_at":"2026-10-08T04:11:00Z"}
    clock={"id":300,"name":"brain-clock-v2","event":"schedule",
           "path":".github/workflows/brain-clock.yml",
           "head_sha":SHA,"head_branch":"main","run_attempt":1,
           "status":"completed","conclusion":"success",
           "created_at":"2026-10-08T04:10:00Z"}
    origin={"kind":"github_schedule","source_sha":SHA,"clock_run_id":300,
            "core_actor":"github-actions[bot]","soak_pass":False}
    job={"name":"scheduled-watchdog","status":"completed","conclusion":"success",
         "steps":[{"name":"Dispatch one overdue core without inventing a PASS",
                   "conclusion":"success"}]}
    decision={"status":"DUE","dispatch":True,"source_sha":SHA,"soak_pass":False}
    return core,clock,origin,job,decision

class Proof(unittest.TestCase):
    def test_complete_github_native_chain_can_be_attested(self):
        result=validate_link(*sample(),source_sha=SHA)
        self.assertEqual(result["kind"],"github_schedule")
        self.assertTrue(result["provider_scheduler_verified"])
    def test_manual_core_actor_is_not_automatic(self):
        c=sample()
        c[0]["actor"]["login"]="P00NSMASHER"
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
    def test_manual_parent_not_scheduled(self):
        c=sample()
        c[1]["event"]="workflow_dispatch"
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
    def test_parent_failure_and_unrelated_core_rejected(self):
        for index,field,value in [(1,"conclusion","failure"),(0,"head_sha","b"*40),
                                  (1,"run_attempt",2),(1,"path","other")]:
            c=sample()
            c[index][field]=value
            with self.subTest(index=index,field=field),self.assertRaises(EvidenceError):
                validate_link(*c,source_sha=SHA)
    def test_successful_watchdog_without_dispatch_step_rejected(self):
        c=sample()
        c[3]["steps"][0]["conclusion"]="skipped"
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
    def test_clock_job_failed_not_automatic(self):
        c=sample()
        c[3]["conclusion"]="failure"
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
    def test_false_due_or_unrelated_origin_rejected(self):
        c=sample()
        c[4]["dispatch"]=False
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
        c=sample()
        c[2]["clock_run_id"]=400
        with self.assertRaises(EvidenceError):
            validate_link(*c,source_sha=SHA)
    def test_delayed_or_reverse_parent_time_rejected(self):
        for clock,core in [("2026-10-08T04:00:00Z","2026-10-08T04:30:00Z"),
                           ("2026-10-08T04:20:00Z","2026-10-08T04:10:00Z")]:
            c=sample()
            c[1]["created_at"]=clock
            c[0]["created_at"]=core
            with self.subTest(clock=clock),self.assertRaises(EvidenceError):
                validate_link(*c,source_sha=SHA)

if __name__=="__main__":
    unittest.main()
