"""Real private SQLite restart tests for advisory v9 local mission planning."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from brain.core import BrainError, digest
from brain.v8.contracts import advance, LOCAL_STATES
from brain.v8.journal import KernelJournal
from brain.v9.missions import compile_mission, project_mission
from test_brain_v8_contracts import work, NOW, LATER
from test_brain_v8_journal import operation


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'kernel.sqlite'
        self.a = work()
        self.b = work('other', resource='e' * 64, dependencies=[self.a['work_id']])
        self.heads = {self.a['repository']: self.a['source_sha']}

    def compile(self, rows=None, **kwargs):
        return compile_mission(rows or [self.a, self.b], source_heads=self.heads, **kwargs)

    def project(self, mission, **kwargs):
        with KernelJournal(self.path, readonly=True) as journal:
            return project_mission(mission, journal, source_heads=self.heads,
                                   now=LATER, **kwargs)

    def seed(self, rows):
        with KernelJournal(self.path, create=True) as journal:
            for index, row in enumerate(rows):
                journal.append(operation(row, ident=str(index + 1)))

    def test_canonical_identity_and_detached_inputs(self):
        mission = self.compile()
        self.assertEqual(mission, self.compile([self.b, self.a]))
        changed = copy.deepcopy(self.a)
        changed['state'] = 'DIAGNOSED'
        self.assertEqual(mission, self.compile([changed, self.b]))
        self.a['owner'] = 'different'
        self.assertNotEqual(mission['mission_id'], self.compile()['mission_id'])
        self.assertEqual(mission['work'][0]['owner'], 'school-owner')

    def test_invalid_dags_duplicates_bounds_and_sources(self):
        a, b = copy.deepcopy(self.a), copy.deepcopy(self.b)
        a['dependencies'] = [b['work_id']]
        for rows in ([a, b], [self.b], [self.a, self.a]):
            with self.subTest(rows=rows), self.assertRaises(BrainError):
                self.compile(rows)
        for limit in (True, 0, 6, '1'):
            with self.subTest(limit=limit), self.assertRaises(BrainError):
                self.compile(max_parallel=limit)
        with self.assertRaises(BrainError):
            compile_mission([], source_heads=self.heads)
        with self.assertRaises(BrainError):
            compile_mission([self.a] * 257, source_heads=self.heads)
        with self.assertRaises(BrainError):
            compile_mission([self.a], source_heads={self.a['repository']: 'f' * 40})

    def test_restart_projection_is_identical_and_does_not_write(self):
        mission = self.compile()
        self.seed([self.a, self.b])
        before = self.path.read_bytes()
        first = self.project(mission)
        self.assertEqual(first, self.project(mission))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([x['work_id'] for x in first['selected']], [self.a['work_id']])
        self.assertEqual(first['blocked'][0]['reason'], 'LOCAL_DEPENDENCY_UNFINISHED')
        self.assertFalse(first['automatic_execution_authority'])
        self.assertFalse(first['release_authority'])

    def test_tested_unlocks_local_dependency_but_never_acceptance_or_release(self):
        mission = self.compile()
        self.seed([self.a, self.b])
        row = self.a
        with KernelJournal(self.path) as journal:
            for index, target in enumerate(LOCAL_STATES[1:]):
                prior = row['state']
                row = advance(row, target, evidence_ids=['d' * 64], now=LATER)
                journal.append(operation(row, ident=str(index + 3), expected=prior))
        result = self.project(mission)
        self.assertEqual(result['local_completed'], [self.a['work_id']])
        self.assertEqual(result['selected'], [dict(work_id=self.b['work_id'],
                          source_sha=self.b['source_sha'], next_local_state='DIAGNOSED')])
        self.assertFalse(result['independently_accepted'])
        self.assertFalse(result['release_authority'])

    def test_unknown_provider_write_blocks_even_after_expired_claim(self):
        mission = self.compile([self.a])
        self.seed([self.a])
        with KernelJournal(self.path) as journal:
            journal.claim(resource=self.a['resource'], owner=self.a['owner'],
                          operation_id='2' * 64, source_sha=self.a['source_sha'],
                          now=NOW, expires_at=LATER)
            journal.append(operation(self.a, ident='2', expected='OBSERVED',
                                     outcome='EXTERNAL_INTENT'))
            journal.append(operation(self.a, ident='3', expected='OBSERVED',
                                     outcome='EXTERNAL_UNKNOWN'))
        result = self.project(mission)
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['blocked'][0]['reason'], 'EXTERNAL_RECONCILIATION_REQUIRED')
        with KernelJournal(self.path) as journal:
            journal.append(operation(self.a, ident='4', expected='OBSERVED',
                                     outcome='EXTERNAL_CONFIRMED'))
        self.assertEqual(self.project(mission)['blocked'][0]['reason'], 'RESOURCE_CLAIM_HELD')
        with KernelJournal(self.path) as journal:
            journal.release_claim(resource=self.a['resource'], owner=self.a['owner'],
                                  operation_id='2' * 64, now=LATER)
        self.assertEqual(len(self.project(mission)['selected']), 1)

    def test_unrelated_pending_write_on_same_resource_blocks(self):
        foreign = work('foreign')
        mission = self.compile([self.a])
        self.seed([self.a, foreign])
        with KernelJournal(self.path) as journal:
            journal.append(operation(foreign, ident='3', expected='OBSERVED',
                                     outcome='EXTERNAL_INTENT'))
        self.assertEqual(self.project(mission)['blocked'][0]['reason'],
                         'EXTERNAL_RECONCILIATION_REQUIRED')

    def test_resource_conflicts_and_parallel_limit(self):
        same = work('same')
        independent = work('independent', resource='f' * 64)
        self.seed([self.a, same, independent])
        result = self.project(self.compile([self.a, same, independent], max_parallel=5))
        self.assertEqual(len(result['selected']), 2)
        self.assertEqual(result['deferred'][0]['reason'], 'RESOURCE_COLLISION')
        result = self.project(self.compile([self.a, same, independent], max_parallel=1))
        self.assertEqual(len(result['selected']), 1)
        self.assertEqual(len(result['deferred']), 2)

    def test_missing_work_drift_and_mutated_mission_fail_closed(self):
        mission = self.compile()
        self.seed([self.a])
        self.assertIn('WORK_NOT_OBSERVED', [x['reason'] for x in self.project(mission)['blocked']])
        altered = copy.deepcopy(mission)
        altered['max_parallel'] = 5
        with self.assertRaises(BrainError):
            self.project(altered)
        with KernelJournal(self.path, readonly=True) as journal:
            with self.assertRaises(BrainError):
                project_mission(mission, journal,
                    source_heads={self.a['repository']: 'f' * 40}, now=LATER)
            with self.assertRaises(BrainError):
                project_mission(mission, journal, source_heads=self.heads,
                                now='2026-10-15T19:00:00Z')

    def test_membership_is_bound_to_journal_identity(self):
        mission = self.compile([self.a])
        altered = dict(self.a, owner='different')
        self.seed([altered])
        with self.assertRaises(BrainError):
            self.project(mission)

    def test_corrupted_journal_is_not_accepted(self):
        mission = self.compile([self.a])
        self.seed([self.a])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE kernel_events SET body_hash=?", ('0' * 64,))
        with self.assertRaises(BrainError):
            self.project(mission)

    def test_stopped_work_cannot_schedule(self):
        mission = self.compile()
        self.seed([self.a, self.b])
        with KernelJournal(self.path) as journal:
            failed = advance(self.a, 'FAILED', evidence_ids=['d' * 64], now=LATER)
            journal.append(operation(failed, ident='3', expected='OBSERVED'))
        result = self.project(mission)
        self.assertEqual(result['selected'], [])
        self.assertEqual(len(result['blocked']), 2)


if __name__ == '__main__':
    unittest.main()
