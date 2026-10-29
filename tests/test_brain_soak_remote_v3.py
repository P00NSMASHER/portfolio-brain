import unittest
import json
from urllib import error
from soak_v3.remote_probe import GitHubReadOnly,git_blob_hash,verify_native_run
from soak_v3.audit import EvidenceError,REQUIRED_STEPS
SHA='a'*40
class RemoteProofTests(unittest.TestCase):
    def fake(self,event='schedule',conclusion='success',jobs=True):
        run={'id':55,'event':event,'head_sha':SHA,'head_branch':'main','status':'completed','conclusion':conclusion,'run_attempt':1}
        job={'name':'monitor','status':'completed','conclusion':'success','steps':[{'name':s,'conclusion':'success'} for s in REQUIRED_STEPS]}
        data={'/actions/runs/55':run,'/branches/main':{'commit':{'sha':SHA}},'/actions/runs/55/jobs?per_page=100':{'total_count':1,'jobs':[job]},'/actions/runs/55/artifacts?per_page=100':{'artifacts':[{'id':123,'name':'brain-v2-cycle-'+SHA+'-55-1','expired':False,'workflow_run':{'id':55,'head_sha':SHA}}]}}
        return GitHubReadOnly('',transport=lambda p:json.dumps(data[p]).encode())
    def test_native_run_provider_identities(self):
        self.assertEqual(verify_native_run(self.fake(),55,SHA)['id'],123)
    def test_manual_fails_provider_identity(self):
        with self.assertRaisesRegex(EvidenceError,'NATIVE_SCHEDULE_EVENT_NOT_VERIFIED'):
            verify_native_run(self.fake(event='workflow_dispatch'),55,SHA)
    def test_failed_job_cannot_be_counted(self):
        with self.assertRaisesRegex(EvidenceError,'NATIVE_RUN_FAILED_OR_RETRIED'):
            verify_native_run(self.fake(conclusion='failure'),55,SHA)
    def test_blob_hash_includes_git_object_header(self):
        self.assertEqual(git_blob_hash(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')

    def test_transient_provider_failure_retries_with_bounded_backoff(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*_): return False
            def read(self,_): return b'{}'
        class Opener:
            calls=0
            def open(self,*_,**__):
                self.calls+=1
                if self.calls<3: raise error.URLError('synthetic transient')
                return Response()
        delays=[]
        api=GitHubReadOnly('token',max_calls=3,max_attempts=3,sleep=delays.append)
        api.opener=Opener()
        self.assertEqual(api.get('/branches/main'),b'{}')
        self.assertEqual(api.calls,3)
        self.assertEqual(delays,[1,2])

    def test_permanent_provider_failure_is_bounded_and_fail_closed(self):
        class Opener:
            def open(self,*_,**__): raise error.URLError('synthetic unavailable')
        delays=[]
        api=GitHubReadOnly('token',max_calls=3,max_attempts=3,sleep=delays.append)
        api.opener=Opener()
        with self.assertRaisesRegex(EvidenceError,'GITHUB_API_UNAVAILABLE'):
            api.get('/actions/artifacts/1/zip')
        self.assertEqual(api.calls,3)
        self.assertEqual(delays,[1,2])

    def test_nonretryable_http_failure_is_not_reported_as_success(self):
        class Opener:
            def open(self,*_,**__):
                raise error.HTTPError('https://api.github.com',404,'missing',{},None)
        delays=[]
        api=GitHubReadOnly('token',max_calls=3,max_attempts=3,sleep=delays.append)
        api.opener=Opener()
        with self.assertRaisesRegex(EvidenceError,'GITHUB_API_HTTP_REJECTED'):
            api.get('/actions/artifacts/1/zip')
        self.assertEqual(api.calls,1)
        self.assertEqual(delays,[])

    def test_json_preserves_provider_and_budget_failure_reasons(self):
        class Opener:
            def open(self,*_,**__): raise error.URLError('unavailable')
        for budget,reason in [(3,'GITHUB_API_UNAVAILABLE'),(1,'API_CALL_BUDGET')]:
            api=GitHubReadOnly('token',max_calls=budget,sleep=lambda _:None)
            api.opener=Opener()
            with self.subTest(budget=budget),self.assertRaisesRegex(EvidenceError,reason):
                api.json('/branches/main')
            self.assertEqual(api.calls,budget)
        api=GitHubReadOnly('token',transport=lambda _:b'not json')
        with self.assertRaisesRegex(EvidenceError,'API_JSON_INVALID'):
            api.json('/branches/main')

    def test_retryable_http_codes_exhaust_with_precise_reasons(self):
        for status,reason in [(403,'GITHUB_API_QUOTA_OR_FORBIDDEN'),(429,'GITHUB_API_RATE_LIMITED'),(503,'GITHUB_API_UNAVAILABLE')]:
            class Opener:
                def open(self,*_,**__):
                    raise error.HTTPError('https://api.github.com',status,'unavailable',{},None)
            delays=[]
            api=GitHubReadOnly('token',max_calls=3,sleep=delays.append)
            api.opener=Opener()
            with self.subTest(status=status),self.assertRaisesRegex(EvidenceError,reason):
                api.json('/branches/main')
            self.assertEqual(api.calls,3)
            self.assertEqual(delays,[1,2])
