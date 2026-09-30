import unittest

from hunting.downstream_lifecycle import (
    APPROVAL_CODE,
    acceptance_source_ref,
    apply_reviews_and_acceptances,
    load_seed_state,
)
from hunting.steps10_12_live_acceptance import controlled_review

H=lambda c:"sha256:"+c*64

def review_state(review):
    return {
      "schema_version":"1.0.0",
      "state_id":"portfolio-hunter-proposal-review-state",
      "sequence":1,
      "updated_at":review["reviewed_at"],
      "applied_execution_ids":[review["source_execution_id"]],
      "reviews":[review],
    }

def approval_ledger(review,*,source_ref=None,status="ACTIVE"):
    return {
      "schema_version":"1.0.0",
      "ledger_id":"portfolio-owner-approvals",
      "approvals":[{
        "approval_id":"OAPR-CONTROLLED-HUNTER",
        "source_ref":source_ref or acceptance_source_ref(review),
        "project_ids":["PRJ-000"],
        "approval_requirements":[APPROVAL_CODE],
        "approved_by":"P00NSMASHER",
        "approved_at":"2026-09-30T14:05:00Z",
        "status":status,
        "reason_hash":H("d"),
      }],
    }

class HunterDownstreamLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.review=controlled_review()
        self.reviews=review_state(self.review)
        self.base_sha="d"*40

    def apply(self,state=None,approvals=None,branch="main",repository="P00NSMASHER/portfolio-brain"):
        return apply_reviews_and_acceptances(
          state or load_seed_state(),self.reviews,
          approvals or {"schema_version":"1.0.0","ledger_id":"portfolio-owner-approvals","approvals":[]},
          base_sha=self.base_sha,current_repository=repository,source_branch=branch,
        )

    def test_review_alone_never_creates_downstream_work(self):
        state,report=self.apply()
        self.assertEqual(state["sequence"],1)
        self.assertEqual(state["records"][0]["lifecycle"]["current_stage"],"REVIEWED")
        self.assertIsNone(state["records"][0]["acceptance_receipt"])
        self.assertIsNone(state["records"][0]["factory_work"])
        self.assertEqual(report["accepted_work"],[])

    def test_exact_owner_acceptance_creates_governed_factory_work_once(self):
        approvals=approval_ledger(self.review)
        state,report=self.apply(approvals=approvals)
        record=state["records"][0]
        self.assertEqual(state["sequence"],2)
        self.assertEqual(record["lifecycle"]["current_stage"],"ACCEPTED_FOR_WORK")
        self.assertEqual(record["factory_work"]["state"],"QUEUED")
        self.assertTrue(record["factory_event_chain_valid"])
        self.assertFalse(record["lifecycle"]["market_verified"])
        self.assertFalse(record["lifecycle"]["revenue_verified"])
        self.assertFalse(record["lifecycle"]["merge_authority_granted"])
        self.assertFalse(record["lifecycle"]["deployment_authority_granted"])
        self.assertEqual(len(report["accepted_work"]),1)

        replay,replay_report=self.apply(state,approvals)
        self.assertEqual(replay["sequence"],state["sequence"])
        self.assertEqual(replay["records"][0]["factory_work"]["work_id"],record["factory_work"]["work_id"])
        self.assertEqual(replay_report["accepted_work"],[])

    def test_approval_must_bind_exact_review_hash(self):
        approvals=approval_ledger(self.review,source_ref="hunter-review:HREV-WRONG:"+H("e"))
        state,report=self.apply(approvals=approvals)
        self.assertEqual(state["records"][0]["lifecycle"]["current_stage"],"REVIEWED")
        self.assertEqual(report["accepted_work"],[])

    def test_non_main_or_non_current_factory_target_fails_closed(self):
        approvals=approval_ledger(self.review)
        branch_state,branch_report=self.apply(approvals=approvals,branch="feature/test")
        self.assertEqual(branch_state["records"][0]["lifecycle"]["current_stage"],"REVIEWED")
        self.assertEqual(branch_report["blocked_acceptances"][0]["reason"],"NON_MAIN_ACCEPTANCE_DISABLED")

        repo_state,repo_report=self.apply(approvals=approvals,repository="P00NSMASHER/not-this-repo")
        self.assertEqual(repo_state["records"][0]["lifecycle"]["current_stage"],"REVIEWED")
        self.assertEqual(repo_report["blocked_acceptances"][0]["reason"],"NO_CURRENT_REPOSITORY_FACTORY_TARGET")

if __name__=="__main__":
    unittest.main()
