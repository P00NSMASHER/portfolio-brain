"""Pending journal integration: observations cannot authorize retry or release."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from brain.core import BrainError, digest
from brain.v8.journal import KernelJournal
from brain.v9.missions import compile_mission
from brain.v9.pending_review import review_pending_draft
from tests.test_brain_v8_contracts import work, NOW, LATER
from tests.test_brain_v8_journal import operation


class PendingReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'kernel.sqlite'
        self.intent = dict(schema_version=1, repository='P00NSMASHER/portfolio-brain',
                           base_sha='a'*40, head_sha='b'*40, pull_number=719,
                           expected_files={'docs/example.md': 'c'*40}, actor_login='P00NSMASHER')
        self.row = work(repository=self.intent['repository'], source_sha=self.intent['base_sha'],
                        fingerprint=digest(self.intent), resource=digest(dict(repository=self.intent['repository'].casefold())))
        self.mission = compile_mission([self.row], source_heads={self.row['repository']:self.row['source_sha']})
        self.ident = digest({'pending':'draft'})
        with KernelJournal(self.path, create=True) as j:
            j.append(operation(self.row))
            j.claim(resource=self.row['resource'], owner=self.row['owner'], operation_id=self.ident,
                    source_sha=self.row['source_sha'], now=NOW, expires_at=LATER)
            j.append(dict(schema_version=1, operation_id=self.ident, work=self.row,
                          expected_state='OBSERVED', occurred_at=NOW, outcome='EXTERNAL_INTENT'))

    def review(self, intent=None):
        with KernelJournal(self.path, readonly=True) as j:
            return review_pending_draft(self.mission,j,intent or self.intent,token='dummy',now=LATER)

    def test_readback_retains_pending_and_journal_even_after_expiry(self):
        before=self.path.read_bytes()
        with patch('brain.v9.pending_review.observe_draft',return_value={'evidence_kind':'INJECTED_TRANSPORT_OBSERVATION'}) as provider:
            result=self.review()
        provider.assert_called_once()
        self.assertTrue(result['pending_retained'])
        self.assertFalse(result['retry_authority'])
        self.assertFalse(result['release_authority'])
        self.assertEqual(result['operation_id'],self.ident)
        self.assertEqual(before,self.path.read_bytes())

    def test_changed_intent_is_rejected_before_network(self):
        changed=copy.deepcopy(self.intent);changed['pull_number']+=1
        with patch('brain.v9.pending_review.observe_draft') as provider:
            with self.assertRaisesRegex(BrainError,'INTENT_MEMBERSHIP'): self.review(changed)
        provider.assert_not_called()

    def test_provider_failure_leaves_intent_and_claim_untouched(self):
        before=self.path.read_bytes()
        with patch('brain.v9.pending_review.observe_draft',side_effect=ValueError('HTTP_UNCERTAIN')):
            with self.assertRaises(ValueError):self.review()
        self.assertEqual(before,self.path.read_bytes())

    def test_concurrent_journal_progress_invalidates_readback(self):
        def concurrent(*args,**kwargs):
            row=dict(self.row,updated_at=LATER)
            with KernelJournal(self.path) as j:
                j.append(dict(schema_version=1,operation_id=digest({'unknown':1}),work=row,
                              expected_state='OBSERVED',occurred_at=LATER,outcome='EXTERNAL_UNKNOWN'))
            return {'evidence_kind':'INJECTED_TRANSPORT_OBSERVATION'}
        with patch('brain.v9.pending_review.observe_draft',side_effect=concurrent):
            with self.assertRaisesRegex(BrainError,'JOURNAL_CHANGED'): self.review()

    def test_writable_journal_is_refused(self):
        with KernelJournal(self.path) as j, patch('brain.v9.pending_review.observe_draft') as provider:
            with self.assertRaisesRegex(BrainError,'READONLY'):
                review_pending_draft(self.mission,j,self.intent,token='dummy',now=LATER)
        provider.assert_not_called()

    def test_cli_missing_credential_returns_blocked_and_preserves_journal(self):
        import contextlib, io, json, os
        from brain.v9.__main__ import main
        root=self.path.parent
        (root/'mission.json').write_text(json.dumps(self.mission))
        (root/'intent.json').write_text(json.dumps(self.intent))
        before=self.path.read_bytes();output=io.StringIO()
        with patch.dict(os.environ, {'V9_GITHUB_READ_TOKEN':''}), contextlib.redirect_stdout(output):
            code=main(['review-pending','--mission',str(root/'mission.json'),
                       '--intent',str(root/'intent.json'),'--journal',str(self.path)])
        self.assertEqual(code,2)
        self.assertEqual(json.loads(output.getvalue())['status'],'BLOCKED')
        self.assertEqual(before,self.path.read_bytes())

    def test_replaced_journal_path_invalidates_old_connection_readback(self):
        def replace(*args, **kwargs):
            import os
            replacement=self.path.parent/'replacement.sqlite'
            replacement.write_bytes(self.path.read_bytes()); replacement.chmod(0o600)
            os.replace(replacement,self.path)
            return {'evidence_kind':'INJECTED_TRANSPORT_OBSERVATION'}
        with patch('brain.v9.pending_review.observe_draft',side_effect=replace):
            with self.assertRaisesRegex(BrainError,'JOURNAL_REPLACED'):self.review()

    def test_existing_transaction_is_refused_before_provider_access(self):
        with KernelJournal(self.path,readonly=True) as journal:
            journal.db.execute('BEGIN')
            with patch('brain.v9.pending_review.observe_draft') as provider:
                with self.assertRaisesRegex(BrainError,'ACTIVE_SNAPSHOT'):
                    review_pending_draft(self.mission,journal,self.intent,token='dummy',now=LATER)
            provider.assert_not_called()
