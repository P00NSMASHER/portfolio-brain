"""Unit fake-provider coverage; these tests do not establish live GitHub access."""
import base64
import copy
import hashlib
import json
import unittest
from unittest.mock import patch, Mock
from brain.core import BrainError
from brain.v9.github_observer import observe_repositories, _https_get, MAX_RESPONSE

REPO = 'P00NSMASHER/portfolio-brain'
SHA = 'a' * 40
NOW = '2026-10-18T08:00:00Z'
RAW = b'hello\n'
BLOB = hashlib.sha1(b'blob 6\0' + RAW).hexdigest()


class ObserverTests(unittest.TestCase):
    def responses(self):
        return [dict(full_name=REPO, default_branch='main', permissions={'pull': True, 'push': True}),
                dict(ref='refs/heads/main', object={'type': 'commit', 'sha': SHA}),
                dict(type='file', path='README.md', encoding='base64', size=6,
                     content=base64.b64encode(RAW).decode(), sha=BLOB),
                dict(ref='refs/heads/main', object={'type': 'commit', 'sha': SHA})]

    def run_fake(self, responses=None, requests=None):
        values = self.responses() if responses is None else responses
        if len(values) == 4:
            values = values[:2] + [dict(sha=SHA, tree={'sha': 'c' * 40}),
                dict(sha='c' * 40, truncated=False, tree=[dict(path='README.md',
                     type='blob', mode='100644', sha=BLOB)])] + values[2:]
        records = iter(values)
        calls = []
        def get(path, token):
            calls.append((path, token))
            response = next(records)
            return response if type(response) is bytes else json.dumps(response).encode()
        result = observe_repositories(requests or {REPO: ['README.md']}, token='test-only-token', now=NOW, transport=get)
        return result, calls

    def test_source_bound_sanitized_evidence(self):
        result, calls = self.run_fake()
        self.assertEqual(result['source_heads'], {REPO: SHA})
        self.assertIn('?ref=' + SHA, calls[4][0])
        self.assertFalse(result['write_authority'])
        self.assertEqual(result['evidence_kind'], 'INJECTED_TRANSPORT_OBSERVATION')
        self.assertNotIn('test-only-token', json.dumps(result))
        self.assertNotIn('content', result['repositories'][0]['files'][0])
        self.assertEqual(result['repositories'][0]['permissions_observed'], {'pull': True})

    def test_provider_lies_and_stale_sources_rejected(self):
        cases = [(0, 'full_name', REPO.lower()), (0, 'permissions', {'pull': 1}),
                 (1, 'object', {'type': 'blob', 'sha': SHA}),
                 (3, 'object', {'type': 'commit', 'sha': 'b' * 40}),
                 (2, 'type', 'symlink'), (2, 'type', 'submodule'),
                 (2, 'target', 'elsewhere'), (2, 'submodule_git_url', None),
                 (2, 'path', 'other'), (2, 'truncated', True),
                 (2, 'size', True), (2, 'size', 5), (2, 'sha', 'b' * 40),
                 (2, 'encoding', 'none'), (2, 'content', '%%%')]
        for index, key, value in cases:
            with self.subTest(key=key, value=value):
                responses = self.responses()
                responses[index][key] = value
                with self.assertRaises((BrainError, ValueError)):
                    self.run_fake(responses)

    def test_request_bounds_before_any_network(self):
        for request in ({REPO: ['../secret']}, {REPO: ['a\\b']}, {REPO: ['/a']},
                        {REPO: ['a//b']}, {REPO: ['a', 'a']}, {REPO: [[]]},
                        {REPO: ['x'] * 17}, {REPO: [], REPO.lower(): []},
                        {'https://evil.test/repo': []}, {}):
            fake = Mock()
            with self.subTest(request=request), self.assertRaises((BrainError, ValueError)):
                observe_repositories(request, token='test-token', now=NOW, transport=fake)
            fake.assert_not_called()
        for token in ('', 'bad\r\nheader', 'x' * 4097, None):
            fake = Mock()
            with self.assertRaises(BrainError):
                observe_repositories({REPO: []}, token=token, now=NOW, transport=fake)
            fake.assert_not_called()

    def test_bad_json_and_oversize(self):
        for value in (b'{"a":1,"a":2}', b'NaN', b'[]', b'\xff', b'x' * (MAX_RESPONSE + 1)):
            with self.subTest(value=value[:20]), self.assertRaises((BrainError, ValueError)):
                self.run_fake([value])

    def test_real_transport_structure_no_redirect_and_bounded(self):
        with patch('brain.v9.github_observer.http.client.HTTPSConnection') as connection:
            instance = connection.return_value
            response = instance.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'identity'
            response.read1.side_effect = [b'{}', b'']
            self.assertEqual(_https_get('/repos/test/test', 'secret'), b'{}')
            self.assertEqual(connection.call_args.args, ('api.github.com',))
            self.assertGreater(connection.call_args.kwargs['timeout'], 0)
            self.assertLessEqual(connection.call_args.kwargs['timeout'], 15)
            self.assertEqual(instance.request.call_args.args, ('GET', '/repos/test/test'))
            self.assertEqual(response.read1.call_count, 2)
            instance.close.assert_called_once()
            for code in (301, 302, 401, 403, 404, 429, 500):
                response.status = code
                with self.assertRaises(BrainError):
                    _https_get('/repos/test/test', 'secret')
            response.status = 200
            response.read1.side_effect = [b'x' * (MAX_RESPONSE + 1)]
            with self.assertRaises(BrainError):
                _https_get('/repos/test/test', 'secret')

    def test_dereferenced_symlink_and_incomplete_tree_rejected(self):
        for mode, truncated in [('120000', False), ('160000', False), ('100644', True)]:
            responses = self.responses()
            responses = responses[:2] + [dict(sha=SHA, tree={'sha': 'c' * 40}),
                dict(sha='c' * 40, truncated=truncated, tree=[dict(path='README.md',
                     type='blob', mode=mode, sha=BLOB)])] + responses[2:]
            with self.assertRaises(BrainError):
                self.run_fake(responses)

    def test_deadlines_refuse_late_responses(self):
        with patch('brain.v9.github_observer.time.monotonic', side_effect=[0, 0, 61]):
            with self.assertRaises(ValueError):
                self.run_fake()
        with patch('brain.v9.github_observer.http.client.HTTPSConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'identity'
            response.read1.return_value = b'{}'
            with patch('brain.v9.github_observer.time.monotonic', side_effect=[0, 0, 0, 0, 16]):
                with self.assertRaises(BrainError):
                    _https_get('/repos/test/test', 'secret')
            connection.return_value.close.assert_called_once()

    def test_transport_errors_do_not_echo_secret(self):
        with patch('brain.v9.github_observer.http.client.HTTPSConnection') as connection:
            connection.return_value.request.side_effect = OSError('secret token')
            with self.assertRaisesRegex(ValueError, '^V9_GITHUB_TRANSPORT_FAILED$'):
                _https_get('/repos/test/test', 'secret token')
            connection.return_value.close.assert_called_once()
