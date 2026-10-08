"""Adversarial proof tests for the isolated soak-focused replacement candidate."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from soak_v3.audit import (REQUIRED_STEPS, EvidenceError, digest,
                           evaluate_window, verify_sqlite, verify_artifact)

SHA = 'a'*40
PARENT = 'b'*40
START = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)

def utc(dt):
    return dt.isoformat().replace('+00:00','Z')

def run(index, *, event='schedule'):
    dt=START+timedelta(hours=index)
    before = PARENT if index == 0 else format(index, '040x')
    after = format(index+1, '040x')
    return {
        'run_id': 500+index, 'attempt': 1,
        'source_sha': SHA, 'event': event,
        'started_at': utc(dt), 'completed_at': utc(dt+timedelta(seconds=30)),
        'status': 'completed', 'conclusion': 'success',
        'steps': {x: 'success' for x in REQUIRED_STEPS},
        'artifact': {'status':'PASS', 'state_sequence': 100+index, 'canonical_hash':format(index+1,'064x')},
        'state': {'status':'PASS', 'parent':before, 'commit':after, 'sequence':100+index,'canonical_hash':format(index+1,'064x')}
    }

def evaluate(records, *, now=None, start=None, deadline=None, current_main=SHA):
    return evaluate_window(records, source_sha=SHA, current_main=current_main, first_state_parent=PARENT,
                           started_at=utc(start or START), deadline_at=utc(deadline or START+timedelta(hours=5)),
                           now=utc(now or START+timedelta(hours=2,seconds=40)))

class ProofTests(unittest.TestCase):
    def test_three_real_scheduled_cycles_not_a_declared_pass(self):
        result=evaluate([run(0),run(1),run(2)])
        self.assertEqual(result.status,'PRE_POSTVALIDATION')
        self.assertEqual(result.reason,'POST_SOAK_INDEPENDENT_CHECKS_REQUIRED')
        self.assertEqual(result.automatic_run_ids,(500,501,502))
        self.assertEqual(result.span_seconds,7200)

    def test_manual_dispatches_never_count(self):
        entries=[run(0),run(1,event='workflow_dispatch'),run(2)]
        entries[1]['external_clock']={'kind':'manual_probe', 'independently_verified':True}
        self.assertEqual(evaluate(entries).reason,'INSUFFICIENT_GENUINE_AUTOMATIC_CYCLES')
        entries[1]['external_clock']={'kind':'scheduled', 'independently_verified':True}
        self.assertEqual(evaluate(entries).reason,'INSUFFICIENT_GENUINE_AUTOMATIC_CYCLES')

    def test_full_external_clock_chain_required(self):
        entries=[run(0),run(1,event='workflow_dispatch'),run(2)]
        entries[1]['external_clock']={'kind':'scheduled','source_sha':SHA,'independently_verified':True,
                                     'actual_task_execution_verified':True,'clock_job_verified':True,
                                     'core_receipt_verified':True}
        self.assertEqual(evaluate(entries).status,'PRE_POSTVALIDATION')

    def test_one_failed_cycle_poison_soak_even_with_three_successes(self):
        entries=[run(0),run(1),run(2)]
        failed=copy.deepcopy(run(1));failed['run_id']=700
        failed['conclusion']='failure'
        self.assertEqual(evaluate(entries+[failed]).reason,'CORE_EXECUTION_FAILED')

    def test_an_inflight_cycle_does_not_falsely_fail(self):
        entries=[run(0),run(1),run(2)]
        entries[1]['status']='in_progress';entries[1]['conclusion']=None
        self.assertEqual(evaluate(entries).reason,'CORE_EXECUTION_INCOMPLETE')
        self.assertEqual(evaluate(entries).status,'WAITING')

    def test_missing_mandatory_step_is_not_green(self):
        entries=[run(0),run(1),run(2)]
        del entries[1]['steps']['Read-only public project monitoring']
        self.assertEqual(evaluate(entries).reason,'MANDATORY_STEP_FAILED_OR_MISSING')

    def test_parent_mismatch_is_terminal(self):
        entries=[run(0),run(1),run(2)]
        entries[1]['state']['parent']='f'*40
        self.assertEqual(evaluate(entries).reason,'STATE_PARENT_CHAIN_BROKEN')

    def test_artifact_and_state_cannot_disagree(self):
        entries=[run(0),run(1),run(2)]
        entries[1]['artifact']['canonical_hash']='f'*64
        self.assertEqual(evaluate(entries).reason,'STATE_AND_ARTIFACT_DISAGREE')

    def test_main_drift_fails(self):
        self.assertEqual(evaluate([run(0),run(1),run(2)],current_main='c'*40).reason,'MAIN_DRIFT')

    def test_missing_artifact_is_blocked_not_pass(self):
        entries=[run(0),run(1),run(2)]
        entries[1]['artifact']['status']='UNKNOWN'
        self.assertEqual(evaluate(entries).reason,'ARTIFACT_NOT_VERIFIED')

    def test_gap_over_ninety_fails_even_three_green(self):
        entries=[run(0),run(1),run(2)]
        entries[1]['started_at']=utc(START+timedelta(seconds=6000))
        entries[1]['completed_at']=utc(START+timedelta(seconds=6030))
        self.assertEqual(evaluate(entries, now=START+timedelta(hours=3)).reason,'AUTOMATIC_DELIVERY_GAP_EXCEEDED')

    def test_insufficient_duration_blocks(self):
        entries=[run(0),run(1),run(2)]
        entries[2]['started_at']=utc(START+timedelta(seconds=7000))
        entries[2]['completed_at']=utc(START+timedelta(seconds=7030))
        self.assertEqual(evaluate(entries).reason,'SOAK_DURATION_INCOMPLETE')

    def test_deadline_and_no_runs_are_not_pass(self):
        self.assertEqual(evaluate([],now=START+timedelta(hours=1)).status,'WAITING')
        self.assertEqual(evaluate([],now=START+timedelta(hours=5)).status,'BLOCKED')
        self.assertEqual(evaluate([run(0)],now=START+timedelta(hours=5)).status,'BLOCKED')

    def test_duplicate_run_attempt_and_invalid_time_rejected(self):
        with self.assertRaisesRegex(EvidenceError,'CYCLE_DUPLICATE_ATTEMPT'):
            evaluate([run(0),run(0)])
        entries=[run(0),run(1),run(2)]
        entries[1]['completed_at']='2026-10-08T03:00:30+01:00'
        with self.assertRaisesRegex(EvidenceError,'TIME_MUST_BE_EXPLICIT_UTC'):
            evaluate(entries)

    def test_automatic_clock_policy_bounds(self):
        self.assertGreater((45+60)*60, 5400)
        self.assertLessEqual((25+60)*60, 5400)

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
    def artifact(self, *, corrupt=False):
        d={'schema_version':2,'source_sha':SHA,'state_parent':PARENT,'state_commit':'c'*40,'run_id':'500','publication_verified':True,'soak_completed':False}
        doc={'status':'PASS','source_sha':SHA,'pending_events':0,'state_sequence':5,'canonical_hash':'d'*64,'workflow_delivery':'NOT_TESTED_BY_LOCAL_DOCTOR'}
        pre={'status':'PASS','source_sha':SHA,'live_sources':'NOT_TESTED'}
        if corrupt:doc['pending_events']=1
        target=self.root/'artifact.zip'
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('delivery.json',json.dumps(d));z.writestr('doctor/report.json',json.dumps(doc));z.writestr('preflight/report.json',json.dumps(pre))
        return target,'sha256:'+hashlib.sha256(target.read_bytes()).hexdigest()
    def test_provider_digest_and_embedded_receipts(self):
        path,dig=self.artifact()
        self.assertEqual(verify_artifact(path,dig,run_id=500,source_sha=SHA,state_parent=PARENT,state_commit='c'*40)['status'],'PASS')
    def test_mismatched_digest_rejected(self):
        path,_=self.artifact()
        with self.assertRaisesRegex(EvidenceError,'ARTIFACT_SHA256_MISMATCH'):
            verify_artifact(path,'sha256:'+'f'*64,run_id=500,source_sha=SHA,state_parent=PARENT,state_commit='c'*40)
    def test_doctor_backlog_rejected(self):
        path,dig=self.artifact(corrupt=True)
        with self.assertRaisesRegex(EvidenceError,'DOCTOR_NOT_PASS'):
            verify_artifact(path,dig,run_id=500,source_sha=SHA,state_parent=PARENT,state_commit='c'*40)

class StateTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.path=Path(self.t.name)/'state.sqlite'
        c=sqlite3.connect(self.path)
        c.executescript('''
          CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,status TEXT NOT NULL,received_at TEXT NOT NULL);
          CREATE TABLE ledger(seq INTEGER PRIMARY KEY,prev_hash TEXT NOT NULL,chain_hash TEXT NOT NULL);
          CREATE TABLE reports(id INTEGER PRIMARY KEY AUTOINCREMENT,seq INTEGER NOT NULL,chain_hash TEXT NOT NULL,source_sha TEXT NOT NULL,created_at TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
        ''')
        c.execute("INSERT INTO meta VALUES('schema_version','2')");c.execute("INSERT INTO meta VALUES('visibility','PUBLIC')")
        event={'id':'repository:test','visibility':'PUBLIC','kind':'repository','key':'test','source_sha':SHA,'observed_at':utc(START),'data_kind':'ACTUAL','payload':{}}
        h=digest(event)
        chain=digest({'seq':1,'event_hash':h,'previous':'0'*64})
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(1,event['id'],json.dumps(event),h,'APPLIED',utc(START)))
        c.execute('INSERT INTO ledger VALUES(?,?,?)',(1,'0'*64,chain))
        report={'status':'PASS','source_sha':SHA,'pending_events':0,'state_sequence':1,'canonical_hash':chain}
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?)',(1,1,chain,SHA,utc(START),json.dumps(report),digest(report)))
        c.commit();c.close()
        self.chain=chain
    def test_independent_sqlite_chain_replay(self):
        self.assertEqual(verify_sqlite(self.path,expected_sequence=1,expected_chain=self.chain,expected_source=SHA)['status'],'PASS')
    def test_corrupt_chain_fails_even_if_sqlite_integrity_ok(self):
        c=sqlite3.connect(self.path);c.execute('UPDATE ledger SET chain_hash=?',('f'*64,));c.commit();c.close()
        with self.assertRaisesRegex(EvidenceError,'STATE_CHAIN_DIGEST_INVALID'):
            verify_sqlite(self.path,expected_sequence=1,expected_chain=self.chain,expected_source=SHA)
    def test_pending_event_fails(self):
        c=sqlite3.connect(self.path);c.execute("UPDATE events SET status='PENDING'");c.commit();c.close()
        with self.assertRaisesRegex(EvidenceError,'STATE_PENDING_EVENTS'):
            verify_sqlite(self.path,expected_sequence=1,expected_chain=self.chain,expected_source=SHA)

if __name__=='__main__':unittest.main()
