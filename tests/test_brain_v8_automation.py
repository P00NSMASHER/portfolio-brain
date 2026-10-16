"""Crash-safe task edits: durable intent, exact readback and conditional rollback."""
import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from brain.core import BrainError

BEFORE=dict(prompt='private instructions',title='Owned task',schedule='existing schedule',is_enabled=True)

class AutomationTests(unittest.TestCase):
    def controller(self,path,owned=('task-one',)):
        try: cls=importlib.import_module('brain.v8.automation').AutomationReconciler
        except ModuleNotFoundError: self.fail('private automation reconciler is missing')
        return cls(Path(path),owned)

    def test_durable_private_stage_apply_readback_idempotence_and_redaction(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new private instructions'})
            state=copy.deepcopy(BEFORE)
            calls=[]
            def update(task,changes):
                self.assertEqual(task,'task-one')
                calls.append(changes)
                state.update(changes)
            result=control.apply(ident,lambda task:copy.deepcopy(state),update)
            self.assertEqual(state['prompt'],'new private instructions')
            self.assertEqual(result['status'],'APPLIED')
            self.assertNotIn('private instructions',json.dumps(result))
            self.assertEqual(self.controller(folder).apply(ident,lambda task:state,update)['status'],'APPLIED')
            self.assertEqual(len(calls),1)
            self.assertEqual(state['schedule'],BEFORE['schedule'])
            for path in Path(folder).iterdir(): self.assertEqual(path.stat().st_mode&0o077,0)

    def test_conflicting_read_prevents_write_and_unowned_or_unsupported_fields_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            result=control.apply(ident,lambda task:dict(BEFORE,prompt='other owner edit'),lambda *args:self.fail('must not overwrite'))
            self.assertEqual(result['status'],'CONFLICT')
            for task,changes in [('not-owned',{'prompt':'new'}),('task-one',{'is_enabled':False}),('task-one',{'credentials':'secret'}),('task-one',{'schedule':'* * * * *'})]:
                with self.subTest(task=task,changes=changes),self.assertRaises(BrainError): control.stage(task,BEFORE,changes)
            with self.assertRaises(BrainError): self.controller(folder,owned=('another-task',)).apply(ident,lambda task:BEFORE,lambda *args:self.fail('not owned'))

    def test_write_timeout_after_success_reconciles_without_duplicate_provider_call(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            state=copy.deepcopy(BEFORE)
            def ambiguous(task,changes):
                state.update(changes)
                raise TimeoutError('private provider diagnostics')
            self.assertEqual(control.apply(ident,lambda task:copy.deepcopy(state),ambiguous)['status'],'UNKNOWN')
            result=self.controller(folder).apply(ident,lambda task:state,lambda *a:self.fail('duplicate external call'))
            self.assertEqual(result['status'],'APPLIED')

    def test_unknown_outcome_never_retries_merely_because_old_state_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            def timeout(*args): raise TimeoutError()
            control.apply(ident,lambda task:BEFORE,timeout)
            result=self.controller(folder).apply(ident,lambda task:BEFORE,lambda *a:self.fail('unsafe retry'))
            self.assertEqual(result['status'],'UNKNOWN')

    def test_rollback_restores_before_image_only_if_owned_write_still_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            state=copy.deepcopy(BEFORE)
            def update(task,changes): state.update(changes)
            control.apply(ident,lambda task:copy.deepcopy(state),update)
            self.assertEqual(control.rollback(ident,lambda task:copy.deepcopy(state),update)['status'],'ROLLED_BACK')
            self.assertEqual(state,BEFORE)
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            state=copy.deepcopy(BEFORE)
            def update(task,changes): state.update(changes)
            control.apply(ident,lambda task:copy.deepcopy(state),update)
            state['prompt']='later external edit'
            self.assertEqual(control.rollback(ident,lambda task:state,lambda *a:self.fail('unsafe rollback'))['status'],'CONFLICT')

    def test_shared_symlinked_and_foreign_private_storage_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            os.chmod(root,0o755)
            with self.assertRaises(BrainError): self.controller(root)
            os.chmod(root,0o700)
            alias=root/'alias'
            alias.symlink_to(root,target_is_directory=True)
            with self.assertRaises(BrainError): self.controller(alias)

    def test_provider_read_error_before_intent_does_not_expose_text_or_mutate(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            ident=control.stage('task-one',BEFORE,{'prompt':'new'})
            def unavailable(task): raise TimeoutError('private provider diagnostics')
            result=control.apply(ident,unavailable,lambda *a:self.fail('must not write'))
            self.assertEqual(result['status'],'READ_UNAVAILABLE')
            self.assertNotIn('private provider diagnostics',json.dumps(result))

    def test_unknown_write_reserves_task_against_previously_staged_other_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            a=control.stage('task-one',BEFORE,{'prompt':'first delayed'})
            b=control.stage('task-one',BEFORE,{'prompt':'second write'})
            def pending(*args): raise TimeoutError()
            control.apply(a,lambda task:BEFORE,pending)
            result=self.controller(folder).apply(b,lambda task:BEFORE,lambda *a:self.fail('overlapping uncertain task write'))
            self.assertEqual(result['status'],'TASK_RECONCILIATION_REQUIRED')

    def test_unknown_rollback_reserves_task_and_lock_refuses_second_local_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            control=self.controller(folder)
            a=control.stage('task-one',BEFORE,{'prompt':'new'})
            state=copy.deepcopy(BEFORE)
            def update(task,changes): state.update(changes)
            control.apply(a,lambda task:copy.deepcopy(state),update)
            def pending(*args): raise TimeoutError()
            self.assertEqual(control.rollback(a,lambda task:copy.deepcopy(state),pending)['status'],'ROLLBACK_UNKNOWN')
            b=control.stage('task-one',state,{'prompt':'second write'})
            self.assertEqual(control.apply(b,lambda task:copy.deepcopy(state),lambda *a:self.fail('overlapping rollback'))['status'],'TASK_RECONCILIATION_REQUIRED')
            with control.files.lock(),self.assertRaises(BrainError):
                self.controller(folder).apply(a,lambda task:state,lambda *a:self.fail('concurrent writer'))
