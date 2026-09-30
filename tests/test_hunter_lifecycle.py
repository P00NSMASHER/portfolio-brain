import tempfile
import unittest
from pathlib import Path

from hunting.lifecycle import (
    HunterLifecycleError,
    apply_acceptance,
    apply_external_evidence,
    apply_factory_evidence,
    build_acceptance_receipt,
    enqueue_factory_work,
    lifecycle_from_review,
)
from hunting.proposal_review_state import digest
from software_factory.software_factory import SoftwareFactory

H=lambda c:"sha256:"+c*64

def controlled_review():
    core={
      "review_id":"HREV-CONTROLLED-LIFECYCLE",
      "proposal_id":"HEXP-CONTROLLED-LIFECYCLE",
      "finding_id":"HFD-CONTROLLED-LIFECYCLE",
      "project_ids":["PRJ-000"],
      "repository_full_name":"HypothesisWorks/hypothesis",
      "repository_id":8685799,
      "revision":"a"*40,"tree_sha":"b"*40,
      "rank_score":9,"rank_band":"HIGH",
      "capability_key":"capability-coverage:property-testing",
      "license_spdx_id":"MPL-2.0","license_name":"Mozilla Public License 2.0",
      "license_state":"LICENSE_METADATA_PRESENT_INFORMATIONAL",
      "rights_state":"OPERATOR_ASSUMED",
      "reuse_authorized":False,"implementation_authorized":False,
      "code_execution_performed":False,"downstream_mutation_performed":False,
      "source_execution_id":"WEXEC-CONTROLLED-LIFECYCLE",
      "source_execution_receipt_hash":H("c"),
      "reviewed_at":"2026-09-30T13:00:00Z",
      "evidence_refs":[
        "hunter-proposal:HEXP-CONTROLLED-LIFECYCLE",
        "hunter-finding:HFD-CONTROLLED-LIFECYCLE",
        "github:HypothesisWorks/hypothesis@"+"a"*40,
        "git-tree:"+"b"*40,
        "license-metadata:MPL-2.0",
      ],
    }
    return {**core,"review_hash":digest(core)}

class HunterLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.review=controlled_review()
        self.lifecycle=lifecycle_from_review(self.review)
        self.acceptance=build_acceptance_receipt(
          self.lifecycle,acceptance_id="HACC-CONTROLLED-0001",
          target_repository_id="REPO-008",project_id="PRJ-000",
          verifier_agent_id="AGT-TESTER",accepted_at="2026-09-30T13:01:00Z",
          evidence_refs=["issue:210","controlled-proof:step12"],controlled_proof=True,
        )

    def test_review_does_not_auto_accept_or_claim_value(self):
        self.assertEqual(self.lifecycle["current_stage"],"REVIEWED")
        self.assertEqual([x["stage"] for x in self.lifecycle["stage_history"]],["DISCOVERED","REVIEWED"])
        self.assertFalse(self.lifecycle["market_verified"])
        self.assertFalse(self.lifecycle["revenue_verified"])
        self.assertFalse(self.lifecycle["merge_authority_granted"])
        self.assertFalse(self.lifecycle["deployment_authority_granted"])

    def test_controlled_accepted_finding_creates_real_governed_factory_work(self):
        accepted=apply_acceptance(self.lifecycle,self.acceptance)
        self.assertEqual(accepted["current_stage"],"ACCEPTED_FOR_WORK")
        with tempfile.TemporaryDirectory() as td:
            sf=SoftwareFactory(Path(td)/"factory.sqlite3")
            try:
                bound,work=enqueue_factory_work(
                  sf,accepted,self.acceptance,base_sha="d"*40,now=1.0
                )
                self.assertEqual(work["state"],"QUEUED")
                self.assertEqual(work["project_id"],"PRJ-000")
                self.assertEqual(work["repository_id"],"REPO-008")
                self.assertTrue(work["work_id"].startswith("SFW-HUNTER-"))
                self.assertIn("hunter-acceptance:HACC-CONTROLLED-0001",work["provenance_refs"])
                self.assertEqual(bound["current_stage"],"ACCEPTED_FOR_WORK")
            finally:
                sf.close()

    def test_factory_and_external_evidence_advance_only_one_stage_at_a_time(self):
        accepted=apply_acceptance(self.lifecycle,self.acceptance)
        with tempfile.TemporaryDirectory() as td:
            sf=SoftwareFactory(Path(td)/"factory.sqlite3")
            try:
                lifecycle,work=enqueue_factory_work(sf,accepted,self.acceptance,base_sha="d"*40,now=1.0)
                sf.claim(work["work_id"],"AGT-ENGINEER",now=2.0)
                sf.record_candidate_commit(
                  work["work_id"],"AGT-ENGINEER",commit_sha="e"*40,
                  changed_paths=["hunting/example.py"],test_commands=["python -m unittest tests.test_example"],
                  test_receipt_hashes=[H("t")],diff_hash=H("f"),now=3.0,
                )
                lifecycle=apply_factory_evidence(lifecycle,sf.get(work["work_id"]),at="2026-09-30T13:02:00Z")
                self.assertEqual(lifecycle["current_stage"],"IMPLEMENTED")
                self.assertFalse(lifecycle["market_verified"])

                sf.verify(
                  work["work_id"],"AGT-TESTER","PASS",report_hash=H("r"),
                  evidence_refs=["test:independent"],now=4.0,
                )
                lifecycle=apply_factory_evidence(lifecycle,sf.get(work["work_id"]),at="2026-09-30T13:03:00Z")
                self.assertEqual(lifecycle["current_stage"],"TECHNICALLY_VERIFIED")
                self.assertFalse(lifecycle["market_verified"])
                self.assertFalse(lifecycle["revenue_verified"])

                with self.assertRaises(HunterLifecycleError):
                    apply_external_evidence(lifecycle,{
                      "proposal_id":lifecycle["proposal_id"],"target_stage":"MARKET_VERIFIED",
                      "evidence_kind":"CI_PASS","verified":True,
                      "observed_at":"2026-09-30T13:04:00Z","evidence_refs":["ci:pass"],
                    })
                market=apply_external_evidence(lifecycle,{
                  "proposal_id":lifecycle["proposal_id"],"target_stage":"MARKET_VERIFIED",
                  "evidence_kind":"MARKET_OUTCOME","verified":True,
                  "observed_at":"2026-09-30T13:05:00Z","evidence_refs":["market-outcome:MKT-1"],
                })
                self.assertTrue(market["market_verified"])
                self.assertFalse(market["revenue_verified"])
                revenue=apply_external_evidence(market,{
                  "proposal_id":market["proposal_id"],"target_stage":"REVENUE_VERIFIED",
                  "evidence_kind":"REVENUE_OUTCOME","verified":True,"transaction_ref":"TXN-1",
                  "observed_at":"2026-09-30T13:06:00Z","evidence_refs":["revenue-outcome:REV-1","transaction:TXN-1"],
                })
                self.assertTrue(revenue["revenue_verified"])
                self.assertEqual([x["stage"] for x in revenue["stage_history"]],[
                  "DISCOVERED","REVIEWED","ACCEPTED_FOR_WORK","IMPLEMENTED",
                  "TECHNICALLY_VERIFIED","MARKET_VERIFIED","REVENUE_VERIFIED"
                ])
            finally:
                sf.close()

    def test_stage_skipping_and_lineage_conflicts_fail_closed(self):
        with self.assertRaises(HunterLifecycleError):
            apply_external_evidence(self.lifecycle,{
              "proposal_id":self.lifecycle["proposal_id"],"target_stage":"MARKET_VERIFIED",
              "evidence_kind":"MARKET_OUTCOME","verified":True,
              "observed_at":"2026-09-30T13:05:00Z","evidence_refs":["market-outcome:MKT-1"],
            })
        bad=dict(self.acceptance);bad["proposal_id"]="HEXP-OTHER"
        body=dict(bad);body.pop("acceptance_hash");bad["acceptance_hash"]=__import__("hunting.lifecycle",fromlist=["_hash"])._hash(body)
        with self.assertRaisesRegex(HunterLifecycleError,"lineage"):
            apply_acceptance(self.lifecycle,bad)

if __name__=="__main__":
    unittest.main()
