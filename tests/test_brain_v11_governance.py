"""Keep V11 gated by original workflows, not new schedules or fake checks."""
import unittest
from pathlib import Path
from brain.v11 import verified_delivery as delivery
from brain.v11 import results_dashboard as results

ROOT = Path(__file__).resolve().parents[1]


class GovernanceTests(unittest.TestCase):
    def test_existing_runner_only_and_no_additional_timer_or_privilege(self):
        native = (ROOT / ".github/workflows/v9-guarded-native-automerge.yml").read_text()
        self.assertIn('workflows: ["foundation-ci"]', native)
        self.assertIn("python -m brain.v9.guarded_merge_runner", native)
        self.assertIn("python -m brain.v11.verified_delivery", native)
        self.assertIn("V11_EVENT_HEAD:", native)
        for forbidden in ("schedule:", "pull_request_target:", "workflow_dispatch:",
                          "permission-workflows:", "PORTFOLIO_RUNTIME_PRIVATE_KEY",
                          "PORTFOLIO_VERIFIER_PRIVATE_KEY", "gh pr merge"):
            self.assertNotIn(forbidden, native)
        self.assertEqual(native.count("      pull-requests: write"), 1)
        self.assertEqual(native.count("      contents: write"), 1)

    def test_original_core_artifact_not_new_recurring_workflow(self):
        core = (ROOT / ".github/workflows/brain-cycle.yml").read_text()
        # The original core is immutable under reviewed V8 authority.
        from brain.v8.authority import runtime_authority
        from brain.core import BrainError
        self.assertEqual(runtime_authority()["workflow_declares"]["repository_default"],
                         {"contents": "read"})
        self.assertNotIn("python -m brain.v11.results_dashboard", core)
        # Reports attach to existing, trusted-main Foundation follow-up.
        native = (ROOT / ".github/workflows/v9-guarded-native-automerge.yml").read_text()
        self.assertIn("python -m brain.v11.results_dashboard", native)
        self.assertIn("--expected-main \"${{ github.sha }}\"", native)
        self.assertIn("continue-on-error: true", native)
        self.assertIn("--json /tmp/brain-v11/results.json", native)
        self.assertIn("--html /tmp/brain-v11/results.html", native)
        self.assertIn("actions/upload-artifact@v4", native)
        self.assertEqual(delivery.REPO, results.REPO)
        self.assertEqual(delivery.gm.REQUIRED_CHECKS, results.REQUIRED)

    def test_retired_observer_never_reappeared(self):
        for name in ("reliability-day.yml", "portfolio-source-acceptance.yml",
                     "portfolio-source-acceptance-producer.yml"):
            self.assertFalse((ROOT / ".github/workflows" / name).exists())
        live = (ROOT / "verification/independent_verifier.py").read_text()
        self.assertNotIn("verify_predecessor_acceptance", live)
        self.assertNotIn("PORTFOLIO_12H_", live)


if __name__ == "__main__":
    unittest.main()
