"""Exact owner routing, privacy boundaries, and round-robin exclusion."""
import unittest
from brain.v9.batch_queue import BatchFault,PROJECTS
from brain.v9.batch_routing import route_defect,select_distinct_owners
SHA='a'*40

class RoutingTests(unittest.TestCase):
    def route(self,project,path,kind='FEATURE'):
        return route_defect(project_id=project,repository=PROJECTS[project],
                            source_sha=SHA,path=path,kind=kind)
    def test_real_lane_specificity_and_separate_verifier(self):
        cases=[
          ('portfolio-brain','brain/intelligence.py','PRODUCTION_INCIDENT','brain-reliability'),
          ('portfolio-brain','brain/v8/planning.py','FEATURE','brain-engineering'),
          ('abvm','scripts/teacher-data.mjs','DATA_ACCURACY','abvm-sources'),
          ('abvm','src/study-guide.mjs','USER_EXPERIENCE','abvm-guides'),
          ('abvm','src/mastery-scoring.mjs','DATA_ACCURACY','abvm-learning'),
          ('abvm','src/service-worker.mjs','PRODUCTION_INCIDENT','abvm-reliability'),
          ('retally','lab/reconciliation.py','DATA_ACCURACY','retally-evidence'),
          ('retally','web/index.tsx','USER_EXPERIENCE','retally-website'),
          ('permitplate','src/intake.py','FEATURE','retally-product'),
          ('research-labs','datasets/provenance.py','RESEARCH','research-provenance')]
        for project,path,kind,expected in cases:
            with self.subTest(project=project,path=path):
                outcome=self.route(project,path,kind)
                self.assertEqual(outcome['owner'],expected)
                self.assertNotEqual(outcome['owner'],outcome['verifier'])
                self.assertFalse(outcome['automatic_execution_authority'])
                self.assertEqual(outcome['provider_writes'],0)
    def test_unscoped_adverse_check_routes_to_reliability_without_prod_assertion(self):
        triage = self.route('portfolio-brain', 'repository-observation',
                            'CHECK_EVIDENCE_TRIAGE')
        self.assertEqual(triage['owner'], 'brain-reliability')
        self.assertEqual(triage['verifier'], 'brain-qa')
        self.assertEqual(triage['defect_kind'], 'CHECK_EVIDENCE_TRIAGE')
        self.assertFalse(triage['automatic_execution_authority'])

    def test_malformed_project_path_kind_and_source_denied(self):
        for row in [
            dict(project_id='unknown',repository='evil/repo',source_sha=SHA,path='src/main.py',kind='FEATURE'),
            dict(project_id='abvm',repository=PROJECTS['abvm'],source_sha=SHA,path='../secrets',kind='FEATURE'),
            dict(project_id='abvm',repository=PROJECTS['abvm'],source_sha='bad',path='src/app.js',kind='FEATURE'),
            dict(project_id='abvm',repository=PROJECTS['abvm'],source_sha=SHA,path='src/app.js',kind=[]),
        ]:
            with self.subTest(row=row),self.assertRaises(BatchFault):
                route_defect(**row)
    def test_rotating_same_owner_projects_without_parallel_assignment(self):
        rows=[]
        for project in ('capturebrief','permitplate'):
            item=self.route(project,'src/intake.py')
            item['priority']=0;rows.append(item)
        other=self.route('abvm','src/service-worker.mjs','PRODUCTION_INCIDENT')
        other['priority']=0;rows.append(other)
        seen=set()
        for cycle in range(6):
            plan=select_distinct_owners(rows,limit=3,cycle=cycle)
            self.assertEqual(len(plan['selected']),2)
            self.assertEqual(len({r['owner'] for r in plan['selected']}),2)
            self.assertFalse(plan['automatic_execution_authority'])
            seen.update(r['project_id'] for r in plan['selected'])
        self.assertEqual(seen,{'abvm','capturebrief','permitplate'})
    def test_bounds_and_duplicate_resources_fail_closed(self):
        item=self.route('abvm','src/service-worker.mjs','PRODUCTION_INCIDENT')
        item['priority']=0
        for bad in (0,6,True):
            with self.assertRaises(BatchFault):
                select_distinct_owners([item],limit=bad)
        result=select_distinct_owners([item,item.copy()],limit=2)
        self.assertEqual(len(result['selected']),1)
        self.assertEqual(len(result['deferred']),1)
if __name__=='__main__':unittest.main()
