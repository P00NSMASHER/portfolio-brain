import unittest
from verification.reliability_day import evaluate
from verification.source_acceptance_verifier import SourceAcceptanceError

class ObservationTests(unittest.TestCase):
    def test_short_window_cannot_pass(self):
        self.assertEqual(evaluate({'span':43199,'maximum_gap':1800})['status'],'COLLECTING')
    def test_terminal_follow_through_never_passes_before_thirty_minutes(self):
        from datetime import datetime, timedelta, timezone
        from verification.reliability_day import terminal_follow_through_ready
        terminal = {'completed': datetime(2026, 10, 29, 12, tzinfo=timezone.utc)}
        self.assertFalse(terminal_follow_through_ready(
            terminal, now=terminal['completed'] + timedelta(minutes=29, seconds=59)))
        self.assertTrue(terminal_follow_through_ready(
            terminal, now=terminal['completed'] + timedelta(minutes=30)))

    def test_twelve_hours_requires_bounded_gaps(self):
        result=evaluate({'span':43200,'maximum_gap':1800})
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['required_span_seconds'],43200)
        self.assertFalse(result['independent_release_authority'])
        with self.assertRaises(SourceAcceptanceError):
            evaluate({'span':43200,'maximum_gap':5401})

class CensusTests(unittest.TestCase):
    def test_pagination_requires_complete_unique_inventory(self):
        from verification.reliability_day import inventory
        class API:
            def json(self, path):
                rows = [{'id': n} for n in range(100)] if path.endswith('=1') else [{'id':100}]
                return {'total_count':101,'workflow_runs':rows}
        self.assertEqual(len(inventory(API(), '/runs?per_page=100')),101)

    def test_pending_core_is_excluded_but_failed_original_is_rejected(self):
        from verification.reliability_day import window
        row = dict(id=1,head_sha='a',created_at='2026-10-26T00:00:00Z',status='completed',
                   conclusion='success',run_attempt=1,event='push')
        self.assertEqual(window([row, dict(row,id=2,status='in_progress')], 'a'),[row])
        with self.assertRaises(SourceAcceptanceError):
            window([dict(row, conclusion='failure')], 'a')

    def test_post_window_failure_does_not_retroactively_erase_pass(self):
        from verification.reliability_day import window
        source = 'a' * 40
        def core(run_id, created_at, conclusion='success'):
            return dict(id=run_id, head_sha=source, created_at=created_at,
                        status='completed', conclusion=conclusion,
                        run_attempt=1, event='workflow_dispatch')
        first = core(1, '2026-10-27T18:40:22Z')
        terminal = core(2, '2026-10-28T07:00:22Z')
        outside = core(3, '2026-10-28T07:30:22Z', 'failure')
        self.assertEqual(window([outside, terminal, first], source), [first, terminal])

    def test_failure_inside_fixed_window_remains_rejected(self):
        from verification.reliability_day import window
        source = 'a' * 40
        row = dict(id=1, head_sha=source, created_at='2026-10-27T18:40:22Z',
                   status='completed', conclusion='success',
                   run_attempt=1, event='workflow_dispatch')
        inside = dict(row, id=2, created_at='2026-10-28T07:00:23Z',
                      conclusion='failure')
        with self.assertRaisesRegex(SourceAcceptanceError, 'original core failed or retried'):
            window([row, inside], source)

    def test_exact_boundary_run_is_included_and_must_succeed(self):
        from verification.reliability_day import window
        source = 'a' * 40
        row = dict(id=1, head_sha=source, created_at='2026-10-27T18:40:22Z',
                   status='completed', conclusion='success',
                   run_attempt=1, event='workflow_dispatch')
        boundary = dict(row, id=2, created_at='2026-10-28T07:10:22Z')
        self.assertEqual(window([row, boundary], source), [row, boundary])
        with self.assertRaisesRegex(SourceAcceptanceError, 'original core failed or retried'):
            window([row, dict(boundary, conclusion='failure')], source)

    def test_retried_repair_cannot_erase_original_failure(self):
        from verification.reliability_day import verify_repairs
        with self.assertRaises(SourceAcceptanceError):
            verify_repairs(None,[dict(head_sha='a',status='completed',conclusion='success',run_attempt=2)],'a',{1})

    def test_repair_coverage_requires_original_core_identity(self):
        import hashlib,io,json,zipfile
        from verification.reliability_day import verify_repairs
        raw = io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('v8-origin.json',json.dumps(dict(source_sha='a',run_id='2',status='ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED')))
        data=raw.getvalue()
        class API:
            def json(self,path):
                return {'total_count':1,'artifacts':[dict(id=7,expired=False,workflow_run=dict(id=3,head_sha='a'),digest='sha256:'+hashlib.sha256(data).hexdigest())]}
            def get(self,*args,**kwargs):return data
        rows=[dict(id=3,head_sha='a',status='completed',conclusion='success',run_attempt=1)]
        self.assertFalse(verify_repairs(API(),rows,'a',{1}))
        self.assertTrue(verify_repairs(API(),rows,'a',{2}))

    def test_repair_completed_after_cutoff_is_not_retrospective_proof(self):
        from verification.reliability_day import verify_repairs
        from verification.source_acceptance_verifier import utc
        cutoff = utc('2026-10-29T12:30:00Z')
        late = dict(id=7, head_sha='a', created_at='2026-10-29T12:00:00Z',
                    updated_at='2026-10-29T12:31:00Z', status='completed',
                    conclusion='success', run_attempt=1)
        self.assertFalse(verify_repairs(None, [late], 'a', {14}, cutoff=cutoff))

    def test_late_uploaded_repair_artifact_does_not_retroactively_pass(self):
        from verification.reliability_day import verify_repairs
        from verification.source_acceptance_verifier import utc
        class API:
            def json(self, path):
                return {'total_count': 1, 'artifacts': [{
                    'id': 91, 'created_at': '2026-10-29T12:31:00Z'}]}
        ontime_run = dict(id=8, head_sha='a', created_at='2026-10-29T12:00:00Z',
                          updated_at='2026-10-29T12:03:00Z',
                          status='completed', conclusion='success', run_attempt=1)
        self.assertFalse(verify_repairs(API(), [ontime_run], 'a', {14},
                                        cutoff=utc('2026-10-29T12:30:00Z')))

    def test_later_repairs_do_not_consume_window_budget(self):
        from verification.reliability_day import verify_repairs
        from verification.source_acceptance_verifier import utc
        self.assertTrue(verify_repairs(None,[{'created_at':'2026-10-28T00:00:00Z'}], 'a',set(),
                                      cutoff=utc('2026-10-27T00:00:00Z')))
