import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/portfolio-liveness-watchdog.yml"


class LivenessWatchdogWorkflowTests(unittest.TestCase):
    def test_liveness_engine_is_actually_scheduled(self):
        text = WORKFLOW.read_text()
        self.assertIn("name: portfolio-liveness-watchdog", text)
        self.assertIn('cron: "7,37 * * * *"', text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("group: portfolio-liveness-watchdog", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_watchdog_has_only_the_write_authority_needed_to_redispatch_actions(self):
        text = WORKFLOW.read_text()
        permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
        self.assertIn("contents: read", permissions)
        self.assertIn("actions: write", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertNotIn("pull-requests: write", permissions)
        self.assertNotIn("issues: write", permissions)

    def test_watchdog_uses_existing_bounded_liveness_policy_and_canonical_cost_context(self):
        text = WORKFLOW.read_text()
        self.assertIn("python -m state_journal.production_reader", text)
        self.assertIn("--domain cost", text)
        self.assertIn("--metadata-output cost_governor/live/cost_state.meta.json", text)
        self.assertIn("python -m operations.workflow_liveness", text)
        self.assertIn("--state cost_governor/live/cost_state.json", text)
        self.assertIn("--state-metadata cost_governor/live/cost_state.meta.json", text)
        self.assertIn("--output operations/out/workflow_liveness_report.json", text)

    def test_watchdog_keeps_an_evidence_trail(self):
        text = WORKFLOW.read_text()
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("portfolio-liveness-watchdog-report-", text)
        self.assertIn("operations/out/workflow_liveness_report.json", text)


if __name__ == "__main__":
    unittest.main()
