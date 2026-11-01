"""Retired timed observations must not reappear in the active release pipeline."""
from pathlib import Path
import unittest
from brain.validate import validate_policy
ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    ".github/workflows/reliability-day.yml",
    ".github/workflows/portfolio-source-acceptance-producer.yml",
    ".github/workflows/portfolio-source-acceptance.yml",
)

class NoTimedObservationTests(unittest.TestCase):
    def test_all_timed_jobs_removed_and_owner_variables_unused(self):
        for path in RETIRED:
            with self.subTest(path=path):
                self.assertFalse((ROOT/path).exists())
        workflow_dir = ROOT / ".github/workflows"
        for path in workflow_dir.glob("*.yml"):
            body=path.read_text(encoding="utf-8")
            with self.subTest(workflow=path.name):
                self.assertNotIn("PORTFOLIO_12H_OBSERVATION_ENABLED", body)
                self.assertNotIn("PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA", body)
                self.assertNotIn("python -m verification.source_acceptance_producer", body)
                self.assertNotIn("python -m verification.reliability_day", body)

    def test_original_core_schedule_and_independent_release_gates_remain(self):
        core=(ROOT/".github/workflows/brain-cycle.yml").read_text()
        clock=(ROOT/".github/workflows/brain-clock.yml").read_text()
        verifier=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text()
        self.assertIn('name: brain-cycle-v2', core)
        self.assertIn("schedule:", clock)
        self.assertIn("portfolio-phase1-gate", (ROOT/"verification/independent_verifier.py").read_text())
        self.assertIn('app-id: "5121826"', verifier)
        self.assertNotIn("pull_request_target:", verifier)

    def test_contract_passes_without_timed_wait(self):
        result=validate_policy()
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["production_accepted"])

if __name__=="__main__":
    unittest.main()
