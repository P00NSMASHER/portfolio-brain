import unittest
from pathlib import Path

from acceptance.step23_prearm_preflight import build_drain_correlation

ROOT=Path(__file__).resolve().parents[1]


class Step23PrearmPreflightTests(unittest.TestCase):
    def test_drain_correlation_uses_only_non_secret_run_identity(self):
        self.assertEqual(
            build_drain_correlation("initial",1,"37560158270"),
            "prearm-initial-drain-1-37560158270",
        )
        for unsafe in ("ghs_exampletoken","token-value","", "local"):
            with self.subTest(unsafe=unsafe), self.assertRaisesRegex(
                RuntimeError,"non-secret GitHub run id"
            ):
                build_drain_correlation("initial",1,unsafe)

    def test_secret_and_correlation_inputs_remain_structurally_separate(self):
        text=(ROOT/"acceptance/step23_prearm_preflight.py").read_text()
        self.assertIn("github_token=token",text)
        self.assertIn("correlation_seed=orchestrator",text)
        self.assertNotIn('drain-{round_number}-{token}',text)

    def test_new_push_preflight_supersedes_only_stale_active_preflight(self):
        text=(ROOT/".github/workflows/step23-prearm-validation.yml").read_text()
        self.assertIn(
            "github.event.workflow_run.event == 'push' && 'step23-prearm-validation'",
            text,
        )
        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'workflow_run' && github.event.workflow_run.event == 'push' }}",
            text,
        )

    def test_prearm_hardening_retriggers_schedule_delivery_recovery(self):
        text=(ROOT/".github/workflows/portfolio-schedule-delivery.yml").read_text()
        for path in (
            "acceptance/step23_prearm_preflight.py",
            "acceptance/step23_prearm_doctor.py",
            ".github/workflows/step23-prearm-validation.yml",
        ):
            self.assertIn(path,text)


if __name__=="__main__":
    unittest.main()
