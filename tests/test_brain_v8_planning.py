"""Catch incident starvation, dependency bypass and mutation of caller evidence."""
import copy
import unittest
from brain.core import BrainError
from test_brain_v8_contracts import work
try:
    from brain.v8.planning import select_work
except ImportError:
    select_work=None


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(select_work),'v8 planning is missing')

    def test_incident_precedes_profitable_upgrade(self):
        rows=[work('school',priority_tier=0),work('retally',priority_tier=3)]
        for cycle in range(12):
            out=select_work(rows,cycle=cycle,limit=1)
            self.assertEqual(out['selected'][0]['project_id'],'school')
            self.assertFalse(out['automatic_execution_authority'])
        with self.assertRaises(BrainError):
            select_work([dict(rows[1],estimated_revenue=999999)],cycle=0,limit=1)

    def test_equal_priority_projects_rotate(self):
        rows=[work('project-'+str(i)) for i in range(9)]
        before=copy.deepcopy(rows)
        first=[select_work(rows,cycle=i,limit=1)['selected'][0]['project_id'] for i in range(9)]
        self.assertEqual(len(set(first)),9)
        self.assertEqual(rows,before)
        self.assertEqual(len(select_work(rows,cycle=0,limit=5)['deferred']),4)

    def test_one_project_cannot_fill_batch_ahead_of_peer(self):
        rows=[work('a',fingerprint=str(i)*64) for i in range(5)]+[work('b')]
        out=select_work(rows,cycle=0,limit=2)
        self.assertEqual([r['project_id'] for r in out['selected']],['a','b'])

    def test_unknown_self_cyclic_and_unfinished_dependencies_block(self):
        a,b=work('a'),work('b')
        cases=[([dict(a,dependencies=['work:'+'9'*64])],'DEPENDENCY_UNKNOWN'),
               ([dict(a,dependencies=[a['work_id']])],'DEPENDENCY_CYCLE'),
               ([dict(a,dependencies=[b['work_id']]),dict(b,dependencies=[a['work_id']])],'DEPENDENCY_CYCLE'),
               ([dict(a,dependencies=[b['work_id']]),b],'DEPENDENCY_UNFINISHED')]
        for rows,code in cases:
            with self.subTest(code=code):
                out=select_work(rows,cycle=0,limit=5)
                self.assertNotIn(a['work_id'],[r['work_id'] for r in out['selected']])
                self.assertIn(code,[r['reason'] for r in out['blocked_dependencies']])
        out=select_work([dict(a,dependencies=[b['work_id']]),dict(b,state='LEARNED')],cycle=0,limit=5)
        self.assertEqual([r['project_id'] for r in out['selected']],['a'])

    def test_oldest_semantic_time_first_within_project(self):
        older=work(fingerprint='1'*64,updated_at='2026-10-15T20:00:00Z')
        newer=work(fingerprint='2'*64,updated_at='2026-10-15T20:00:00.000001Z')
        self.assertEqual(select_work([newer,older],cycle=0,limit=1)['selected'][0]['work_id'],older['work_id'])

    def test_bounds_and_inactive_states(self):
        for cycle,limit in [(True,1),(-1,1),(2**63,1),(0,True),(0,0),(0,6)]:
            with self.assertRaises(BrainError): select_work([work()],cycle=cycle,limit=limit)
        with self.assertRaises(BrainError): select_work([work(),work()],cycle=0,limit=1)
        with self.assertRaises(BrainError): select_work([work()]*257,cycle=0,limit=1)
        out=select_work([work(state='FAILED'),work('other',state='LEARNED')],cycle=0,limit=5)
        self.assertEqual(out['selected'],[])
        self.assertEqual(select_work([],cycle=0,limit=1)['selected'],[])

    def test_shared_completed_dependency_graph_finishes_within_bound(self):
        import subprocess,sys
        code="""import sys
sys.path.insert(0,'tests')
from test_brain_v8_contracts import work
from brain.v8.planning import select_work
rows=[]
for i in range(40):
 row=work('p'+str(i),state='LEARNED')
 row['dependencies']=[r['work_id'] for r in rows[-2:]]
 rows.append(row)
rows[-1]['state']='OBSERVED'
assert len(select_work(rows,cycle=0,limit=1)['selected'])==1
"""
        try:
            result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=5)
        except subprocess.TimeoutExpired:
            self.fail('bounded shared dependency graph exceeded five seconds')
        self.assertEqual(result.returncode,0,result.stderr)
