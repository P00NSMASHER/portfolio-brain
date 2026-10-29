"""Exercise real SQLite durability, tamper rejection and private path boundaries."""
import copy
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from brain.core import BrainError
from test_brain_v8_contracts import work, NOW, LATER
try:
    from brain.v8.journal import KernelJournal
except ImportError:
    KernelJournal=None


def operation(row=None, ident='1', expected=None, outcome='LOCAL_COMMITTED'):
    row=work() if row is None else row
    return dict(schema_version=1,operation_id=ident*64,work=row,expected_state=expected,
                occurred_at=row['updated_at'],outcome=outcome)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(KernelJournal),'v8 journal is missing')
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'kernel.sqlite'

    def test_duplicate_operation_is_noop_and_conflict_rejected(self):
        with KernelJournal(self.path,create=True) as journal:
            first=journal.append(operation())
            self.assertEqual(journal.append(operation()),first)
            self.assertEqual(len(journal.replay()),1)
            self.assertFalse(first['automatic_execution_authority'])
            with self.assertRaises(BrainError): journal.append(operation(work('other')))
        with KernelJournal(self.path) as journal:
            self.assertEqual(journal.append(operation()),first)
            self.assertEqual(len(journal.replay()),1)

    def test_restart_and_bad_transition_leave_original_unchanged(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            before=journal.replay()
            with self.assertRaises(BrainError):
                journal.append(operation(work(state='PATCHED',updated_at=LATER),ident='2',expected='OBSERVED'))
            self.assertEqual(journal.replay(),before)
        with KernelJournal(self.path) as journal:
            row=work(state='DIAGNOSED',updated_at=LATER)
            journal.append(operation(row,ident='2',expected='OBSERVED'))
            self.assertEqual(journal.replay()[-1]['operation']['work']['state'],'DIAGNOSED')

    def test_transaction_rolls_back_after_process_death(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
        import subprocess, sys
        code="import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); c.execute('DELETE FROM kernel_events'); os._exit(9)"
        result=subprocess.run([sys.executable,'-c',code,str(self.path)],timeout=5)
        self.assertEqual(result.returncode,9)
        with KernelJournal(self.path) as journal:
            self.assertEqual(len(journal.replay()),1)

    def test_external_intent_without_result_requires_reconciliation(self):
        with KernelJournal(self.path,create=True) as journal:
            result=journal.append(operation(outcome='EXTERNAL_INTENT'))
            self.assertTrue(result['reconciliation_required'])
        with KernelJournal(self.path) as journal:
            self.assertEqual(journal.replay()[-1]['operation']['outcome'],'EXTERNAL_INTENT')
            with self.assertRaises(BrainError):
                journal.append(operation(work(updated_at=LATER),ident='2',expected='OBSERVED',outcome='EXTERNAL_INTENT'))
            unknown=journal.append(operation(work(updated_at=LATER),ident='3',expected='OBSERVED',outcome='EXTERNAL_UNKNOWN'))
            self.assertTrue(unknown['reconciliation_required'])

    def test_immutable_fields_and_fabricated_external_completion_rejected(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            for changes in [dict(owner='other'),dict(resource='9'*64),dict(priority_tier=0),dict(attempts=-1)]:
                row=work(state='DIAGNOSED',updated_at=LATER,**changes)
                with self.assertRaises(BrainError): journal.append(operation(row,ident='2',expected='OBSERVED'))
            with self.assertRaises(BrainError):
                journal.append(operation(work(updated_at=LATER),ident='3',expected='OBSERVED',outcome='EXTERNAL_CONFIRMED'))

    def test_replay_rejects_body_hash_sequence_and_chain_tampering(self):
        for field,value in [('body','{}'),('body_hash','0'*64),('seq',2),('prev_hash','f'*64),('chain_hash','0'*64)]:
            path=Path(self.tmp.name)/(field+'.sqlite')
            with KernelJournal(path,create=True) as journal: journal.append(operation())
            with sqlite3.connect(path) as db:
                db.execute('UPDATE kernel_events SET '+field+'=?',(value,))
            with self.subTest(field=field), self.assertRaises(BrainError):
                with KernelJournal(path) as journal: journal.replay()

    def test_readonly_replay_refuses_append_and_never_creates_missing_file(self):
        with KernelJournal(self.path,create=True) as journal: journal.append(operation())
        before=self.path.read_bytes()
        with KernelJournal(self.path,readonly=True) as journal:
            self.assertEqual(len(journal.replay()),1)
            with self.assertRaises(BrainError): journal.append(operation())
        self.assertEqual(self.path.read_bytes(),before)
        missing=Path(self.tmp.name)/'missing.sqlite'
        with self.assertRaises(BrainError): KernelJournal(missing)
        self.assertFalse(missing.exists())

    def test_foreign_database_is_never_modified(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
            db.execute("INSERT INTO meta VALUES('schema_version','2')")
        self.path.chmod(0o600)
        before=(self.path.read_bytes(),self.path.stat().st_mode)
        with self.assertRaises(BrainError): KernelJournal(self.path,create=True)
        self.assertEqual((self.path.read_bytes(),self.path.stat().st_mode),before)

    def test_symlink_hardlink_and_shared_parent_refused(self):
        target=Path(self.tmp.name)/'original'
        target.write_text('preserve')
        self.path.symlink_to(target)
        with self.assertRaises(BrainError): KernelJournal(self.path,create=True)
        self.path.unlink()
        os.link(target,self.path)
        with self.assertRaises(BrainError): KernelJournal(self.path,create=True)
        self.assertEqual(target.read_text(),'preserve')
        public=Path(self.tmp.name)/'shared'
        public.mkdir(mode=0o755)
        with self.assertRaises(BrainError): KernelJournal(public/'new.sqlite',create=True)
        self.assertFalse((public/'new.sqlite').exists())


class ClaimTests(unittest.TestCase):
    setUp = JournalTests.setUp
    def test_competing_connections_cannot_claim_one_resource(self):
        self.assertTrue(callable(getattr(KernelJournal,'claim',None)),'v8 claims are missing')
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            journal.append(operation(work('second',owner='second-owner'),ident='4'))
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def compete(owner):
            with KernelJournal(self.path) as journal:
                barrier.wait(timeout=5)
                try:
                    journal.claim(resource='c'*64,owner=owner,operation_id='2'*64,
                        source_sha='a'*40,now=NOW,expires_at=LATER)
                    return 'claimed'
                except BrainError: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(compete,o) for o in ['school-owner','second-owner']]
            results=[f.result(timeout=10) for f in futures]
        self.assertEqual(sorted(results),['claimed','conflict'])

    def test_expired_claim_with_unresolved_intent_is_not_stolen(self):
        self.assertTrue(callable(getattr(KernelJournal,'claim',None)),'v8 claims are missing')
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            journal.append(operation(work('second',owner='second-owner'),ident='4'))
            journal.claim(resource='c'*64,owner='school-owner',operation_id='2'*64,
                source_sha='a'*40,now=NOW,expires_at='2026-10-15T20:00:30Z')
            journal.append(operation(ident='2',expected='OBSERVED',outcome='EXTERNAL_INTENT'))
        with KernelJournal(self.path) as journal:
            with self.assertRaisesRegex(BrainError,'RECONCILIATION'):
                journal.claim(resource='c'*64,owner='second-owner',operation_id='5'*64,
                    source_sha='a'*40,now=LATER,expires_at='2026-10-15T20:02:00Z')
            with self.assertRaises(BrainError):
                journal.release_claim(resource='c'*64,owner='school-owner',operation_id='2'*64,now=LATER)
            journal.append(operation(work(updated_at=LATER),ident='3',expected='OBSERVED',outcome='EXTERNAL_CONFIRMED'))
            result=journal.claim(resource='c'*64,owner='second-owner',operation_id='5'*64,
                source_sha='a'*40,now=LATER,expires_at='2026-10-15T20:02:00Z')
            self.assertFalse(result['automatic_execution_authority'])

    def test_wrong_claim_identity_or_release_preserves_owner(self):
        self.assertTrue(callable(getattr(KernelJournal,'claim',None)),'v8 claims are missing')
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            args=dict(resource='c'*64,owner='school-owner',operation_id='2'*64,source_sha='a'*40,now=NOW,expires_at=LATER)
            for change in [dict(source_sha='f'*40),dict(expires_at=NOW),dict(owner='unknown')]:
                with self.assertRaises(BrainError): journal.claim(**dict(args,**change))
            first=journal.claim(**args)
            self.assertEqual(journal.claim(**args),first)
            for change in [dict(owner='other'),dict(operation_id='3'*64),dict(resource='9'*64),dict(now='2026-10-14T20:00:00Z')]:
                release={k:args[k] for k in ['resource','owner','operation_id','now']}
                with self.assertRaises(BrainError): journal.release_claim(**dict(release,**change))
            journal.release_claim(resource='c'*64,owner='school-owner',operation_id='2'*64,now=LATER)
            self.assertEqual(journal.replay()[-1]['kind'],'CLAIM_RELEASE')


class ReviewRegressionTests(unittest.TestCase):
    setUp=JournalTests.setUp

    def test_committed_tail_truncation_is_rejected(self):
        with KernelJournal(self.path,create=True) as journal: journal.append(operation())
        with sqlite3.connect(self.path) as db: db.execute('DELETE FROM kernel_events')
        with self.assertRaises(BrainError):
            with KernelJournal(self.path) as journal: journal.replay()

    def test_sqlite_like_wildcard_cannot_hide_unrecognized_trigger(self):
        with KernelJournal(self.path,create=True) as journal: journal.append(operation())
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TRIGGER sqliteXhidden AFTER INSERT ON kernel_events BEGIN DELETE FROM kernel_events; END')
        before=self.path.read_bytes()
        with self.assertRaises(BrainError): KernelJournal(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_completed_action_cannot_be_claimed_for_new_resource(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            journal.append(operation(work('other',resource='8'*64),ident='4'))
            with self.assertRaises(BrainError):
                journal.claim(resource='8'*64,owner='school-owner',operation_id='1'*64,
                    source_sha='a'*40,now=NOW,expires_at=LATER)

    def test_one_action_identity_cannot_be_claimed_across_resources(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            journal.append(operation(work('other',resource='8'*64),ident='4'))
            journal.claim(resource='c'*64,owner='school-owner',operation_id='2'*64,
                source_sha='a'*40,now=NOW,expires_at=LATER)
            with self.assertRaises(BrainError):
                journal.claim(resource='8'*64,owner='school-owner',operation_id='2'*64,
                    source_sha='a'*40,now=NOW,expires_at=LATER)

    def test_foreign_wal_database_rejection_creates_no_sidecars(self):
        import shutil
        source=Path(self.tmp.name)/'foreign-live.sqlite'
        live=sqlite3.connect(source)
        try:
            live.execute('PRAGMA journal_mode=WAL')
            live.execute('CREATE TABLE meta(key TEXT,value TEXT)')
            live.execute("INSERT INTO meta VALUES('schema_version','2')")
            live.commit()
            shutil.copyfile(source,self.path)
            shutil.copyfile(str(source)+'-wal',str(self.path)+'-wal')
            self.path.chmod(0o600)
            names=set(Path(self.tmp.name).iterdir())
            before=self.path.read_bytes()
            with self.assertRaises(BrainError): KernelJournal(self.path,readonly=True)
            self.assertEqual(set(Path(self.tmp.name).iterdir()),names)
            self.assertEqual(self.path.read_bytes(),before)
        finally: live.close()

    def test_terminal_attempt_cannot_start_new_external_intent(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation())
            failed=work(state='FAILED',updated_at=LATER)
            journal.append(operation(failed,ident='2',expected='OBSERVED'))
            failed['updated_at']='2026-10-15T20:02:00Z'
            with self.assertRaises(BrainError):
                journal.append(operation(failed,ident='3',expected='FAILED',outcome='EXTERNAL_INTENT'))

    def test_failed_attempt_can_still_reconcile_existing_external_intent(self):
        with KernelJournal(self.path,create=True) as journal:
            journal.append(operation(outcome='EXTERNAL_INTENT'))
            failed=work(state='FAILED',updated_at=LATER)
            journal.append(operation(failed,ident='2',expected='OBSERVED',outcome='EXTERNAL_UNKNOWN'))
            failed['updated_at']='2026-10-15T20:02:00Z'
            result=journal.append(operation(failed,ident='3',expected='FAILED',outcome='EXTERNAL_CONFIRMED'))
            self.assertFalse(result['reconciliation_required'])
            self.assertEqual(journal.replay()[-1]['operation']['work']['state'],'FAILED')

    def test_replay_uses_one_snapshot_during_concurrent_append(self):
        from concurrent.futures import ThreadPoolExecutor,TimeoutError
        with KernelJournal(self.path,create=True) as journal: journal.append(operation())
        def append_next():
            with KernelJournal(self.path) as writer:
                writer.append(operation(work(state='DIAGNOSED',updated_at=LATER),ident='2',expected='OBSERVED'))
        with ThreadPoolExecutor(max_workers=1) as pool:
            with KernelJournal(self.path,readonly=True) as reader:
                pending=[]
                def between_rows_and_tip(sql):
                    if sql.startswith('SELECT slot,sequence,chain_hash') and not pending:
                        pending.append(pool.submit(append_next))
                        try: pending[0].result(timeout=1)
                        except TimeoutError: pass
                reader.db.set_trace_callback(between_rows_and_tip)
                try: rows=reader.replay()
                except BrainError as exc: self.fail('concurrent append must not corrupt valid replay: '+str(exc))
                self.assertIn(len(rows),[1,2])
                reader.db.set_trace_callback(None)
            pending[0].result(timeout=6)
        with KernelJournal(self.path) as journal: self.assertEqual(len(journal.replay()),2)
