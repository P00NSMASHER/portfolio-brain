"""Canonical catch-up must fit inside every required consumer's wall-clock budget."""
import inspect
import re
import unittest
from pathlib import Path
from state_journal.production_reader import _wait_for_reduction
from workload_control import workload_gate

ROOT = Path(__file__).resolve().parents[1]

SERVICES = {
    "agent-heartbeat-sweep": ("heartbeat", 8, 2),
    "portfolio-notification-cycle": ("notify", 8, 2),
    "portfolio-autonomous-scheduler": ("schedule", 12, 6),
    "hunter-autonomous-cycle": ("hunt", 10, 4),
    "command-center-pages": ("publish", 10, 4),
}

def timeout_minutes(text):
    values = re.findall(r"^    timeout-minutes: ([0-9]+)$", text, re.M)
    if len(values) != 1:
        raise ValueError("unambiguous finite job timeout required")
    return int(values[0])

def workload_estimate(text):
    marker = "workload_control.workload_gate preflight"
    if text.count(marker) != 1:
        raise ValueError("exactly one workload preflight required")
    tail = text.split(marker, 1)[1][:500]
    match = re.search(r"--estimated-minutes ([0-9]+)", tail)
    if not match:
        raise ValueError("workload estimate missing")
    return int(match.group(1))

def assert_budget(text, policy_maximum, expected, wait_seconds, work_minutes):
    minimum = (wait_seconds + 59) // 60 + work_minutes + 1
    if not (minimum <= timeout_minutes(text) == workload_estimate(text) == policy_maximum == expected):
        raise ValueError("canonical catch-up, useful work and finalization exceed budget")

class ConsumerTimeoutTests(unittest.TestCase):
    def test_all_required_workload_consumers_cover_reader_wait_and_use_same_admission_budget(self):
        wait = inspect.signature(_wait_for_reduction).parameters["timeout_seconds"].default
        policy = workload_gate.load_policy()
        for name, (job, expected, work_minutes) in SERVICES.items():
            with self.subTest(name=name):
                text = (ROOT / f".github/workflows/{name}.yml").read_text()
                assert_budget(
                    text,
                    policy["services"][f"{name}::{job}"]["max_minutes_per_job"],
                    expected,
                    wait,
                    work_minutes,
                )
                self.assertIn("python -m state_journal.production_reader", text)
                if name != "command-center-pages":
                    self.assertIn("group: portfolio-state-writer-v1", text)
                self.assertIn("cancel-in-progress: false", text)

    def test_runtime_sync_and_observe_cover_reader_wait_without_widening_paid_compute_reservation(self):
        wait = inspect.signature(_wait_for_reduction).parameters["timeout_seconds"].default
        policy = workload_gate.load_policy()
        text = (ROOT / ".github/workflows/runtime-worker.yml").read_text()
        self.assertEqual(timeout_minutes(text), 10)
        self.assertEqual(workload_estimate(text), 10)
        for mode in ("observe", "sync"):
            self.assertEqual(policy["services"][f"runtime-worker::runtime-{mode}"]["max_minutes_per_job"], 10)
        self.assertGreaterEqual(10 * 60, wait + 4 * 60 + 60)
        paid = text.split("cost_governor.workflow_gate preflight", 1)[1][:700]
        self.assertIn("--estimated-minutes 5", paid)
        self.assertIn("group: portfolio-state-writer-v1", text)

    def test_watchdog_can_finish_canonical_restore_and_recovery_work(self):
        wait = inspect.signature(_wait_for_reduction).parameters["timeout_seconds"].default
        text = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertEqual(timeout_minutes(text), 8)
        self.assertGreaterEqual(8 * 60, wait + 2 * 60 + 60)
        self.assertIn("python -m state_journal.production_reader --domain cost", text)

    def test_reducer_does_not_consume_canonical_reader_and_keeps_independent_bound(self):
        text = (ROOT / ".github/workflows/portfolio-state-reducer.yml").read_text()
        self.assertNotIn("state_journal.production_reader", text)
        self.assertEqual(timeout_minutes(text), 5)
        self.assertIn("group: portfolio-state-reducer", text)

    def test_underbudget_mutations_fail(self):
        wait = 300
        valid = "    timeout-minutes: 10\nworkload_control.workload_gate preflight\n--estimated-minutes 10\n"
        for text, maximum, expected, work in (
            (valid.replace("timeout-minutes: 10", "timeout-minutes: 5"), 10, 10, 4),
            (valid.replace("estimated-minutes 10", "estimated-minutes 5"), 10, 10, 4),
            (valid, 5, 10, 4),
            (valid, 10, 12, 6),
            (valid, 10, 10, 5),
        ):
            with self.subTest(text=text, maximum=maximum, expected=expected, work=work), self.assertRaises(ValueError):
                assert_budget(text, maximum, expected, wait, work)

if __name__ == "__main__":
    unittest.main()
