"""Real on-disk crash/concurrency tests; provider approval remains synthetic."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from verification import native_final_approval as approval

SOURCE, POLICY, HEAD = 'a' * 40, 'b' * 40, 'c' * 40
STORE_ID = 'e' * 64
EVIDENCE = 'f' * 64
NOW = datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc)


def ticket():
    return dict(repository=approval.REPOSITORY, repository_id=approval.REPOSITORY_ID,
                pr_number=735, pr_node_id='PR_kwDOUrdY3c8test735',
                head_ref='canary/intent-735', head_sha=HEAD,
                base_ref='main', base_sha=SOURCE, controller_source_sha=SOURCE,
                policy_sha=POLICY, approval_check_id=101,
                issued_at='2026-10-21T02:25:00Z', expires_at='2026-10-21T02:35:00Z')


def context():
    return dict(expected_source_sha=SOURCE, expected_policy_sha=POLICY, now=NOW)


class Provider:
    def __init__(self):
        t = ticket(); repo = dict(id=approval.REPOSITORY_ID, full_name=approval.REPOSITORY)
        self.pr = dict(number=735, node_id=t['pr_node_id'], state='open', draft=False,
                       merged=False, mergeable=True, mergeable_state='blocked',
                       labels=[dict(name=approval.LABEL)],
                       head=dict(sha=HEAD, ref=t['head_ref'], repo=repo),
                       base=dict(sha=SOURCE, ref='main', repo=repo),
                       auto_merge=dict(merge_method='squash'))
        self.main = dict(name='main', protected=True, commit=dict(sha=SOURCE))
        self.check = dict(id=101, name=approval.APPROVAL_NAME, head_sha=HEAD,
                          app=dict(id=approval.APP_ID), status='completed', conclusion='success',
                          external_id=approval.approval_fingerprint(t),
                          url=f'https://api.github.com/repos/{approval.REPOSITORY}/check-runs/101',
                          started_at='2026-10-21T02:26:00Z', completed_at='2026-10-21T02:27:00Z')
        self.checks = dict(total_count=2, check_runs=[copy.deepcopy(self.check),
            dict(id=102, name='validate', head_sha=HEAD, app=dict(id=15368),
                 status='completed', conclusion='success')])
        self.calls = []; self.on_read = None

    def __call__(self, path):
        self.calls.append(path)
        if self.on_read: self.on_read(len(self.calls))
        return copy.deepcopy({'/branches/main': self.main, '/pulls/735': self.pr,
                             '/check-runs/101': self.check,
                             f'/commits/{HEAD}/check-runs?per_page=100': self.checks}[path])


def _competing_claim(path, digest, start, results):
    from verification.native_intent_store import IntentStore, StoreDenied
    start.wait(10)
    try:
        with IntentStore(path, expected_store_id=STORE_ID) as store:
            store.claim(735, digest, **context())
        results.put('CLAIMED')
    except StoreDenied:
        results.put('HELD')


class IntentStoreTests(unittest.TestCase):
    def setUp(self):
        try:
            self.mod = importlib.import_module('verification.native_intent_store')
        except ImportError:
            self.mod = None
        self.assertIsNotNone(self.mod, 'Durable native intent store is not implemented')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'intents.sqlite3'
        self.store = self.mod.IntentStore.create(self.path, store_id=STORE_ID)
        self.addCleanup(self.store.close)

    def prepare(self):
        return self.store.prepare(ticket(), **context())

    def enroll(self):
        item = self.prepare()
        self.store.claim(735, item.digest, **context())
        return self.store.record_result(735, item.digest, 'ENROLLED', EVIDENCE)

    def gate(self, provider=None, **overrides):
        settings = context(); settings.update(overrides)
        r = self.mod.verify_recorded_approval(provider or Provider(), self.store,
                                             pr_number=735, **settings)
        self.assertEqual(r.provider_writes, 0)
        self.assertFalse(r.merge_authorized)
        self.assertFalse(r.protected_check_issued)
        return r

    def test_missing_database_is_not_silently_recreated(self):
        missing = self.path.with_name('missing.sqlite3')
        with self.assertRaises(self.mod.StoreDenied):
            self.mod.IntentStore(missing, expected_store_id=STORE_ID)
        self.assertFalse(missing.exists())

    def test_prepare_persists_identical_bytes_across_reopen(self):
        before = self.prepare(); self.store.close()
        with self.mod.IntentStore(self.path, expected_store_id=STORE_ID) as reopened:
            after = reopened.load(735)
        self.assertEqual(before, after); self.assertEqual(after.ticket, ticket())
        self.assertEqual(after.state, 'PREPARED')

    def test_duplicate_prepare_is_idempotent_and_not_new_authority(self):
        first = self.prepare(); second = self.prepare()
        self.assertEqual(first, second)
        self.assertEqual(self.store.event_count(), 1)

    def test_different_ticket_same_pr_cannot_replace_original(self):
        original = self.prepare()
        for field, value in [('head_sha', 'd'*40), ('approval_check_id', 102),
                             ('head_ref', 'canary/replacement')]:
            altered = ticket(); altered[field] = value
            with self.assertRaises(self.mod.StoreDenied):
                self.store.prepare(altered, **context())
        self.assertEqual(self.store.load(735), original)

    def test_claim_is_committed_before_external_action_and_never_repeated(self):
        item = self.prepare(); self.store.claim(735, item.digest, **context())
        self.store.close()
        with self.mod.IntentStore(self.path, expected_store_id=STORE_ID) as reopened:
            self.assertEqual(reopened.load(735).state, 'ATTEMPTED')
            with self.assertRaises(self.mod.StoreDenied):
                reopened.claim(735, item.digest, **context())

    def test_two_processes_cannot_claim_same_request(self):
        item = self.prepare()
        ctx = multiprocessing.get_context('spawn'); start = ctx.Event(); out = ctx.Queue()
        ps = [ctx.Process(target=_competing_claim, args=(str(self.path), item.digest, start, out))
              for _ in range(2)]
        for p in ps: p.start()
        start.set()
        for p in ps:
            p.join(12)
            if p.is_alive(): p.terminate(); p.join(); self.fail('claim worker hung')
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(sorted([out.get(timeout=2), out.get(timeout=2)]), ['CLAIMED', 'HELD'])
        out.close(); self.assertEqual(self.store.event_count(), 2)

    def test_unknown_result_blocks_retry_even_after_restart(self):
        item = self.prepare(); self.store.claim(735, item.digest, **context())
        self.store.record_result(735, item.digest, 'UNKNOWN', EVIDENCE)
        self.store.close()
        with self.mod.IntentStore(self.path, expected_store_id=STORE_ID) as s:
            with self.assertRaises(self.mod.StoreDenied): s.claim(735, item.digest, **context())
            self.assertEqual(s.load(735).state, 'UNKNOWN')

    def test_unknown_can_be_reconciled_without_another_claim(self):
        item = self.prepare(); self.store.claim(735, item.digest, **context())
        self.store.record_result(735, item.digest, 'UNKNOWN', EVIDENCE)
        r = self.store.record_result(735, item.digest, 'ENROLLED', '1'*64)
        self.assertEqual(r.state, 'ENROLLED'); self.assertEqual(self.store.event_count(), 4)

    def test_observation_requires_prior_attempt(self):
        item = self.prepare()
        with self.assertRaises(self.mod.StoreDenied):
            self.store.record_result(735, item.digest, 'ENROLLED', EVIDENCE)
        self.assertEqual(self.store.load(735).state, 'PREPARED')

    def test_duplicate_result_is_idempotent_conflicting_result_is_not(self):
        item = self.enroll()
        self.assertEqual(item, self.store.record_result(735, item.digest, 'ENROLLED', EVIDENCE))
        with self.assertRaises(self.mod.StoreDenied):
            self.store.record_result(735, item.digest, 'DENIED', EVIDENCE)

    def test_revocation_is_sticky_after_restart_and_cannot_rearm(self):
        item = self.enroll(); self.store.revoke(735, item.digest, 'HEAD_CHANGED')
        self.store.close()
        with self.mod.IntentStore(self.path, expected_store_id=STORE_ID) as s:
            self.assertEqual(s.load(735).state, 'REVOKED')
            with self.assertRaises(self.mod.StoreDenied): s.claim(735, item.digest, **context())
            with self.assertRaises(self.mod.StoreDenied):
                s.record_result(735, item.digest, 'ENROLLED', EVIDENCE)

    def test_source_policy_and_expiry_rechecked_before_claim(self):
        item = self.prepare()
        for settings in [dict(expected_source_sha='d'*40), dict(expected_policy_sha='d'*40),
                         dict(now=NOW+timedelta(minutes=5))]:
            args = context(); args.update(settings)
            with self.assertRaises(self.mod.StoreDenied): self.store.claim(735, item.digest, **args)
        self.assertEqual(self.store.load(735).state, 'PREPARED')

    def test_ticket_and_returned_copy_cannot_mutate_store(self):
        t = ticket(); item = self.store.prepare(t, **context())
        t['head_sha'] = 'd'*40; item.ticket['head_sha'] = 'd'*40
        self.assertEqual(self.store.load(735).ticket['head_sha'], HEAD)

    @unittest.skipUnless(os.name == 'posix', 'POSIX-specific filesystem operation')
    def test_wrong_store_id_and_untrusted_file_rejected(self):
        with self.assertRaises(self.mod.StoreDenied):
            self.mod.IntentStore(self.path, expected_store_id='1'*64)
        os.chmod(self.path, 0o644)
        with self.assertRaises(self.mod.StoreDenied): self.store.load(735)
        os.chmod(self.path, 0o600)

    @unittest.skipUnless(os.name == 'posix', 'POSIX-specific filesystem operation')
    def test_symlink_and_hardlink_rejected(self):
        link = self.path.with_name('link.sqlite3'); link.symlink_to(self.path)
        with self.assertRaises(self.mod.StoreDenied):
            self.mod.IntentStore(link, expected_store_id=STORE_ID)
        link.unlink(); os.link(self.path, link)
        try:
            with self.assertRaises(self.mod.StoreDenied): self.store.load(735)
        finally: link.unlink()

    def test_foreign_database_and_existing_store_are_not_overwritten(self):
        before = self.path.read_bytes()
        with self.assertRaises(self.mod.StoreDenied):
            self.mod.IntentStore.create(self.path, store_id=STORE_ID)
        self.assertEqual(before, self.path.read_bytes())
        other = self.path.with_name('foreign.db')
        with sqlite3.connect(other) as db: db.execute('CREATE TABLE foreign_data(x)')
        os.chmod(other, 0o600)
        with self.assertRaises(self.mod.StoreDenied):
            self.mod.IntentStore(other, expected_store_id=STORE_ID)

    def test_missing_record_holds_without_any_provider_read(self):
        p = Provider(); r = self.gate(p)
        self.assertEqual(r.status, 'HOLD'); self.assertEqual(p.calls, [])

    def test_prepared_attempted_unknown_and_denied_records_do_not_pass_gate(self):
        item = self.prepare()
        self.assertEqual(self.gate().status, 'HOLD')
        self.store.claim(735, item.digest, **context())
        self.assertEqual(self.gate().status, 'HOLD')
        self.store.record_result(735, item.digest, 'UNKNOWN', EVIDENCE)
        self.assertEqual(self.gate().status, 'HOLD')
        self.store.record_result(735, item.digest, 'DENIED', '1'*64)
        self.assertEqual(self.gate().status, 'HOLD')

    def test_persisted_intent_and_independent_provider_match_is_read_only(self):
        self.enroll(); p = Provider(); r = self.gate(p)
        self.assertEqual(r.status, 'APPROVAL_MATCHED_NOT_ENFORCEMENT')
        self.assertEqual(len(p.calls), 7)

    def test_locally_asserted_enrollment_does_not_forge_approval(self):
        self.enroll(); p = Provider(); p.check['app']['id'] = 15368
        self.assertEqual(self.gate(p).status, 'HOLD')

    def test_later_head_and_label_change_retain_intent_and_block(self):
        before = self.enroll()
        for change in [lambda p: p.pr['head'].update(sha='d'*40),
                       lambda p: p.pr.update(labels=[]),
                       lambda p: p.pr['base'].update(ref='other')]:
            p = Provider(); change(p)
            self.assertEqual(self.gate(p).status, 'HOLD')
            self.assertEqual(self.store.load(735), before)

    def test_revocation_during_provider_reads_blocks_positive_result(self):
        item = self.enroll(); p = Provider()
        def revoke(n):
            if n == 7:
                with self.mod.IntentStore(self.path, expected_store_id=STORE_ID) as other:
                    other.revoke(735, item.digest, 'OWNER_REVOKED')
        p.on_read = revoke
        r = self.gate(p)
        self.assertEqual(r.status, 'HOLD'); self.assertEqual(r.reason, 'INTENT_CHANGED_DURING_VERIFICATION')

    @unittest.skipUnless(os.name == 'posix', 'POSIX-specific filesystem operation')
    def test_lost_store_after_enrollment_is_hold_not_generic_success(self):
        self.enroll(); self.path.unlink(); p = Provider()
        self.assertEqual(self.gate(p).status, 'HOLD'); self.assertEqual(p.calls, [])
        self.assertFalse(self.path.exists())

    def test_sql_update_delete_and_malformed_evidence_are_rejected(self):
        item = self.enroll()
        with sqlite3.connect(self.path) as db:
            for sql in ['DELETE FROM events', 'UPDATE intents SET body="{}"']:
                with self.assertRaises(sqlite3.DatabaseError): db.execute(sql)
        with self.assertRaises(self.mod.StoreDenied): self.store.revoke(735, item.digest, 'token=secret')

    def test_tampered_chain_or_schema_cannot_be_read_as_approval(self):
        self.enroll()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER events_no_update')
            db.execute("UPDATE events SET chain_hash=? WHERE seq=2", ('0'*64,))
        self.assertEqual(self.gate().status, 'HOLD')

    @unittest.skipUnless(os.name == 'posix', 'POSIX-specific filesystem operation')
    def test_oversized_or_replaced_database_is_rejected(self):
        self.enroll(); other = self.path.with_name('saved.sqlite3')
        self.path.rename(other); self.path.write_bytes(other.read_bytes()); os.chmod(self.path, 0o600)
        self.assertEqual(self.gate().status, 'HOLD')

    def test_wrong_expected_digest_cannot_record_result_or_revoke(self):
        self.enroll()
        for action in [lambda: self.store.record_result(735, '0'*64, 'DENIED', EVIDENCE),
                       lambda: self.store.revoke(735, '0'*64, 'OWNER_REVOKED')]:
            with self.assertRaises(self.mod.StoreDenied): action()
        self.assertEqual(self.store.load(735).state, 'ENROLLED')

    def test_expired_ticket_cannot_pass_final_gate(self):
        self.enroll(); self.assertEqual(self.gate(now=NOW+timedelta(minutes=5)).status, 'HOLD')

    @unittest.skipUnless(os.name == 'posix', 'POSIX-specific filesystem operation')
    def test_public_parent_is_refused(self):
        os.chmod(self.tmp.name, 0o755)
        try:
            with self.assertRaises(self.mod.StoreDenied): self.store.load(735)
        finally: os.chmod(self.tmp.name, 0o700)

    def test_boolean_pr_and_bad_result_codes_are_rejected(self):
        item = self.prepare()
        for call in [lambda: self.store.load(True), lambda: self.store.claim(True, item.digest, **context()),
                     lambda: self.store.record_result(735, item.digest, 'MERGED', EVIDENCE),
                     lambda: self.store.record_result(735, item.digest, 'ENROLLED', 'secret')]:
            with self.assertRaises(self.mod.StoreDenied): call()


if __name__ == '__main__':
    unittest.main()
