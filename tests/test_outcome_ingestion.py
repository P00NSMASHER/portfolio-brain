import copy
import json
import tempfile
import unittest
from pathlib import Path

from hunting.autonomous_hunter import load_seed_state as hunter_seed
from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import load_seed_state as learning_seed
from model_router.feedback_state import load_seed_state as model_seed
from model_router.model_router import hashv
from value_proof.feedback_loop import FeedbackLoopError
from value_proof.model_task import digest, load_contract
from value_proof.outcome_ingestion import OutcomeIngestionError, ingest_verified_outcome
from value_proof.verifier import load_verifier_contract
from scheduler.autonomous_scheduler import build_context, load_state, schedule_cycle

ROOT=Path(__file__).resolve().parents[1]

def call_receipt(invocation_id,tier,model_id,group):
    core={
      "schema_version":"1.0.0","invocation_id":invocation_id,
      "request_id":"MRQ-"+invocation_id,"route_id":"MRT-"+invocation_id,
      "tier":tier,"provider_id":"openai","model_id":model_id,"independence_group":group,
      "status":"SUCCESS","started_at":"2026-09-27T03:44:00Z","completed_at":"2026-09-27T03:44:10Z",
      "input_tokens":100,"output_tokens":20,"cost_usd":0.01,"cost_basis":"CONFIGURED_RATE",
      "latency_ms":1000,"input_hash":"sha256:"+"1"*64,"output_hash":"sha256:"+"2"*64,
      "authority_granted":False,"evidence_upgraded":False,"downstream_outcome_ids":[],
    }
    return {**core,"receipt_hash":hashv(core)}

def outcome(task,builder,verifier):
    source=task["source_candidate"]
    core={
      "schema_version":"1.0.0","outcome_id":"MVOUT-INGESTION-0001","task_id":task["task_id"],
      "project_ids":task["project_ids"],"hunter_finding_id":source["finding_id"],
      "hunter_experiment_proposal_id":source["experiment_proposal_id"],
      "repository_full_name":source["repository_full_name"],"revision":source["revision"],
      "evidence_pack_hash":"sha256:"+"3"*64,"builder_execution_receipt_hash":"sha256:"+"4"*64,
      "builder_provider_receipt_hash":builder["receipt_hash"],"builder_model_id":builder["model_id"],
      "deterministic_verification_receipt_hash":"sha256:"+"5"*64,
      "independent_verification_receipt_hash":"sha256:"+"6"*64,
      "verifier_provider_receipt_hash":verifier["receipt_hash"],"verifier_model_id":verifier["model_id"],
      "value_status":"VALUE_OUTCOME_VERIFIED","value_class":"TECHNICAL_RESEARCH_DECISION_UTILITY",
      "decision":"PROCEED_TO_BOUNDED_INTEGRATION_REVIEW",
      "decision_basis":{"builder_recommendation":"DEEPER_BOUNDED_REVIEW","builder_confidence":0.8,
        "verifier_confidence":0.9,"evidence_supported":True,"contract_compliant":True,
        "useful_for_bounded_followup":True},
      "evidence_state":"VERIFIED","useful_outcome":True,"external_customer_value_claimed":False,
      "rights_state":"OPERATOR_ASSUMED","capability_verification_claimed":False,
      "deployment_authorized":False,"authority_granted":False,"evidence_upgraded":False,
      "provenance_refs":["test:outcome-ingestion"],
    }
    return {**core,"outcome_hash":digest(core)}

class OutcomeIngestionTests(unittest.TestCase):
    def setUp(self):
        self.task=load_contract()
        self.verifier_contract=load_verifier_contract()
        self.builder=call_receipt("MINV-INGEST-B",2,"gpt-5.6-terra","openai-terra")
        self.verifier=call_receipt("MINV-INGEST-V",3,"gpt-5.6-sol","openai-sol")
        self.outcome=outcome(self.task,self.builder,self.verifier)
        self.cases=json.loads((ROOT/"hunting"/"CONTROLLED_PROOF_CASES.json").read_text())

    def apply(self,hunter=None,model=None,learning=None,outcome_value=None):
        return ingest_verified_outcome(
          task_contract=self.task,verifier_contract=self.verifier_contract,
          outcome=outcome_value or self.outcome,builder_provider_receipt=self.builder,
          verifier_provider_receipt=self.verifier,hunter_state=hunter or hunter_seed(),
          model_feedback_state=model or model_seed(),learning_state=learning or learning_seed(),
          controlled_cases=self.cases,at="2026-09-27T03:45:00Z",
        )

    def test_verified_outcome_routes_to_existing_projections_once(self):
        hunter,model,learning,report=self.apply()
        self.assertEqual(report["status"],"INGESTED")
        self.assertEqual(report["integrity_status"],"HEALTHY")
        self.assertEqual(len(learning["observations"]),3)
        self.assertEqual(len(model["outcomes"]),2)
        self.assertEqual(sum(x["verified_value_outcomes"] for x in hunter["strategy_stats"].values()),1)
        self.assertFalse(report["market_verified"])
        self.assertFalse(report["revenue_verified"])

        hunter2,model2,learning2,report2=self.apply(hunter,model,learning)
        self.assertEqual(report2["status"],"ALREADY_INGESTED")
        self.assertEqual(hunter2["sequence"],hunter["sequence"])
        self.assertEqual(model2["sequence"],model["sequence"])
        self.assertEqual(learning2["sequence"],learning["sequence"])
        self.assertEqual(len(learning2["observations"]),3)

    def test_ingested_outcome_changes_subsequent_learning_selection_cycle(self):
        hunter,model,learning,report=self.apply()
        self.assertEqual(report["status"],"INGESTED")
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"learning.json"
            path.write_text(json.dumps(learning))
            rebuilt=rebuild_from_sources(path)
        self.assertEqual(rebuilt["source_observation_count"],3)
        self.assertEqual(rebuilt["fresh_learning_observation_count"],3)

        baseline=rebuild_from_sources(None)
        baseline_context=build_context(learning_state=baseline)
        fresh_context=build_context(learning_state=rebuilt)
        baseline_uncertainties={row["uncertainty_id"] for row in baseline_context["uncertainty"]["candidates"]}
        fresh_uncertainties={row["uncertainty_id"] for row in fresh_context["uncertainty"]["candidates"]}
        self.assertIn("UNC-LEARNING-PRJ-000",baseline_uncertainties)
        self.assertNotIn("UNC-LEARNING-PRJ-000",fresh_uncertainties)

        _,baseline_cycle=schedule_cycle(
          load_state(),baseline_context,at="2026-09-27T03:46:00Z"
        )
        _,fresh_cycle=schedule_cycle(
          load_state(),fresh_context,at="2026-09-27T03:46:00Z"
        )
        self.assertEqual(baseline_cycle["status"],"PASS")
        self.assertEqual(fresh_cycle["status"],"PASS")
        self.assertEqual(baseline_cycle["fresh_learning_observation_count"],0)
        self.assertEqual(fresh_cycle["fresh_learning_observation_count"],3)
        self.assertEqual(
          fresh_cycle["uncertainty_snapshot_hash"],
          fresh_context["uncertainty"]["snapshot_hash"],
        )
        self.assertNotEqual(
          baseline_cycle["uncertainty_snapshot_hash"],
          fresh_cycle["uncertainty_snapshot_hash"],
        )

    def test_unverified_or_malformed_outcome_is_rejected_without_mutation(self):
        hunter= hunter_seed(); model=model_seed(); learning=learning_seed()
        before=copy.deepcopy((hunter,model,learning))
        bad=copy.deepcopy(self.outcome);bad["evidence_state"]="OBSERVED"
        body=dict(bad);body.pop("outcome_hash");bad["outcome_hash"]=digest(body)
        with self.assertRaises(FeedbackLoopError):
            self.apply(hunter,model,learning,bad)
        self.assertEqual((hunter,model,learning),before)

    def test_same_outcome_identity_with_different_hash_fails_closed(self):
        hunter,model,learning,_=self.apply()
        conflict=copy.deepcopy(self.outcome)
        conflict["provenance_refs"]=["test:conflicting-identity"]
        body=dict(conflict);body.pop("outcome_hash");conflict["outcome_hash"]=digest(body)
        before=copy.deepcopy((hunter,model,learning))
        with self.assertRaisesRegex(OutcomeIngestionError,"conflicting"):
            self.apply(hunter,model,learning,conflict)
        self.assertEqual((hunter,model,learning),before)

    def test_hunter_only_partial_identity_without_hash_fails_closed(self):
        hunter,_,_,_=self.apply()
        model=model_seed(); learning=learning_seed()
        before=copy.deepcopy((hunter,model,learning))
        with self.assertRaisesRegex(OutcomeIngestionError,"ambiguous prior Hunter"):
            self.apply(hunter,model,learning)
        self.assertEqual((hunter,model,learning),before)

if __name__=="__main__":
    unittest.main()
