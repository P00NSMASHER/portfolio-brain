import unittest
from acceptance.step22_finalize import build_receipt

H=lambda c:"sha256:"+c*64
S=lambda c:c*40

class Step22FinalizeTests(unittest.TestCase):
    def test_builds_contract_valid_receipt(self):
        meta={
          "schema_version":"1.0.0","current_main_sha":S("b"),
          "fault":{"base_sha":S("a"),"detected_at":"2026-09-30T20:00:00Z","dispatched_at":"2026-09-30T20:00:01Z","dispatch_run_id":1,"receipt_hash":H("1"),"fingerprint":H("2")},
          "repair":{
            "base_sha":S("a"),"workflow_run_id":2,"workflow_created_at":"2026-09-30T20:00:02Z",
            "pr_number":3,"pr_created_at":"2026-09-30T20:00:03Z","actor_login":"github-actions[bot]","branch":"factory/auto-repair-test",
            "candidate_head_sha":S("c"),"new_regression_added":True,"new_regression_paths":["tests/test_new_step22.py"],
            "full_test_suite_passed":True,"handoff_artifact_digest":H("3"),"independent_review_artifact_digest":H("4"),
            "foundation_check":{"check_run_id":4,"name":"validate","app_id":15368,"head_sha":S("c"),"conclusion":"success","completed_at":"2026-09-30T20:00:04Z"},
            "hosted_verifier_check":{"check_run_id":5,"name":"portfolio-phase1-gate","app_id":5121826,"head_sha":S("c"),"conclusion":"success","completed_at":"2026-09-30T20:00:05Z"},
            "merged_at":"2026-09-30T20:00:06Z","merge_sha":S("b"),"merge_receipt_hash":H("5"),
          },
          "cycles":{
            "runtime":{"run_id":6,"head_sha":S("b"),"conclusion":"success","completed_at":"2026-09-30T20:00:07Z","artifact_hashes":[H("6")]},
            "reducer":{"run_id":7,"head_sha":S("b"),"conclusion":"success","completed_at":"2026-09-30T20:00:08Z","artifact_hashes":[H("7")]},
            "scheduler":{"run_id":8,"head_sha":S("b"),"conclusion":"success","completed_at":"2026-09-30T20:00:09Z","artifact_hashes":[H("8")]},
          },
        }
        receipt=build_receipt(meta)
        self.assertEqual(receipt["status"],"PASS")
        self.assertEqual(receipt["step"],22)
        self.assertEqual(receipt["repair_merge_sha"],S("b"))

if __name__=="__main__":unittest.main()
