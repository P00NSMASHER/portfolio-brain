import os
import unittest
from unittest.mock import patch

from hunting.steps10_12_live_acceptance import LiveAcceptanceError, build_receipt

class Steps1012LiveAcceptanceTests(unittest.TestCase):
    def test_controlled_acceptance_receipt_is_fail_closed_and_non_value_claiming(self):
        receipt=build_receipt(
          source_sha="d"*40,
          run_id="controlled-unit-proof",
          source_branch="main",
        )
        self.assertEqual(receipt["status"],"PASS")
        self.assertEqual(receipt["step10"]["first_ingestion_status"],"INGESTED")
        self.assertEqual(receipt["step10"]["second_ingestion_status"],"ALREADY_INGESTED")
        self.assertEqual(receipt["step10"]["fresh_learning_before"],0)
        self.assertGreater(receipt["step10"]["fresh_learning_after"],0)
        self.assertNotEqual(
          receipt["step10"]["baseline_cycle_receipt_hash"],
          receipt["step10"]["fresh_cycle_receipt_hash"],
        )
        self.assertFalse(receipt["step11"]["baseline_or_seed_fresh_credit"])
        self.assertFalse(receipt["step11"]["pinned_upstream_fresh_credit"])
        self.assertTrue(receipt["step11"]["verified_outcome_fresh_credit"])
        self.assertEqual(receipt["step12"]["current_stage"],"ACCEPTED_FOR_WORK")
        self.assertEqual(receipt["step12"]["scheduler_work_type"],"IMPLEMENTATION")
        self.assertEqual(receipt["step12"]["scheduler_dispatch_status"],"ACCEPTED")
        self.assertEqual(receipt["step12"]["dispatch_result_kind"],"HUNTER_IMPLEMENTATION_DISPATCHED")
        self.assertEqual(receipt["step12"]["factory_bound_source_kind"],"HUNTER_ACCEPTED_WORK")
        self.assertEqual(receipt["step12"]["dispatch_mode"],"CONTROLLED_IN_PROCESS")
        self.assertIsNone(receipt["step12"]["dispatch_workflow_file"])
        self.assertFalse(receipt["step12"]["dispatch_authority_granted"])
        self.assertEqual(
          receipt["step12"]["factory_bound_request_fingerprint"],
          receipt["step12"]["factory_bound_request"]["fingerprint"],
        )
        self.assertFalse(receipt["step12"]["implementation_complete"])
        self.assertFalse(receipt["step12"]["technical_verified"])
        self.assertFalse(receipt["step12"]["market_verified"])
        self.assertFalse(receipt["step12"]["revenue_verified"])
        self.assertTrue(receipt["step12"]["ci_market_promotion_rejected"])
        self.assertFalse(receipt["step12"]["merge_authority_granted"])
        self.assertFalse(receipt["step12"]["deployment_authority_granted"])
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])

    def test_live_mode_uses_governed_github_workflow_dispatch_boundary(self):
        calls=[]
        def fake_dispatch(requests, *, token, repository, workflow_file):
            self.assertEqual(token,"fixture-token")
            self.assertEqual(repository,"P00NSMASHER/portfolio-brain")
            self.assertEqual(workflow_file,"portfolio-autonomous-repair.yml")
            self.assertEqual(len(requests),1)
            request=requests[0]
            calls.append(request)
            return [{
              "request_id":request["request_id"],
              "fingerprint":request["fingerprint"],
              "workflow_file":workflow_file,
              "dispatch_status":"ACCEPTED",
              "authority_granted":False,
            }]
        live_sha="e"*40
        with patch.dict(os.environ,{
               "GITHUB_TOKEN":"fixture-token",
               "GITHUB_ACTIONS":"true",
               "GITHUB_REF_NAME":"main",
               "GITHUB_SHA":live_sha,
             }), \
             patch("scheduler.work_executor.dispatch_requests",side_effect=fake_dispatch):
            receipt=build_receipt(
              source_sha=live_sha,
              run_id="controlled-live-dispatch-proof",
              source_branch="main",
              dispatch_live=True,
            )
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["source_kind"],"HUNTER_ACCEPTED_WORK")
        self.assertEqual(receipt["step12"]["dispatch_mode"],"LIVE_GITHUB_WORKFLOW")
        self.assertEqual(receipt["step12"]["dispatch_workflow_file"],"portfolio-autonomous-repair.yml")
        self.assertEqual(
          receipt["step12"]["factory_bound_request_fingerprint"],
          calls[0]["fingerprint"],
        )
        self.assertFalse(receipt["step12"]["dispatch_authority_granted"])
        self.assertFalse(receipt["step12"]["implementation_complete"])
        self.assertFalse(receipt["step12"]["market_verified"])
        self.assertFalse(receipt["step12"]["revenue_verified"])

    def test_live_dispatch_fails_closed_outside_exact_github_actions_context(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(LiveAcceptanceError,"GitHub Actions"):
                build_receipt(
                  source_sha="f"*40,
                  run_id="not-a-live-actions-run",
                  source_branch="main",
                  dispatch_live=True,
                )

if __name__=="__main__":
    unittest.main()
