import unittest

from hunting.steps10_12_live_acceptance import build_receipt

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
        self.assertFalse(receipt["step12"]["implementation_complete"])
        self.assertFalse(receipt["step12"]["technical_verified"])
        self.assertFalse(receipt["step12"]["market_verified"])
        self.assertFalse(receipt["step12"]["revenue_verified"])
        self.assertTrue(receipt["step12"]["ci_market_promotion_rejected"])
        self.assertFalse(receipt["step12"]["merge_authority_granted"])
        self.assertFalse(receipt["step12"]["deployment_authority_granted"])
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])

if __name__=="__main__":
    unittest.main()
