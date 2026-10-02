import json
import re
import unittest
from pathlib import Path

from acceptance.final_acceptance import _load_policy


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "acceptance" / "STEP23_LIVE_EVIDENCE_MANIFEST.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class Step23LiveManifestTests(unittest.TestCase):
    def test_manifest_is_explicitly_non_pass_and_matches_policy_scope(self):
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        policy = _load_policy()["step23"]

        self.assertEqual(doc["schema_version"], "1.0.0")
        self.assertEqual(doc["manifest_id"], "portfolio-step23-live-evidence-v1")
        self.assertEqual(doc["status"], "WAITING_FOR_LIVE_EVIDENCE")
        self.assertRegex(doc["exact_main_sha"], SHA40)
        self.assertEqual(
            doc["required_successful_scheduled_cycles_per_workflow"],
            policy["min_successful_scheduled_cycles_per_workflow"],
        )
        self.assertEqual(
            set(doc["required_handler_types"]),
            set(policy["required_handler_types"]),
        )
        self.assertEqual(
            set(doc["workflows"]),
            set(policy["required_workflows"]),
        )

        self.assertFalse(doc["receipt_inputs"]["hash_traceability_pass"])
        self.assertFalse(doc["receipt_inputs"]["dashboard"]["fresh"])
        self.assertIsNone(doc["receipt_inputs"]["pending_events_final"])

    def test_manifest_windows_are_four_real_oct2_utc_crons_per_workflow(self):
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for workflow, cfg in doc["workflows"].items():
            with self.subTest(workflow=workflow):
                crons = cfg["bounded_crons"]
                self.assertEqual(len(crons), 4)
                self.assertEqual(len(crons), len(set(crons)))
                for cron in crons:
                    fields = cron.split()
                    self.assertEqual(len(fields), 5)
                    self.assertEqual(fields[2:4], ["2", "10"])
                self.assertEqual(cfg["successful_run_ids"], [])
                self.assertEqual(cfg["cancelled_coalesced_run_ids"], [])
                self.assertEqual(cfg["failure_run_ids"], [])

    def test_manifest_completion_gate_preserves_fail_closed_contract(self):
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        gate = doc["completion_requirements"]
        self.assertTrue(gate["exact_main_must_remain_unchanged"])
        self.assertTrue(gate["all_runs_must_be_event_schedule"])
        self.assertTrue(gate["no_actual_failure_in_claimed_window"])
        self.assertTrue(gate["cancelled_requires_later_same_workflow_success"])
        self.assertEqual(gate["pending_events_final_must_equal"], 0)
        self.assertTrue(gate["substantive_hunter_work_required"])
        self.assertTrue(gate["heartbeat_only_hunter_work_rejected"])
        self.assertTrue(gate["dashboard_must_be_fresh_and_hash_traceable"])
        self.assertEqual(
            gate["final_validator"],
            "acceptance.final_acceptance.validate_step23",
        )


if __name__ == "__main__":
    unittest.main()
