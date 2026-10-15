"""Provider outcomes cannot manufacture uptime, revenue or retry success."""
import unittest

from brain.operational_outcomes import collect_outcomes
from brain.core import BrainError

SHA = 'a' * 40
START = '2026-10-15T00:00:00Z'
END = '2026-10-15T23:00:00Z'


def run(number, conclusion='success', attempt=1):
    return {'id': number, 'head_sha': SHA, 'head_branch': 'main',
            'path': '.github/workflows/brain-cycle.yml', 'event': 'schedule',
            'created_at': '2026-10-15T12:00:00Z',
            'status': 'completed', 'conclusion': conclusion, 'run_attempt': attempt}


class Provider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, repo, path):
        self.calls.append((repo, path))
        if path == '/branches/main':
            return {'name': 'main', 'commit': {'sha': SHA}}
        return {'total_count': len(self.rows), 'workflow_runs': self.rows}


class OutcomeTests(unittest.TestCase):
    def collect(self, api):
        return collect_outcomes(api, ['portfolio-brain'], started_at=START, ended_at=END)

    def test_measures_actual_provider_conclusions_without_claiming_uptime_or_money(self):
        api = Provider([run(1), run(2, 'failure')])
        result = self.collect(api)
        row = result['projects'][0]
        self.assertEqual(row['successful_terminal_runs'], 1)
        self.assertEqual(row['adverse_terminal_runs'], 1)
        self.assertEqual(row['terminal_success_fraction'], 0.5)
        self.assertIsNone(row['production_uptime'])
        self.assertIsNone(row['verified_revenue'])
        self.assertFalse(result['production_accepted'])
        self.assertEqual(len(api.calls), 3)

    def test_rerun_and_pending_are_unknown_not_success(self):
        queued = run(3)
        queued.update(status='queued', conclusion=None)
        row = self.collect(Provider([run(1, attempt=2), queued]))['projects'][0]
        self.assertFalse(row['attempt_history_complete'])
        self.assertIsNone(row['terminal_success_fraction'])
        self.assertEqual(row['rerun_ids_needing_attempt_census'], [1])
        self.assertEqual(row['pending_runs'], 1)

    def test_empty_page_is_unknown_not_perfect_reliability(self):
        row = self.collect(Provider([]))['projects'][0]
        self.assertIsNone(row['terminal_success_fraction'])
        self.assertEqual(row['evidence_status'], 'NO_RUNS_OBSERVED')

    def test_duplicates_and_malformed_provider_rows_fail_closed(self):
        for rows in ([run(1), run(1)], [run(True)], [run(1, attempt=True)],
                     [dict(run(1), head_branch='other')],
                     [dict(run(1), created_at='2026-10-16T00:00:00Z')],
                     [run(1, conclusion='invented')]):
            with self.subTest(rows=rows), self.assertRaises(BrainError):
                self.collect(Provider(rows))

    def test_changed_main_or_truncated_pages_cannot_receive_metrics(self):
        class Drift(Provider):
            def __call__(self, repo, path):
                result = super().__call__(repo, path)
                if len(self.calls) == 3:
                    result['commit']['sha'] = 'b' * 40
                return result
        with self.assertRaisesRegex(BrainError, 'OUTCOME_SOURCE_CHANGED'):
            self.collect(Drift([run(1)]))
        class Truncated(Provider):
            def __call__(self, repo, path):
                result = super().__call__(repo, path)
                if 'workflow_runs' in result:
                    result['total_count'] = 2
                return result
        with self.assertRaisesRegex(BrainError, 'OUTCOME_PAGE_INCOMPLETE'):
            self.collect(Truncated([run(1)]))

    def test_request_bound_and_project_allowlist_are_enforced(self):
        with self.assertRaises(BrainError):
            collect_outcomes(Provider([]), ['unknown'], started_at=START, ended_at=END)
        with self.assertRaises(BrainError):
            collect_outcomes(Provider([]), ['portfolio-brain'] * 2,
                             started_at=START, ended_at=END)

    def test_repeated_failures_create_source_bound_diagnostic_priority(self):
        result = self.collect(Provider([run(1, 'failure'), run(2, 'failure'), run(3)]))
        signal = result['priority_signals'][0]
        self.assertEqual(signal['adverse_terminal_runs'], 2)
        self.assertEqual(signal['workflow_path'], '.github/workflows/brain-cycle.yml')
        self.assertEqual(signal['next_operation'], 'DIAGNOSE_ORIGINAL_JOBS_AND_ARTIFACTS')
        self.assertFalse(signal['root_cause_verified'])
        self.assertIsNone(signal['customer_value'])

    def test_complete_pagination_and_changed_page_totals(self):
        class Pages(Provider):
            def __call__(self, repo, path):
                self.calls.append((repo, path))
                if path == '/branches/main':
                    return {'name': 'main', 'commit': {'sha': SHA}}
                page = 2 if '&page=2&' in path else 1
                return {'total_count': 101, 'workflow_runs':
                        [run(i) for i in (range(1, 101) if page == 1 else [101])]}
        api = Pages([])
        self.assertEqual(self.collect(api)['projects'][0]['successful_terminal_runs'], 101)
        self.assertEqual(len(api.calls), 4)
        class Changed(Pages):
            def __call__(self, repo, path):
                result = super().__call__(repo, path)
                if '&page=2&' in path:
                    result['total_count'] = 102
                return result
        with self.assertRaisesRegex(BrainError, 'OUTCOME_INVENTORY_CHANGED'):
            self.collect(Changed([]))

