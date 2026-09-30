import unittest

from hunting.downstream_lifecycle import (
    APPROVAL_CODE,
    HunterDownstreamError,
    acceptance_source_ref,
    apply_reviews_and_acceptances,
    load_seed_state,
)
from hunting.steps10_12_live_acceptance import controlled_review
from repair.autonomous_repair import request_from_hunter_acceptance
from scheduler.autonomous_scheduler import build_context, load_state, policy as scheduler_policy, schedule_cycle

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
        self.milestone=scheduler_policy()["external_milestones"][0]

    def apply(self,state=None,approvals=None,branch="main",repository="P00NSMASHER/portfolio-brain",**kwargs):
        return apply_reviews_and_acceptances(
          state or load_seed_state(),self.reviews,
          approvals or {"schema_version":"1.0.0","ledger_id":"portfolio-owner-approvals","approvals":[]},
          base_sha=self.base_sha,current_repository=repository,source_branch=branch,
          current_external_milestone=self.milestone,
          **kwargs,
        )

    def implementation_evidence(self,state,*,foundation=True,independent=True):
        acceptance=state["records"][0]["acceptance_receipt"]
        request=request_from_hunter_acceptance(
          {"work_type":"IMPLEMENTATION","source_ref":acceptance["acceptance_id"]},
          state,
          base_sha=self.base_sha,
        )
        fingerprint=request["fingerprint"]
        head="a"*40
        return {
          "status":"REPAIR_PR_FOUND",
          "source_ref":acceptance["acceptance_id"],
          "factory_work_id":"AUTO-REPAIR-"+fingerprint.split(":",1)[1][:16].upper()+"-36758526194",
          "request_fingerprint":fingerprint,
          "base_sha":self.base_sha,
          "candidate_sha":head,
          "pr_number":321,
          "head_sha":head,
          "head_ref":"factory/auto-repair-controlled/attempt-1",
          "foundation_success":foundation,
          "independent_success":independent,
          "checks":[
            {"id":1,"name":"validate","conclusion":"success" if foundation else None,
             "app_id":15368,"completed_at":"2026-09-30T14:06:00Z"},
            {"id":2,"name":"portfolio-phase1-gate","conclusion":"success" if independent else None,
             "app_id":5121826,"completed_at":"2026-09-30T14:06:01Z"},
          ],
          "observed_at":"2026-09-30T14:06:01Z",
          "evidence_refs":[
            "repair-pr:321","commit:"+head,
            "check:validate:15368:1","check:portfolio-phase1-gate:5121826:2",
          ],
        }

    def test_review_alone_never_creates_downstream_work(self):
        state,report=self.apply()
        record=state["records"][0]
        self.assertEqual(state["sequence"],1)
        self.assertEqual(record["lifecycle"]["current_stage"],"REVIEWED")
        self.assertIsNone(record["acceptance_receipt"])
        self.assertIsNone(record["implementation_evidence"])
        self.assertEqual(report["accepted_work"],[])

    def test_exact_owner_acceptance_creates_scheduler_ready_work_once(self):
        approvals=approval_ledger(self.review)
        state,report=self.apply(approvals=approvals)
        record=state["records"][0]
        self.assertEqual(state["sequence"],2)
        self.assertEqual(record["lifecycle"]["current_stage"],"ACCEPTED_FOR_WORK")
        self.assertIsNone(record["implementation_evidence"])
        self.assertEqual(len(report["accepted_work"]),1)
        accepted=report["accepted_work"][0]
        self.assertEqual(accepted["scheduler_work_type"],"IMPLEMENTATION")
        self.assertEqual(accepted["acceptance_id"],record["acceptance_receipt"]["acceptance_id"])
        self.assertFalse(record["lifecycle"]["market_verified"])
        self.assertFalse(record["lifecycle"]["revenue_verified"])
        self.assertFalse(record["lifecycle"]["merge_authority_granted"])
        self.assertFalse(record["lifecycle"]["deployment_authority_granted"])

        replay,replay_report=self.apply(state,approvals)
        self.assertEqual(replay["sequence"],state["sequence"])
        self.assertEqual(
          replay["records"][0]["acceptance_receipt"]["acceptance_id"],
          record["acceptance_receipt"]["acceptance_id"],
        )
        self.assertEqual(replay_report["accepted_work"],[])

    def test_accepted_finding_enters_real_scheduler_implementation_queue(self):
        state,_=self.apply(approvals=approval_ledger(self.review))
        acceptance=state["records"][0]["acceptance_receipt"]
        context=build_context(hunter_lifecycle_state=state)
        scheduled,receipt=schedule_cycle(
          load_state(),context,
          at="2026-09-30T14:05:30Z",
          candidate_filter=lambda row: row["work_type"]=="IMPLEMENTATION",
          max_new_items=1,
        )
        self.assertEqual(len(receipt["selected_work"]),1)
        work=receipt["selected_work"][0]
        self.assertEqual(work["source_ref"],acceptance["acceptance_id"])
        self.assertEqual(work["work_type"],"IMPLEMENTATION")
        self.assertEqual(work["required_authority"],"MODIFY")
        self.assertEqual(work["state"],"QUEUED")
        self.assertTrue(any(row["source_ref"]==acceptance["acceptance_id"] for row in scheduled["work_items"]))

    def test_implementation_and_technical_evidence_do_not_claim_market_or_revenue(self):
        approvals=approval_ledger(self.review)
        accepted,_=self.apply(approvals=approvals)
        evidence=self.implementation_evidence(accepted)
        verified,report=self.apply(
          accepted,approvals,
          reconcile_implementation=True,
          implementation_evidence_provider=lambda _source:evidence,
          observed_at="2026-09-30T14:06:00Z",
        )
        lifecycle=verified["records"][0]["lifecycle"]
        self.assertEqual(lifecycle["current_stage"],"TECHNICALLY_VERIFIED")
        self.assertEqual([x["stage"] for x in report["implementation_advancements"]],["IMPLEMENTED","TECHNICALLY_VERIFIED"])
        self.assertFalse(lifecycle["market_verified"])
        self.assertFalse(lifecycle["revenue_verified"])

    def test_spoofed_factory_fingerprint_fails_closed(self):
        approvals=approval_ledger(self.review)
        accepted,_=self.apply(approvals=approvals)
        evidence=self.implementation_evidence(accepted)
        evidence["request_fingerprint"]="sha256:"+"0"*64
        with self.assertRaisesRegex(HunterDownstreamError,"request fingerprint mismatch"):
            self.apply(
              accepted,approvals,
              reconcile_implementation=True,
              implementation_evidence_provider=lambda _source:evidence,
              observed_at="2026-09-30T14:06:02Z",
            )
        self.assertEqual(accepted["records"][0]["lifecycle"]["current_stage"],"ACCEPTED_FOR_WORK")

    def test_conflicting_pr_identity_after_implementation_fails_closed(self):
        approvals=approval_ledger(self.review)
        accepted,_=self.apply(approvals=approvals)
        initial=self.implementation_evidence(accepted,foundation=False,independent=False)
        implemented,_=self.apply(
          accepted,approvals,
          reconcile_implementation=True,
          implementation_evidence_provider=lambda _source:initial,
          observed_at="2026-09-30T14:06:02Z",
        )
        self.assertEqual(implemented["records"][0]["lifecycle"]["current_stage"],"IMPLEMENTED")
        conflict=dict(initial)
        conflict["head_sha"]="b"*40
        conflict["candidate_sha"]="b"*40
        with self.assertRaisesRegex(HunterDownstreamError,"conflicting Hunter implementation evidence"):
            self.apply(
              implemented,approvals,
              reconcile_implementation=True,
              implementation_evidence_provider=lambda _source:conflict,
              observed_at="2026-09-30T14:06:03Z",
            )

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
