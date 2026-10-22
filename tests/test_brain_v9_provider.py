"""Adversarial original issuer/readback admission tests (no network)."""
import unittest
from unittest.mock import patch
from brain.v9.batch_queue import BatchFault
from brain.v9.batch_provider import GitHubOriginalReader,validate_original_checks
R='P00NSMASHER/portfolio-brain';SHA='a'*40;BASE='b'*40;OP='c'*64
def checks():
    return dict(total_count=2,check_runs=[
       dict(name='validate',head_sha=SHA,status='completed',conclusion='success',app=dict(id=15368)),
       dict(name='portfolio-phase1-gate',head_sha=SHA,status='completed',conclusion='success',app=dict(id=5121826))])
def pr():
    return dict(number=741,draft=True,state='open',merged=False,
       head=dict(sha=SHA,repo=dict(full_name=R)),
       base=dict(sha=BASE,ref='main',repo=dict(full_name=R)),
       body='BRAIN_BATCH_OPERATION_ID: '+OP)
class ReadbackTests(unittest.TestCase):
    def test_valid_original_and_adverse_check_issuers(self):
        self.assertEqual(validate_original_checks(checks(),SHA)['status'],'ORIGINAL_CHECK_ISSUERS_MATCHED')
        cases=[]
        m=checks();m['check_runs'].pop();m['total_count']=1;cases.append(m)
        m=checks();m['check_runs'][1]['app']['id']=999;cases.append(m)
        m=checks();m['check_runs'][1]['head_sha']=BASE;cases.append(m)
        m=checks();m['check_runs'][1]['conclusion']='failure';cases.append(m)
        m=checks();m['check_runs'].append(m['check_runs'][1].copy());m['total_count']=3;cases.append(m)
        m=checks();m['total_count']=101;cases.append(m)
        for row in cases:
            with self.subTest(row=row),self.assertRaises(BatchFault):
                validate_original_checks(row,SHA)
    def test_readback_is_exact_head_and_operation_bound(self):
        r=GitHubOriginalReader()
        with patch.object(r,'_get',side_effect=[
            {'commit':{'sha':BASE}},pr(),checks(),{'commit':{'sha':BASE}}]) as get:
            item=r.verify_draft_and_checks(R,741,base_sha=BASE,head_sha=SHA,operation_id=OP)
        self.assertEqual(item['status'],'OBSERVED_BY_GITHUB_READBACK_NOT_RELEASED')
        self.assertFalse(item['production_accepted'])
        self.assertFalse(item['six_hour_acceptance_passed'])
        self.assertEqual(get.call_count,4)
    def test_head_marker_and_main_drift_are_refused(self):
        for defect in ('head','marker','main'):
            row=pr()
            if defect=='head':row['head']['sha']='d'*40
            if defect=='marker':row['body']=''
            tip='d'*40 if defect=='main' else BASE
            reader=GitHubOriginalReader()
            with patch.object(reader,'_get',side_effect=[
                {'commit':{'sha':BASE}},row,checks(),{'commit':{'sha':tip}}]):
                with self.subTest(defect=defect),self.assertRaises(BatchFault):
                    reader.verify_draft_and_checks(R,741,base_sha=BASE,head_sha=SHA,operation_id=OP)
    def test_uncertain_pr_creation_is_reconciled_without_green_checks(self):
        r=GitHubOriginalReader()
        with patch.object(r,'_get',side_effect=[
            {'commit':{'sha':BASE}},pr(),{'commit':{'sha':BASE}}]) as get:
            evidence=r.read_draft_only(R,741,base_sha=BASE,head_sha=SHA,operation_id=OP)
        self.assertEqual(get.call_count,3)
        self.assertEqual(evidence['status'],'ORIGINAL_DRAFT_WRITE_OBSERVED_CHECKS_UNKNOWN')
        self.assertFalse(evidence['independent_check_verified'])
        self.assertFalse(evidence['production_accepted'])

    def test_max_gets_and_scoped_repositories(self):
        with self.assertRaises(ValueError):GitHubOriginalReader(max_gets=25)
        reader=GitHubOriginalReader(max_gets=1)
        for repo,no in (('evil/repo',741),(R,-1)):
            with self.assertRaises(BatchFault):
                reader.verify_draft_and_checks(repo,no,base_sha=BASE,head_sha=SHA,operation_id=OP)
        self.assertEqual(reader.gets_remaining,1)
if __name__=='__main__':unittest.main()
