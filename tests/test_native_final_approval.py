"""Synthetic original-provider shapes; never live merge/permission evidence."""
import copy
import hashlib
import importlib
import json
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

REPO = 'P00NSMASHER/portfolio-brain'
NOW = datetime(2026, 10, 20, 22, 50, tzinfo=timezone.utc)
SOURCE = 'a' * 40
POLICY = 'b' * 40
HEAD = 'c' * 40


def ticket():
    return dict(repository=REPO, repository_id=1387747549,
                pr_number=731, pr_node_id='PR_kwDOUrdY3c8test731',
                head_ref='canary/native-731', head_sha=HEAD,
                base_ref='main', base_sha=SOURCE,
                controller_source_sha=SOURCE, policy_sha=POLICY,
                approval_check_id=101, issued_at='2026-10-20T22:45:00Z',
                expires_at='2026-10-20T22:55:00Z')


def fingerprint(t):
    # Independent test oracle, not a call to the implementation helper.
    body = {k: v for k, v in t.items() if k != 'approval_check_id'}
    raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    return 'native-admission-v1:' + hashlib.sha256(raw).hexdigest()


class Provider:
    def __init__(self):
        t = ticket()
        repo = dict(id=1387747549, full_name=REPO)
        self.pr = dict(number=731, node_id=t['pr_node_id'], state='open',
                       draft=False, merged=False, mergeable=True,
                       mergeable_state='blocked', labels=[dict(name='brain:guarded-automerge')],
                       head=dict(sha=HEAD, ref=t['head_ref'], repo=repo),
                       base=dict(sha=SOURCE, ref='main', repo=repo),
                       auto_merge=dict(merge_method='squash'))
        self.main = dict(name='main', protected=True, commit=dict(sha=SOURCE))
        self.approval = dict(id=101, name='portfolio-native-admission', head_sha=HEAD,
                             app=dict(id=5121826), status='completed', conclusion='success',
                             external_id=fingerprint(t),
                             url=f'https://api.github.com/repos/{REPO}/check-runs/101',
                             started_at='2026-10-20T22:46:00Z', completed_at='2026-10-20T22:47:00Z')
        self.checks = dict(total_count=2, check_runs=[
            dict(id=102, name='validate', head_sha=HEAD, app=dict(id=15368),
                 status='completed', conclusion='success'), copy.deepcopy(self.approval)])
        self.calls = []
        self.mutate_on = None

    def __call__(self, path):
        self.calls.append(path)
        if self.mutate_on:
            self.mutate_on(self, len(self.calls))
        allowed = {'/pulls/731': self.pr, '/branches/main': self.main,
                   '/check-runs/101': self.approval,
                   f'/commits/{HEAD}/check-runs?per_page=100': self.checks}
        if path not in allowed:
            raise AssertionError('Unexpected provider endpoint')
        return copy.deepcopy(allowed[path])


class FinalApprovalTests(unittest.TestCase):
    def check(self, provider=None, admission=None, now=NOW):
        try:
            mod = importlib.import_module('verification.native_final_approval')
        except ImportError:
            mod = None
        self.assertIsNotNone(mod, 'Final-approval read-only verifier is not implemented')
        result = mod.verify_final_approval(
            provider or Provider(), ticket() if admission is None else admission,
            expected_source_sha=SOURCE, expected_policy_sha=POLICY, now=now)
        self.assertEqual(result.provider_writes, 0)
        self.assertFalse(result.merge_authorized)
        self.assertFalse(result.protected_check_issued)
        return result

    def hold(self, provider=None, admission=None, now=NOW):
        result = self.check(provider, admission, now)
        self.assertEqual(result.status, 'HOLD')
        return result

    def test_exact_separate_app_approval_matches_but_is_not_enforcement(self):
        p = Provider()
        r = self.check(p)
        self.assertEqual(r.status, 'APPROVAL_MATCHED_NOT_ENFORCEMENT')
        self.assertEqual(r.head_sha, HEAD)
        self.assertEqual(len(p.calls), 7)

    def test_plain_green_foundation_is_not_native_approval(self):
        p = Provider(); p.approval['name'] = 'portfolio-phase1-gate'
        self.hold(p)

    def test_candidate_cannot_supply_self_asserted_approval(self):
        t = ticket(); t['approved'] = True
        p = Provider(); self.hold(p, t); self.assertEqual(p.calls, [])

    def test_missing_or_extra_ticket_fields_fail_before_reads(self):
        for field in ticket():
            with self.subTest(field=field):
                t = ticket(); del t[field]
                p = Provider(); self.hold(p, t); self.assertEqual(p.calls, [])

    def test_ticket_scalars_are_strict(self):
        for key, value in [('pr_number', True), ('repository_id', True),
                           ('approval_check_id', True), ('head_sha', []),
                           ('pr_node_id', 'https://other.invalid'),
                           ('head_ref', '../main'), ('head_ref', 'main')]:
            with self.subTest(key=key, value=value):
                t = ticket(); t[key] = value; p = Provider()
                self.hold(p, t); self.assertEqual(p.calls, [])

    def test_foreign_repository_source_and_policy_rejected(self):
        for key, value in [('repository', 'other/repo'), ('repository_id', 1),
                           ('controller_source_sha', 'd'*40), ('policy_sha', 'd'*40),
                           ('base_sha', 'd'*40), ('base_ref', 'other')]:
            with self.subTest(key=key):
                t = ticket(); t[key] = value; self.hold(admission=t)

    def test_expired_future_naive_and_overlong_authorization_rejected(self):
        for key, value in [('expires_at', '2026-10-20T22:50:00Z'),
                           ('issued_at', '2026-10-20T22:51:00Z'),
                           ('expires_at', '2026-10-20T23:55:00Z'),
                           ('issued_at', '2026-10-20T22:45:00')]:
            with self.subTest(key=key, value=value):
                t = ticket(); t[key] = value; self.hold(admission=t)
        self.hold(now=NOW.replace(tzinfo=None))

    def test_wrong_head_cannot_inherit_enrollment_or_approval(self):
        p = Provider(); p.pr['head']['sha'] = 'd'*40; self.hold(p)

    def test_foreign_same_named_repository_cannot_match(self):
        for side in ['head', 'base']:
            p = Provider(); p.pr[side]['repo'] = dict(id=99, full_name=REPO)
            self.hold(p)

    def test_pr_node_number_branch_and_base_must_match(self):
        for mutate in [lambda p: p.pr.update(number=732),
                       lambda p: p.pr.update(node_id='PR_other'),
                       lambda p: p.pr['head'].update(ref='other'),
                       lambda p: p.pr['base'].update(ref='unprotected'),
                       lambda p: p.pr['base'].update(sha='d'*40)]:
            p = Provider(); mutate(p); self.hold(p)

    def test_removed_label_and_unknown_or_foreign_enrollment_block(self):
        for mutate in [lambda p: p.pr.update(labels=[]),
                       lambda p: p.pr.update(auto_merge=None),
                       lambda p: p.pr.update(auto_merge={'merge_method': 'merge'}),
                       lambda p: p.pr.update(draft=True),
                       lambda p: p.pr.update(state='closed'),
                       lambda p: p.pr.update(mergeable_state='behind')]:
            p = Provider(); mutate(p); self.hold(p)

    def test_issuer_and_original_check_identity_are_mandatory(self):
        for key, value in [('app', {'id': 15368}), ('app', {'id': True}),
                           ('id', 999), ('url', 'https://other.invalid/101'),
                           ('head_sha', 'd'*40), ('external_id', 'self-approved')]:
            with self.subTest(key=key):
                p = Provider(); p.approval[key] = value; self.hold(p)

    def test_failed_pending_skipped_and_future_approval_never_match(self):
        for key, value in [('conclusion', 'failure'), ('conclusion', 'skipped'),
                           ('status', 'in_progress'),
                           ('completed_at', '2026-10-20T22:51:00Z'),
                           ('started_at', '2026-10-20T22:44:00Z')]:
            p = Provider(); p.approval[key] = value; self.hold(p)

    def test_self_rehashing_different_pr_binding_cannot_forge_app_approval(self):
        t = ticket(); t['head_ref'] = 'canary/replacement'
        p = Provider(); p.pr['head']['ref'] = t['head_ref']
        self.hold(p, t)

    def test_full_check_census_is_required(self):
        for mutate in [lambda p: p.checks.update(total_count=100),
                       lambda p: p.checks.update(total_count=True),
                       lambda p: p.checks['check_runs'].append(None),
                       lambda p: p.checks['check_runs'][0].update(id=101)]:
            p = Provider(); mutate(p); self.hold(p)

    def test_foundation_wrong_issuer_head_and_non_success_block(self):
        for key, value in [('app', {'id': 5121826}), ('head_sha', 'd'*40),
                           ('status', 'queued'), ('conclusion', 'neutral')]:
            p = Provider(); p.checks['check_runs'][0][key] = value; self.hold(p)

    def test_approval_missing_from_exact_head_census_blocks(self):
        p = Provider(); p.checks['check_runs'].pop(); p.checks['total_count'] = 1
        self.hold(p)

    def test_main_or_protection_drift_at_final_read_blocks(self):
        for change in [lambda p: p.main['commit'].update(sha='d'*40),
                       lambda p: p.main.update(protected=False)]:
            p = Provider(); p.mutate_on = lambda obj, n: change(obj) if n == 5 else None
            self.hold(p)

    def test_head_drift_at_final_read_blocks(self):
        p = Provider()
        p.mutate_on = lambda obj, n: obj.pr['head'].update(sha='d'*40) if n == 6 else None
        self.hold(p)

    def test_final_approval_revocation_blocks(self):
        p = Provider()
        p.mutate_on = lambda obj, n: obj.approval.update(conclusion='failure') if n == 7 else None
        self.hold(p)

    def test_provider_error_is_sanitized_and_not_retried(self):
        calls = []
        def broken(path):
            calls.append(path); raise RuntimeError('secret-token-do-not-echo')
        result = self.hold(broken)
        self.assertNotIn('secret', repr(result))
        self.assertEqual(len(calls), 1)

    def test_callback_cannot_replace_caller_ticket_mid_observation(self):
        t = ticket(); p = Provider()
        def substitute(obj, n):
            if n == 1:
                t['head_ref'] = 'canary/replacement'
                obj.pr['head']['ref'] = t['head_ref']
                obj.approval['external_id'] = fingerprint(t)
                obj.checks['check_runs'][1]['external_id'] = fingerprint(t)
        p.mutate_on = substitute
        self.hold(p, t)

    def test_slow_provider_cannot_outlive_observation_deadline(self):
        p = Provider()
        with patch('verification.native_final_approval.time.monotonic', side_effect=[0, 0, 31]):
            r = self.hold(p)
        self.assertEqual(r.reason, 'OBSERVATION_DEADLINE')
        self.assertEqual(len(p.calls), 1)

    def test_ticket_expiring_during_provider_read_cannot_match(self):
        p = Provider()
        close_to_expiry = datetime(2026, 10, 20, 22, 54, 59, tzinfo=timezone.utc)
        with patch('verification.native_final_approval.time.monotonic', side_effect=[0, 0, 2]):
            self.hold(p, now=close_to_expiry)
        self.assertEqual(len(p.calls), 1)

    def test_inputs_are_not_mutated_and_fingerprint_is_deterministic(self):
        p = Provider(); t = ticket(); original = copy.deepcopy(t)
        self.check(p, t); self.assertEqual(t, original)
        mod = importlib.import_module('verification.native_final_approval')
        self.assertEqual(mod.approval_fingerprint(t), fingerprint(t))


if __name__ == '__main__':
    unittest.main()
