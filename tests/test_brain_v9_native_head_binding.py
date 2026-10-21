"""Network-free atomic native enrollment and post-write identity regressions."""
import copy
import unittest
from unittest.mock import patch

from brain.v9 import guarded_merge as gm
from test_brain_v9_guarded_merge import FakeProvider, EventRunnerProvider, BASE, HEAD, PR, NODE, ROOT


class RecordingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.native_variables = None
        self.server_head = HEAD
        self.post_readback_change = None
        self.rejection = None

    def graphql(self, query, variables):
        if query == gm.ENABLE_MUTATION:
            self.native_variables = copy.deepcopy(variables)
            if self.rejection is not None:
                return copy.deepcopy(self.rejection)
            # Model GitHub's atomic compare-and-set, not a preflight reread.
            if ('expected_head' in variables
                    and variables['expected_head'] != self.server_head):
                return {'errors': [{'type': 'UNPROCESSABLE', 'message': 'head changed'}],
                        'data': {'enablePullRequestAutoMerge': None}}
        return super().graphql(query, variables)

    def get(self, path):
        result = super().get(path)
        if self.enabled and path == ROOT + 'pulls/' + str(PR):
            if self.post_readback_change is not None:
                self.post_readback_change(result)
        return result


class NativeHeadBindingTests(unittest.TestCase):
    def test_native_mutation_binds_exact_observed_head_atomically(self):
        provider = RecordingProvider()
        result = gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(result['status'], 'NATIVE_AUTO_MERGE_ENROLLED')
        self.assertEqual(provider.native_variables, {'id': NODE, 'expected_head': HEAD})
        self.assertIn('expectedHeadOid: $expected_head', gm.ENABLE_MUTATION)
        self.assertIn('$expected_head: GitObjectID!', gm.ENABLE_MUTATION)

    def test_race_after_final_reads_cannot_enroll_replacement_head(self):
        provider = RecordingProvider()
        provider.server_head = 'd' * 40
        try:
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        except gm.Denied:
            pass
        self.assertEqual(provider.mutations, 0, 'Replacement head was enrolled')
        self.assertFalse(provider.enabled)

    def test_native_transport_rejects_missing_invalid_or_extra_head_binding(self):
        invalid = [
            {'id': NODE}, {'id': NODE, 'expected_head': None},
            {'id': NODE, 'expected_head': 'A' * 40},
            {'id': NODE, 'expected_head': True},
            {'id': NODE, 'expected_head': 'b' * 39},
            {'id': NODE, 'expected_head': HEAD, 'merge_method': 'MERGE'},
            {'id': ['injected'], 'expected_head': HEAD},
        ]
        for values in invalid:
            with self.subTest(values=values):
                client = gm.GitHub('a' * 32)
                with patch.object(client, '_request') as request:
                    with self.assertRaises(gm.Denied):
                        client.graphql(gm.ENABLE_MUTATION, values)
                    request.assert_not_called()

    def test_valid_bound_request_is_the_only_native_transport_shape(self):
        client = gm.GitHub('a' * 32)
        values = {'id': NODE, 'expected_head': HEAD}
        with patch.object(client, '_request', return_value={'ok': True}) as request:
            result = client.graphql(gm.ENABLE_MUTATION, values)
            self.assertEqual(result, {'ok': True})
            request.assert_called_once_with('POST', 'graphql',
                                            {'query': gm.ENABLE_MUTATION, 'variables': values})

    def test_changed_open_enrollment_identity_is_uncertain_not_success(self):
        changes = [
            lambda p: p.update(number=PR+1),
            lambda p: p.update(node_id='PR_wrong_identity'),
            lambda p: p['base'].update(ref='other'),
            lambda p: p['base'].update(sha='d'*40),
            lambda p: p['base']['repo'].update(full_name='P00NSMASHER/other'),
            lambda p: p['head']['repo'].update(full_name='P00NSMASHER/other'),
            lambda p: p.update(draft=True),
            lambda p: p.update(merged=True),
            lambda p: p.update(labels=[]),
        ]
        for change in changes:
            with self.subTest(change=change):
                provider = RecordingProvider()
                provider.post_readback_change = change
                with self.assertRaisesRegex(gm.Denied, 'AUTO_MERGE_'):
                    gm.run(provider, number=PR, expected_main=BASE, apply=True)
                self.assertEqual(provider.mutations, 1, 'Ambiguous POST was retried')

    def test_changed_head_after_enrollment_never_reports_success(self):
        provider = RecordingProvider()
        provider.post_readback_change = lambda p: p['head'].update(sha='d'*40)
        with self.assertRaisesRegex(gm.Denied, 'AUTO_MERGE_'):
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(provider.mutations, 1)

    def test_explicit_forbidden_payload_retains_only_sanitized_error_type(self):
        provider = RecordingProvider()
        provider.rejection = {'errors': [{'type': 'FORBIDDEN',
            'message': 'SECRET_PRIVATE_MESSAGE', 'path': ['enablePullRequestAutoMerge']}],
            'data': {'enablePullRequestAutoMerge': None}}
        with self.assertRaises(gm.Denied) as caught:
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(str(caught.exception), 'AUTO_MERGE_PROVIDER_REJECTION_FORBIDDEN')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertEqual(provider.mutations, 0)

    def test_untrusted_error_text_and_partial_success_remain_uncertain(self):
        for response in [
            {'errors': [{'type': 'SECRET_PRIVATE_MESSAGE'}], 'data': None},
            {'errors': [{'type': 'FORBIDDEN'}], 'data': {'enablePullRequestAutoMerge':
                {'pullRequest': {'id': NODE}}}},
            {'errors': [{'type': 'FORBIDDEN'}, {'type': 'UNPROCESSABLE'}], 'data': None},
            {'errors': ['SECRET_PRIVATE_MESSAGE'], 'data': None},
        ]:
            with self.subTest(response=response):
                provider = RecordingProvider()
                provider.rejection = response
                with self.assertRaisesRegex(gm.Denied,
                    '^AUTO_MERGE_WRITE_UNCERTAIN_READBACK_REQUIRED$'):
                    gm.run(provider, number=PR, expected_main=BASE, apply=True)
                self.assertEqual(provider.mutations, 0)

    def test_runner_keeps_explicit_rejection_unknown_and_stops_without_retry(self):
        from brain.v9 import guarded_merge_runner as runner
        provider = EventRunnerProvider()
        with patch.object(runner, 'run', side_effect=gm.Denied(
                'AUTO_MERGE_PROVIDER_REJECTION_FORBIDDEN')) as attempt:
            result = runner.dispatch_once(lambda: provider, BASE, apply=True)
        self.assertEqual(result['provider_writes'], 'UNKNOWN')
        self.assertEqual(result['status'], 'POST_WRITE_UNCERTAIN_MANUAL_RECONCILIATION')
        attempt.assert_called_once()

    def test_malformed_enrollment_labels_fail_with_sanitized_post_write_error(self):
        provider = RecordingProvider()
        provider.post_readback_change = lambda p: p.update(labels=[{'name': []}])
        with self.assertRaisesRegex(gm.Denied, '^AUTO_MERGE_'):
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(provider.mutations, 1)

    def test_readonly_observation_still_has_no_native_request(self):
        provider = RecordingProvider()
        result = gm.run(provider, number=PR, expected_main=BASE, apply=False)
        self.assertEqual(result['provider_writes'], 0)
        self.assertIsNone(provider.native_variables)

    def test_new_native_query_cannot_be_used_as_a_read_query(self):
        client = gm.GitHub('a' * 32)
        with patch.object(client, '_request') as request:
            with self.assertRaises(gm.Denied):
                client.graphql(gm.THREADS_QUERY, {'id': NODE, 'expected_head': HEAD})
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
