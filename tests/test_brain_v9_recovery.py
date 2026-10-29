"""Read-only recovery controls across claims, unknown effects, and crashes."""
import copy,unittest
from brain.v9.batch_queue import BatchFault
from brain.v9.batch_recovery import recovery_plan
SHA='a'*40;T='2026-10-22T03:00:00Z';LATER='2026-10-22T03:25:00Z'
class FakeQueue:
    def __init__(self,work,drift=False):self.work=work;self.drift=drift;self.n=0
    def checkpoint(self):
        self.n+=1
        return {'sequence':self.n if self.drift else 7,'tip':SHA}
    def snapshot(self):return {'work':copy.deepcopy(self.work)}
def item(wid,*,pending=None,claim=None,stage='TESTED',effects=None):
    return dict(work_id=wid,created_at=T,project_id='abvm',owner='school-owner',
       source_sha=SHA,priority=1,stage=stage,pending=pending,claim=claim,effects=effects or {})
class RecoveryTests(unittest.TestCase):
    def test_unknown_write_survives_expired_lease_without_retry(self):
        wid='b'*64
        row=item(wid,pending={'operation_id':'c'*64,'status':'UNKNOWN'},
                 claim={'expires_at':'2026-10-22T03:10:00Z'})
        snapshot=copy.deepcopy(row)
        output=recovery_plan(FakeQueue({wid:row}),now=LATER)
        self.assertEqual(output['actions'][0]['next_action'],
                         'ORIGINAL_PROVIDER_RECONCILIATION_REQUIRED_NO_RETRY')
        self.assertEqual(output['uncertain_external_effects'],1)
        self.assertEqual(output['provider_writes'],0)
        self.assertEqual(row,snapshot)
    def test_active_and_expired_claims_have_separate_recovery(self):
        rows={'b'*64:item('b'*64,claim={'expires_at':'2026-10-22T03:10:00Z'}),
              'c'*64:item('c'*64,claim={'expires_at':'2026-10-22T03:40:00Z'})}
        output=recovery_plan(FakeQueue(rows),now=LATER)
        actions={x['work_id']:x['next_action'] for x in output['actions']}
        self.assertEqual(actions['b'*64],'REOBSERVE_SOURCE_BEFORE_NEW_FENCED_CLAIM')
        self.assertEqual(actions['c'*64],'LIVE_OWNER_LEASE_DO_NOT_REASSIGN')
    def test_drift_and_limit_fail_closed(self):
        with self.assertRaisesRegex(BatchFault,'RECOVERY_SNAPSHOT_MOVED'):
            recovery_plan(FakeQueue({},drift=True),now=LATER)
        with self.assertRaisesRegex(BatchFault,'RECOVERY_LIMIT_INVALID'):
            recovery_plan(FakeQueue({}),now=LATER,limit=6)
    def test_confirmed_draft_still_requires_real_issuer_evidence(self):
        wid='f'*64
        output=recovery_plan(FakeQueue({wid:item(wid,effects={'op':'draft'})}),now=LATER)
        self.assertEqual(output['actions'][0]['next_action'],
                         'VERIFY_ORIGINAL_INDEPENDENT_CHECKS')
        self.assertFalse(output['production_accepted'])
    def test_noncanonical_utc_clock_is_refused(self):
        for invalid in ('20261022T032500Z','2026-10-22T03:25:00.1234567Z',
                        '2026-10-22T03:25:00+00:00',True):
            with self.subTest(invalid=invalid),self.assertRaisesRegex(
                    BatchFault,'RECOVERY_CLOCK_INVALID'):
                recovery_plan(FakeQueue({}),now=invalid)

class DurableCrashRecovery(unittest.TestCase):
    def test_intent_survives_reopen_without_duplicate_write(self):
        import tempfile
        from pathlib import Path
        from brain.v9.batch_queue import BatchQueue
        from test_brain_v9_batch import issue, EVIDENCE, T0, T1, T2
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'queue.sqlite'
            queue = BatchQueue(path)
            work = queue.observe(issue(), now=T0)
            token = queue.claim(work, 'retally-product', now=T0, ttl_seconds=1200)
            for stage in ('DIAGNOSED','PATCHED','TESTED'):
                queue.advance(work, token, stage, evidence_sha=EVIDENCE, now=T1)
            operation = queue.begin_effect(work, token, action='CREATE_DRAFT_PR', now=T1)
            queue.close()
            queue = BatchQueue(path)
            try:
                before = queue.checkpoint()
                result = recovery_plan(queue, now=T2)
                self.assertEqual(result['actions'][0]['operation_id'], operation)
                self.assertEqual(result['actions'][0]['next_action'],
                                 'ORIGINAL_PROVIDER_RECONCILIATION_REQUIRED_NO_RETRY')
                self.assertEqual(result['provider_writes'], 0)
                self.assertEqual(queue.checkpoint(), before)
                with self.assertRaises(BatchFault):
                    queue.claim(work, 'retally-product', now=T2)
            finally:
                queue.close()

if __name__=='__main__':unittest.main()
