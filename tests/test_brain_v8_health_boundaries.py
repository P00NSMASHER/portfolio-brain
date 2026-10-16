"""Admission must not poison durable history; hostile enum inputs must fail closed."""
import copy
from pathlib import Path
import tempfile
import unittest
from brain.core import BrainError
from brain.v8.learning import record_outcome
from brain.v8.automation import AutomationReconciler
from brain.v8.supervisor import supervise
from brain.v8.research import research_actions
from brain.v8.private_state import PrivateFiles
from tests.test_brain_v8_automation import BEFORE
from tests.test_brain_v8_engineering import run,NOW,SHA


def outcome(i):
    return dict(schema_version=1,project_id='abvm',source_sha=SHA,
        attempt_id=f'{i:064x}',outcome='FAILED',data_kind='ACTUAL',
        evidence_id='b'*64,observed_at=NOW)

class BoundaryTests(unittest.TestCase):
    def test_capacity_refusal_does_not_write_unreadable_257th_outcome(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i in range(256): record_outcome(root,outcome(i))
            with self.assertRaises(BrainError): record_outcome(root,outcome(256))
            self.assertEqual(len(list(root.glob('outcome-*.json'))),256)
            self.assertEqual(record_outcome(root,outcome(0))['counts']['observed'],256)

    def test_full_automation_store_still_allows_reconciliation_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);control=AutomationReconciler(root,['owned'])
            ids=[control.stage('owned',BEFORE,{'prompt':f'private update {i}'}) for i in range(256)]
            with self.assertRaises(BrainError): control.stage('owned',BEFORE,{'prompt':'overflow'})
            self.assertEqual(len(list(root.glob('automation-*.json'))),256)
            state=copy.deepcopy(BEFORE)
            def update(task,changes): state.update(changes)
            self.assertEqual(control.apply(ids[-1],lambda task:copy.deepcopy(state),update)['status'],'APPLIED')
            self.assertEqual(control.rollback(ids[-1],lambda task:copy.deepcopy(state),update)['status'],'ROLLED_BACK')

    def test_unhashable_provider_enums_raise_contract_errors(self):
        for changes in [{'status':[]},{'conclusion':{}},{'run_attempt':True}]:
            with self.subTest(changes=changes),self.assertRaises(BrainError):
                supervise({'total_count':1,'workflow_runs':[run(**changes)]},source_sha=SHA,now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            for changes in [{'outcome':[]},{'data_kind':{}}]:
                with self.subTest(changes=changes),self.assertRaises(BrainError):
                    record_outcome(Path(folder),dict(outcome(0),**changes))

    def test_bad_research_history_is_rejected_without_a_typeerror(self):
        with self.assertRaises(BrainError):
            research_actions([],[],[{'finding_id':[],'outcome':'FAILED'}])

    def test_malformed_provider_readback_is_redacted_and_left_reconcilable(self):
        with tempfile.TemporaryDirectory() as folder:
            control=AutomationReconciler(Path(folder),['owned'])
            ident=control.stage('owned',BEFORE,{'prompt':'new'})
            self.assertEqual(control.apply(ident,lambda task:{},lambda *a:self.fail('must not write'))['status'],'READ_UNAVAILABLE')
            calls=[]
            def read(task): return copy.deepcopy(BEFORE) if not calls else {}
            def update(task,changes): calls.append(changes)
            self.assertEqual(control.apply(ident,read,update)['status'],'UNKNOWN')
            self.assertEqual(control.apply(ident,lambda task:BEFORE,lambda *a:self.fail('ambiguous retry'))['status'],'UNKNOWN')
