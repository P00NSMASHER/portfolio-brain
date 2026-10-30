"""Review-only tests: observation must be explicitly opted in, never automatic by default."""
import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLAG = "vars.PORTFOLIO_12H_OBSERVATION_ENABLED == 'true'"
REPAIR = ".github/workflows/v8-scoped-repair.yml"
OBSERVER = ".github/workflows/reliability-day.yml"
PRODUCER = ".github/workflows/portfolio-source-acceptance-producer.yml"
VERIFIER = ".github/workflows/portfolio-source-acceptance.yml"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def blob(path):
    raw = (ROOT / path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()


class ObservationOptInTests(unittest.TestCase):
    def test_both_observer_and_receipt_producer_require_explicit_opt_in(self):
        for file in (OBSERVER, PRODUCER):
            with self.subTest(file=file):
                wf = read(file)
                self.assertEqual(wf.count(FLAG), 1)
                # A repository variable alone cannot restart a paused observation.
                # Deliberate re-arming needs a separately reviewed source change.
                self.assertRegex(wf, r"(?m)^\s+false &&$")
                self.assertIn("workflow_run:", wf)
                self.assertNotIn("workflow_dispatch:", wf)
                self.assertNotIn("schedule:", wf)
                self.assertNotIn("pull_request_target:", wf)

    def test_original_core_and_repair_cadences_remain_authorized_unchanged(self):
        clock = read(".github/workflows/brain-clock.yml")
        core = read(".github/workflows/brain-cycle.yml")
        repair = read(REPAIR)
        self.assertIn("workflow_run:", repair)
        self.assertIn('workflows: ["brain-cycle-v2"]', repair)
        self.assertNotIn("schedule:", repair)
        self.assertNotIn("schedule:", core)
        self.assertIn("schedule:", clock)
        self.assertNotIn(FLAG, clock)
        self.assertNotIn(FLAG, core)
        self.assertNotIn(FLAG, repair)

    def test_immutable_original_code_hashes_are_still_pinned(self):
        for workflow, implementation in (
            (REPAIR, "brain/v8/repair_core_origin.py"),
            (PRODUCER, "verification/source_acceptance_verifier.py"),
            (VERIFIER, "verification/source_acceptance_verifier.py"),
        ):
            with self.subTest(workflow=workflow, implementation=implementation):
                self.assertIn(blob(implementation), read(workflow))

    def test_no_automatic_receipt_mint_without_user_opt_in(self):
        wf = read(PRODUCER)
        before = wf.index(FLAG)
        before += len(FLAG)
        self.assertLess(before, wf.index("Mint short-lived one-repository"))
        self.assertNotIn(FLAG, read(REPAIR))
        self.assertNotIn(FLAG, read(VERIFIER))
        self.assertNotIn(FLAG, read(".github/workflows/v9-guarded-native-automerge.yml"))


if __name__ == "__main__":
    unittest.main()
