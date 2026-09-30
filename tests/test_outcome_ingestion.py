import copy
import unittest

from hunting.autonomous_hunter import load_seed_state as load_hunter_state
from learning.live_observations import load_seed_state as load_learning_state
from model_router.feedback_state import load_seed_state as load_feedback_state
from model_router.model_router import hashv
from value_proof.model_task import digest, load_contract
from value_proof.outcome_ingestion import OutcomeIngestionError, ingest_verified_outcome
from value_proof.verifier import load_verifier_contract
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def call_receipt(*,invocation_id,tier,model_id,group,completed_at):
    core={
      "schema_version":"1.0.0",
      "invocation_id":invocation_id,
      "request_id":"MRQ-"+invocation_id,
      "route_id":"MRT-"+invocation_id,
      "tier":tier,
      "provider_id":"openai",
      "model_id":model_id,
      "independence_group":group,
      "status":"SUCCESS",
      "started_at":"2026-09-30T12:00:00Z",
      "completed_at":completed_at,
      "input_tokens":400,
      "output_tokens":80,
      "cost_usd":0.01,
      "cost_basis":"CONFIGURED_RATE",
      "latency_ms":1200,
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
      "outcome_id":"MVOUT-INGESTION-0001",
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
      "rights_state":"OPERATOR_ASSUMED",
      "capability_verification_claimed":False,
      "deployment_authorized":False,
      "authority_granted":False,
      "evidence_upgraded":False,
      "provenance_refs":["test:outcome-ingestion"],
    }
    return {**core,"outcome_hash":digest(core)}


class OutcomeIngestionTests(unittest.TestCase):
    def setUp(self):
        self.task=load_contract()
        self.verifier_contract=load_verifier_contract()
        self.builder=call_receipt(
          invocation_id="MINV-INGEST-BUILDER",tier=2,model_id="gpt-5.6-terra",
          group="openai-terra",completed_at="2026-09-30T12:00:08Z",
        )
        self.verifier=call_receipt(
          invocation_id="MINV-INGEST-VERIFIER",tier=3,model_id="gpt-5.6-sol",
          group="openai-sol",completed_at="2026-09-30T12:00:10Z",
        )
        self.outcome=value_outcome(self.task,self.builder,self.verifier)
        self.cases=json.loads((ROOT/"hunting"/"CONTROLLED_PROOF_CASES.json").read_text())

    def ingest(self,hunter=None,feedback=None,learning=None,outcome=None):
        return ingest_verified_outcome(
          task_contract=self.task,
          verifier_contract=self.verifier_contract,
          outcome=outcome or self.outcome,
          builder_provider_receipt=self.builder,
          verifier_provider_receipt=self.verifier,
          hunter_state=hunter or load_hunter_state(),
          model_feedback_state=feedback or load_feedback_state(),
          learning_state=learning or load_learning_state(),
          controlled_cases=self.cases,
          at="2026-09-30T12:01:00Z",
        )

    def test_same_verified_outcome_consumed_twice_is_one_logical_ingestion(self):
        hunter,feedback,learning,first=self.ingest()
        sequences=(hunter["sequence"],feedback["sequence"],learning["sequence"])
        hunter,feedback,learning,second=self.ingest(hunter,feedback,learning)
        self.assertEqual(first["status"],"INGESTED")
        self.assertEqual(second["status"],"ALREADY_INGESTED")
        self.assertEqual((hunter["sequence"],feedback["sequence"],learning["sequence"]),sequences)
        self.assertEqual(len(learning["applied_source_keys"]),1)
        self.assertEqual(len(learning["observations"]),3)
        self.assertTrue(all(not applied for applied in second["projection_applied"].values()))

    def test_unverified_or_malformed_outcome_is_rejected_before_deduplication(self):
        hunter,feedback,learning,_=self.ingest()
        bad=copy.deepcopy(self.outcome)
        bad["evidence_state"]="OBSERVED"
        body=dict(bad);body.pop("outcome_hash")
        bad["outcome_hash"]=digest(body)
        with self.assertRaises(Exception):
            self.ingest(hunter,feedback,learning,bad)

    def test_conflicting_immutable_outcome_identity_fails_closed(self):
        hunter,feedback,learning,_=self.ingest()
        conflict=copy.deepcopy(self.outcome)
        conflict["decision_basis"]["builder_confidence"]=0.81
        body=dict(conflict);body.pop("outcome_hash")
        conflict["outcome_hash"]=digest(body)
        with self.assertRaises(OutcomeIngestionError):
            self.ingest(hunter,feedback,learning,conflict)

    def test_verified_outcome_updates_existing_projections_without_claiming_market_or_revenue(self):
        hunter,feedback,learning,receipt=self.ingest()
        strategy="STRAT:capability-conjunction-search-claim-tracing"
        self.assertEqual(hunter["strategy_stats"][strategy]["verified_value_outcomes"],1)
        self.assertEqual(len(feedback["outcomes"]),2)
        self.assertEqual(len(learning["observations"]),3)
        self.assertEqual(
          receipt["value_verification"],
          {"technical":"VERIFIED","market":"NOT_VERIFIED","revenue":"NOT_VERIFIED"},
        )
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["market_value_claimed"])
        self.assertFalse(receipt["revenue_value_claimed"])


if __name__=="__main__":
    unittest.main()
