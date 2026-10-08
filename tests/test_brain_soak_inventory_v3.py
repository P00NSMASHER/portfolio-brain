import unittest
from soak_v3.provider_inventory import collect_core_run_inventory
from soak_v3.audit import EvidenceError
START='2026-10-08T02:00:00Z'
END='2026-10-08T04:00:00Z'
CORE='.github/workflows/brain-cycle.yml'

def row(number,path=CORE,event='schedule'):
    return {'id':number,'path':path,'event':event,'head_sha':'a'*40,
            'created_at':'2026-10-08T02:30:00Z',
            'run_attempt':1,'status':'completed','conclusion':'success'}

class API:
    def __init__(self,results):self.results=list(results);self.calls=0
    def json(self,_):
        self.calls+=1
        return self.results[self.calls-1]

class ProviderInventoryTests(unittest.TestCase):
    def test_complete_inventory_includes_failed_manual_and_push(self):
        records=[row(11),row(12,event='workflow_dispatch'),row(13,event='push'),row(14,path='.github/workflows/foundation-ci.yml')]
        records[1]['conclusion']='failure'
        result=collect_core_run_inventory(API([{'total_count':4,'workflow_runs':records}]),
                                           started_at=START,ended_at=END)
        self.assertTrue(result['coverage_complete'])
        self.assertFalse(result['soak_pass'])
        self.assertEqual([x['run_id'] for x in result['core_runs']],[11,12,13])
        self.assertEqual(result['core_runs'][1]['conclusion'],'failure')

    def test_complete_two_page_inventory(self):
        records=[row(i+1,path=CORE if i in (0,100) else '.github/workflows/foundation-ci.yml') for i in range(101)]
        result=collect_core_run_inventory(API([{'total_count':101,'workflow_runs':records[:100]},
                                                {'total_count':101,'workflow_runs':records[100:]}]),
                                         started_at=START,ended_at=END)
        self.assertEqual([x['run_id'] for x in result['core_runs']],[1,101])
        self.assertEqual(result['total_repo_runs_in_window'],101)

    def test_truncated_last_page_refused(self):
        api=API([{'total_count':102,'workflow_runs':[row(i+1) for i in range(100)]},
                 {'total_count':102,'workflow_runs':[row(101)]}])
        with self.assertRaisesRegex(EvidenceError,'INVENTORY_TRUNCATED_PAGE'):
            collect_core_run_inventory(api,started_at=START,ended_at=END)

    def test_changing_history_refused(self):
        api=API([{'total_count':101,'workflow_runs':[row(i+1) for i in range(100)]},
                 {'total_count':102,'workflow_runs':[row(101),row(102)]}])
        with self.assertRaisesRegex(EvidenceError,'INVENTORY_CHANGING_DURING_SCAN'):
            collect_core_run_inventory(api,started_at=START,ended_at=END)

    def test_duplicate_identity_refused(self):
        api=API([{'total_count':2,'workflow_runs':[row(11),row(11)]}])
        with self.assertRaisesRegex(EvidenceError,'INVENTORY_DUPLICATE_OR_INVALID_RUN'):
            collect_core_run_inventory(api,started_at=START,ended_at=END)

    def test_unknown_core_trigger_not_hidden(self):
        api=API([{'total_count':1,'workflow_runs':[row(11,event='repository_dispatch')]}])
        with self.assertRaisesRegex(EvidenceError,'INVENTORY_UNEXPECTED_CORE_TRIGGER'):
            collect_core_run_inventory(api,started_at=START,ended_at=END)

    def test_page_cap_fails_closed(self):
        api=API([{'total_count':501,'workflow_runs':[]}])
        with self.assertRaisesRegex(EvidenceError,'INVENTORY_UNBOUNDED_OR_INVALID'):
            collect_core_run_inventory(api,started_at=START,ended_at=END)

    def test_zero_records_is_not_soak_pass(self):
        result=collect_core_run_inventory(API([{'total_count':0,'workflow_runs':[]}]),started_at=START,ended_at=END)
        self.assertEqual(result['core_count'],0)
        self.assertFalse(result['soak_pass'])
