import unittest
import json
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
