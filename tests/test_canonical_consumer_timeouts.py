"""Canonical catch-up must fit inside every required consumer's wall-clock budget."""
from legacy.workflow_archive import legacy_workflow_path
import ast
import copy
import inspect
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from runtime.validate_runtime import RuntimeValidationError, validate_runtime, validate_workflow_budgets
from state_journal.contracts import JournalError
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
                text = (legacy_workflow_path(ROOT / f".github/workflows/{name}.yml")).read_text()
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

    def test_watchdog_can_finish_canonical_restore_and_recovery_work(self):
        wait = inspect.signature(_wait_for_reduction).parameters["timeout_seconds"].default
        text = (legacy_workflow_path(ROOT / ".github/workflows/portfolio-cost-watchdog.yml")).read_text()
        self.assertEqual(timeout_minutes(text), 8)
        self.assertGreaterEqual(8 * 60, wait + 2 * 60 + 60)
        self.assertIn("python -m state_journal.production_reader --domain cost", text)

    def test_reducer_does_not_consume_canonical_reader_and_keeps_independent_bound(self):
        text = (legacy_workflow_path(ROOT / ".github/workflows/portfolio-state-reducer.yml")).read_text()
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

class RuntimeConsumerTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.worker = (legacy_workflow_path(ROOT/'.github/workflows/runtime-worker.yml')).read_text()
        self.budgets = json.loads((ROOT/'runtime/RUNTIME_POLICY.json').read_text())['budgets']
        self.workload = workload_gate.load_policy()
        self.cost = json.loads((ROOT/'cost_governor/COST_GOVERNOR_POLICY.json').read_text())

    def validate(self, **overrides):
        values = dict(worker=self.worker, budgets=self.budgets, workload=self.workload, cost=self.cost)
        values.update(overrides)
        return validate_workflow_budgets(**values)

    def test_real_reader_can_exhaust_its_wait_without_exhausting_nonpaid_job(self):
        # Exercise the actual default wait and fail-closed deadline with a fake
        # clock; a missing reducer must never become an accepted stale restore.
        elapsed = 0
        def clock():
            return elapsed
        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds
        policy = json.loads((ROOT/'state_journal/POLICY.json').read_text())
        pending = [{'id': 12, 'created_at': '2026-10-06T02:58:23Z'}]
        with patch('state_journal.production_reader.GitHubReader') as reader:
            reader.return_value.get.return_value = {'workflow_runs': []}
            with self.assertRaisesRegex(JournalError, 'STALE_CANONICAL_STATE_REDUCTION_TIMEOUT'):
                _wait_for_reduction('test-token', policy, pending, current_run='fixture', clock=clock, sleep=sleep)
        self.assertEqual(elapsed, 300)
        core_and_restores = self.budgets['max_runtime_seconds'] + self.budgets['max_state_restore_seconds']
        forwarding_and_health = 6*20 + 2*(1+2) + 2*2*20
        full_work = elapsed + core_and_restores + forwarding_and_health + 60
        self.assertGreater(full_work, 8*60)
        self.assertGreater(full_work, 12*60)
        limits = self.validate()
        self.assertLessEqual(full_work, limits['nonpaid_runtime_timeout_minutes']*60)
        self.assertEqual(limits['paid_runtime_timeout_minutes'], 5)

    def test_composed_read_allowances_match_current_implementations(self):
        # Guard the explicit read/retry bounds used in the composed budget. The
        # functions retain their existing behavior; changing a bound requires a
        # fresh job-budget calculation instead of silently outgrowing the job.
        forwarding = ast.parse((ROOT/'runtime/forwarding_artifact_state.py').read_text())
        calls = [node for node in ast.walk(forwarding) if isinstance(node, ast.Call)]
        self.assertEqual([node.comparators[0].value for node in ast.walk(forwarding)
                          if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                          and node.left.id == 'used' and isinstance(node.ops[0], ast.GtE)], [6])
        self.assertEqual([node.args[0].value for node in calls if isinstance(node.func, ast.Name)
                          and node.func.id == 'range'], [3])
        self.assertEqual([kw.value.value for node in calls if isinstance(node.func, ast.Name)
                          and node.func.id == 'open_url' for kw in node.keywords if kw.arg == 'timeout'], [20])
        self.assertEqual([ast.unparse(node.args[0]) for node in calls if isinstance(node.func, ast.Attribute)
                          and node.func.attr == 'sleep'], ['attempt + 1'])
        health = ast.parse((ROOT/'adapters/abvm_health.py').read_text())
        functions = {node.name: node for node in health.body if isinstance(node, ast.FunctionDef)}
        for function, callee in (('fetch_live_evidence', '_get_json'), ('_get_json', 'request')):
            calls = [node for node in ast.walk(functions[function]) if isinstance(node, ast.Call)]
            self.assertEqual(sum(isinstance(node.func, ast.Name) and node.func.id == callee for node in calls), 2)
        self.assertEqual([kw.value.value for node in ast.walk(health) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute) and node.func.attr == 'urlopen'
                          for kw in node.keywords if kw.arg == 'timeout'], [20])

    def test_mutations_to_timeout_estimates_and_mode_boundaries_are_rejected(self):
        mutations = (
            ('&& 15 || 5', '&& 5 || 5'),
            ('&& 15 || 5', '&& 0 || 5'),
            ('&& 15 || 5', '&& 16 || 5'),
            ('&& 15 || 5', '&& 15 || 15'),
            ("(inputs.mode == 'observe' || inputs.mode == 'sync') && 15", "(inputs.mode == 'observe' || inputs.mode == 'daily') && 15"),
            ('--estimated-minutes 15', '--estimated-minutes 5'),
            ('--estimated-minutes 5', '--estimated-minutes 15'),
            ("if: ${{ inputs.mode == 'daily' || inputs.mode == 'weekly' }}", "if: ${{ inputs.mode == 'observe' || inputs.mode == 'sync' }}"),
            ("if: ${{ inputs.mode == 'observe' || inputs.mode == 'sync' }}", "if: ${{ inputs.mode == 'daily' || inputs.mode == 'weekly' }}"),
        )
        for before, after in mutations:
            with self.subTest(before=before, after=after), self.assertRaises(RuntimeValidationError):
                self.validate(worker=self.worker.replace(before, after))

    def test_each_policy_cap_and_growing_phase_budget_is_checked(self):
        for mode in ('sync', 'observe'):
            for cap in (5, 16):
                policy = copy.deepcopy(self.workload)
                policy['services'][f'runtime-worker::runtime-{mode}']['max_minutes_per_job'] = cap
                with self.subTest(mode=mode, cap=cap), self.assertRaises(RuntimeValidationError):
                    self.validate(workload=policy)
        for mode in ('daily', 'weekly'):
            policy = copy.deepcopy(self.cost)
            policy['workflow_job_ceilings'][f'runtime-worker::runtime-{mode}']['max_minutes_per_job'] = 15
            with self.subTest(mode=mode), self.assertRaises(RuntimeValidationError):
                self.validate(cost=policy)
        for phase in ('max_runtime_seconds', 'max_state_restore_seconds'):
            budgets = dict(self.budgets)
            budgets[phase] += 60
            with self.subTest(phase=phase), self.assertRaises(RuntimeValidationError):
                self.validate(budgets=budgets)
        def slower_reader(*, timeout_seconds=360):
            pass
        with patch('runtime.validate_runtime._wait_for_reduction', slower_reader), self.assertRaises(RuntimeValidationError):
            self.validate()

    def test_real_admission_blocks_overrun_and_paid_modes_remain_cost_governed(self):
        for mode in ('sync', 'observe'):
            for minutes, allowed in ((15, True), (16, False), (0, False)):
                decision = workload_gate.evaluate(workflow_id='runtime-worker', job_id=f'runtime-{mode}', estimated_minutes=minutes)
                self.assertEqual(decision['allowed'], allowed)
        for mode in ('daily', 'weekly', 'unsupported'):
            decision = workload_gate.evaluate(workflow_id='runtime-worker', job_id=f'runtime-{mode}', estimated_minutes=5)
            self.assertFalse(decision['allowed'])
        paid_guard = "(inputs.mode == 'daily' || inputs.mode == 'weekly')"
        for title in ('Run governed model-assisted analysis', 'Commit conservative paid runtime compute usage'):
            step = self.worker.split('- name: '+title, 1)[1].split('      - ', 1)[0]
            self.assertIn(paid_guard, step)
        self.assertIn('--authority OBSERVE', self.worker)
        self.assertIn('group: portfolio-state-writer-v1', self.worker)
        self.assertIn("'portfolio-cost-governed-autonomy'", self.worker)

    def test_foundation_runtime_validator_enforces_the_budget_contract(self):
        original = Path.read_text
        def undersized(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return value.replace('&& 15 || 5', '&& 5 || 5') if path.name == 'runtime-worker.yml' else value
        with patch.object(Path, 'read_text', undersized), self.assertRaises(RuntimeValidationError):
            validate_runtime()


if __name__ == "__main__":
    unittest.main()
