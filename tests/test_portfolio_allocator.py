import unittest
from allocator.portfolio_allocator import build_allocation_snapshot,policy

class PortfolioAllocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap=build_allocation_snapshot()
        cls.by={p["resource_type"]:p for p in cls.snap["plans"]}

    def test_nine_resources_are_explicit(self):
        self.assertEqual(set(self.by),{"MODEL_CALLS","ENGINEERING_CAPACITY","TESTING","RESEARCH","HUNTER_RUNS","ART_PRODUCTION","HUMAN_REVIEW","API_INFRASTRUCTURE","CASH"})

    def test_current_evidence_allocates_only_research_hunter_and_human_review(self):
        active={k for k,v in self.by.items() if v["status"]=="ACTIVE_RECOMMENDATION"}
        self.assertEqual(active,{"RESEARCH","HUNTER_RUNS","HUMAN_REVIEW"})

    def test_cash_and_model_calls_remain_unallocated(self):
        self.assertEqual(self.by["CASH"]["allocated_share_basis_points"],0)
        self.assertEqual(self.by["MODEL_CALLS"]["allocated_share_basis_points"],0)

    def test_engineering_testing_art_and_api_are_not_busywork_allocations(self):
        for key in ["ENGINEERING_CAPACITY","TESTING","ART_PRODUCTION","API_INFRASTRUCTURE"]:
            self.assertEqual(self.by[key]["allocated_share_basis_points"],0)

    def test_recoveryworks_is_top_human_review_priority_but_not_approved(self):
        r=self.by["HUMAN_REVIEW"]["recommendations"][0]
        self.assertEqual(r["project_id"],"PRJ-001")
        self.assertEqual(r["authority_requirement"],"HUMAN_GATED_ACT")
        self.assertEqual(r["actionability"],"HUMAN_APPROVAL_REQUIRED")

    def test_learning_measurement_is_top_research_priority(self):
        self.assertEqual(self.by["RESEARCH"]["recommendations"][0]["project_id"],"PRJ-000")

    def test_share_accounting_conserves_bps_and_caps_concentration(self):
        cap=policy()["max_project_share_basis_points"]
        for plan in self.by.values():
            self.assertEqual(plan["allocated_share_basis_points"]+plan["unallocated_share_basis_points"],10000)
            self.assertTrue(all(x["share_basis_points"]<=cap for x in plan["recommendations"]))

    def test_every_recommendation_retains_full_eight_component_vector(self):
        expected={"importance","uncertainty","test_cost","time_to_evidence","reversibility","downstream_impact","strategic_reuse","external_validation_value"}
        for plan in self.by.values():
            for r in plan["recommendations"]:
                self.assertEqual(set(r["uncertainty_components"]),expected)
                self.assertTrue(r["evidence_refs"])

    def test_normalized_shares_are_not_claimed_real_units(self):
        self.assertEqual(self.snap["mode"],"ADVISORY_NORMALIZED_SHARES_ONLY")
        self.assertEqual(self.snap["normalized_share_basis_points"],10000)

    def test_no_score_fields_exist(self):
        def walk(v):
            if isinstance(v,dict):
                self.assertFalse({"score","weighted_score","composite_score"} & set(v))
                for x in v.values():walk(x)
            elif isinstance(v,list):
                for x in v:walk(x)
        walk(self.snap)

if __name__=="__main__":unittest.main()
