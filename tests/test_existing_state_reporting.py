"""Repairs to existing status signals; fixtures are not production outcomes."""
from legacy.workflow_archive import legacy_workflow_path
import copy
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from cost_governor.cost_governor import load_state
from dashboard import operational_telemetry as telemetry
from dashboard.live_state_bridge import apply_cost_verification
from operations.workflow_liveness import cost_state_observation, _hash_value, verify_work_proof, load_policy
from operations.liveness_artifact_state import restore, load_verified, MEMBER, WORKFLOW_PATH

AT='2026-09-29T14:45:00Z'
NOW=datetime.fromisoformat(AT.replace('Z','+00:00'))

def fixture():
    cycle={'cycle_id':'cycle-'+'a'*24,'mode':'sync','status':'PASS',
           'finished_at':'2026-09-29T14:40:00Z','receipt_hash':'sha256:'+'a'*64}
    row={'workflow_name':'runtime-hourly-sync','workflow_file':'runtime-hourly-sync.yml',
         'latest_run_id':42,'latest_conclusion':'success','dispatch_required':False,
         'status':'HEALTHY_VERIFIED_WORK','work_proof_status':'VERIFIED_WORK',
         'work_proof_reason':'RUNTIME_SYNC_RECEIPT',
         'work_proof_metrics':{k:cycle[k] for k in ('cycle_id','finished_at','receipt_hash')}}
    row['work_proof_metrics'].update(observations=7,api_requests=11)
    doc={'schema_version':'1.0.0','status':'HEALTHY_VERIFIED_WORK','checked_at':AT,
         'hard_stop_reason':None,'dispatches':[],'targets':[row],
         'authority_granted':False,'api_requests':3,'verified_work_target_count':1}
    source={'generated_at':AT,'sources':{'runtime':{'status':'LIVE','source_run_id':99},
                                      'cost':{'status':'STALE','source_run_id':5}}}
    return cycle,doc,source

def save_receipt(directory,doc):
    (directory/MEMBER).write_text(json.dumps(doc))
    (directory/'workflow_liveness_restore.json').write_text(json.dumps({
        'restore_status':'RESTORED','source_run_id':88,'source_workflow':WORKFLOW_PATH,
        'receipt_hash':_hash_value(doc)}))

class ExistingStateReportingTests(unittest.TestCase):
    def test_nonpaid_sync_uses_actual_receipt_not_a_cost_reservation(self):
        cycle,doc,source=fixture()
        result=telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {'reservations':[]},source,doc)
        self.assertEqual(result['status'],'VERIFIED_SYNC_WORK')
        self.assertEqual(result['source_run_id'],42)
        self.assertEqual(result['runtime_artifact_source_run_id'],99)
        self.assertIsNone(result['reservation_id'])

    def test_mismatched_sync_receipt_is_not_rescued_by_a_matching_run_id(self):
        for field,value in [('receipt_hash','sha256:'+'f'*64),('cycle_id','other'),('finished_at','2026-09-29T14:41:00Z')]:
            with self.subTest(field=field):
                cycle,doc,source=fixture();doc['targets'][0]['work_proof_metrics'][field]=value
                source['sources']['runtime']['source_run_id']=42
                r=telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {}, source,doc)
                self.assertEqual(r['status'],'UNVERIFIED_SYNC_WORK')

    def test_stale_or_future_sync_not_verified(self):
        for publication in ('2026-09-29T18:00:00Z','2026-09-29T14:30:00Z'):
            cycle,doc,source=fixture();source['generated_at']=publication
            self.assertEqual(telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {},source,doc)['status'],'UNVERIFIED_SYNC_WORK')

    def test_sync_requires_positive_work_and_nonboolean_run_identity(self):
        for key,val in [('observations',0),('api_requests',0),('api_requests',True)]:
            cycle,doc,source=fixture();doc['targets'][0]['work_proof_metrics'][key]=val
            self.assertEqual(telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {},source,doc)['status'],'UNVERIFIED_SYNC_WORK')
        cycle,doc,source=fixture();doc['targets'][0]['latest_run_id']=True
        self.assertEqual(telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {},source,doc)['status'],'UNVERIFIED_SYNC_WORK')

    def test_duplicate_sync_targets_remain_unverified(self):
        cycle,doc,source=fixture();doc['targets']*=2
        self.assertEqual(telemetry._runtime_sync_proof({'recent_cycles':[cycle]}, {},source,doc)['status'],'UNVERIFIED_SYNC_WORK')

    def test_unvalidated_cycle_cannot_become_watchdog_proof(self):
        target=next(t for t in load_policy()['targets'] if t['proof_kind']=='RUNTIME_SYNC')
        malformed={'schema_version':'1.0.0','mode':'sync','status':'PASS','observations':[{}],'api_requests':1}
        malformed['receipt_hash']=_hash_value(malformed)
        self.assertEqual(verify_work_proof(target,malformed,run_id=42)['status'],'INVALID_WORK_PROOF')

    def cost_fixture(self):
        state=load_state(); state['sequence']=4;state['updated_at']='2026-09-28T12:00:00Z'
        meta={'restore_status':'RESTORED','artifact_name':'portfolio-cost-governor-state',
              'artifact_id':12,'source_run_id':13,'source_sequence':4,'source_state_hash':_hash_value(state)}
        source={'status':'STALE','source_kind':'GITHUB_ACTIONS_ARTIFACT','artifact_id':12,
                'source_run_id':13,'artifact_created_at':'2026-09-28T12:00:10Z',
                'state_updated_at':state['updated_at'],'age_minutes':1600}
        doc=fixture()[1];doc['cost_state_proof']=cost_state_observation(state,meta,at=AT)
        return state,meta,source,doc

    def test_rechecking_unchanged_cost_state_does_not_change_ledger_or_timestamps(self):
        state,meta,source,doc=self.cost_fixture();before=copy.deepcopy(state)
        apply_cost_verification(source,state,doc,now=NOW)
        self.assertEqual(state,before)
        self.assertEqual(source['status'],'LIVE')
        self.assertEqual(source['state_updated_at'],'2026-09-28T12:00:00Z')
        self.assertEqual(source['artifact_created_at'],'2026-09-28T12:00:10Z')
        self.assertEqual(source['age_minutes'],1600)
        self.assertEqual(source['last_verified_at'],AT)

    def test_seed_or_missing_cost_metadata_never_claims_current(self):
        state,meta,source,doc=self.cost_fixture()
        self.assertIsNone(cost_state_observation(state,{},at=AT))
        meta['restore_status']='NO_PRIOR_ARTIFACT'
        self.assertIsNone(cost_state_observation(state,meta,at=AT))
        source['source_kind']='CHECKED_IN_SEED'
        apply_cost_verification(source,state,doc,now=NOW)
        self.assertEqual(source['status'],'STALE')

    def test_changed_cost_state_invalidates_old_freshness_proof(self):
        for field,val in [('sequence',5),('updated_at','2026-09-29T14:42:00Z')]:
            state,meta,source,doc=self.cost_fixture();state[field]=val
            apply_cost_verification(source,state,doc,now=NOW)
            self.assertEqual(source['status'],'STALE')

    def test_different_cost_source_or_hash_is_not_verified(self):
        for field,val in [('source_artifact_id',44),('source_run_id',44),('state_hash','sha256:'+'0'*64),('state_mutated',True)]:
            state,meta,source,doc=self.cost_fixture();doc['cost_state_proof'][field]=val
            apply_cost_verification(source,state,doc,now=NOW)
            self.assertEqual(source['status'],'STALE')

    def test_expired_or_future_cost_check_stays_stale(self):
        for checked in ('2026-09-29T12:00:00Z','2026-09-29T15:00:00Z'):
            state,meta,source,doc=self.cost_fixture();doc['checked_at']=checked;doc['cost_state_proof']['checked_at']=checked
            apply_cost_verification(source,state,doc,now=NOW)
            self.assertEqual(source['status'],'STALE')

    def test_missing_tampered_or_stale_projected_receipt_is_rejected(self):
        with TemporaryDirectory() as d:
            path=Path(d);self.assertIsNone(load_verified(path,now=NOW))
            doc=fixture()[1];save_receipt(path,doc)
            self.assertEqual(load_verified(path,now=NOW),doc)
            doc['targets'][0]['work_proof_metrics']['api_requests']=999
            (path/MEMBER).write_text(json.dumps(doc))
            self.assertIsNone(load_verified(path,now=NOW))
            save_receipt(path,doc)
            self.assertIsNone(load_verified(path,now=datetime(2026,9,30,tzinfo=timezone.utc)))

    def provider_fixture(self):
        doc=fixture()[1];buff=io.BytesIO()
        with zipfile.ZipFile(buff,'w') as z:z.writestr(MEMBER,json.dumps(doc))
        raw=buff.getvalue()
        item={'id':8,'name':'portfolio-workflow-liveness','expired':False,'created_at':AT,
              'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),
              'workflow_run':{'id':7,'head_sha':'a'*40,'head_branch':'main'}}
        run={'id':7,'path':WORKFLOW_PATH,'head_branch':'main','head_sha':'a'*40,
             'status':'completed','conclusion':'success','repository':{'full_name':'owner/repo'},
             'head_repository':{'full_name':'owner/repo'},'run_started_at':'2026-09-29T14:44:00Z','updated_at':AT}
        class FakeHTTP:
            def json(self,url):return {'artifacts':[item]} if '?' in url else run
            def bytes(self,url):return raw
        return item,run,FakeHTTP()

    def try_restore(self,http):
        with TemporaryDirectory() as d,patch.dict(os.environ,{'GITHUB_REPOSITORY':'owner/repo','GITHUB_TOKEN':'synthetic','GITHUB_RUN_ID':'999'}):
            path=Path(d)
            result=restore(path/MEMBER,path/'workflow_liveness_restore.json',http=http,now=NOW)
            return result,load_verified(path,now=NOW)

    def test_provider_bound_watchdog_receipt_restores(self):
        result,doc=self.try_restore(self.provider_fixture()[2])
        self.assertEqual(result,'RESTORED');self.assertIsNotNone(doc)

    def test_wrong_workflow_or_fork_does_not_supply_proof(self):
        for field,val in [('path','.github/workflows/unrelated.yml'),('head_sha','b'*40),('conclusion','failure')]:
            item,run,http=self.provider_fixture();run[field]=val
            result,doc=self.try_restore(http)
            self.assertEqual(result,'NO_VALID_LIVENESS_ARTIFACT');self.assertIsNone(doc)

    def test_modified_archive_digest_is_rejected(self):
        item,run,http=self.provider_fixture();item['digest']='sha256:'+'0'*64
        self.assertEqual(self.try_restore(http),('NO_VALID_LIVENESS_ARTIFACT',None))

    def test_old_run_attempt_or_future_receipt_is_rejected(self):
        item,run,http=self.provider_fixture();run['run_started_at']='2026-09-29T14:46:00Z'
        self.assertEqual(self.try_restore(http),('NO_VALID_LIVENESS_ARTIFACT',None))

    def test_watchdog_does_not_publish_or_reset_cost_ledger(self):
        root=Path(__file__).resolve().parents[1]
        s=(legacy_workflow_path(root/'.github/workflows/portfolio-cost-watchdog.yml')).read_text()
        self.assertIn('--metadata-output cost_governor/live/cost_restore.json',s)
        self.assertIn('--state-metadata cost_governor/live/cost_restore.json',s)
        self.assertNotIn('name: portfolio-cost-governor-state',s)
        self.assertNotIn('cost_governor.workflow_gate',s)
