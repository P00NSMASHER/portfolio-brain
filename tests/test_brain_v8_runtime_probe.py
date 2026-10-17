import unittest
from pathlib import Path
from brain.v8.runtime_probe import APP_SLUG, INSTALLATION_ID, NoRedirect, probe


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        self.inventory = {'total_count': 1, 'repositories': [
            {'full_name': 'P00NSMASHER/portfolio-brain'}]}

    def get(self, path):
        self.paths.append(path)
        if path.startswith('/installation/'):
            return self.inventory
        if path == '/repos/P00NSMASHER/portfolio-brain':
            return {'full_name': 'P00NSMASHER/portfolio-brain',
                    'archived': False, 'default_branch': 'main'}
        if '/branches/' in path:
            return {'commit': {'sha': 'a' * 40}}
        return {}

    def run_probe(self, **changes):
        args = dict(get=self.get, repository='portfolio-brain',
                    installation_id=INSTALLATION_ID, app_slug=APP_SLUG)
        args.update(changes)
        return probe(**args)

    def test_read_success_does_not_grant_write_or_acceptance(self):
        result = self.run_probe()
        self.assertEqual(len(self.paths), 7)
        self.assertFalse(result['provider_write_actions_verified'])
        self.assertFalse(result['release_authority_verified'])
        self.assertFalse(result['acceptance_started'])

    def test_unknown_repository_denied_before_network(self):
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            self.run_probe(repository='unreviewed-repo')
        self.assertEqual(self.paths, [])

    def test_wrong_installation_or_verifier_identity_denied(self):
        for changes in ({'installation_id': '166155679'}, {'app_slug': 'portfolio-brain-522'}):
            with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                self.run_probe(**changes)
        self.assertEqual(self.paths, [])

    def test_broad_token_denied_before_project_reads(self):
        self.inventory['total_count'] = 2
        with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
            self.run_probe()
        self.assertEqual(len(self.paths), 1)

    def test_wrong_repository_scope_denied(self):
        self.inventory['repositories'][0]['full_name'] = 'P00NSMASHER/capturebrief'
        with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
            self.run_probe()

    def test_provider_failure_is_not_success(self):
        def failing_get(path):
            if '/check-runs' in path:
                raise OSError('permission denied')
            return self.get(path)
        with self.assertRaises(OSError):
            self.run_probe(get=failing_get)

    def test_source_identity_invalid_is_not_success(self):
        def malformed_get(path):
            return {'commit': {'sha': '../untrusted'}} if '/branches/' in path else self.get(path)
        with self.assertRaisesRegex(ValueError, 'SOURCE_INVALID'):
            self.run_probe(get=malformed_get)

    def test_redirect_never_forwards_authorization(self):
        with self.assertRaisesRegex(ValueError, 'REDIRECT_REJECTED'):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')

    def test_workflow_has_manual_main_only_read_scopes(self):
        workflow = Path('.github/workflows/v8-runtime-preflight.yml').read_text()
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn(': write', workflow)
        self.assertNotIn('PORTFOLIO_VERIFIER_PRIVATE_KEY', workflow)
        self.assertIn('skip-token-revoke: false', workflow)
        self.assertIn('persist-credentials: false', workflow)

class RuntimeCredentialCanaryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = Path('.github/workflows/foundation-ci.yml').read_text()
        cls.canary = cls.workflow.split('  v8-runtime-credential-canary:', 1)[1]

    def test_manual_only_disabled_by_default_and_bound_to_reviewed_branch(self):
        self.assertIn('  workflow_dispatch:\n', self.workflow)
        self.assertNotIn('verify_v8_runtime:', self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.canary)
        self.assertIn("github.repository == 'P00NSMASHER/portfolio-brain'", self.canary)
        self.assertIn("github.ref == 'refs/heads/feature/v8-authority-map-20261016'", self.canary)
        self.assertIn('needs: validate', self.canary)
        self.assertNotIn('schedule:', self.canary)

    def test_exact_source_original_independent_checks_precede_credential(self):
        self.assertIn('pulls/710', self.canary)
        self.assertIn("quote(branch, safe='')", self.canary)
        self.assertIn('get("sha") == sha', self.canary)
        self.assertIn('get("total_count") == len(checks)', self.canary)
        self.assertIn('("validate", 15368)', self.canary)
        self.assertIn('("portfolio-phase1-gate", 5121826)', self.canary)
        self.assertIn('c.get("head_sha") == sha', self.canary)
        self.assertIn('c.get("conclusion") == "success"', self.canary)
        self.assertLess(self.canary.index('Require both original exact-head CI checks'),
                        self.canary.index('Mint scoped read-only GitHub App token'))

    def test_secret_never_enters_candidate_code_or_broad_write_scope(self):
        self.assertEqual(self.canary.count('secrets.PORTFOLIO_RUNTIME_PRIVATE_KEY'), 1)
        self.assertIn('git hash-object brain/v8/runtime_probe.py', self.canary)
        self.assertIn('c479f8c4f422a4e7de9bcb558127f8a2ab56378f', self.canary)
        self.assertIn('python -I "$RUNNER_TEMP/v8-runtime-probe.py"', self.canary)
        self.assertIn('persist-credentials: false', self.canary)
        self.assertIn('skip-token-revoke: false', self.canary)
        for name in ('contents', 'actions', 'checks', 'pull-requests', 'statuses'):
            self.assertIn('permission-' + name + ': read', self.canary)
        self.assertNotIn('permission-contents: write', self.canary)
        self.assertNotIn('PORTFOLIO_VERIFIER_PRIVATE_KEY', self.canary)
