"""Canonical catch-up must fit inside consumer wall-clock admission and timeout."""
import inspect
import re
import unittest
from pathlib import Path
from state_journal.production_reader import _wait_for_reduction
from workload_control import workload_gate

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {'agent-heartbeat-sweep': 'heartbeat', 'portfolio-notification-cycle': 'notify'}

def validate_budget(text, maximum, wait_seconds):
    timeout = re.findall(r'^    timeout-minutes: ([0-9]+)$', text, re.M)
    estimate = re.findall(r'--estimated-minutes ([0-9]+)', text)
    if len(timeout) != 1 or len(estimate) != 1:
        raise ValueError('unambiguous finite wall-clock budget required')
    minimum = (wait_seconds + 59) // 60 + 2 + 1
    if not (minimum <= int(timeout[0]) == int(estimate[0]) == maximum == 8):
        raise ValueError('canonical catch-up, work and finalization exceed budget')

class ConsumerTimeoutTests(unittest.TestCase):
    def test_deployed_consumers_cover_the_actual_reader_wait(self):
        wait = inspect.signature(_wait_for_reduction).parameters['timeout_seconds'].default
        policy = workload_gate.load_policy()
        for name, job in SERVICES.items():
            with self.subTest(name=name):
                text = (ROOT/f'.github/workflows/{name}.yml').read_text()
                validate_budget(text, policy['services'][f'{name}::{job}']['max_minutes_per_job'], wait)
                self.assertIn('group: portfolio-state-writer-v1', text)
                self.assertIn('cancel-in-progress: false', text)
                self.assertNotIn('cost_governor.workflow_gate', text)
                self.assertIn('python -m state_journal.production_reader', text)

    def test_mutations_to_each_independent_budget_are_rejected(self):
        valid = '    timeout-minutes: 8\n--estimated-minutes 8\n'
        for text, maximum, wait in (
            (valid.replace('timeout-minutes: 8', 'timeout-minutes: 2'), 8, 300),
            (valid.replace('estimated-minutes 8', 'estimated-minutes 2'), 8, 300),
            (valid, 2, 300), (valid, 9, 300), (valid, 8, 360),
            (valid.replace('timeout-minutes: 8', 'timeout-minutes: 0'), 8, 300),
        ):
            with self.subTest(text=text,maximum=maximum,wait=wait), self.assertRaises(ValueError):
                validate_budget(text, maximum, wait)

    def test_known_116_second_catchup_does_not_exhaust_job_budget(self):
        old_total = 2*60
        observed_wait = 116
        work_and_finalize = 2*60 + 60
        self.assertGreater(observed_wait + work_and_finalize, old_total)
        self.assertLessEqual(300 + work_and_finalize, 8*60)

    def test_admission_is_finite_and_still_blocks_overrun(self):
        for name, job in SERVICES.items():
            accepted = workload_gate.evaluate(workflow_id=name,job_id=job,estimated_minutes=8)
            blocked = workload_gate.evaluate(workflow_id=name,job_id=job,estimated_minutes=9)
            self.assertTrue(accepted['allowed'])
            self.assertFalse(blocked['allowed'])
            self.assertEqual(blocked['status'], 'BLOCKED_WORKLOAD')

    def test_other_service_and_paid_runtime_limits_are_unchanged(self):
        services = workload_gate.load_policy()['services']
        for scope in ('runtime-worker::runtime-sync', 'runtime-worker::runtime-observe',
                      'portfolio-autonomous-scheduler::schedule', 'hunter-autonomous-cycle::hunt'):
            self.assertEqual(services[scope]['max_minutes_per_job'], 5)
        runtime = (ROOT/'.github/workflows/runtime-worker.yml').read_text()
        self.assertIn('timeout-minutes: 5', runtime)
        self.assertIn('cost_governor.workflow_gate preflight', runtime)

if __name__ == '__main__': unittest.main()
