"""Source- and owner-bound real local negative/positive repair trials."""
import copy
import unittest
from unittest.mock import patch
from brain.core import BrainError
from brain.v8.owner_trials import trial_owner_repair
from tests.test_brain_repair_patch_executor import FIXTURE, request

BRAINSHA = 'f' * 40
SOURCE = 'a' * 40
NOW = '2026-10-16T07:00:00Z'
RETALLY = 'P00NSMASHER/github-value-hunt-ledger'
PERMIT = 'P00NSMASHER/permitplate-nyc'


def project(pid, repo, state='ADVERSE_CHECKS_OBSERVED', source=SOURCE):
    return dict(id=pid, repository=repo, repository_revision=source,
                source_check_state=state)


def trial(rows, *, project_id='permitplate', cycle=0, req=None, original=None):
    report = dict(source_sha=BRAINSHA, projects=rows)
    return trial_owner_repair(report, req or request(FIXTURE,
        repository=PERMIT, path='.github/workflows/permitplate-tests.yml'),
        FIXTURE.encode() if original is None else original, source_sha=BRAINSHA,
        cycle=cycle, now=NOW, project_id=project_id)


class OwnerRepairTrials(unittest.TestCase):
    def test_isolated_original_regression_fails_before_and_passes_after(self):
        rows = [project('permitplate', PERMIT)]
        before = copy.deepcopy(rows)
        one = trial(rows)
        two = trial(rows)
        self.assertEqual(one, two)
        self.assertEqual(one['status'], 'SOURCE_BOUND_OWNER_TRIAL_RED_GREEN')
        self.assertNotEqual(one['original_returncode'], 0)
        self.assertEqual(one['corrected_returncode'], 0)
        self.assertEqual(one['owner'], 'portfolio-health-owner')
        self.assertFalse(one['target_code_executed'])
        self.assertFalse(one['target_repository_modified'])
        self.assertFalse(one['independent_gate_passed'])
        self.assertFalse(one['production_accepted'])
        self.assertFalse(one['merge_or_deployment_authority'])
        self.assertEqual(one['provider_calls'], 0)
        self.assertEqual(rows, before)

    def test_source_drift_denied_before_execution(self):
        rows = [project('permitplate', PERMIT, source='b' * 40)]
        with patch('brain.v8.owner_trials.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError,
                                        'V8_REPAIR_TRIAL_SOURCE_NOT_SELECTED'):
                trial(rows)
            runner.assert_not_called()

    def test_not_adverse_does_not_run_incident_recipe(self):
        rows = [project('permitplate', PERMIT,
             state='NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL')]
        with patch('brain.v8.owner_trials.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError,
                                        'V8_REPAIR_TRIAL_NOT_ADVERSE_OR_AUTHORIZED'):
                trial(rows)
            runner.assert_not_called()

    def test_shared_repo_uses_only_exact_selected_owner(self):
        rows = [project('retally', RETALLY),
                project('research-labs', RETALLY)]
        req = request(FIXTURE, repository=RETALLY,
                      path='.github/workflows/freight-ci.yml')
        with patch('brain.v8.owner_trials.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'SOURCE_NOT_SELECTED'):
                trial(rows, project_id='retally', cycle=0, req=req)
            runner.assert_not_called()
        selected = trial(rows, project_id='retally', cycle=1, req=req)
        self.assertEqual(selected['project_id'], 'retally')
        self.assertEqual(selected['repository'], RETALLY)
        self.assertFalse(selected['target_repository_modified'])

    def test_unassigned_factory_is_not_granted_a_repair_slot(self):
        rows = [project('product-factory', 'P00NSMASHER/x402-product-factory')]
        with patch('brain.v8.owner_trials.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'SOURCE_NOT_SELECTED'):
                trial(rows, project_id='product-factory', req=request())
            runner.assert_not_called()

    def test_tampered_content_or_request_cannot_satisfy_red_green(self):
        rows = [project('permitplate', PERMIT)]
        with self.assertRaisesRegex(BrainError, 'AUTOFIX_EXACT_SOURCE_HASH_MISMATCH'):
            trial(rows, original=FIXTURE.replace('npm test', 'npm run test').encode())
        with self.assertRaisesRegex(BrainError, 'AUTOFIX_REQUEST_SCOPE_REFUSED'):
            trial(rows, req=request(FIXTURE, repository=PERMIT,
                path='.github/workflows/permitplate-tests.yml',
                independent_gate_required=False))


if __name__ == '__main__':
    unittest.main()
