"""Network-free regressions for restart safety and acceptance provenance."""
import copy
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from brain.v9 import guarded_merge as gm, guarded_merge_runner as runner
from brain.v9.batch_queue import BatchQueue, BatchFault
from brain.v9 import batch_queue as bq
from test_brain_v9_guarded_merge import BASE, HEAD, PR, ROOT, REVIEW_TIP, FakeProvider, EventRunnerProvider
from test_brain_v9_early_native_enrollment import early_fixture


class RedTeamTests(unittest.TestCase):
    def observation(self, number, fingerprint='d'*64):
        return dict(project_id='portfolio-brain', repository=gm.REPO,
                    source_sha=format(number, '040x'), fingerprint=fingerprint,
                    owner='brain', path='repository-observation', priority=1)

    def test_segment_exhaustion_preserves_existing_work(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_WORK', 2), patch.object(bq, 'MAX_ARCHIVE_SEGMENTS', 1):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                for number in range(4):
                    queue.observe(self.observation(number), now='2026-10-22T20:00:00Z')
                before = queue.checkpoint()
                with self.assertRaisesRegex(BatchFault, 'ARCHIVE_CAPACITY'):
                    queue.observe(self.observation(4), now='2026-10-22T20:00:00Z')
                self.assertEqual(queue.checkpoint(), before)
            finally:
                queue.close()

    def test_archive_raw_byte_exhaustion_rolls_back_rotation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_WORK', 2):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                for number in range(2):
                    queue.observe(self.observation(number), now='2026-10-22T20:00:00Z')
                before = queue.checkpoint()
                with patch.object(bq, 'MAX_ARCHIVE_RAW_BYTES', 1), self.assertRaisesRegex(BatchFault, 'ARCHIVE_'):
                    queue.observe(self.observation(2), now='2026-10-22T20:00:00Z')
                self.assertEqual(queue.checkpoint(), before)
            finally:
                queue.close()

    def test_unrelated_fingerprints_cannot_be_evicted(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_WORK', 2):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                queue.observe(self.observation(0), now='2026-10-22T20:00:00Z')
                queue.observe(self.observation(1, 'e'*64), now='2026-10-22T20:00:00Z')
                before = queue.checkpoint()
                with self.assertRaisesRegex(BatchFault, 'WORK_CAPACITY'):
                    queue.observe(self.observation(2, 'f'*64), now='2026-10-22T20:00:00Z')
                self.assertEqual(queue.checkpoint(), before)
            finally:
                queue.close()

    def test_expired_claim_is_retained_when_unclaimed_sources_retire(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_WORK', 2):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                claimed = queue.observe(self.observation(0), now='2026-10-22T20:00:00Z')
                queue.claim(claimed, 'brain', now='2026-10-22T20:00:00Z', ttl_seconds=1)
                queue.observe(self.observation(1), now='2026-10-22T20:00:00Z')
                queue.observe(self.observation(2), now='2026-10-22T20:01:00Z')
                self.assertIsNotNone(queue.snapshot()['work'][claimed]['claim'])
            finally:
                queue.close()

    def test_event_rotation_keeps_sequence_and_all_unrelated_work(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_EVENTS', 4):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                for number in range(8):
                    queue.observe(self.observation(number), now='2026-10-22T20:00:00Z')
                self.assertEqual(queue.checkpoint()['sequence'], 8)
                self.assertEqual(len(queue.snapshot()['work']), 8)
                self.assertEqual(queue.restore_drill()['status'], 'ISOLATED_RESTORE_REPLAY_PASSED')
            finally:
                queue.close()

    def test_archive_byte_pressure_warns_before_segment_limit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bq, 'MAX_WORK', 2):
            queue = BatchQueue(Path(directory) / 'q.sqlite')
            try:
                for number in range(3):
                    queue.observe(self.observation(number), now='2026-10-22T20:00:00Z')
                compressed = queue.db.execute('SELECT body FROM batch_archive WHERE slot=1').fetchone()[0]
                size = len(zlib.decompress(compressed))
                with patch.object(bq, 'MAX_ARCHIVE_RAW_BYTES', size + size//4), patch.object(bq, 'MAX_WORK', 256):
                    metrics = queue.metrics(now='2026-10-22T20:00:00Z')
                self.assertEqual(metrics['capacity_warning'], 'QUEUE_CAPACITY_APPROACHING')
                self.assertEqual(metrics.get('archive_raw_bytes'), size)
            finally:
                queue.close()

    def test_marker_creation_failure_prevents_native_mutation(self):
        provider = early_fixture()
        def lost_marker(*args):
            raise TimeoutError('lost create response')
        provider.reserve_native_intent = lost_marker
        with self.assertRaisesRegex(gm.Denied, 'AUTO_MERGE_'):
            gm.run(provider, number=PR, expected_main=BASE, apply=True, early=True)
        self.assertEqual(provider.mutations, 0)

    def test_uncertain_write_is_not_retried_by_fresh_invocation(self):
        first = early_fixture()
        first.provider_fail = True
        with self.assertRaises(gm.Denied):
            gm.run(first, number=PR, expected_main=BASE, apply=True, early=True)
        second = early_fixture()
        second.native_intents = first.native_intents  # Same remote GitHub state; fresh process.
        with self.assertRaises(gm.Denied):
            gm.run(second, number=PR, expected_main=BASE, apply=True, early=True)
        self.assertEqual(first.mutations + second.mutations, 1)

    def test_http_intent_reservation_is_exact_and_create_once(self):
        requests = []
        marker = 'refs/heads/brain-native-intent/pr-812-' + HEAD
        class Response:
            def __init__(self):
                self.status = 201 if len(requests) == 1 else 422
            def read(self, maximum):
                return json.dumps({'ref': marker, 'object': {'type': 'commit', 'sha': HEAD}}).encode()
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, method, path, body=None, headers=None):
                requests.append((method, path, json.loads(body)))
            def getresponse(self): return Response()
            def close(self): pass
        with patch.object(gm.http.client, 'HTTPSConnection', Connection):
            gm.GitHub('a'*32).reserve_native_intent(PR, HEAD)
            with self.assertRaisesRegex(gm.Denied, 'AUTO_MERGE_INTENT_UNVERIFIED_NO_RETRY'):
                gm.GitHub('a'*32).reserve_native_intent(PR, HEAD)
            with self.assertRaisesRegex(gm.Denied, 'GITHUB_METHOD_INVALID'):
                gm.GitHub('a'*32)._request('POST', ROOT + 'git/refs', {'ref': 'refs/heads/main', 'sha': HEAD})
        self.assertEqual(requests, [('POST', '/' + ROOT + 'git/refs', {'ref': marker, 'sha': HEAD})]*2)

    def test_blocked_candidate_is_not_reported_as_success(self):
        provider = early_fixture(EventRunnerProvider)
        provider.no_acceptance = True
        result = runner.dispatch_once(lambda: provider, BASE, early=True, event_head=HEAD)
        self.assertEqual(result['status'], 'CANDIDATES_BLOCKED')
        with patch.object(runner, 'dispatch_once', return_value=result), patch('builtins.print'):
            self.assertEqual(runner.main(), 2)

    def test_receipt_without_independent_attestation_is_denied(self):
        provider = FakeProvider()
        original = provider.get
        provider.get = lambda route: ({'total_count': 0, 'check_runs': []}
            if route == ROOT + 'commits/' + REVIEW_TIP + '/check-runs?per_page=100'
            else original(route))
        with self.assertRaisesRegex(gm.Denied, 'ACCEPTANCE_ATTESTATION'):
            gm.accepted_source(provider, BASE)

    def test_attestation_cannot_be_replayed_for_other_source_or_receipt(self):
        for field, value in [('external_id', 'source-acceptance:' + 'f'*40 + ':' + 'e'*64),
                             ('head_sha', 'e'*40), ('app', {'id': 15368}),
                             ('conclusion', 'failure')]:
            with self.subTest(field=field):
                provider = FakeProvider()
                original = provider.get
                def hostile(route):
                    result = original(route)
                    if route == ROOT + 'commits/' + REVIEW_TIP + '/check-runs?per_page=100':
                        result['check_runs'][0][field] = value
                    return result
                provider.get = hostile
                with self.assertRaisesRegex(gm.Denied, 'ACCEPTANCE_ATTESTATION'):
                    gm.accepted_source(provider, BASE)

    def test_source_churn_does_not_exhaust_observation_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = BatchQueue(Path(directory) / 'queue.sqlite')
            try:
                for number in range(270):
                    latest = queue.observe(dict(project_id='portfolio-brain',
                        repository=gm.REPO, source_sha=format(number, '040x'),
                        fingerprint='d'*64, owner='brain', path='repository-observation',
                        priority=1), now='2026-10-22T20:00:00Z')
                self.assertIn(latest, queue.snapshot()['work'])
                checkpoint = queue.checkpoint()
                queue.close()
                queue = BatchQueue(Path(directory) / 'queue.sqlite')
                self.assertEqual(queue.checkpoint(), checkpoint)
                self.assertGreater(queue.metrics(now='2026-10-22T20:00:00Z')['archive_segments'], 0)
                self.assertEqual(queue.restore_drill()['status'], 'ISOLATED_RESTORE_REPLAY_PASSED')
            finally:
                queue.close()

    def test_rotation_keeps_uncertain_effect_and_rejects_clock_rollback(self):
        from test_brain_v9_batch import issue, T0, T1, EVIDENCE
        with tempfile.TemporaryDirectory() as directory:
            queue = BatchQueue(Path(directory) / 'queue.sqlite')
            try:
                work = queue.observe(issue(), now=T0)
                token = queue.claim(work, 'retally-product', now=T0)
                for stage in ('DIAGNOSED', 'PATCHED', 'TESTED'):
                    queue.advance(work, token, stage, evidence_sha=EVIDENCE, now=T0)
                operation = queue.begin_effect(work, token, action='CREATE_BRANCH', now=T0)
                queue.mark_unknown(work, operation, now=T0)
                for number in range(255):
                    queue.observe(dict(issue(), source_sha=format(number+1, '040x')), now=T1)
                before = queue.checkpoint()
                with self.assertRaisesRegex(BatchFault, 'TIME_REVERSED'):
                    queue.observe(dict(issue(), source_sha='f'*40), now=T0)
                self.assertEqual(queue.checkpoint(), before)
                queue.observe(dict(issue(), source_sha='f'*40), now=T1)
                self.assertEqual(queue.snapshot()['work'][work]['pending']['status'], 'UNKNOWN')
                queue.db.execute("UPDATE batch_archive SET body=x'00' WHERE slot=1")
                with self.assertRaisesRegex(BatchFault, 'ARCHIVE_'):
                    queue.snapshot()
            finally:
                queue.close()


if __name__ == '__main__':
    unittest.main()
