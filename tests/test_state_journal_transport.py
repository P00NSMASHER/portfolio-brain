"""Provider-bound source admission and real emitter integration tests."""
import copy
import gzip
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import seed_state
from state_journal.contracts import DOMAINS, JournalError, PRODUCERS, digest, strict_load, validate_source_evidence
from state_journal import legacy_parity, smoke_dispatch
from state_journal.emitter import capture
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, make_snapshot, validate_checkpoint
from state_journal.transport import (EVENT_PREFIX, EMIT_STEP, UPLOAD_STEP, REPO_ID, REPOSITORY,
                                     GitHubReader, extract_json, validate_provider_event)
from state_journal.github_reducer import reduce_from_provider
from test_state_journal import tick, SHA, fixture_evidence

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = json.loads((ROOT/'state_journal/UPLOAD_STEPS.json').read_text())


def fixture():
    before=seed_state();after=tick(before)
    event=make_event('runtime-worker','101',SHA,[make_change('heartbeat',before,after)])
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:archive.writestr('event.json',json.dumps(event))
    raw=output.getvalue()
    meta={'id':12,'name':f'{EVENT_PREFIX}101-runtime-worker-{SHA}-1','expired':False,
          'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),
          'workflow_run':{'id':101,'head_sha':SHA,'head_branch':'main','repository_id':REPO_ID,'head_repository_id':REPO_ID}}
    run={'id':101,'run_attempt':1,'head_sha':SHA,'head_branch':'main','event':'workflow_dispatch',
         'repository':{'full_name':REPOSITORY,'id':REPO_ID},'head_repository':{'full_name':REPOSITORY,'id':REPO_ID},
         'status':'completed','conclusion':'success','path':'.github/workflows/runtime-hourly-sync.yml','workflow_id':45}
    job={'id':20,'run_id':101,'run_attempt':1,'steps':[{'name':name,'status':'completed','conclusion':'success'}
         for name in [EMIT_STEP,UPLOAD_STEP,UPLOADS['runtime-worker']['heartbeat']]]}
    return meta,run,{'total_count':1,'jobs':[job]},raw,event


class StateJournalTransportTests(unittest.TestCase):
    def test_exact_source_and_publication_steps_admit_event(self):
        meta,run,jobs,raw,event=fixture()
        actual,evidence=validate_provider_event(meta,run,jobs,raw,UPLOADS)
        self.assertEqual(actual,event)
        validate_source_evidence(evidence, event)
        self.assertEqual(evidence['source_run_id'],101)
        self.assertEqual(evidence['source_conclusion'],'success')

    def test_failures_preserve_actual_published_state_without_claiming_work_success(self):
        meta,run,jobs,raw,event=fixture();run['conclusion']='failure'
        actual,evidence=validate_provider_event(meta,run,jobs,raw,UPLOADS)
        self.assertEqual(evidence['source_conclusion'],'failure')
        self.assertNotIn('value_verified',evidence)

    def test_foreign_stale_or_ambiguous_provider_metadata_is_rejected(self):
        changes=[
          lambda m,r,j:m.update(digest='sha256:'+'0'*64),
          lambda m,r,j:m.update(expired=True),
          lambda m,r,j:m.update(id=True),
          lambda m,r,j:m.update(name=m['name'][:-1]+'2'),
          lambda m,r,j:m['workflow_run'].update(id=999),
          lambda m,r,j:m['workflow_run'].update(head_sha='b'*40),
          lambda m,r,j:m['workflow_run'].update(head_branch='feature'),
          lambda m,r,j:m['workflow_run'].update(head_repository_id=999),
          lambda m,r,j:r.update(head_sha='b'*40),
          lambda m,r,j:r.update(head_branch='feature'),
          lambda m,r,j:r.update(event='pull_request'),
          lambda m,r,j:r.update(run_attempt=2),
          lambda m,r,j:r.update(status='in_progress'),
          lambda m,r,j:r.update(conclusion='skipped'),
          lambda m,r,j:r.update(path='.github/workflows/unregistered.yml'),
          lambda m,r,j:r.update(workflow_id=None),
          lambda m,r,j:r['head_repository'].update(full_name='attacker/fork'),
          lambda m,r,j:j.update(total_count=2),
          lambda m,r,j:j['jobs'][0].update(run_id=999),
          lambda m,r,j:j['jobs'][0].update(run_attempt=2),
          lambda m,r,j:j['jobs'].append(copy.deepcopy(j['jobs'][0])),
        ]
        for index,change in enumerate(changes):
            meta,run,jobs,raw,_=fixture();change(meta,run,jobs)
            with self.subTest(mutation=index),self.assertRaises(JournalError):
                validate_provider_event(meta,run,jobs,raw,UPLOADS)

    def test_matching_name_does_not_replace_successful_upload_step(self):
        for name in [EMIT_STEP,UPLOAD_STEP,UPLOADS['runtime-worker']['heartbeat']]:
            meta,run,jobs,raw,_=fixture()
            next(s for s in jobs['jobs'][0]['steps'] if s['name']==name)['conclusion']='skipped'
            with self.subTest(step=name),self.assertRaises(JournalError):validate_provider_event(meta,run,jobs,raw,UPLOADS)

    def test_duplicate_or_unsafe_zip_member_rejected(self):
        for extra in ['event.json','../payload.py','secret.txt']:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                z.writestr('event.json','{}');z.writestr(extra,'{}')
            with self.subTest(extra=extra),self.assertRaises(JournalError):extract_json(stream.getvalue(),'event.json')

    def test_open_ended_evidence_cannot_persist_private_fields(self):
        m,r,j,raw,e=fixture();_,source=validate_provider_event(m,r,j,raw,UPLOADS)
        source['customer_email']='not-allowed'
        with self.assertRaises(JournalError):validate_source_evidence(source,e)

    def test_fixture_cannot_masquerade_as_provider_authorization(self):
        e=fixture()[-1];source=fixture_evidence(e);source['kind']='GITHUB_ACTIONS'
        with self.assertRaises(JournalError):validate_source_evidence(source,e)

    def test_emitter_uses_only_successful_domain_uploads(self):
        before=seed_state();after=tick(before)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'agents/live').mkdir(parents=True);(root/'agents/out').mkdir(parents=True)
            (root/'agents/live/agent_heartbeat_state.json').write_text(json.dumps(before))
            (root/'agents/out/agent_heartbeat_state.json').write_text(json.dumps(after))
            published={'runtime':False,'heartbeat':True,'cost':False}
            event=capture(root,'runtime-worker','101',SHA,published)
            self.assertEqual([c['domain'] for c in event['changes']],['heartbeat'])
            self.assertEqual(event['changes'][0]['before'],before)
            self.assertEqual(event['changes'][0]['after'],after)

    def test_missing_or_nonboolean_publication_outcomes_fail_closed(self):
        for flags in [{}, {'runtime':False,'heartbeat':'true','cost':False}]:
            with self.assertRaises(JournalError):capture(Path('.'),'runtime-worker','101',SHA,flags)

    def test_no_successful_uploads_do_not_create_fake_activity(self):
        event=capture(Path('.'),'runtime-worker','101',SHA,{'runtime':False,'heartbeat':False,'cost':False})
        self.assertIsNone(event)

    def test_reported_upload_without_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td,self.assertRaises(JournalError):
            capture(Path(td),'runtime-worker','101',SHA,{'runtime':False,'heartbeat':True,'cost':False})

    def test_absent_canonical_snapshot_never_automatically_reboots_empty(self):
        class Reader:
            def list_recent_artifacts(self,*args):return []
        with self.assertRaisesRegex(JournalError,'CHECKPOINT_REQUIRED'):
            reduce_from_provider(Reader(),since='2026-09-29T14:00:00Z',current_run='999',upload_steps=UPLOADS)

    def test_explicit_initialization_preserves_exact_checkpoint(self):
        class Reader:
            def list_recent_artifacts(self,*args):return []
        base=checkpoint({'heartbeat':seed_state()},{'heartbeat':'fixture:heartbeat'})
        state,receipt=reduce_from_provider(Reader(),since='2026-09-29T14:00:00Z',current_run='999',upload_steps=UPLOADS,explicit_checkpoint=base)
        self.assertEqual(state['checkpoint'],base)
        self.assertEqual(state['sequence'],0)
        self.assertFalse(receipt['production_authority'])

    def test_checked_in_checkpoint_is_source_bound_and_complete(self):
        doc=strict_load(gzip.decompress((ROOT/'state_journal/CHECKPOINT.json.gz').read_bytes()))
        validate_checkpoint(doc)
        self.assertEqual(set(doc['states']),set(DOMAINS))
        self.assertEqual(set(doc['source_refs']),set(DOMAINS))
        self.assertTrue(all('github-actions:' in ref or 'repo-seed:' in ref for ref in doc['source_refs'].values()))
        self.assertEqual(doc['states']['heartbeat']['sequence'],142)
        self.assertEqual(doc['states']['history']['sequence'],144)
        self.assertIn('artifact=11048615497',doc['source_refs']['heartbeat'])
        self.assertIn('artifact=11048660700',doc['source_refs']['history'])
        policy=json.loads((ROOT/'state_journal/POLICY.json').read_text())
        self.assertEqual(policy['artifact_scan_start'],'2026-09-29T16:35:30Z')

    def test_legacy_parity_rejects_one_domain_drift(self):
        doc=strict_load(gzip.decompress((ROOT/'state_journal/CHECKPOINT.json.gz').read_bytes()))
        same=copy.deepcopy(doc['states'])
        refs={k:'fixture:'+k for k in same}
        with patch.object(legacy_parity,'restore_all',return_value=(same,refs)):
            self.assertEqual(legacy_parity.verify(doc['states'],Path('unused'))['status'],'PASS')
        drift=copy.deepcopy(same)
        domain=next(iter(sorted(drift)))
        drift[domain]['sequence']+=1
        with patch.object(legacy_parity,'restore_all',return_value=(drift,refs)):
            with self.assertRaisesRegex(JournalError,'LEGACY_PARITY_MISMATCH'):
                legacy_parity.verify(doc['states'],Path('unused'))

    def test_live_shadow_instrumentation_keeps_legacy_authoritative(self):
        for producer in PRODUCERS:
            text=(ROOT/'.github/workflows'/f'{producer}.yml').read_text()
            self.assertNotIn('PORTFOLIO_STATE_JOURNAL_ENABLED',text)
            self.assertIn('if: ${{ always() }}',text)
            self.assertIn('overwrite: false',text)
            self.assertIn('python -m state_journal.emitter --producer '+producer,text)
            for domain,name in UPLOADS[producer].items():
                self.assertIn(name,text)
                self.assertIn('steps.journal_upload_'+domain+".outcome == 'success'",text)

    def test_only_reducer_can_publish_canonical_journal(self):
        publishers=[]
        for p in (ROOT/'.github/workflows').glob('*.yml'):
            if 'name: portfolio-canonical-shadow-state' in p.read_text():publishers.append(p.name)
        self.assertEqual(publishers,['portfolio-state-reducer.yml'])
        text=(ROOT/'.github/workflows/portfolio-state-reducer.yml').read_text()
        self.assertIn('group: portfolio-state-reducer',text)
        self.assertNotIn('group: portfolio-state-writer-v1',text)
        self.assertIn('cancel-in-progress: false',text)
        self.assertIn('queue: max',text)
        self.assertNotIn('contents: write',text)
        self.assertIn('persist-credentials: false',text)
        self.assertNotIn('PORTFOLIO_STATE_JOURNAL_ENABLED',text)
        self.assertIn('legacy_parity.json',text)

    def test_shadow_smoke_uses_existing_dispatch_entrypoints_only(self):
        self.assertEqual(smoke_dispatch.TARGETS,(
            'hunter-autonomous-cycle.yml','portfolio-autonomous-scheduler.yml',
            'runtime-hourly-sync.yml','agent-heartbeat-sweep.yml'))
        workflow=(ROOT/'.github/workflows/step2-shadow-smoke.yml').read_text()
        self.assertIn('actions: write',workflow)
        self.assertIn('contents: read',workflow)
        self.assertNotIn('contents: write',workflow)
        self.assertIn('persist-credentials: false',workflow)
        self.assertIn('python -m state_journal.smoke_dispatch',workflow)
        self.assertIn('timeout-minutes: 12',workflow)
        for name in ('portfolio-autonomous-scheduler.yml','agent-heartbeat-sweep.yml'):
            text=(ROOT/'.github/workflows'/name).read_text()
            self.assertNotIn('\n  push:',text)

    def test_smoke_dispatch_requires_exact_merged_sha(self):
        source=(ROOT/'state_journal/smoke_dispatch.py').read_text()
        self.assertIn('row.get("head_sha") == expected_sha',source)
        self.assertIn('row.get("event") == "workflow_dispatch"',source)
        self.assertNotIn('repository_dispatch',source)
        self.assertIn('time.monotonic() + 300',source)
        self.assertIn('def wait_for_reducer',source)
        self.assertIn('portfolio-state-reducer',source)
        self.assertIn('STEP_2_CANONICAL_PRODUCTION_SMOKE',source)
        self.assertIn('canonical_reader_barrier_proven',source)

    def test_incomplete_artifact_pagination_cannot_be_treated_as_complete(self):
        reader=object.__new__(GitHubReader)
        reader.get=lambda _: {'artifacts':[{'id':i+1,'created_at':'2026-09-29T14:00:00Z'} for i in range(100)]}
        with self.assertRaisesRegex(JournalError,'scan incomplete'):
            reader.list_recent_artifacts('2026-09-29T00:00:00Z',max_pages=1)

    def test_artifact_boundary_filters_after_full_bounded_scan_even_when_order_is_scrambled(self):
        reader=object.__new__(GitHubReader)
        reader.get=lambda _: {'artifacts':[
            {'id':1,'created_at':'2026-09-28T14:00:00Z'},
            {'id':3,'created_at':'2026-09-29T15:00:00Z'},
            {'id':2,'created_at':'2026-09-29T14:00:00Z'}]}
        rows=reader.list_recent_artifacts('2026-09-29T00:00:00Z')
        self.assertEqual([row['id'] for row in rows],[3,2])

    def test_exact_duplicate_artifact_rows_across_pages_are_deduplicated(self):
        reader=object.__new__(GitHubReader)
        row={'id':7,'created_at':'2026-09-29T14:00:00Z'}
        calls=[]
        def get(_):
            calls.append(1)
            return {'artifacts':([row]*100 if len(calls)==1 else [row])}
        reader.get=get
        rows=reader.list_recent_artifacts('2026-09-29T00:00:00Z')
        self.assertEqual(rows,[row])

    def test_policy_authority_flags_are_stage_consistent(self):
        policy=json.loads((ROOT/'state_journal/POLICY.json').read_text())
        self.assertIn(policy['mode'],{'SHADOW','CANONICAL_READY','CANONICAL'})
        self.assertFalse(policy['steps_3_to_8_started'])
        if policy['mode']=='SHADOW':
            self.assertFalse(policy['production_readers_enabled'])
            self.assertFalse(policy['production_cutover_complete'])
        elif policy['mode']=='CANONICAL_READY':
            self.assertTrue(policy['canonical_snapshot_authorized'])
            self.assertFalse(policy['production_readers_enabled'])
            self.assertFalse(policy['production_cutover_complete'])
        else:
            self.assertTrue(policy['canonical_snapshot_authorized'])
            self.assertTrue(policy['production_readers_enabled'])
            self.assertTrue(policy['production_cutover_complete'])


if __name__ == '__main__':unittest.main()