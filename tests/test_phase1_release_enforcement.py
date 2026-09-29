import copy
import unittest
import test_phase1_release_gate as base_tests
from verification.release_gate import verify_release


class Phase1ReleaseEnforcementTests(unittest.TestCase):
    def fixture(self):
        return base_tests.Phase1ReleaseGateTests().fixture()

    def run_case(self,f,api=None):
        return verify_release('owner/brain',1,'a'*40,gate_app_id=900,policy=f[0],
                              get_json=api or (lambda u:copy.deepcopy(f[1][u])))

    def test_candidate_cannot_rewrite_required_ci_workflow(self):
        f=self.fixture(); prefix='https://api.github.com/repos/owner/brain'; b='b'*40; h='a'*40
        f[1][f"{prefix}/contents/.github/workflows/foundation-ci.yml?ref={b}"]['sha']='1'*40
        f[1][f"{prefix}/contents/.github/workflows/foundation-ci.yml?ref={h}"]['sha']='2'*40
        with self.assertRaisesRegex(ValueError,'workflow changed'):
            self.run_case(f)

    def test_required_workflow_must_exist_on_base_and_head(self):
        f=self.fixture(); prefix='https://api.github.com/repos/owner/brain'; b='b'*40
        f[1][f"{prefix}/contents/.github/workflows/foundation-ci.yml?ref={b}"]['type']='dir'
        with self.assertRaisesRegex(ValueError,'workflow file missing'):
            self.run_case(f)

    def test_current_base_label_is_not_ancestry_proof(self):
        f=self.fixture(); c=next(v for k,v in f[1].items() if '/compare/' in k)
        c.update(status='diverged',behind_by=1,merge_base_commit={'sha':'c'*40})
        with self.assertRaisesRegex(ValueError,'contain current main'):self.run_case(f)

    def test_comparison_must_match_exact_base(self):
        f=self.fixture();c=next(v for k,v in f[1].items() if '/compare/' in k);c['base_commit']['sha']='c'*40
        with self.assertRaisesRegex(ValueError,'contain current main'):self.run_case(f)

    def test_green_ci_does_not_replace_branch_protection(self):
        f=self.fixture();f[1]['https://api.github.com/repos/owner/brain/branches/main']['protected']=False
        with self.assertRaisesRegex(ValueError,'live protection'):self.run_case(f)

    def test_green_ci_does_not_replace_effective_rules(self):
        f=self.fixture();f[1]['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1']=[]
        with self.assertRaisesRegex(ValueError,'live protection'):self.run_case(f)

    def test_gate_itself_must_be_required_from_correct_app(self):
        f=self.fixture();data=f[1]
        data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1'][-1]['parameters']['required_status_checks'][-1]['integration_id']=100
        data['https://api.github.com/repos/owner/brain/rulesets/55']['rules'][-1]['parameters']['required_status_checks'][-1]['integration_id']=100
        with self.assertRaisesRegex(ValueError,'live protection'):self.run_case(f)

    def test_check_link_cannot_borrow_another_jobs_result(self):
        f=self.fixture();f[3]['details_url']='https://github.com/owner/brain/actions/runs/7/job/999'
        with self.assertRaisesRegex(ValueError,'another job'):self.run_case(f)

    def test_job_check_binding_required(self):
        f=self.fixture();f[5]['check_run_url']='https://api.github.com/repos/owner/brain/check-runs/666'
        with self.assertRaisesRegex(ValueError,'not the required check'):self.run_case(f)

    def test_job_run_binding_required(self):
        f=self.fixture();f[5]['run_id']=666
        with self.assertRaisesRegex(ValueError,'wrong run/attempt'):self.run_case(f)

    def test_rerun_cannot_reuse_old_attempt_job(self):
        f=self.fixture();f[4]['run_attempt']=2
        with self.assertRaisesRegex(ValueError,'wrong run/attempt'):self.run_case(f)

    def test_source_fork_rejected(self):
        f=self.fixture();f[4]['head_repository']['full_name']='attacker/fork'
        with self.assertRaisesRegex(ValueError,'repository/fork'):self.run_case(f)

    def test_pr_wrong_repository_rejected(self):
        f=self.fixture();f[2]['base']['repo']['full_name']='other/repo'
        with self.assertRaisesRegex(ValueError,'target repository'):self.run_case(f)

    def test_run_restarted_during_verification_rejected(self):
        f=self.fixture();count=0
        def api(url):
            nonlocal count
            r=copy.deepcopy(f[1][url])
            if url.endswith('/actions/runs/7'):
                count+=1
                if count>1:r['run_attempt']=2
            return r
        with self.assertRaisesRegex(ValueError,'run changed'):self.run_case(f,api)

    def test_ci_replaced_during_verification_rejected(self):
        f=self.fixture();count=0
        def api(url):
            nonlocal count
            r=copy.deepcopy(f[1][url])
            if '/check-runs?' in url:
                count+=1
                if count>1:r['check_runs'][0]['id']=999
            return r
        with self.assertRaisesRegex(ValueError,'checks changed'):self.run_case(f,api)

    def test_pr_closed_during_verification_rejected(self):
        f=self.fixture();count=0
        def api(url):
            nonlocal count
            r=copy.deepcopy(f[1][url])
            if url.endswith('/pulls/1'):
                count+=1
                if count>1:r['state']='closed'
            return r
        with self.assertRaisesRegex(ValueError,'PR closed'):self.run_case(f,api)

    def test_required_step_string_not_allowed(self):
        f=self.fixture();f[0]['required_checks'][0]['required_steps']='Run regression tests'
        with self.assertRaisesRegex(ValueError,'step list'):self.run_case(f)

    def test_boolean_app_id_not_allowed(self):
        f=self.fixture();f[0]['required_checks'][0]['app_id']=True
        with self.assertRaisesRegex(ValueError,'check identity'):self.run_case(f)
