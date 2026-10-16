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
