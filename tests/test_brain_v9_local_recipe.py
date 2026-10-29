"""Real fixed-regression execution plus durable crash/restart negative controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain.core import BrainError, canonical, digest
from brain.v8.journal import KernelJournal
from brain.v8.private_state import PrivateFiles
from brain.v9.local_recipe import execute_recipe
from brain.v9.missions import compile_mission
from tests.test_brain_repair_patch_executor import FIXTURE, request
from tests.test_brain_v8_contracts import work, NOW, LATER
from tests.test_brain_v8_journal import operation


class LocalRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.request = request()
        self.row = work('fixture', repository=self.request['repository'],
                        fingerprint=digest(self.request),
                        resource=digest(dict(repository=self.request['repository'].casefold())))
        self.heads = {self.row['repository']: self.row['source_sha']}
        self.mission = compile_mission([self.row], source_heads=self.heads)
        with KernelJournal(self.path, create=True) as journal:
            journal.append(operation(self.row))

    def run_recipe(self, journal=None, **changes):
        args = dict(source_heads=self.heads, now=LATER)
        args.update(changes)
        if journal is not None:
            return execute_recipe(self.mission, journal, self.request, FIXTURE.encode(), **args)
        with KernelJournal(self.path) as opened:
            return execute_recipe(self.mission, opened, self.request, FIXTURE.encode(), **args)

    def test_real_regression_persists_artifact_then_restarts_without_execution(self):
        first = self.run_recipe()
        self.assertFalse(first['reused_result'])
        self.assertEqual(first['status'], 'LOCAL_RECIPE_TESTED')
        body = json.loads(Path(first['artifact_path']).read_text())['body']
        self.assertEqual(body['result']['original_returncode'], 1)
        self.assertEqual(body['result']['corrected_returncode'], 0)
        self.assertIn('persist-credentials: false', body['artifact']['changed_content'])
        with KernelJournal(self.path, readonly=True) as journal:
            records = journal.replay()
        states = [r['operation']['work']['state'] for r in records if r['kind'] == 'WORK']
        self.assertEqual(states, ['OBSERVED'] * 3 + ['DIAGNOSED', 'REPRODUCED', 'PATCHED', 'TESTED'])
        before = self.path.read_bytes()
        with patch('brain.v9.local_recipe.exercise_repair', side_effect=AssertionError('rerun')):
            second = self.run_recipe()
        self.assertTrue(second['reused_result'])
        self.assertEqual(second['artifact_sha256'], first['artifact_sha256'])
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(second['independently_accepted'])
        self.assertFalse(second['release_authority'])
        self.assertEqual(second['provider_calls'], 0)

    def test_exception_after_intent_remains_blocked_even_after_lease_expiry(self):
        with patch('brain.v9.local_recipe.exercise_repair', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                self.run_recipe()
        with patch('brain.v9.local_recipe.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'UNCERTAIN_RESULT'):
                self.run_recipe(now='2026-10-15T21:00:00Z')
            runner.assert_not_called()
        with KernelJournal(self.path, readonly=True) as journal:
            self.assertEqual(journal.replay()[-1]['operation']['outcome'], 'EXTERNAL_INTENT')

    def test_saved_result_recovers_after_crash_before_confirmation(self):
        with KernelJournal(self.path) as journal:
            append = journal.append
            def crash(op):
                if op['outcome'] == 'EXTERNAL_CONFIRMED':
                    raise RuntimeError('crash before confirmation')
                return append(op)
            with patch.object(journal, 'append', side_effect=crash):
                with self.assertRaises(RuntimeError):
                    self.run_recipe(journal)
        with patch('brain.v9.local_recipe.exercise_repair', side_effect=AssertionError('rerun')):
            result = self.run_recipe()
        self.assertTrue(result['reused_result'])

    def test_crash_after_each_committed_stage_resumes_without_rerun(self):
        for stage in ('DIAGNOSED', 'REPRODUCED', 'PATCHED', 'TESTED'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'kernel.sqlite'
                with KernelJournal(path, create=True) as journal:
                    journal.append(operation(self.row))
                    append = journal.append
                    def crash(op):
                        receipt = append(op)
                        if op['work']['state'] == stage:
                            raise RuntimeError('after commit')
                        return receipt
                    with patch.object(journal, 'append', side_effect=crash):
                        with self.assertRaises(RuntimeError):
                            self.run_recipe(journal)
                with KernelJournal(path) as journal, patch(
                        'brain.v9.local_recipe.exercise_repair', side_effect=AssertionError('rerun')):
                    self.assertTrue(self.run_recipe(journal)['reused_result'])

    def test_artifact_write_failure_does_not_rerun(self):
        with patch.object(PrivateFiles, 'write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_recipe()
        with patch('brain.v9.local_recipe.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'UNCERTAIN_RESULT'):
                self.run_recipe()
            runner.assert_not_called()

    def test_corrupted_result_and_rehashed_substitution_fail_closed(self):
        result = self.run_recipe()
        path = Path(result['artifact_path'])
        raw = json.loads(path.read_text())
        changed = copy.deepcopy(raw)
        changed['body']['artifact']['changed_content'] += '\nmalicious\n'
        for rehash in (False, True):
            if rehash:
                changed['sha256'] = digest(changed['body'])
            path.write_text(canonical(changed))
            with patch('brain.v9.local_recipe.exercise_repair') as runner:
                with self.assertRaises(BrainError):
                    self.run_recipe()
                runner.assert_not_called()

    def test_source_drift_and_request_changes_do_not_write_or_run(self):
        before = self.path.read_bytes()
        with patch('brain.v9.local_recipe.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'SOURCE_DRIFT'):
                self.run_recipe(source_heads={self.row['repository']: 'b' * 40})
            self.request = request(path='.github/workflows/other-ci.yml')
            with self.assertRaisesRegex(BrainError, 'WORK_BINDING'):
                self.run_recipe()
            self.request = request(repository='outsider/unauthorized')
            with self.assertRaises(BrainError):
                self.run_recipe()
            runner.assert_not_called()
        self.assertEqual(before, self.path.read_bytes())

    def test_foreign_claim_and_competing_directory_lock_block_execution(self):
        with PrivateFiles(self.path.parent).lock():
            with self.assertRaisesRegex(BrainError, 'WRITER_BUSY'):
                self.run_recipe()
        with KernelJournal(self.path) as journal:
            journal.claim(resource=self.row['resource'], owner=self.row['owner'],
                          operation_id='f' * 64, source_sha=self.row['source_sha'],
                          now=NOW, expires_at=LATER)
        with patch('brain.v9.local_recipe.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'NOT_SELECTED'):
                self.run_recipe()
            runner.assert_not_called()

    def test_intent_durable_before_runner_and_lock_held_during_execution(self):
        from brain.v8.engineering import exercise_repair
        def inspected(request_doc, source):
            with KernelJournal(self.path, readonly=True) as reader:
                self.assertEqual(reader.replay()[-1]['operation']['outcome'], 'EXTERNAL_INTENT')
            with self.assertRaisesRegex(BrainError, 'WRITER_BUSY'):
                with PrivateFiles(self.path.parent).lock():
                    pass
            return exercise_repair(request_doc, source)
        with patch('brain.v9.local_recipe.exercise_repair', side_effect=inspected):
            self.run_recipe()

    def test_readonly_journal_and_noncanonical_resource_refused(self):
        with KernelJournal(self.path, readonly=True) as journal:
            with self.assertRaisesRegex(BrainError, 'WRITABLE_JOURNAL'):
                self.run_recipe(journal)
        row = dict(self.row, resource='c' * 64)
        self.mission = compile_mission([row], source_heads=self.heads)
        with self.assertRaises(BrainError):
            self.run_recipe()

    def test_bad_regression_result_keeps_intent_unresolved(self):
        with patch('brain.v9.local_recipe.exercise_repair', return_value={'status': 'success'}):
            with self.assertRaisesRegex(BrainError, 'REGRESSION_FAILED'):
                self.run_recipe()
        with self.assertRaisesRegex(BrainError, 'UNCERTAIN_RESULT'):
            self.run_recipe()

    def test_crash_after_claim_before_intent_requires_external_reconciliation(self):
        with KernelJournal(self.path) as journal:
            with patch.object(journal, 'append', side_effect=RuntimeError('before intent')):
                with self.assertRaises(RuntimeError):
                    self.run_recipe(journal)
        with patch('brain.v9.local_recipe.exercise_repair') as runner:
            with self.assertRaisesRegex(BrainError, 'NOT_SELECTED'):
                self.run_recipe(now='2026-10-15T21:00:00Z')
            runner.assert_not_called()

    def test_cross_repository_recipe_reuse_and_uncertain_dependency_recovery(self):
        child_request = request(repository='P00NSMASHER/github-value-hunt-ledger')
        child = work('second-repository', repository=child_request['repository'],
                     fingerprint=digest(child_request), dependencies=[self.row['work_id']],
                     resource=digest(dict(repository=child_request['repository'].casefold())))
        heads = dict(self.heads, **{child['repository']: child['source_sha']})
        mission = compile_mission([self.row, child], source_heads=heads)
        with KernelJournal(self.path) as journal:
            journal.append(operation(child, ident='2'))
            first = execute_recipe(mission, journal, self.request, FIXTURE.encode(),
                                   source_heads=heads, now=LATER)
            append = journal.append
            def crash(op):
                if op['outcome'] == 'EXTERNAL_CONFIRMED':
                    raise RuntimeError('before child confirm')
                return append(op)
            with patch.object(journal, 'append', side_effect=crash):
                with self.assertRaises(RuntimeError):
                    execute_recipe(mission, journal, child_request, FIXTURE.encode(),
                                   source_heads=heads, now=LATER)
            parent = [record['operation']['work'] for record in journal.replay()
                      if record['kind'] == 'WORK'
                      and record['operation']['work']['work_id'] == self.row['work_id']][-1]
            journal.append(operation(parent, ident='9', expected='TESTED', outcome='EXTERNAL_INTENT'))
            with patch('brain.v9.local_recipe.exercise_repair') as runner:
                with self.assertRaisesRegex(BrainError, 'DEPENDENCY_UNCERTAIN'):
                    execute_recipe(mission, journal, child_request, FIXTURE.encode(),
                                   source_heads=heads, now=LATER)
                runner.assert_not_called()
            journal.append(operation(parent, ident='8', expected='TESTED', outcome='EXTERNAL_CONFIRMED'))
            second = execute_recipe(mission, journal, child_request, FIXTURE.encode(),
                                    source_heads=heads, now=LATER)
        self.assertTrue(second['reused_result'])
        self.assertNotEqual(first['artifact_sha256'], second['artifact_sha256'])
        self.assertEqual(second['status'], 'LOCAL_RECIPE_TESTED')


if __name__ == '__main__':
    unittest.main()
