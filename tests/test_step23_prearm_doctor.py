import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from acceptance.step23_prearm_doctor import REQUIRED, static_checks, strict_arm_checks
from operations.validate_operating_mode import workflow_top_level_triggers

ROOT=Path(__file__).resolve().parents[1]


class Step23PrearmDoctorTests(unittest.TestCase):
    def test_static_contract_is_two_hours_two_successes_across_all_sources(self):
        result=static_checks()
        self.assertEqual(result["status"],"STATIC_PASS")
        self.assertEqual(result["duration_seconds"],7200)
        self.assertEqual(result["required_successes_per_workflow"],2)
        self.assertEqual(set(result["required_workflows"]),REQUIRED)

        policy=json.loads((ROOT/"acceptance/FINAL_ACCEPTANCE_POLICY.json").read_text())["step23"]
        window=json.loads((ROOT/"operations/STEP23_DELIVERY_WINDOW.json").read_text())
        control=json.loads((ROOT/"operations/STEP23_CONTROL.json").read_text())
        self.assertEqual(policy["max_soak_duration_seconds"],window["max_soak_duration_seconds"])
        self.assertEqual(policy["max_soak_duration_seconds"],control["max_soak_duration_seconds"])
        self.assertEqual(policy["min_successful_scheduled_cycles_per_workflow"],window["required_successes_per_workflow"])
        self.assertEqual(policy["min_successful_scheduled_cycles_per_workflow"],control["required_successes_per_workflow"])

    def test_strict_doctor_refuses_to_arm_while_control_is_canary_required(self):
        with self.assertRaisesRegex(RuntimeError,"STEP23_DOCTOR_NOT_ARMABLE"):
            strict_arm_checks("a"*40,now=datetime(2026,10,7,tzinfo=timezone.utc))

    def test_preflight_workflow_is_event_driven_not_scheduled(self):
        path=ROOT/".github/workflows/step23-prearm-preflight.yml"
        self.assertEqual(workflow_top_level_triggers(path),{"push","workflow_dispatch"})
        text=path.read_text()
        self.assertIn("actions: write",text)
        self.assertIn("--static-only",text)
        self.assertIn("acceptance.step23_preflight",text)


if __name__=="__main__":
    unittest.main()
