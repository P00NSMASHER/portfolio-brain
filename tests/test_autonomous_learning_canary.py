import json,tempfile,unittest
from pathlib import Path
from canary.autonomous_learning_canary import execute_canary

class AutonomousLearningCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.receipt=execute_canary(Path(cls.tmp.name)/"out")
        cls.out=Path(cls.tmp.name)/"out"
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_canary_passes_without_interactive_dependency(self):
        self.assertEqual(self.receipt["status"],"PASS")
        self.assertTrue(self.receipt["no_interactive_chatgpt_dependency"])
        self.assertEqual(self.receipt["network_mode"],"LOCAL_CURSOR_MIRROR_ONLY")

    def test_first_cycle_runs_bounded_runtime_and_scheduler(self):
        first=self.receipt["first_cycle"]
        self.assertEqual(first["runtime_status"],"PASS")
        self.assertLessEqual(first["runtime_api_reads"],8)
        self.assertGreaterEqual(first["scheduler_selected_count"],3)
        self.assertLessEqual(first["scheduler_selected_count"],8)
        self.assertTrue({"HUNT","INTEGRATION","RESEARCH"}<=set(first["scheduler_selected_work_types"]))
        self.assertEqual(first["scheduler_blocked_approval_count"],6)

    def test_canary_uses_zero_paid_model_api(self):
        first=self.receipt["first_cycle"]
        self.assertEqual(first["paid_cost_usd"],0.0)
        self.assertEqual(first["model_calls"],0)
        self.assertFalse(self.receipt["paid_model_api_used"])

    def test_persisted_continuation_suppresses_duplicate_work(self):
        c=self.receipt["continuation"]
        self.assertEqual(c["scheduler_selected_count"],0)
        self.assertGreaterEqual(c["scheduler_suppressed_duplicates"],self.receipt["first_cycle"]["scheduler_selected_count"])
        self.assertEqual(c["cost_status"],"DUPLICATE_SUPPRESSED")
        self.assertEqual(c["notifications_emitted"],0)
        self.assertGreaterEqual(c["notification_suppressed"],2)

    def test_learning_rebuild_is_deterministic_and_not_promoted(self):
        first=self.receipt["first_cycle"];cont=self.receipt["continuation"]
        self.assertEqual(first["learning_observations"],0)
        self.assertEqual(first["learning_eligible_records"],0)
        self.assertTrue(cont["learning_state_hash_unchanged"])

    def test_zero_authority_violations_and_forbidden_actions(self):
        self.assertEqual(self.receipt["authority_violations"],0)
        self.assertEqual(self.receipt["forbidden_actions_attempted"],0)

    def test_all_five_durable_state_classes_are_restored(self):
        self.assertEqual(set(self.receipt["state_restoration"]),{"runtime","scheduler","cost","notifications","learning"})
        self.assertTrue(all(self.receipt["state_restoration"].values()))
        for name in ["runtime_state.json","scheduler_state.json","cost_state.json","notification_state.json","learning_state.json","canary_receipt.json"]:
            self.assertTrue((self.out/name).exists(),name)

    def test_receipt_is_sanitized_machine_readable_evidence(self):
        body=json.loads((self.out/"canary_receipt.json").read_text())
        self.assertTrue(body["receipt_hash"].startswith("sha256:"))
        raw=json.dumps(body).lower()
        for forbidden in ["password","api_key","secret_key","customer_email","private_payload"]:
            self.assertNotIn(forbidden,raw)

if __name__=="__main__":unittest.main()
