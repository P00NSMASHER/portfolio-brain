import copy
import hashlib
import json
import unittest
from pathlib import Path

from hunting.autonomous_hunter import HunterError, apply_verified_feedback, load_seed_state
from model_router.feedback_state import load_seed_state as load_model_feedback_seed, validate_state as validate_model_feedback_state
from model_router.model_router import hashv
from value_proof.feedback_loop import FeedbackLoopError, _legacy_hunter_feedback_id, apply_verified_value_feedback
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT=Path(__file__).resolve().parents[1]

def call_receipt(*,invocation_id,tier,model_id,group,cost,request_id,route_id):
    core={
      "schema_version":"1.0.0",
      "invocation_id":invocation_id,
      "request_id":request_id,
      "route_id":route_id,
      "tier":tier,
      "provider_id":"openai",
      "model_id":model_id,
      "independence_group":group,
      "status":"SUCCESS",
      "started_at":"2026-09-27T03:44:00Z",
      "completed_at":"2026-09-27T03:44:10Z",
      "input_tokens":100,
      "output_tokens":20,
      "cost_usd":cost,
      "cost_basis":"CONFIGURED_RATE_CONSERVATIVE_INPUT",
      "latency_ms":1000,
      "input_hash":"sha256:"+"1"*64,
      "output_hash":"sha256:"+"2"*64,
      "authority_granted":False,
      "evidence_upgraded":False,
      "downstream_outcome_ids":[],
    }
    return {**core,"receipt_hash":hashv(core)}

def value_outcome(task,builder,verifier):
    source=task["source_candidate"]
    core={
      "schema_version":"1.0.0",
      "outcome_id":"MVOUT-TEST-STEP8",
      "task_id":task["task_id"],
      "project_ids":task["project_ids"],
      "hunter_finding_id":source["finding_id"],
      "hunter_experiment_proposal_id":source["experiment_proposal_id"],
      "repository_full_name":source["repository_full_name"],
      "revision":source["revision"],
      "evidence_pack_hash":"sha256:"+"3"*64,
      "builder_execution_receipt_hash":"sha256:"+"4"*64,
      "builder_provider_receipt_hash":builder["receipt_hash"],
      "builder_model_id":builder["model_id"],
      "deterministic_verification_receipt_hash":"sha256:"+"5"*64,
      "independent_verification_receipt_hash":"sha256:"+"6"*64,
      "verifier_provider_receipt_hash":verifier["receipt_hash"],
      "verifier_model_id":verifier["model_id"],
      "value_status":"VALUE_OUTCOME_VERIFIED",
      "value_class":"TECHNICAL_RESEARCH_DECISION_UTILITY",
      "decision":"PROCEED_TO_BOUNDED_INTEGRATION_REVIEW",
      "decision_basis":{
        "builder_recommendation":"DEEPER_BOUNDED_REVIEW",
        "builder_confidence":0.8,
        "verifier_confidence":0.9,
        "evidence_supported":True,
        "contract_compliant":True,
        "useful_for_bounded_followup":True,
      },
      "evidence_state":"VERIFIED",
      "useful_outcome":True,
      "external_customer_value_claimed":False,
      "rights_state":"UNKNOWN_REQUIRES_REVIEW",
      "capability_verification_claimed":False,
      "deployment_authorized":False,
      "authority_granted":False,
      "evidence_upgraded":False,
      "provenance_refs":["test:step8"],
    }
    return {**core,"outcome_hash":digest(core)}

class VerifiedFeedbackLoopTests(unittest.TestCase):
    def setUp(self):
        self.task=load_contract()
        self.verifier_contract=load_verifier_contract()
        self.builder=call_receipt(
          invocation_id="MINV-STEP8-BUILDER",tier=2,model_id="gpt-5.6-terra",
          group="openai-terra",cost=.01,request_id="MRQ-STEP8-B",route_id="MRT-STEP8-B"
        )
        self.verifier=call_receipt(
          invocation_id="MINV-STEP8-VERIFIER",tier=3,model_id="gpt-5.6-sol",
          group="openai-sol",cost=.02,request_id="MRQ-STEP8-V",route_id="MRT-STEP8-V"
        )
        self.outcome=value_outcome(self.task,self.builder,self.verifier)
        self.cases=json.loads((ROOT/"hunting"/"CONTROLLED_PROOF_CASES.json").read_text())

    def apply(self,hunter=None,model=None,outcome=None):
        return apply_verified_value_feedback(
          task_contract=self.task,
          verifier_contract=self.verifier_contract,
          outcome=outcome or self.outcome,
          builder_provider_receipt=self.builder,
          verifier_provider_receipt=self.verifier,
          hunter_state=hunter if hunter is not None else load_seed_state(),
          model_feedback_state=model if model is not None else load_model_feedback_seed(),
          controlled_cases=self.cases,
          at="2026-09-27T03:45:00Z",
        )

    def test_verified_outcome_updates_hunter_and_both_model_roles(self):
        hunter=load_seed_state();model=load_model_feedback_seed()
        report=self.apply(hunter,model)
        self.assertEqual(report["status"],"FEEDBACK_APPLIED")
        strategy="STRAT:capability-conjunction-search-claim-tracing"
        self.assertEqual(hunter["strategy_stats"][strategy]["verified_value_outcomes"],1)
        self.assertEqual(len(hunter["feedback_ids"]),1)
        validate_model_feedback_state(model)
        self.assertEqual(model["sequence"],2)
        self.assertEqual(len(model["calls"]),2)
        self.assertEqual(len(model["outcomes"]),2)
        terra=model["routing_task_summaries"]["OPPORTUNITY_REASONING"]["T2::openai::gpt-5.6-terra"]
        sol=model["routing_task_summaries"]["PROMOTION_VERIFICATION"]["T3::openai::gpt-5.6-sol"]
        self.assertEqual((terra["verified_outcomes"],terra["mean_verified_outcome_value"]),(1,1.0))
        self.assertEqual((sol["verified_outcomes"],sol["mean_verified_outcome_value"]),(1,1.0))
        self.assertFalse(report["authority_granted"])
        self.assertFalse(report["evidence_upgraded"])
        self.assertFalse(report["customer_value_claimed"])

    def test_feedback_is_idempotent_across_reruns_of_same_task_lineage(self):
        hunter=load_seed_state();model=load_model_feedback_seed()
        first=self.apply(hunter,model)
        sequence=model["sequence"]
        second=self.apply(hunter,model)
        self.assertEqual(first["status"],"FEEDBACK_APPLIED")
        self.assertEqual(second["status"],"ALREADY_APPLIED")
        self.assertEqual(model["sequence"],sequence)
        self.assertEqual(len(model["outcomes"]),2)
        strategy=second["hunter_strategy_id"]
        self.assertEqual(hunter["strategy_stats"][strategy]["verified_value_outcomes"],1)

    def test_direct_feedback_requires_matching_verified_outcome_and_canonical_id(self):
        hunter=load_seed_state()
        source=self.task["source_candidate"]
        feedback={
            "feedback_id":"HFB-INVALID-ALIAS",
            "strategy_id":"STRAT:capability-conjunction-search-claim-tracing",
            "finding_id":source["finding_id"],
            "outcome_event_id":self.outcome["outcome_id"],
            "evidence_state":"VERIFIED",
            "value_realized":True,
        }
        def attempt(candidate,proof=self.outcome):
            return apply_verified_feedback(hunter,candidate,task_contract=self.task,outcome=proof)
        for change in (
            {"finding_id":"HFD-NONEXISTENT"},
            {"outcome_event_id":"EVT-NONEXISTENT"},
            {"strategy_id":"STRAT:first-party-production-source-triangulation"},
            {"evidence_state":"OBSERVED"},
            {},
        ):
            with self.subTest(change=change),self.assertRaises(HunterError):
                attempt({**feedback,**change})
            self.assertEqual(hunter["feedback_ids"],[])
        bad_outcome={**self.outcome,"hunter_finding_id":"HFD-NONEXISTENT"}
        with self.assertRaises(FeedbackLoopError):attempt(feedback,bad_outcome)
        self.assertEqual(hunter["feedback_ids"],[])

        for field,value in (("hunter_finding_id","HFD-NONEXISTENT"),("revision","0"*40)):
            bad={**self.outcome,field:value}
            body=dict(bad);body.pop("outcome_hash");bad["outcome_hash"]=digest(body)
            with self.subTest(field=field),self.assertRaises(HunterError):attempt(feedback,bad)
            self.assertEqual(hunter["feedback_ids"],[])

        valid={**feedback,"feedback_id":"HFB-"+hashlib.sha256(self.outcome["outcome_id"].encode()).hexdigest()[:24].upper()}
        attempt(valid)
        self.assertEqual(hunter["strategy_stats"][valid["strategy_id"]]["verified_value_outcomes"],1)
        with self.assertRaises(HunterError):attempt({**valid,"feedback_id":"HFB-SECOND-ALIAS"})
        with self.assertRaises(HunterError):attempt(valid)
        self.assertEqual(hunter["strategy_stats"][valid["strategy_id"]]["verified_value_outcomes"],1)

    def test_legacy_verified_feedback_is_not_credited_again(self):
        hunter=load_seed_state()
        strategy="STRAT:capability-conjunction-search-claim-tracing"
        hunter["feedback_ids"].append(_legacy_hunter_feedback_id(task_id=self.task["task_id"],finding_id=self.task["source_candidate"]["finding_id"]))
        hunter["strategy_stats"][strategy]["verified_value_outcomes"]=1
        report=self.apply(hunter,load_model_feedback_seed())
        self.assertFalse(report["hunter_feedback_applied"])
        self.assertEqual(hunter["strategy_stats"][strategy]["verified_value_outcomes"],1)

    def test_unverified_or_nonuseful_outcome_cannot_train(self):
        for field,value in (("evidence_state","OBSERVED"),("useful_outcome",False)):
            bad=copy.deepcopy(self.outcome);bad[field]=value
            body=dict(bad);body.pop("outcome_hash");bad["outcome_hash"]=digest(body)
            hunter=load_seed_state();model=load_model_feedback_seed()
            with self.assertRaises(FeedbackLoopError):
                self.apply(hunter,model,bad)
            self.assertEqual(hunter["feedback_ids"],[])
            self.assertEqual(model["outcomes"],[])

    def test_receipt_lineage_mismatch_fails_closed(self):
        bad=copy.deepcopy(self.outcome)
        bad["builder_provider_receipt_hash"]="sha256:"+"9"*64
        body=dict(bad);body.pop("outcome_hash");bad["outcome_hash"]=digest(body)
        with self.assertRaises(FeedbackLoopError):
            self.apply(outcome=bad)

if __name__=="__main__":
    unittest.main()
