"""Adversarial tests for the bounded, read-only GitHub App canary."""
import hashlib
from pathlib import Path
import unittest

from brain.v8.runtime_probe import (
    APP_SLUG, INSTALLATION_ID, NoRedirect, REPOSITORIES, probe,
)

_SHA = 'a' * 40
_REPO = 'P00NSMASHER/portfolio-brain'


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        self.inventory = {
            'total_count': 1, 'repositories': [{'full_name': _REPO}],
        }
        self.source = _SHA
        self.default_branch = 'main'

    def get(self, path):
        self.paths.append(path)
        if path == '/installation/repositories?per_page=100':
            return self.inventory
        if path == '/repos/' + _REPO:
            return {
                'full_name': _REPO, 'archived': False,
                'default_branch': self.default_branch,
            }
        if path.startswith('/repos/' + _REPO + '/branches/'):
            return {'commit': {'sha': self.source}}
        if path.endswith('/actions/runs?per_page=1'):
            return {'total_count': 0, 'workflow_runs': []}
        if path.endswith('/check-runs?per_page=1'):
            return {'total_count': 0, 'check_runs': []}
        if path.endswith('/status'):
            return {'sha': self.source, 'state': 'pending', 'statuses': []}
        if path.endswith('/pulls?state=open&per_page=1'):
            return []
        raise AssertionError('UNEXPECTED_NETWORK_PATH')

    def run_probe(self, **changes):
        kwargs = dict(
            get=self.get, repository='portfolio-brain',
            installation_id=INSTALLATION_ID, app_slug=APP_SLUG,
        )
        kwargs.update(changes)
        return probe(**kwargs)

    def test_read_success_binds_source_and_never_grants_write_or_acceptance(self):
        result = self.run_probe()
        self.assertEqual(result['result'], 'AUTHENTICATED_READ_CANARY_PASSED')
        self.assertEqual(result['source_sha'], _SHA)
        self.assertEqual(result['token_repository_count'], 1)
        self.assertEqual(len(self.paths), 7)
        self.assertFalse(result['provider_write_actions_verified'])
        self.assertFalse(result['release_authority_verified'])
        self.assertFalse(result['acceptance_started'])
        self.assertTrue(all(path.startswith('/repos/' + _REPO)
                            or path.startswith('/installation/') for path in self.paths))

    def test_unknown_target_denied_before_network(self):
        for repo in ('unreviewed-repo', '../portfolio-brain', None, True):
            with self.subTest(repo=repo), self.assertRaisesRegex(
                    ValueError, 'NOT_REVIEWED'):
                self.run_probe(repository=repo)
        self.assertEqual(self.paths, [])

    def test_wrong_app_identity_denied_before_network(self):
        for changes in (
            {'installation_id': '166155679'},
            {'app_slug': 'independent-verifier'},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    ValueError, 'IDENTITY_MISMATCH'):
                self.run_probe(**changes)
        self.assertEqual(self.paths, [])

    def test_broad_or_forged_inventory_denied_before_project_reads(self):
        variants = (
            {'total_count': 2, 'repositories': [{'full_name': _REPO}]},
            {'total_count': True, 'repositories': [{'full_name': _REPO}]},
            {'total_count': 1, 'repositories': [{'full_name': 'P00NSMASHER/capturebrief'}]},
            {'total_count': 1, 'repositories': ['not-a-repo']},
            {'total_count': 1, 'repositories': []},
            {'total_count': 1, 'repositories': [{'full_name': _REPO}, {'full_name': _REPO}]},
            {'message': 'fake 200'},
            [],
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.inventory = variant
                self.paths.clear()
                with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
                    self.run_probe()
                self.assertEqual(len(self.paths), 1)

    def test_untrusted_branch_name_rejected_before_source_read(self):
        for name in ('../main', 'main?x=y', 'main#fragment', '', 'weird\nheader', 'bad.lock'):
            with self.subTest(branch=name):
                self.default_branch = name
                self.paths.clear()
                with self.assertRaisesRegex(ValueError, 'BRANCH_INVALID'):
                    self.run_probe()
                self.assertEqual(len(self.paths), 2)

    def test_malformed_sha_or_branch_body_cannot_be_verified(self):
        for sha in ('../untrusted', '', True, None, 'z' * 40):
            self.source = sha
            self.paths.clear()
            with self.subTest(sha=sha), self.assertRaisesRegex(
                    ValueError, 'SOURCE_INVALID'):
                self.run_probe()
            self.assertEqual(len(self.paths), 3)

    def test_successful_http_responses_with_invalid_endpoint_bodies_fail_closed(self):
        invalid = (
            ('/actions/runs?', {'message': 'not actually authenticated'}, 'ACTIONS_RESPONSE_INVALID'),
            ('/actions/runs?', {'total_count': True, 'workflow_runs': []}, 'ACTIONS_RESPONSE_INVALID'),
            ('/actions/runs?', {'total_count': 0, 'workflow_runs': [{}]}, 'ACTIONS_RESPONSE_INVALID'),
            ('/check-runs?', {'total_count': 1, 'check_runs': ['invalid']}, 'CHECKS_RESPONSE_INVALID'),
            ('/check-runs?', {'total_count': -1, 'check_runs': []}, 'CHECKS_RESPONSE_INVALID'),
            ('/status', {'sha': _SHA, 'state': 'success', 'statuses': 'fake'}, 'STATUS_RESPONSE_INVALID'),
            ('/status', {'sha': 'b' * 40, 'state': 'success', 'statuses': []}, 'STATUS_RESPONSE_INVALID'),
            ('/status', {'sha': _SHA, 'state': 'unexpected', 'statuses': []}, 'STATUS_RESPONSE_INVALID'),
            ('/pulls?', {'message': 'fake 200'}, 'PULLS_RESPONSE_INVALID'),
            ('/pulls?', ['not-a-pr'], 'PULLS_RESPONSE_INVALID'),
        )
        for path_marker, bad, error in invalid:
            with self.subTest(marker=path_marker, bad=bad):
                def get(path):
                    return bad if path_marker in path else self.get(path)
                with self.assertRaisesRegex(ValueError, error):
                    self.run_probe(get=get)

    def test_provider_failure_is_not_success(self):
        def failing_get(path):
            if '/check-runs' in path:
                raise OSError('permission denied')
            return self.get(path)
        with self.assertRaises(OSError):
            self.run_probe(get=failing_get)

    def test_redirect_never_forwards_authorization(self):
        with self.assertRaisesRegex(ValueError, 'REDIRECT_REJECTED'):
            NoRedirect().redirect_request(None, None, 302, '', {},
                                          'https://other.example')

    def test_workflow_is_manual_main_only_and_uses_exact_isolated_probe(self):
        workflow = Path('.github/workflows/v8-runtime-preflight.yml').read_text()
        source = Path('brain/v8/runtime_probe.py').read_bytes()
        git_blob = hashlib.sha1(
            b'blob ' + str(len(source)).encode() + b'\x00' + source,
        ).hexdigest()
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn(': write', workflow)
        self.assertNotIn('PORTFOLIO_VERIFIER_PRIVATE_KEY', workflow)
        self.assertIn('skip-token-revoke: false', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn('git hash-object brain/v8/runtime_probe.py', workflow)
        self.assertIn(git_blob, workflow)
        self.assertIn('install -m 0500', workflow)
        self.assertIn('python -I "$RUNNER_TEMP/v8-runtime-probe.py"', workflow)
        self.assertNotIn('python -m brain.v8.runtime_probe', workflow)
        self.assertNotIn('from brain', source.decode())
        matrix = next(line for line in workflow.splitlines()
                      if 'repository: [' in line).split('[', 1)[1].split(']', 1)[0]
        self.assertEqual(set(matrix.split(', ')), REPOSITORIES)
