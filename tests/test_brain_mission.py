import copy
import unittest

from brain.core import BrainError
from brain.mission import MISSION, mission_priorities
from brain.projects import build_project_portfolio, extended_repositories
from test_brain_projects import canonical_report, repo_row, SHA


class MissionTests(unittest.TestCase):
    def portfolio(self):
        return build_project_portfolio(canonical_report(),
            [repo_row(r) for r in extended_repositories()], source_sha=SHA)

    def test_all_registered_projects_are_covered_without_commercial_goal(self):
        report = self.portfolio()
        tasks = report["mission_priorities"]
        self.assertEqual({t["project_id"] for t in tasks},
                         {p["id"] for p in report["projects"]})
        self.assertEqual(len(tasks), 9)
        self.assertEqual(report["mission"], MISSION)
        self.assertTrue(all(not t["merge_or_deployment_authority"] for t in tasks))
        self.assertTrue(all(not t["delivered_improvement_verified"] for t in tasks))
        self.assertTrue(all(t["measured_result"] is None for t in tasks))

    def test_adverse_school_checks_outrank_green_commercial_project(self):
        projects = copy.deepcopy(self.portfolio()["projects"])
        for p in projects:
            p["source_check_state"] = "NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL"
            p["estimated_revenue"] = 999999 if p["id"] == "retally" else 0
        school = next(p for p in projects if p["id"] == "abvm")
        school["source_check_state"] = "ADVERSE_CHECKS_OBSERVED"
        for cycle in range(18):
            tasks = mission_priorities(projects, cycle=cycle)
            self.assertEqual(tasks[0]["project_id"], "abvm")
            self.assertEqual(tasks[0]["next_operation"], "DIAGNOSE_REPRODUCE_AND_REPAIR")

    def test_missing_evidence_is_verification_work_not_success(self):
        projects = self.portfolio()["projects"]
        for p in projects:
            p["source_check_state"] = "SOURCE_UNOBSERVED"
        tasks = mission_priorities(projects)
        self.assertTrue(all(t["next_operation"] == "VERIFY_CURRENT_SOURCE_AND_RUNTIME" for t in tasks))
        self.assertTrue(all(not t["delivered_improvement_verified"] for t in tasks))

    def test_equal_evidence_rotates_fairly_across_every_project(self):
        projects = self.portfolio()["projects"]
        for p in projects:
            p["source_check_state"] = "NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL"
        firsts = {mission_priorities(projects, cycle=i)[0]["project_id"]
                  for i in range(len(projects))}
        self.assertEqual(firsts, {p["id"] for p in projects})
        for cycle in [-1, True, 0.5, 2**63]:
            with self.assertRaises(BrainError):
                mission_priorities(projects, cycle=cycle)
