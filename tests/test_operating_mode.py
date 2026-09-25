import json,unittest
from pathlib import Path
from operations.validate_operating_mode import validate_operating_mode
ROOT=Path(__file__).resolve().parents[1]

class OperatingModeTests(unittest.TestCase):
    def test_release_candidate_contract_passes(self):
        result=validate_operating_mode()
        self.assertEqual(result["approved_recurring_workflows"],7)
        self.assertEqual(result["enabled_nonzero_models"],0)
        self.assertFalse(result["interactive_chatgpt_runtime_dependency"])

    def test_all_recurring_workflows_have_expected_trigger_class(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        self.assertEqual(set(p["approved_recurring_workflows"]),{
          "runtime-hourly-sync","runtime-daily-learning","runtime-weekly-synthesis",
          "hunter-autonomous-cycle","portfolio-autonomous-scheduler",
          "portfolio-cost-watchdog","portfolio-notification-cycle"
        })

    def test_no_autonomous_customer_payment_trading_deploy_merge_authority(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        boundaries=set(p["permanent_authority_boundaries"])
        self.assertIn("CUSTOMER_COMMUNICATION_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("PAYMENT_CASH_MOVEMENT_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED",boundaries)
        self.assertIn("DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",boundaries)

    def test_chatgpt_tasks_are_advisory_not_runtime_dependency(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        self.assertFalse(p["interactive_chatgpt_runtime_dependency"])
        self.assertTrue(any("advisory" in x.lower() for x in p["invariants"]))

    def test_step24_canary_is_release_prerequisite(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        a=p["activation_prerequisites"]
        self.assertEqual(a["step24_status"],"COMPLETE")
        self.assertEqual(a["step24_authority_violations"],0)
        self.assertEqual(a["step24_paid_cost_usd"],0.0)
        self.assertEqual(a["step24_continuation_selected_work"],0)

if __name__=="__main__":unittest.main()
