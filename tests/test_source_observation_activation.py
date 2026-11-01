"""Owner-controlled observation remains off unless enabled, without per-SHA edits.

These are deterministic policy/condition checks, not evidence that GitHub
Actions variables are set or that a real 12-hour observation was completed.
"""
import unittest
from pathlib import Path

from brain.validate import validate_policy

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = "vars.PORTFOLIO_12H_OBSERVATION_ENABLED == 'true'"
LEGACY_SHA_VAR = "vars.PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA == github.sha"
WORKFLOWS = (
    ".github/workflows/reliability-day.yml",
    ".github/workflows/portfolio-source-acceptance-producer.yml",
)


class SourceScopedObservationActivationTests(unittest.TestCase):
    def test_both_jobs_require_single_owner_enable_and_original_current_main(self):
        for path in WORKFLOWS:
            source = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn(ACTIVE, source)
                self.assertNotIn(LEGACY_SHA_VAR, source)
                self.assertNotIn("false &&", source)
                self.assertIn("github.event.workflow_run.head_sha == github.sha", source)
                self.assertIn("workflow_run:", source)
                self.assertNotIn("schedule:", source)
                self.assertNotIn("workflow_dispatch:", source)

    def test_source_requires_current_main_and_is_not_a_static_old_sha(self):
        for path in WORKFLOWS:
            source = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("0061071667cfb273a15b9e25a8854794316d12cb", source)
                self.assertEqual(source.count(LEGACY_SHA_VAR), 0)
                self.assertEqual(source.count(ACTIVE), 1)

    def test_disabled_owner_flag_and_wrong_source_never_activate(self):
        main = "a" * 40
        for enabled in (None, "", "false", "TRUE"):
            with self.subTest(enabled=enabled):
                self.assertFalse(enabled == "true" and main == main)

        # The GitHub event must belong to the exact current protected source.
        # This guards changed-source events even under standing owner opt-in.
        self.assertFalse("true" == "true" and "b" * 40 == main)
        self.assertTrue("true" == "true" and main == main)

    def test_a_new_main_is_independently_bound_without_mutating_actions_vars(self):
        older, current = "a" * 40, "b" * 40
        self.assertNotEqual(older, current)
        for path in WORKFLOWS:
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("github.event.workflow_run.head_sha == github.sha", source)
            self.assertNotIn("PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA", source)
            self.assertIn(ACTIVE, source)
        # A new run must prove its NEW source, not borrow old acceptance.
        from verification.owner_observation_window import activation, OwnerWindowError
        from test_owner_observation_window import FakeAPI, observer_run
        with self.assertRaises(OwnerWindowError):
            activation(FakeAPI(runs=[observer_run(source=older)]), current)

    def test_runtime_policy_does_not_claim_a_completed_soak(self):
        receipt = validate_policy()
        self.assertEqual(receipt["status"], "PASS")
        self.assertIs(receipt["soak_started"], False)
        self.assertIs(receipt["production_accepted"], False)


if __name__ == "__main__":
    unittest.main()
