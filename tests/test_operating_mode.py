import json,unittest
from pathlib import Path
from operations.validate_operating_mode import validate_operating_mode
ROOT=Path(__file__).resolve().parents[1]

class OperatingModeTests(unittest.TestCase):
    def test_operational_contract_passes(self):
        result=validate_operating_mode()
        self.assertEqual(result["approved_recurring_workflows"],7)
        self.assertEqual(result["durable_state_artifacts"],5)
        self.assertEqual(result["gmail_gateway_account"],"jayp19386@gmail.com")
        self.assertEqual(result["enabled_nonzero_models"],3)
        self.assertFalse(result["interactive_chatgpt_runtime_dependency"])
        self.assertEqual(result["release_status"],"OPERATIONAL")
        self.assertEqual(result["promoted_main_sha"],"cdd7adc71472f61a07f3641e9ff414091fc1bc35")

    def test_all_recurring_workflows_have_expected_trigger_class(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        self.assertEqual(set(p["approved_recurring_workflows"]),{
          "runtime-hourly-sync","runtime-daily-learning","runtime-weekly-synthesis",
          "hunter-autonomous-cycle","portfolio-autonomous-scheduler",
          "portfolio-cost-watchdog","portfolio-notification-cycle"
        })

    def test_high_risk_payment_trading_deploy_merge_boundaries_remain(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        boundaries=set(p["permanent_authority_boundaries"])
        self.assertNotIn("CUSTOMER_COMMUNICATION_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("PAYMENT_CASH_MOVEMENT_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED",boundaries)
        self.assertIn("DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",boundaries)

    def test_gmail_gateway_is_connector_bound_and_no_smtp_worker_exists(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        gmail=p["external_connector_gateways"]["gmail"]
        self.assertEqual(gmail["provider"],"CHATGPT_GMAIL_CONNECTOR")
        self.assertEqual(gmail["account"],"jayp19386@gmail.com")
        self.assertEqual(gmail["execution_task_id"],"6ab377c25df08191a6e2aa1537d9d2ef")
        self.assertFalse((ROOT/".github/workflows/portfolio-action-worker.yml").exists())

    def test_chatgpt_tasks_are_advisory_not_runtime_dependency(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        s=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())
        self.assertFalse(p["interactive_chatgpt_runtime_dependency"])
        self.assertTrue(s["operational_without_interactive_chatgpt"])
        self.assertEqual(s["external_chatgpt_tasks_role"],"BOUNDED_GMAIL_GATEWAY_PLUS_ADVISORY_MONITORING")

    def test_post_promotion_evidence_is_recorded(self):
        s=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())
        self.assertEqual(s["final_ci_run_id"],36202440293)
        self.assertEqual(s["post_promotion_runtime_run_id"],36202440452)
        names={x["name"] for x in s["post_promotion_runtime_artifacts"]}
        self.assertIn("portfolio-runtime-state",names)
        self.assertIn("portfolio-cost-governor-state",names)

if __name__=="__main__":unittest.main()
