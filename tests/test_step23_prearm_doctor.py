import unittest
from pathlib import Path

from acceptance.step23_prearm_doctor import REQUIRED, SOAK_SECONDS, validate_static
from operations.validate_operating_mode import workflow_schedule_crons, workflow_top_level_triggers

ROOT=Path(__file__).resolve().parents[1]


class Step23PrearmDoctorTests(unittest.TestCase):
    def test_clean_prearm_contract_passes(self):
        result=validate_static(phase="prearm")
        self.assertEqual(result["static_contract"],"PASS")
        self.assertEqual(result["duration_seconds"],7200)
        self.assertEqual(result["required_successes_per_workflow"],3)
        self.assertEqual(set(result["required_workflows"]),set(REQUIRED))

    def test_prearm_has_only_steady_state_crons(self):
        for name,(filename,steady) in REQUIRED.items():
            with self.subTest(workflow=name):
                path=ROOT/".github/workflows"/filename
                self.assertEqual(workflow_schedule_crons(path),[steady])
                self.assertIn("workflow_dispatch",workflow_top_level_triggers(path))
                self.assertIn("prearm_id",path.read_text())

    def test_prearm_orchestrator_is_event_driven_not_scheduled(self):
        path=ROOT/".github/workflows/step23-prearm-validation.yml"
        self.assertIsNone(workflow_schedule_crons(path))
        triggers=workflow_top_level_triggers(path)
        self.assertEqual(triggers,{"workflow_run","workflow_dispatch"})
        text=path.read_text()
        self.assertIn("acceptance.step23_prearm_preflight",text)
        self.assertIn("acceptance.step23_prearm_doctor",text)
        self.assertIn("github.event.workflow_run.event == 'push'",text)

    def test_armed_validation_refuses_clean_prearm_state(self):
        with self.assertRaisesRegex(RuntimeError,"armed Step 23 control/window status mismatch"):
            validate_static(phase="armed")

    def test_two_hour_constant_is_explicit(self):
        self.assertEqual(SOAK_SECONDS,7200)


if __name__=="__main__":
    unittest.main()
