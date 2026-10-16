"""Catch substituted evidence, optimistic recovery and duplicate work."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from brain.core import BrainError
from tests.test_brain_repair_patch_executor import FIXTURE, request

NOW='2026-10-16T07:00:00Z'
SHA='a'*40
REPO='P00NSMASHER/abvmschoolstarworld'

def asset(data=b'actual deployed bytes',status=200):
    return {'status':status,'body':data}

def project(pid='abvm',repo=REPO,state='NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL'):
    return dict(id=pid,repository=repo,repository_revision=SHA,source_check_state=state)

def run(ident=1,**changes):
    row=dict(id=ident,name='brain-cycle-v2',path='.github/workflows/brain-cycle.yml',head_branch='main',repository={'full_name':'P00NSMASHER/portfolio-brain'},head_sha=SHA,status='completed',conclusion='success',run_attempt=1,event='schedule',created_at='2026-10-16T06:49:00Z',updated_at='2026-10-16T06:50:00Z')
    row.update(changes)
    return row

class EngineeringTests(unittest.TestCase):
    def component(self,name):
        try: return importlib.import_module('brain.v8.'+name)
        except ModuleNotFoundError: self.fail('v8 '+name+' adapter is missing')

    def test_maps_cover_nine_projects_without_conflating_shared_repository(self):
        maps=self.component('inventory').project_maps([project()])
        self.assertEqual(len(maps),9)
        abvm=next(x for x in maps if x['project_id']=='abvm')
        self.assertEqual(abvm['source_sha'],SHA)
        self.assertIn('curriculum',abvm['verification_contract'])
        ret=next(x for x in maps if x['project_id']=='retally')
        lab=next(x for x in maps if x['project_id']=='research-labs')
        self.assertNotEqual(ret['owner'],lab['owner'])
        self.assertIsNone(ret['source_sha'])
        self.assertFalse(abvm['write_capability_verified'])

    def test_maps_refuse_identity_substitution_duplicates_and_unknown_state(self):
        fn=self.component('inventory').project_maps
        for rows in [[project(repo='attacker/fork')],[project(),project()],[project(state='APPROVE_EVERYTHING')],[dict(project(),repository_revision=True)]]:
            with self.subTest(rows=rows),self.assertRaises(BrainError): fn(rows)

    def test_live_asset_requires_original_matching_bytes_and_preserves_scope(self):
        fn=self.component('verification').probe_asset
        result=fn(lambda url:asset(),project_id='abvm',source_sha=SHA,url='https://p00nsmasher.github.io/abvmschoolstarworld/app.js',expected_sha256=hashlib.sha256(b'actual deployed bytes').hexdigest())
        self.assertEqual(result['status'],'ORIGINAL_ASSET_MATCH')
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['recovery_verified'])
        self.assertEqual(result['source_sha'],SHA)

    def test_redirect_bad_digest_oversize_and_unavailable_never_become_recovery(self):
        fn=self.component('verification').probe_asset
        for response in [asset(status=302),asset(b'wrong'),asset(b'x'*1048577)]:
            r=fn(lambda url:response,project_id='abvm',source_sha=SHA,url='https://p00nsmasher.github.io/abvmschoolstarworld/app.js',expected_sha256='b'*64)
            self.assertNotEqual(r['status'],'ORIGINAL_ASSET_MATCH')
            self.assertFalse(r['recovery_verified'])
        def unavailable(url): raise TimeoutError('private provider details')
        self.assertEqual(fn(unavailable,project_id='abvm',source_sha=SHA,url='https://p00nsmasher.github.io/abvmschoolstarworld/app.js',expected_sha256='b'*64)['status'],'UNAVAILABLE')

    def test_asset_destination_is_owned_exact_path_without_redirect_or_credentials(self):
        fn=self.component('verification').probe_asset
        for url in ['https://evil.test/a','https://p00nsmasher.github.io/other-project/a','https://u:p@p00nsmasher.github.io/abvmschoolstarworld/a','https://p00nsmasher.github.io/abvmschoolstarworld/%2e%2e/a','http://p00nsmasher.github.io/abvmschoolstarworld/a','https://p00nsmasher.github.io:444/abvmschoolstarworld/a']:
            with self.subTest(url=url),self.assertRaises(BrainError): fn(lambda u:self.fail('must not request rejected URL'),project_id='abvm',source_sha=SHA,url=url,expected_sha256='b'*64)

    def test_supervisor_keeps_original_failure_adverse_and_incomplete_attempts_unknown(self):
        fn=self.component('supervisor').supervise
        bad=run(conclusion='failure')
        self.assertEqual(fn({'total_count':1,'workflow_runs':[bad]},source_sha=SHA,now=NOW)['next_action'],'DIAGNOSE_ORIGINAL_FAILURE')
        retry=run(run_attempt=2)
        self.assertEqual(fn({'total_count':1,'workflow_runs':[retry]},source_sha=SHA,now=NOW)['status'],'ATTEMPT_CENSUS_REQUIRED')
        self.assertEqual(fn({'total_count':2,'workflow_runs':[run()]},source_sha=SHA,now=NOW)['status'],'INCOMPLETE_INVENTORY')

    def test_supervisor_distinguishes_stall_busy_and_current_health(self):
        fn=self.component('supervisor').supervise
        self.assertEqual(fn({'total_count':0,'workflow_runs':[]},source_sha=SHA,now=NOW)['next_action'],'USE_EXISTING_WATCHDOG')
        busy=run(status='in_progress',conclusion=None)
        self.assertEqual(fn({'total_count':1,'workflow_runs':[busy]},source_sha=SHA,now=NOW)['next_action'],'WAIT_FOR_ORIGINAL_RUN')
        good=fn({'total_count':1,'workflow_runs':[run()]},source_sha=SHA,now=NOW)
        self.assertEqual(good['status'],'RECENT_CORE_OBSERVED')
        self.assertFalse(good['production_accepted'])
        old=run(updated_at='2026-10-16T05:00:00Z',created_at='2026-10-16T04:59:00Z')
        self.assertEqual(fn({'total_count':1,'workflow_runs':[old]},source_sha=SHA,now=NOW)['next_action'],'USE_EXISTING_WATCHDOG')

    def test_manual_and_unrelated_workflows_do_not_refresh_automatic_execution(self):
        fn=self.component('supervisor').supervise
        for rows in [[run(event='workflow_dispatch')],
                     [run(event='workflow_dispatch'),run(2,updated_at='2026-10-16T04:00:00Z',created_at='2026-10-16T03:59:00Z')],
                     [run(path='.github/workflows/fake.yml')],
                     [run(head_branch='untrusted-branch')]]:
            with self.subTest(rows=rows):
                result=fn({'total_count':len(rows),'workflow_runs':rows},source_sha=SHA,now=NOW)
                self.assertNotEqual(result['status'],'RECENT_CORE_OBSERVED')
                self.assertFalse(result['production_accepted'])

    def test_supervisor_refuses_duplicate_future_and_malformed_run(self):
        fn=self.component('supervisor').supervise
        for rows in [[run(),run()],[run(updated_at='2026-10-17T06:00:00Z')],[run(head_sha=True)]]:
            with self.subTest(rows=rows),self.assertRaises(BrainError): fn({'total_count':len(rows),'workflow_runs':rows},source_sha=SHA,now=NOW)

    def test_research_suppresses_unchanged_failed_findings_without_claiming_license(self):
        fn=self.component('research').research_actions
        candidate=dict(key='org/repo:src/curriculum.py',target='school-tools',freshness='CURRENT',matched_terms=['curriculum','study'],test_paths=['tests/test_curriculum.py'],source_ref='https://github.com/org/repo/blob/'+'b'*40+'/src/curriculum.py')
        projects=[dict(project(),research_target='school-tools')]
        result=fn(projects,[candidate],[])
        self.assertEqual(len(result['experiments']),1)
        self.assertFalse(result['experiments'][0]['license_verified'])
        ident=result['experiments'][0]['finding_id']
        self.assertEqual(fn(projects,[candidate,candidate],[{'finding_id':ident,'outcome':'FAILED'}])['experiments'],[])
        irrelevant=dict(candidate,matched_terms=[])
        self.assertEqual(fn(projects,[irrelevant],[])['experiments'],[])
        forged=dict(candidate,source_ref='https://evil.test/source')
        self.assertEqual(fn(projects,[forged],[])['experiments'],[])

    def test_learning_survives_restart_deduplicates_and_rejects_conflicting_results(self):
        mod=self.component('learning')
        with tempfile.TemporaryDirectory() as folder:
            row=dict(schema_version=1,project_id='abvm',source_sha=SHA,attempt_id='b'*64,outcome='FAILED',data_kind='ACTUAL',evidence_id='c'*64,observed_at=NOW)
            first=mod.record_outcome(Path(folder),row)
            self.assertEqual(first['counts']['failed'],1)
            self.assertEqual(mod.record_outcome(Path(folder),row)['counts']['failed'],1)
            with self.assertRaises(BrainError): mod.record_outcome(Path(folder),dict(row,outcome='LIVE_VERIFIED'))
            self.assertNotIn('observations',first)
            self.assertIsNone(first['causal_benefit'])

    def test_simulated_learning_does_not_count_as_actual_live_success(self):
        fn=self.component('learning').record_outcome
        with tempfile.TemporaryDirectory() as folder:
            row=dict(schema_version=1,project_id='abvm',source_sha=SHA,attempt_id='b'*64,outcome='LIVE_VERIFIED',data_kind='SIMULATED',evidence_id='c'*64,observed_at=NOW)
            self.assertEqual(fn(Path(folder),row)['counts']['actual_live_verified'],0)

    def test_repair_bridge_generates_real_source_and_test_without_granting_release(self):
        fn=self.component('engineering').prepare_repair
        result=fn(request(),FIXTURE.encode())
        self.assertIn('persist-credentials: false',result['patch']['changed_content'])
        self.assertIn('independent',result['verification_contract'])
        self.assertFalse(result['runtime_actions_executed'])
        with self.assertRaises(BrainError): fn(dict(request(),command='curl secret'),FIXTURE.encode())
        with self.assertRaises(BrainError): fn(request(source_head_sha='z'*40),FIXTURE.encode())

    def test_trusted_recipe_reproduces_failure_then_passes_in_isolation(self):
        fn=getattr(self.component('engineering'),'exercise_repair',None)
        self.assertTrue(callable(fn),'isolated trusted recipe runner is missing')
        result=fn(request(),FIXTURE.encode())
        self.assertNotEqual(result['original_returncode'],0)
        self.assertEqual(result['corrected_returncode'],0)
        self.assertFalse(result['third_party_code_executed'])
        self.assertFalse(result['production_accepted'])

    def test_cycle_rotates_projects_and_promotes_real_adverse_evidence(self):
        fn=self.component('engineering').build_cycle
        report=dict(source_sha=SHA,projects=[project(),project('capturebrief','P00NSMASHER/capturebrief')])
        a=fn(report,source_sha=SHA,cycle=0,now=NOW)
        b=fn(report,source_sha=SHA,cycle=1,now=NOW)
        self.assertNotEqual(a['owner_jobs'][0]['project_id'],b['owner_jobs'][0]['project_id'])
        self.assertEqual(a['coverage']['registered'],9)
        self.assertEqual(a['coverage']['observed'],2)
        self.assertFalse(a['production_accepted'])
        self.assertEqual(a['runtime_actions_executed'],0)
        adverse=project(state='ADVERSE_CHECKS_OBSERVED')
        out=fn(dict(report,projects=[adverse]),source_sha=SHA,cycle=8,now=NOW)
        self.assertEqual(out['owner_jobs'][0]['project_id'],'abvm')
        self.assertEqual(out['owner_jobs'][0]['next_action'],'DIAGNOSE_REPRODUCE_AND_REPAIR')
        self.assertEqual(a['work_items'][0]['work_id'],fn(report,source_sha=SHA,cycle=0,now=NOW)['work_items'][0]['work_id'])

    def test_cycle_cli_runs_offline_without_source_or_authority_substitution(self):
        self.component('engineering')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'projects.json'
            path.write_text(json.dumps(dict(source_sha=SHA,projects=[project()])))
            cmd=[sys.executable,'-m','brain.v8','cycle','--input',str(path),'--source-sha',SHA,'--cycle','0','--now',NOW]
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(json.loads(p.stdout)['runtime_actions_executed'],0)
            path.write_text(json.dumps(dict(source_sha='f'*40,projects=[project()])))
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,2)
