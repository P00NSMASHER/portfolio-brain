import importlib, json, pathlib, sys, unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).parent
sys.path.insert(0,str(ROOT))

class AuthorizedProbeTests(unittest.TestCase):
    def load(self):
        try: m=importlib.import_module('native_write_authorized_probe')
        except ImportError: m=None
        self.assertIsNotNone(m,'Authorized exact-head driver is not implemented')
        return m
    def test_fresh_exact_head(self):
        self.assertEqual(self.load().probe.HEAD,'4b874598aa00815c0fa0e63ec4a7159892654b01')
    def test_fresh_branch(self):
        self.assertEqual(self.load().probe.BRANCH,'canary/native-write-authorized-20261020')
    def test_lab_is_not_old_denied_request(self):
        self.assertEqual(self.load().probe.LAB,'review/native-write-authorized-20261020')
    def test_same_protected_base(self):
        self.assertEqual(self.load().probe.MAIN,'35ad71868f74e6d4f749a35630a1b86802b91ed0')
    def test_expected_head_binding_retained(self):
        self.assertIn('expectedHeadOid:$expected_head',self.load().probe.MUTATION)
    def test_source_pin_retained(self):
        self.assertEqual(self.load().HELPER_BLOB,'041056175a90d67bb05550d3696021871d72b0ac')
    def test_only_guarded_job_may_invoke(self):
        m=self.load()
        with patch.dict(m.os.environ,{'GITHUB_JOB':'other'},clear=True):
            with self.assertRaises(m.probe.Stop): m.check_context()
    def run_case(self,error=False,uncertain=False):
        m=self.load(); p=m.probe; calls=[]; number=900001; node='PR_1234567890123'
        def api(method,path,data=None):
            calls.append((method,path,data))
            if method=='POST':
                self.assertEqual(data['variables'],{'id':node,'expected_head':p.HEAD})
                if uncertain: raise TimeoutError('synthetic timeout')
                if error: return {'errors':[{'type':'FORBIDDEN','message':'must-not-appear'}]}
                return {'data':{'enablePullRequestAutoMerge':{'pullRequest':{'id':node,'headRefOid':p.HEAD,'autoMergeRequest':{'enabledAt':'2026-10-21T01:30:00Z'}}}}}
            return {'number':number,'node_id':node,'head':{'sha':p.HEAD},'state':'open','merged':False,'auto_merge':None if error or uncertain else {'merge_method':'squash'}}
        result=p.execute_once(api,number,node)
        self.assertEqual(sum(c[0]=='POST' for c in calls),1)
        self.assertEqual(result['permissions'],'contents:write,pull-requests:write')
        self.assertNotIn('must-not-appear',json.dumps(result))
        return result
    def test_success_requires_original_enrollment_readback(self):
        self.assertEqual(self.run_case()['status'],'NATIVE_ENROLLMENT_CONFIRMED')
    def test_forbidden_does_not_retry(self):
        self.assertEqual(self.run_case(error=True)['status'],'NATIVE_POST_REJECTED_FORBIDDEN')
    def test_uncertain_does_not_retry(self):
        self.assertEqual(self.run_case(uncertain=True)['status'],'UNKNOWN_AFTER_POST')

if __name__=='__main__': unittest.main(verbosity=2)
