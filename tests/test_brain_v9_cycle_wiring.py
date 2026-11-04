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
    def test_feature_branch_cancelled_check_stays_triage_not_proven_production(self):
        # Provider run 39904547112 was a cancelled push on
        # stepqa-pb01-main-repro-20261023, although its check SHA equals main.
        # The bounded snapshot retains the adverse check, but not its run event/ref.
        payload = report()
        payload['projects'] = [dict(
            id='portfolio-brain', repository='P00NSMASHER/portfolio-brain',
            repository_revision='58e96a4e7a036b9f877f4bc6903656082ce84ca3',
            source_check_state='ADVERSE_CHECKS_OBSERVED')]
        outcome = run_cycle(payload, self.queue, source_sha=SOURCE, cycle=0, now=NOW)
        self.assertEqual(len(outcome['owner_jobs']), 1)
        handoff = outcome['owner_jobs'][0]
        self.assertEqual(handoff['owner'], 'brain-reliability')
        self.assertEqual(handoff['verifier'], 'brain-qa')
        self.assertEqual(handoff['priority'], 1)
        self.assertEqual(handoff['source_check_state'], 'ADVERSE_CHECKS_OBSERVED')
        self.assertEqual(handoff['incident_classification'],
                         'ADVERSE_CHECK_HISTORY_PRODUCTION_UNVERIFIED')
        self.assertFalse(outcome['automatic_execution_authority'])
        self.assertEqual(outcome['total_project_gets'], 24)
        self.assertEqual(outcome['metrics']['work_items'], 1)

    def test_non_portfolio_adverse_checks_are_triage_not_proven_incidents(self):
        # Existing ABVM fixture has only a SHA and adverse check summary,
        # without proof of protected-main runtime origin or event/ref.
        payload = report()
        outcome = run_cycle(payload, self.queue, source_sha=SOURCE, cycle=0, now=NOW)
        self.assertEqual(len(outcome['owner_jobs']), 1)
        handoff = outcome['owner_jobs'][0]
        self.assertEqual(handoff['owner'], 'abvm-reliability')
        self.assertEqual(handoff['verifier'], 'portfolio-security')
        self.assertEqual(handoff['priority'], 1)
        self.assertEqual(handoff['source_check_state'], 'ADVERSE_CHECKS_OBSERVED')
        self.assertEqual(handoff['incident_classification'],
                         'ADVERSE_CHECK_HISTORY_PRODUCTION_UNVERIFIED')
        self.assertEqual(outcome['total_project_gets'], 24)
        self.assertEqual(outcome['provider_writes'], 0)
        self.assertFalse(outcome['production_accepted'])
        self.assertFalse(outcome['automatic_execution_authority'])

    def test_non_portfolio_clean_checks_do_not_create_engineering_work(self):
        payload = report()
        payload['projects'][0]['source_check_state'] = (
            'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL')
        original_checkpoint = self.queue.checkpoint()
        outcome = run_cycle(payload, self.queue, source_sha=SOURCE, cycle=0, now=NOW)
        self.assertEqual(outcome['owner_jobs'], [])
        self.assertEqual(outcome['metrics']['work_items'], 0)
        self.assertEqual(self.queue.checkpoint(), original_checkpoint)
        self.assertEqual(outcome['nonactionable_source_signals'], [{
            'project_id': 'abvm',
            'repository': 'P00NSMASHER/abvmschoolstarworld',
            'source_sha': TARGET,
            'source_check_state': 'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL',
            'disposition': 'OBSERVED_NON_ACTIONABLE',
        }])
        self.assertFalse(outcome['production_accepted'])

        # Normal continuous deployments must not saturate the 256-item queue.
        for index in range(70):
            payload['projects'][0]['repository_revision'] = f'{index:040x}'
            next_result = run_cycle(payload, self.queue, source_sha=SOURCE,
                                    cycle=index + 1, now=LATER)
            self.assertEqual(next_result['owner_jobs'], [])
            self.assertEqual(next_result['metrics']['work_items'], 0)
        self.assertEqual(self.queue.checkpoint(), original_checkpoint)

    def test_clean_reobservation_never_deletes_existing_adverse_evidence(self):
        first = run_cycle(report(), self.queue, source_sha=SOURCE, cycle=0, now=NOW)
        work_id = first['owner_jobs'][0]['work_id']
        evidence_before = self.queue.checkpoint()
        clean = report()
        clean['projects'][0]['source_check_state'] = (
            'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL')
        second = run_cycle(clean, self.queue, source_sha=SOURCE, cycle=1, now=LATER)
        self.assertEqual(second['owner_jobs'], [])
        self.assertEqual(second['metrics']['stages']['OBSERVED'], 1)
        self.assertEqual(self.queue.checkpoint(), evidence_before)
        self.assertIn(work_id, self.queue.snapshot()['work'])

    def test_pressure_archives_only_superseded_low_priority_observations(self):
        with patch('brain.v9.batch_queue.MAX_WORK', 12):
            low = report()
            project = low['projects'][0]
            project['source_check_state'] = 'INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED'
            for index in range(8):
                project['repository_revision'] = f'{index:040x}'
                run_cycle(low, self.queue, source_sha=SOURCE, cycle=index, now=NOW)
            original = self.queue.snapshot()['work']
            held = next(iter(original))
            self.queue.claim(held, original[held]['owner'], now=NOW)
            run_cycle(report(), self.queue, source_sha=SOURCE, cycle=8, now=NOW)
            current = report()
            project = current['projects'][0]
            project.update(repository_revision='c'*40,
                           source_check_state='NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL')
            source = dict(repository=project['repository'], default_branch='main',
                          data_kind='ACTUAL', head_sha=project['repository_revision'],
                          source_ref=f"https://github.com/{project['repository']}/commit/{project['repository_revision']}",
                          observed_at=LATER)
            checkpoint = self.queue.checkpoint()
            for snapshots in ([], [dict(source, head_sha='d'*40)],
                              [dict(source, observed_at='2026-10-21T08:00:00Z')],
                              [source, source], [dict(source, data_kind='SIMULATED')]):
                current['repositories'] = snapshots
                run_cycle(current, self.queue, source_sha=SOURCE, cycle=9, now=LATER)
                self.assertEqual(self.queue.checkpoint(), checkpoint)

            current['repositories'] = [source]
            result = run_cycle(current, self.queue, source_sha=SOURCE, cycle=9, now=LATER)
            self.assertEqual(result['metrics']['work_items'], 2)
            self.assertEqual(result['archived_superseded_observations'], 7)
            work = self.queue.snapshot()['work']
            self.assertIn(held, work)
            self.assertEqual(sum(row['priority'] == 1 for row in work.values()), 1)
            self.assertEqual(self.queue.checkpoint()['chain_hash'], checkpoint['chain_hash'])
            self.assertEqual(self.queue.restore_drill()['checkpoint'], self.queue.checkpoint())
            self.assertEqual(result['metrics']['actual_live_verified'], 0)
            repeated = run_cycle(current, self.queue, source_sha=SOURCE, cycle=10, now=LATER)
            self.assertEqual(repeated['archived_superseded_observations'], 0)

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
        native_clock = (ROOT / '.github/workflows/brain-clock.yml').read_text()
        self.assertIn('7,27,47 * * * *', native_clock)
        self.assertIn('python -m brain.watchdog decide', native_clock)
        self.assertNotIn('\n  schedule:', workflow)
    def test_restore_of_integrated_queue_is_exact(self):
        run_cycle(report(), self.queue, source_sha=SOURCE, cycle=1, now=NOW)
        result = self.queue.restore_drill()
        self.assertEqual(result['status'], 'ISOLATED_RESTORE_REPLAY_PASSED')
        self.assertFalse(result['production_accepted'])

if __name__ == '__main__':
    unittest.main()
