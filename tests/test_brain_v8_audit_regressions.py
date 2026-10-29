"""Preserve usable state, bounded learning scans and honest operational status."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from brain.core import BrainError
from brain.v8.__main__ import main
from brain.v8.automation import AutomationReconciler
from brain.v8.journal import KernelJournal
from brain.v8.learning import record_outcome
from brain.v8.supervisor import supervise
from tests.test_brain_v8_engineering import run,project,NOW,SHA
from tests.test_brain_v8_automation import BEFORE
from test_brain_v8_contracts import work
from test_brain_v8_journal import operation


class AuditRegressions(unittest.TestCase):
    def test_cycle_preserves_coverage_gap_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'projects.json'
            path.write_text(json.dumps(dict(source_sha=SHA,projects=[project()])))
            output=io.StringIO()
            with redirect_stdout(output):
                code=main(['cycle','--input',str(path),'--source-sha',SHA,
                           '--cycle','0','--now',NOW])
        self.assertEqual(code,0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'OWNER_BRIDGE_READY_WITH_GAPS')
        self.assertEqual(result['command_status'],'PASS')
        self.assertFalse(result['production_accepted'])

    def test_missing_provider_times_raise_contract_error(self):
        for field in ('created_at','updated_at'):
            row=run();del row[field]
            with self.subTest(field=field),self.assertRaises(BrainError):
                supervise(dict(total_count=1,workflow_runs=[row]),source_sha=SHA,now=NOW)

    def test_invalid_durable_task_status_never_reaches_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            control=AutomationReconciler(Path(folder),['owned'])
            ident=control.stage('owned',BEFORE,{'prompt':'new'})
            with control.files.lock():
                row=control.files.read('automation',ident)
                row['status']=[]
                control.files.write('automation',ident,row)
            with self.assertRaises(BrainError):
                control.apply(ident,lambda *a:self.fail('provider read'),
                              lambda *a:self.fail('provider write'))

    def test_learning_counts_stream_without_materializing_history(self):
        record=dict(schema_version=1,project_id='abvm',source_sha=SHA,
            attempt_id='b'*64,outcome='FAILED',data_kind='ACTUAL',
            evidence_id='c'*64,observed_at=NOW)
        with tempfile.TemporaryDirectory() as folder, \
             patch('brain.v8.learning.PrivateFiles.records',
                   side_effect=AssertionError('materialized private history')):
            result=record_outcome(Path(folder),record)
        self.assertEqual(result['counts']['observed'],1)
        self.assertEqual(result['counts']['failed'],1)
        self.assertEqual(result['counts']['actual_live_verified'],0)

    def test_journal_size_refusal_rolls_back_and_remains_reopenable(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite'
            with KernelJournal(path,create=True) as journal:
                journal.append(operation())
                before=journal.replay();image=path.read_bytes()
                big=work('large',evidence_ids=[f'{i:064x}' for i in range(32)],
                    dependencies=['work:'+f'{i:064x}' for i in range(32)])
                with patch('brain.v8.journal.MAX_FILE_BYTES',path.stat().st_size,create=True):
                    with self.assertRaisesRegex(BrainError,'V8_JOURNAL_SIZE_BOUND'):
                        journal.append(operation(big,ident='2'))
                self.assertEqual(journal.replay(),before)
            self.assertEqual(path.read_bytes(),image)
            with KernelJournal(path,readonly=True) as journal:
                self.assertEqual(journal.replay(),before)
