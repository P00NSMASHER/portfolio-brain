import copy, unittest
from allocator.portfolio_allocator import (
    AllocationError, build_allocation_snapshot, hashv, policy, validate_allocation_plan
)

def rehash(plan):
    body={key:value for key,value in plan.items() if key!="plan_hash"}
    plan["plan_hash"]=hashv(body)
    return plan

class PortfolioAllocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap=build_allocation_snapshot()
        cls.by={p["resource_type"]:p for p in cls.snap["plans"]}

    def test_nine_resources_are_explicit(self):
        self.assertEqual(set(self.by),{"MODEL_CALLS","ENGINEERING_CAPACITY","TESTING","RESEARCH","HUNTER_RUNS","ART_PRODUCTION","HUMAN_REVIEW","API_INFRASTRUCTURE","CASH"})

    def test_current_evidence_allocates_model_research_and_hunter(self):
        active={k for k,v in self.by.items() if v["status"]=="ACTIVE_RECOMMENDATION"}
        self.assertEqual(active,{"MODEL_CALLS","RESEARCH","HUNTER_RUNS"})

    def test_cash_remains_unallocated_while_model_calls_are_bounded(self):
        self.assertEqual(self.by["CASH"]["allocated_share_basis_points"],0)
        self.assertGreater(self.by["MODEL_CALLS"]["allocated_share_basis_points"],0)

    def test_engineering_testing_art_and_api_are_not_busywork_allocations(self):
        for key in ["ENGINEERING_CAPACITY","TESTING","ART_PRODUCTION","API_INFRASTRUCTURE"]:
            self.assertEqual(self.by[key]["allocated_share_basis_points"],0)

    def test_resolved_education_validation_no_longer_consumes_human_review(self):
        self.assertEqual(self.by["HUMAN_REVIEW"]["recommendations"],[])
        self.assertEqual(self.by["HUMAN_REVIEW"]["allocated_share_basis_points"],0)
        self.assertEqual(self.by["HUMAN_REVIEW"]["status"],"HOLD_NO_ELIGIBLE_EVIDENCE")

    def test_recoveryworks_bounded_validation_receives_model_capacity(self):
        self.assertTrue(any(r["project_id"]=="PRJ-001" and r["authority_requirement"]=="BOUNDED_ACT" for r in self.by["MODEL_CALLS"]["recommendations"]))

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

    def test_receipts_separate_estimates_from_measured_outcomes(self):
        expected={"importance","uncertainty","test_cost","time_to_evidence","reversibility","downstream_impact","strategic_reuse","external_validation_value"}
        by_uncertainty={}
        for plan in self.by.values():
            validate_allocation_plan(plan)
            for recommendation in plan["recommendations"]:
                by_uncertainty[recommendation["source_uncertainty_id"]]=recommendation
                basis=recommendation["evidence_basis_summary"]
                groups=[basis["policy_estimate_component_ids"],basis["derived_component_ids"],basis["measured_outcome_component_ids"]]
                flattened=[component_id for group in groups for component_id in group]
                self.assertEqual(set(flattened),expected)
                self.assertEqual(len(flattened),len(set(flattened)))
                expected_estimates={
                    component_id for component_id,component in recommendation["uncertainty_components"].items()
                    if component["basis_type"]=="POLICY_ESTIMATE"
                }
                self.assertEqual(set(basis["policy_estimate_component_ids"]),expected_estimates)
                self.assertTrue({"test_cost","time_to_evidence"}<=expected_estimates)
                self.assertEqual(basis["measured_outcome_component_ids"],[])
                self.assertEqual(basis["measurement_state"],"NO_MEASURED_OUTCOME_INPUT")
        self.assertEqual(
            by_uncertainty["UNC-EXTERNAL-PRJ-001"]["uncertainty_components"]["reversibility"]["basis_type"],
            "POLICY_ESTIMATE",
        )
        self.assertEqual(
            by_uncertainty["UNC-LEARNING-PRJ-000"]["uncertainty_components"]["reversibility"]["basis_type"],
            "DERIVED",
        )

    def test_untrusted_basis_receipt_mutations_fail_closed_without_mutation(self):
        source=next(plan for plan in self.snap["plans"] if plan["recommendations"])
        recommendation=source["recommendations"][0]
        component_id="importance"
        basis=recommendation["evidence_basis_summary"]
        source_bucket=next(
            key for key in [
                "policy_estimate_component_ids","derived_component_ids","measured_outcome_component_ids"
            ] if component_id in basis[key]
        )
        other_bucket=next(
            key for key in [
                "policy_estimate_component_ids","derived_component_ids","measured_outcome_component_ids"
            ] if key!=source_bucket
        )

        omitted=copy.deepcopy(source)
        omitted["recommendations"][0]["evidence_basis_summary"][source_bucket].remove(component_id)

        overlapping=copy.deepcopy(source)
        overlapping["recommendations"][0]["evidence_basis_summary"][other_bucket].append(component_id)

        mismatched=copy.deepcopy(source)
        current=mismatched["recommendations"][0]["uncertainty_components"][component_id]["basis_type"]
        mismatched["recommendations"][0]["uncertainty_components"][component_id]["basis_type"]=(
            "DERIVED" if current!="DERIVED" else "POLICY_ESTIMATE"
        )

        future=copy.deepcopy(source)
        future["recommendations"][0]["uncertainty_components"][component_id]["basis_type"]="FUTURE_BASIS"

        wrong_state=copy.deepcopy(source)
        state=wrong_state["recommendations"][0]["evidence_basis_summary"]["measurement_state"]
        wrong_state["recommendations"][0]["evidence_basis_summary"]["measurement_state"]=(
            "MEASURED_OUTCOME_INPUT_PRESENT"
            if state=="NO_MEASURED_OUTCOME_INPUT" else "NO_MEASURED_OUTCOME_INPUT"
        )

        for name,mutated in [
            ("omitted",omitted),("overlapping",overlapping),("mismatched",mismatched),
            ("future",future),("wrong_state",wrong_state)
        ]:
            with self.subTest(name=name):
                rehash(mutated)
                before=copy.deepcopy(mutated)
                with self.assertRaises(AllocationError):
                    validate_allocation_plan(mutated)
                self.assertEqual(mutated,before)

    def test_coordinated_measured_relabel_is_rejected_even_with_valid_hash(self):
        plan=copy.deepcopy(next(p for p in self.snap["plans"] if p["recommendations"]))
        rec=plan["recommendations"][0]
        key="importance"
        basis=rec["evidence_basis_summary"]
        for bucket in ("policy_estimate_component_ids","derived_component_ids"):
            if key in basis[bucket]: basis[bucket].remove(key)
        basis["measured_outcome_component_ids"].append(key)
        basis["measurement_state"]="MEASURED_OUTCOME_INPUT_PRESENT"
        rec["uncertainty_components"][key]["basis_type"]="MEASURED_OUTCOME"
        rehash(plan)
        before=copy.deepcopy(plan)
        with self.assertRaisesRegex(AllocationError,"independent source binding"):
            validate_allocation_plan(plan)
        self.assertEqual(plan,before)

    def test_serialized_receipt_contract_and_policy_mutations_fail_closed(self):
        source=next(p for p in self.snap["plans"] if p["recommendations"])
        mutations={
            "empty_evidence":lambda p: p["recommendations"][0].update(evidence_refs=[]),
            "stripped_component":lambda p: p["recommendations"][0]["uncertainty_components"].update(
                importance={"basis_type":p["recommendations"][0]["uncertainty_components"]["importance"]["basis_type"]}),
            "invalid_value":lambda p: p["recommendations"][0]["uncertainty_components"]["importance"].update(value=True),
            "empty_component_evidence":lambda p: p["recommendations"][0]["uncertainty_components"]["importance"].update(evidence_refs=[]),
            "negative_share":lambda p: p["recommendations"][0].update(share_basis_points=-10000),
            "boolean_share":lambda p: p["recommendations"][0].update(share_basis_points=True),
            "over_cap":lambda p: p["recommendations"][0].update(share_basis_points=5001),
            "share_sum":lambda p: p["recommendations"][0].update(share_basis_points=1),
            "cash_relabel":lambda p: p.update(resource_type="CASH"),
            "infrastructure_relabel":lambda p: p.update(resource_type="API_INFRASTRUCTURE"),
            "invalid_authority":lambda p: p["recommendations"][0].update(authority_requirement="UNRESTRICTED_ACT"),
            "invalid_project":lambda p: p["recommendations"][0].update(project_id=None),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                plan=copy.deepcopy(source)
                mutate(plan)
                rehash(plan)
                before=copy.deepcopy(plan)
                with self.assertRaises(AllocationError):validate_allocation_plan(plan)
                self.assertEqual(plan,before)
        held=copy.deepcopy(next(p for p in self.snap["plans"] if not p["recommendations"]))
        held.update(allocated_share_basis_points=10000,unallocated_share_basis_points=0)
        rehash(held)
        with self.assertRaises(AllocationError):validate_allocation_plan(held)

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
