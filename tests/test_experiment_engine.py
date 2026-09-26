import copy, unittest
from experiments.experiment_engine import ExperimentError, build_experiment_portfolio, hashv, validate_outcome, validate_plan
from uncertainty.highest_value_uncertainty import build_snapshot

class ExperimentEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portfolio=build_experiment_portfolio(build_snapshot())
        cls.by_unc={p["uncertainty_id"]:p for p in cls.portfolio["plans"]}

    def test_all_uncertainties_become_explicit_plans(self):
        self.assertEqual(self.portfolio["plan_count"],20)
        self.assertEqual(self.portfolio["status_counts"],{"READY_FOR_ISOLATED_EXECUTION":12,"READY_FOR_BOUNDED_EXECUTION":4,"HUMAN_APPROVAL_REQUIRED":2,"BLOCKED":2})
        for p in self.portfolio["plans"]:validate_plan(p)

    def test_selected_recoveryworks_plan_is_bounded_external_execution(self):
        p=self.by_unc["UNC-EXTERNAL-PRJ-001"]
        self.assertEqual(p["status"],"READY_FOR_BOUNDED_EXECUTION")
        self.assertTrue(p["autonomous_execution_allowed"])
        self.assertEqual(p["execution_mode"],"BOUNDED_EXTERNAL_VALIDATION")
        self.assertNotIn("CUSTOMER_COMMUNICATION",p["approval_requirements"])
        for key in ["hypothesis","baseline","success_condition","failure_condition","inconclusive_condition"]:
            self.assertTrue(p[key])
        self.assertEqual(p["cost_boundary"]["external_messages_max"],1)
        self.assertEqual(p["cost_boundary"]["autonomous_cash_spend_usd_max"],0)

    def test_plan_preserves_full_uncertainty_vector_without_score(self):
        u=build_snapshot()
        source=next(c for c in u["candidates"] if c["uncertainty_id"]=="UNC-EXTERNAL-PRJ-001")
        plan=self.by_unc[source["uncertainty_id"]]
        self.assertEqual(plan["uncertainty_components"],source["components"])
        self.assertNotIn("score",plan)
        self.assertNotIn("weighted_score",plan)

    def test_cost_and_time_remain_policy_estimates(self):
        for p in self.portfolio["plans"]:
            self.assertEqual(p["cost_boundary"]["basis_type"],"POLICY_ESTIMATE")
            self.assertEqual(p["cost_boundary"]["test_cost_ordinal"],p["uncertainty_components"]["test_cost"]["value"])
            self.assertEqual(p["cost_boundary"]["time_to_evidence_ordinal"],p["uncertainty_components"]["time_to_evidence"]["value"])

    def test_ready_plans_keep_cash_and_writes_zero_and_bound_messages_models(self):
        for p in self.portfolio["plans"]:
            c=p["cost_boundary"]
            self.assertEqual(c["autonomous_cash_spend_usd_max"],0)
            self.assertEqual(c["downstream_writes_max"],0)
            self.assertLessEqual(c["model_calls_max"],2)
            if p["execution_mode"]=="BOUNDED_EXTERNAL_VALIDATION":
                self.assertEqual(c["external_messages_max"],1)
            else:
                self.assertEqual(c["external_messages_max"],0)

    def test_blocked_canary_and_source_remain_blocked(self):
        for uid in ["UNC-CANARY-PRJ-000","UNC-BLOCKER-PRJ-003"]:
            p=self.by_unc[uid]
            self.assertEqual(p["status"],"BLOCKED")
            self.assertFalse(p["autonomous_execution_allowed"])

    def test_blocked_human_gated_source_stays_blocked(self):
        p=self.by_unc["UNC-BLOCKER-PRJ-003"]
        self.assertEqual(p["authority_requirement"],"HUMAN_GATED_ACT")
        self.assertEqual(p["status"],"BLOCKED")
        self.assertFalse(p["autonomous_execution_allowed"])
        self.assertIn("BLK-001",p["hard_blockers"])

    def test_child_facing_approvals_are_inherited(self):
        for uid in ["UNC-EXTERNAL-PRJ-005","UNC-EXTERNAL-PRJ-006"]:
            self.assertIn("CONSEQUENTIAL_CHILD_FACING_CHANGE",self.by_unc[uid]["approval_requirements"])

    def test_market_research_plan_preserves_no_trading_boundaries(self):
        p=self.by_unc["UNC-CAPABILITY-PRJ-007"]
        self.assertIn("NO_AUTONOMOUS_TRADING",p["inherited_hard_boundaries"])
        self.assertIn("NO_BROKER_ORDER_EXECUTION",p["inherited_hard_boundaries"])
        self.assertEqual(p["execution_mode"],"READ_ONLY_EVIDENCE_ACQUISITION")

    def test_semantic_revision_changes_when_success_condition_changes(self):
        p=copy.deepcopy(self.by_unc["UNC-CAPABILITY-PRJ-004"])
        original=p["semantic_revision"]
        p["success_condition"]+=" changed"
        body={k:v for k,v in p.items() if k not in {"experiment_id","semantic_revision","experiment_hash"}}
        self.assertNotEqual(original,hashv(body))

    def test_definitive_outcome_requires_verified_independent_verifier(self):
        exp=self.by_unc["UNC-CAPABILITY-PRJ-004"]
        base={
          "schema_version":"1.0.0","outcome_id":"POUT-1234567890ABCDEF","experiment_id":exp["experiment_id"],
          "result":"PASSED","evidence_state":"OBSERVED","evidence_ids":["EVD-OUTCOME-0001"],"event_ids":["EVT-OUTCOME-0001"],
          "actor_id":"builder","verifier_actor_id":None,"started_at":"2026-09-25T18:00:00Z","completed_at":"2026-09-25T18:01:00Z",
          "observed_metrics":{},"decision_effect":"SUPPORTS_HYPOTHESIS","provenance_refs":["test:receipt"],"outcome_hash":""
        }
        body=dict(base);body.pop("outcome_hash");base["outcome_hash"]=hashv(body)
        with self.assertRaises(ExperimentError):validate_outcome(base,{exp["experiment_id"]:exp})
        base["evidence_state"]="VERIFIED";base["verifier_actor_id"]="builder"
        body=dict(base);body.pop("outcome_hash");base["outcome_hash"]=hashv(body)
        with self.assertRaises(ExperimentError):validate_outcome(base,{exp["experiment_id"]:exp})
        base["verifier_actor_id"]="independent-verifier"
        body=dict(base);body.pop("outcome_hash");base["outcome_hash"]=hashv(body)
        validate_outcome(base,{exp["experiment_id"]:exp})

    def test_inconclusive_outcome_cannot_claim_success(self):
        exp=self.by_unc["UNC-CAPABILITY-PRJ-004"]
        o={
          "schema_version":"1.0.0","outcome_id":"POUT-ABCDEF1234567890","experiment_id":exp["experiment_id"],
          "result":"INCONCLUSIVE","evidence_state":"UNKNOWN","evidence_ids":["EVD-OUTCOME-0002"],"event_ids":["EVT-OUTCOME-0002"],
          "actor_id":"observer","verifier_actor_id":None,"started_at":"2026-09-25T18:00:00Z","completed_at":"2026-09-25T18:01:00Z",
          "observed_metrics":{},"decision_effect":"SUPPORTS_HYPOTHESIS","provenance_refs":["test:receipt"],"outcome_hash":""
        }
        body=dict(o);body.pop("outcome_hash");o["outcome_hash"]=hashv(body)
        with self.assertRaises(ExperimentError):validate_outcome(o,{exp["experiment_id"]:exp})

if __name__=="__main__":unittest.main()
