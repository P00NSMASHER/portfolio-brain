import copy, unittest
from uncertainty.highest_value_uncertainty import build_snapshot, dominates, generate_candidates, rank_candidates

class UncertaintyEngineTests(unittest.TestCase):
    def test_current_selected_question_is_external_validation_for_recoveryworks(self):
        s=build_snapshot()
        self.assertEqual(s["selected_uncertainty_id"],"UNC-EXTERNAL-PRJ-001")
        self.assertEqual(s["selected_authority_requirement"],"BOUNDED_ACT")
        self.assertEqual(s["selected_actionability"],"READY_FOR_BOUNDED_EXTERNAL_EXECUTION")
        self.assertNotIn("CUSTOMER_COMMUNICATION",s["selected_approval_requirements"])

    def test_all_candidates_keep_all_eight_components_and_no_scalar_score(self):
        for c in generate_candidates():
            self.assertEqual(set(c["components"]),{
              "importance","uncertainty","test_cost","time_to_evidence","reversibility",
              "downstream_impact","strategic_reuse","external_validation_value"
            })
            self.assertNotIn("score",c)
            self.assertNotIn("weighted_score",c)
            for component in c["components"].values():
                self.assertTrue(component["evidence_refs"])

    def test_pareto_dominance_uses_benefits_and_burdens(self):
        candidates=generate_candidates()
        learning=next(c for c in candidates if c["uncertainty_id"]=="UNC-LEARNING-PRJ-000")
        cap=next(c for c in candidates if c["uncertainty_id"]=="UNC-CAPABILITY-PRJ-001")
        self.assertTrue(dominates(learning,cap))

    def test_external_validation_and_learning_are_both_frontier_options(self):
        s=build_snapshot()
        self.assertEqual(set(s["pareto_front_candidate_ids"]),{"UNC-EXTERNAL-PRJ-001","UNC-LEARNING-PRJ-000"})

    def test_explicit_tie_break_prefers_external_validation_on_frontier(self):
        s=build_snapshot()
        self.assertEqual(s["selected_uncertainty_id"],"UNC-EXTERNAL-PRJ-001")
        self.assertGreater(s["selected_components"]["external_validation_value"],3)

    def test_blocked_candidates_never_receive_rank(self):
        ranked=rank_candidates(generate_candidates())
        blocked=[c for c in ranked if c["actionability"]=="BLOCKED"]
        self.assertGreaterEqual(len(blocked),2)
        self.assertTrue(all(c["ranking"]["rank_order"] is None for c in blocked))

    def test_cost_and_time_are_explicit_policy_estimates(self):
        for c in generate_candidates():
            self.assertEqual(c["components"]["test_cost"]["basis_type"],"POLICY_ESTIMATE")
            self.assertEqual(c["components"]["time_to_evidence"]["basis_type"],"POLICY_ESTIMATE")

    def test_child_facing_external_questions_remain_human_gated(self):
        cs={c["uncertainty_id"]:c for c in generate_candidates()}
        for uid in ["UNC-EXTERNAL-PRJ-005","UNC-EXTERNAL-PRJ-006"]:
            self.assertEqual(cs[uid]["actionability"],"HUMAN_APPROVAL_REQUIRED")
            self.assertIn("CONSEQUENTIAL_CHILD_FACING_CHANGE",cs[uid]["approval_requirements"])

    def test_canary_cannot_jump_to_step24(self):
        c=next(c for c in generate_candidates() if c["uncertainty_id"]=="UNC-CANARY-PRJ-000")
        self.assertEqual(c["actionability"],"BLOCKED")
        self.assertIn("STEP-24-CANARY-GATE",c["hard_blockers"])

    def test_graph_absence_is_worded_as_uncertainty_not_fact(self):
        c=next(c for c in generate_candidates() if c["uncertainty_id"]=="UNC-CAPABILITY-PRJ-004")
        self.assertIn("establish or reject",c["question"])
        self.assertIn("Graph absence means",c["components"]["uncertainty"]["rationale"])

if __name__=="__main__":unittest.main()
