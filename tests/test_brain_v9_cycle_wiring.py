"""Integration contract for persistent state, original evidence and unchanged budgets."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from brain.v9.batch_queue import BatchQueue, BatchFault
try:
    from brain.v9.batch_cycle import run_cycle
except ImportError:
    run_cycle = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'a' * 40
TARGET = 'b' * 40
NOW = '2026-10-22T08:00:00Z'
LATER = '2026-10-22T08:01:00Z'

def report(requests=24):
    return dict(schema_version=1, source_sha=SOURCE, canonical_pending_events=0,
                operation=dict(name='projects', requests=requests), projects=[
        dict(id='abvm', repository='P00NSMASHER/abvmschoolstarworld',
             repository_revision=TARGET, source_check_state='ADVERSE_CHECKS_OBSERVED')])

class CycleWiringTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(run_cycle), 'v9 durable execution bridge is missing')
        self.home = tempfile.TemporaryDirectory()
        self.queue = BatchQueue(Path(self.home.name) / 'state.sqlite')
    def tearDown(self):
        if hasattr(self, 'queue'):
            self.queue.close()
            self.home.cleanup()
    def test_same_state_file_preserves_progress_across_cycles(self):
        output = run_cycle(report(), self.queue, source_sha=SOURCE, cycle=1, now=NOW)
        ident = output['owner_jobs'][0]['work_id']
        owner = output['owner_jobs'][0]['owner']
        token = self.queue.claim(ident, owner, now=NOW)
        self.queue.advance(ident, token, 'DIAGNOSED', evidence_sha='c'*64, now=NOW)
        second = run_cycle(report(), self.queue, source_sha=SOURCE, cycle=2, now=LATER)
        self.assertEqual(self.queue.snapshot()['work'][ident]['stage'], 'DIAGNOSED')
        self.assertEqual(second['owner_jobs'], [])
        self.assertEqual(second['metrics']['work_items'], 1)
        self.assertEqual(second['provider_gets'], 0)
    def test_old_source_owner_lease_blocks_new_source_handoff(self):
        output = run_cycle(report(), self.queue, source_sha=SOURCE, cycle=1, now=NOW)
        job = output['owner_jobs'][0]
        self.queue.claim(job['work_id'], job['owner'], now=NOW)
        newer = report()
        newer['projects'][0]['repository_revision'] = 'e'*40
        result = run_cycle(newer, self.queue, source_sha=SOURCE, cycle=2, now=LATER)
        self.assertEqual(result['owner_jobs'], [])
        self.assertEqual(result['metrics']['work_items'], 2)

    def test_wrong_source_or_untrusted_budget_cannot_mutate_queue(self):
        initial = self.queue.checkpoint()
        for invalid in (dict(report(), source_sha='d'*40), report(requests=25), report(requests=True)):
            with self.subTest(invalid=invalid), self.assertRaises(BatchFault):
                run_cycle(invalid, self.queue, source_sha=SOURCE, cycle=0, now=NOW)
            self.assertEqual(initial, self.queue.checkpoint())
    def test_missing_source_remains_unknown(self):
        payload = report()
        payload['projects'][0]['repository_revision'] = None
        result = run_cycle(payload, self.queue, source_sha=SOURCE, cycle=0, now=NOW)
        self.assertEqual(result['owner_jobs'], [])
        self.assertEqual(result['unobserved_projects'], ['abvm'])
        self.assertFalse(result['production_accepted'])
    def test_global_clock_rollback_is_rejected_before_commit(self):
        run_cycle(report(), self.queue, source_sha=SOURCE, cycle=0, now=LATER)
        checkpoint = self.queue.checkpoint()
        payload = report()
        payload['projects'][0]['repository_revision'] = 'd'*40
        with self.assertRaisesRegex(BatchFault, 'TIME_REVERSED'):
            run_cycle(payload, self.queue, source_sha=SOURCE, cycle=1, now=NOW)
        self.assertEqual(checkpoint, self.queue.checkpoint())
    def test_original_provider_budget_and_stale_sources_not_promoted(self):
        payload = report(requests=23)
        result = run_cycle(payload, self.queue, source_sha=SOURCE, cycle=0, now=NOW,
                           proof_spec={'schema_version': 1})
        self.assertEqual(result['provider_readback']['status'], 'BUDGET_UNAVAILABLE_NOT_VERIFIED')
        self.assertEqual(result['total_project_gets'], 23)
        self.assertFalse(result['production_accepted'])
    def test_scheduled_core_calls_bridge_before_packing_the_same_state(self):
        workflow = (ROOT / '.github/workflows/brain-cycle.yml').read_text()
        self.assertIn('python -m brain.v9.batch_cycle cycle', workflow)
        anchor = workflow.index('python -m brain.v9.batch_cycle cycle')
        self.assertIn('--db state/state.sqlite', workflow[anchor:anchor+700])
        self.assertIn('--input /tmp/brain/projects/report.json', workflow[anchor:anchor+700])
        self.assertLess(anchor, workflow.index('python -m brain.state_archive pack'))
        self.assertIn('7,27,47 * * * *', workflow)
    def test_restore_of_integrated_queue_is_exact(self):
        run_cycle(report(), self.queue, source_sha=SOURCE, cycle=1, now=NOW)
        result = self.queue.restore_drill()
        self.assertEqual(result['status'], 'ISOLATED_RESTORE_REPLAY_PASSED')
        self.assertFalse(result['production_accepted'])

if __name__ == '__main__':
    unittest.main()
