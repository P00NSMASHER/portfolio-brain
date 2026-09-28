import copy
import unittest
from verification.release_gate import verify_release
from test_phase1_protection import protection_fixture


class Phase1ReleaseGateTests(unittest.TestCase):
    def fixture(self):
        # Simulated provider responses only; these are not live integration proof.
        h='a'*40;b='b'*40
        policy={'schema_version':'2.0.0','gate_check_name':'portfolio-phase1-gate','trusted_gate_app_id':900,'approved_reviewer_ids':[222], 'required_checks':[{'name':'validate','app_id':100,'workflow_id':123,'workflow_path':'.github/workflows/foundation-ci.yml','job_name':'validate','required_steps':['Run regression tests','Validate historical policy replay']} ]}
        pr={'state':'open','draft':False,'head':{'sha':h,'repo':{'full_name':'owner/brain'}},'base':{'sha':b,'ref':'main','repo':{'full_name':'owner/brain'}},'user':{'id':111}}
        check={'id':1,'name':'validate','head_sha':h,'app':{'id':100},'status':'completed','conclusion':'success','details_url':'https://github.com/owner/brain/actions/runs/7/job/8'}
        run={'id':7,'head_sha':h,'workflow_id':123,'path':'.github/workflows/foundation-ci.yml','status':'completed','conclusion':'success','run_attempt':1,'repository':{'full_name':'owner/brain'},'head_repository':{'full_name':'owner/brain'}}
        job={'id':8,'run_id':7,'run_attempt':1,'status':'completed','check_run_url':'https://api.github.com/repos/owner/brain/check-runs/1','name':'validate','head_sha':h,'conclusion':'success','steps':[{'name':n,'status':'completed','conclusion':'success'} for n in policy['required_checks'][0]['required_steps']]}
        reviews=[{'id':10,'state':'APPROVED','commit_id':h,'user':{'id':222}}]
        prefix='https://api.github.com/repos/owner/brain'
        data={f'{prefix}/pulls/1':pr,f'{prefix}/branches/main':{'commit':{'sha':b}},f'{prefix}/commits/{h}/check-runs?filter=latest&per_page=100':{'total_count':1,'check_runs':[check]},f'{prefix}/actions/runs/7':run,f'{prefix}/actions/runs/7/jobs?filter=latest&per_page=100':{'total_count':1,'jobs':[job]},f'{prefix}/pulls/1/reviews?per_page=100':reviews}
        data.update(protection_fixture())
        data[f'{prefix}/compare/{b}...{h}']={'base_commit':{'sha':b},'merge_base_commit':{'sha':b},'behind_by':0,'status':'ahead'}
        return policy,data,pr,check,run,job,reviews

    def run_fixture(self,f):
        p,data,*_=f
        return verify_release('owner/brain',1,'a'*40,gate_app_id=900,policy=p,get_json=lambda u:copy.deepcopy(data[u]))

    def test_positive_simulated_provider_path_does_not_merge(self):
        result=self.run_fixture(self.fixture())
        self.assertEqual(result['status'],'EVIDENCE_VALIDATED_NOT_MERGED')
        self.assertFalse(result['merge_performed'])
        self.assertFalse(result['authority_granted'])

    def test_default_policy_cannot_authorize_itself(self):
        with self.assertRaises(ValueError):
            verify_release('owner/brain',1,'a'*40,get_json=lambda _:self.fail('no network before configuration'))

    def test_skipped_neutral_cancelled_checks_rejected(self):
        for value in ['skipped','neutral','cancelled','failure',None]:
            with self.subTest(value=value):
                f=self.fixture();f[3]['conclusion']=value
                with self.assertRaises(ValueError):self.run_fixture(f)

    def test_missing_or_skipped_required_step_rejected(self):
        for mutate in [lambda j:j['steps'].pop(),lambda j:j['steps'][0].update(conclusion='skipped')]:
            f=self.fixture();mutate(f[5])
            with self.assertRaises(ValueError):self.run_fixture(f)

    def test_untrusted_check_issuer_rejected(self):
        f=self.fixture();f[3]['app']['id']=666
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_stale_check_revision_rejected(self):
        f=self.fixture();f[3]['head_sha']='c'*40
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_workflow_identity_not_inferred_from_check_name(self):
        f=self.fixture();f[4]['workflow_id']=999
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_review_from_author_not_independent(self):
        f=self.fixture();f[0]['approved_reviewer_ids']=[111];f[6][0]['user']['id']=111
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_new_head_invalidates_approval(self):
        f=self.fixture();f[6][0]['commit_id']='c'*40
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_dismissed_review_invalidates_old_approval(self):
        f=self.fixture();f[6].append({'id':11,'state':'DISMISSED','commit_id':'a'*40,'user':{'id':222}})
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_pending_changes_request_blocks_release(self):
        f=self.fixture();f[6].append({'id':11,'state':'CHANGES_REQUESTED','commit_id':'a'*40,'user':{'id':333}})
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_draft_or_old_base_block_release(self):
        for mutate in [lambda p:p.update(draft=True),lambda p:p['base'].update(sha='c'*40)]:
            f=self.fixture();mutate(f[2])
            with self.assertRaises(ValueError):self.run_fixture(f)

    def test_gate_cannot_be_candidate_ci_principal(self):
        f=self.fixture();f[0]['required_checks'][0]['app_id']=900
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_incomplete_check_listing_rejected(self):
        f=self.fixture();next(v for k,v in f[1].items() if '/check-runs?' in k)['total_count']=101
        with self.assertRaises(ValueError):self.run_fixture(f)

    def test_head_update_during_verification_rejected(self):
        f=self.fixture();calls=0
        def api(url):
            nonlocal calls
            result=copy.deepcopy(f[1][url])
            if url.endswith('/pulls/1'):
                calls+=1
                if calls>1:result['head']['sha']='c'*40
            return result
        with self.assertRaises(ValueError):verify_release('owner/brain',1,'a'*40,gate_app_id=900,policy=f[0],get_json=api)
