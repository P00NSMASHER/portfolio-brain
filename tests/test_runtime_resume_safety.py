"""Recovery may not discard independent learning or unproved observations."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_state import _runtime_state_subsumes
from runtime.validate_runtime import validate_runtime, RuntimeValidationError
import test_runtime_fork_recovery as fixtures

ROOT = Path(__file__).resolve().parents[1]


class RuntimeResumeSafetyTests(unittest.TestCase):
    def fork(self):
        return fixtures.RuntimeForkRecoveryTests().fork()

    def test_recovery_preserves_different_learning_and_synthesis(self):
        for field in ('daily_learning_state', 'weekly_synthesis'):
            with self.subTest(field=field):
                other, _, winner, receipt = self.fork()
                other[field] = {'verified_outcomes': ['DO_NOT_DISCARD']}
                self.assertFalse(_runtime_state_subsumes(winner, receipt, other))

    def test_advancing_observation_requires_matching_receipt_projection(self):
        other, _, winner, receipt = self.fork()
        winner['repositories']['REPO-008']['observed_at'] = '2026-09-28T10:01:30Z'
        self.assertFalse(_runtime_state_subsumes(winner, receipt, other))

    def test_duplicate_observation_identifiers_do_not_establish_dominance(self):
        other, _, winner, receipt = self.fork()
        receipt['observations'].append(copy.deepcopy(receipt['observations'][0]))
        self.assertFalse(_runtime_state_subsumes(winner, receipt, other))

    def test_partial_receipt_cannot_establish_timestamp_dominance(self):
        other, _, winner, receipt = self.fork()
        receipt['observations'] = [x for x in receipt['observations'] if x['repository_id'] != 'REPO-008']
        self.assertFalse(_runtime_state_subsumes(winner, receipt, other))

    def test_identical_learning_is_retained_without_rewriting_the_winner(self):
        other, _, winner, receipt = self.fork()
        value = {'outcomes': ['preserved']}
        for field in ('daily_learning_state', 'weekly_synthesis'):
            other[field] = copy.deepcopy(value)
            winner[field] = copy.deepcopy(value)
        before = copy.deepcopy(winner)
        self.assertTrue(_runtime_state_subsumes(winner, receipt, other))
        self.assertEqual(winner, before)

    def test_all_runtime_modes_share_the_same_job_mutex_and_keep_paid_lock(self):
        text = (ROOT/'.github/workflows/runtime-worker.yml').read_text()
        job = text.split('  runtime:\n', 1)[1].split('    steps:', 1)[0]
        self.assertIn('group: portfolio-runtime-state-writer', job)
        self.assertIn('queue: max', job)
        self.assertIn('cancel-in-progress: false', job)
        group_line = next(x for x in job.splitlines() if 'group:' in x)
        self.assertNotIn('${{', group_line)
        self.assertIn("'portfolio-cost-governed-autonomy'", text.split('jobs:', 1)[0])

    def test_outer_event_caller_cannot_cancel_an_active_state_writer(self):
        text = (ROOT/'.github/workflows/runtime-event-observe.yml').read_text()
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('queue: max', text)
        self.assertNotIn('cancel-in-progress: ${{', text)

    def test_runtime_validator_rejects_removal_of_the_unconditional_job_mutex(self):
        original = Path.read_text
        def poisoned(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if str(path).endswith('runtime-worker.yml'):
                return value.replace('group: portfolio-runtime-state-writer', 'group: per-mode-writer')
            return value
        with patch.object(Path, 'read_text', poisoned):
            with self.assertRaises(RuntimeValidationError):
                validate_runtime()
