import unittest
from dashboard.executive_dashboard import build_dashboard_snapshot,render_markdown

class ExecutiveDashboardTests(unittest.TestCase):
    def setUp(self):self.s=build_dashboard_snapshot()
    def test_all_registered_projects_are_present(self):
        self.assertEqual(self.s["project_count"],12)
        self.assertEqual({p["project_id"] for p in self.s["projects"]},{f"PRJ-{i:03d}" for i in range(12)})
    def test_dashboard_grants_no_authority(self):
        self.assertEqual(self.s["authority_class"],"OBSERVE")
        self.assertIn("No dashboard field grants authority or executes work.",render_markdown(self.s))
        self.assertTrue(all("authority_granted" not in p for p in self.s["projects"]))
    def test_missing_outcomes_are_not_invented(self):
        self.assertTrue(all(p["recent_measured_outcomes"]==[] for p in self.s["projects"]))
        self.assertTrue(all(p["measured_outcome_status"]=="NONE_IN_CHECKED_IN_VERIFIED_LEDGER" for p in self.s["projects"]))
    def test_measured_costs_are_zero_from_empty_checked_in_cost_ledger(self):
        self.assertEqual(self.s["portfolio"]["checked_in_measured_model_cost_usd"],0.0)
        self.assertTrue(all(p["model_costs"]["measured_usd"]==0 for p in self.s["projects"]))
    def test_estimates_never_become_measured(self):
        self.assertFalse(self.s["portfolio"]["estimated_value_presented_as_measured"])
        self.assertIn("ESTIMATED VALUE",render_markdown(self.s))
    def test_health_is_evidence_coverage_not_score(self):
        self.assertTrue(all(p["health"] in {"BLOCKED","EVIDENCE_GAPS","UNKNOWN"} for p in self.s["projects"]))
        self.assertTrue(all(p["health_basis"]=="EVIDENCE_COVERAGE_NOT_SUBJECTIVE_SCORE" for p in self.s["projects"]))
    def test_permitplate_surfaces_open_blocker(self):
        p=next(x for x in self.s["projects"] if x["project_id"]=="PRJ-003")
        self.assertIn("BLK-001",p["open_blockers"])
    def test_current_portfolio_queue_is_visible(self):
        self.assertGreaterEqual(self.s["portfolio"]["pending_autonomous_work_count"],3)
        self.assertLessEqual(self.s["portfolio"]["pending_autonomous_work_count"],8)
        self.assertEqual(self.s["portfolio"]["blocked_action_count"],0)
    def test_all_projects_have_required_executive_fields(self):
        required={"project_id","name","project_type","lifecycle_status","maturity_basis","health","health_basis","current_bottleneck","highest_value_uncertainty","active_experiment","recent_measured_outcomes","measured_outcome_status","resource_recommendations","learned_capabilities","pending_autonomous_work","blocked_actions","open_blockers","model_costs","evidence_coverage"}
        self.assertTrue(all(set(p)==required for p in self.s["projects"]))
if __name__=="__main__":unittest.main()
