import copy
import json
import tempfile
import unittest
from pathlib import Path

from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import (
    LiveLearningError,
    apply_verified_value_outcome,
    load_seed_state,
    make_verified_learning_observations,
    validate_state,
)
from model_router.model_router import hashv
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract


def call_receipt(*,invocation_id,tier,model_id,group,cost,input_tokens,output_tokens,completed_at):
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
      "started_at":"2026-09-27T03:44:00Z",
      "completed_at":completed_at,
      "input_tokens":input_tokens,
      "output_tokens":output_tokens,
      "cost_usd":cost,
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
      "outcome_id":"MVOUT-LIVE-LEARNING-0001",
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
      "provenance_refs":["test:live-learning"],
    }
    return {**core,"outcome_hash":digest(core)}


def feedback_receipt(outcome,task):
    core={
      "schema_version":"1.0.0",
      "feedback_loop_id":"portfolio-verified-value-feedback-v1",
      "status":"FEEDBACK_APPLIED",
      "source_outcome_id":outcome["outcome_id"],
      "source_outcome_hash":outcome["outcome_hash"],
      "hunter_finding_id":outcome["hunter_finding_id"],
      "hunter_strategy_id":"STRAT:capability-conjunction-search-claim-tracing",
      "hunter_feedback_id":"HFB-LIVE-LEARNING-0001",
      "hunter_feedback_applied":True,
      "hunter_verified_value_outcomes":1,
      "builder_feedback_key":"MFBK-BUILDER",
      "builder_feedback_applied":True,
      "verifier_feedback_key":"MFBK-VERIFIER",
      "verifier_feedback_applied":True,
      "model_feedback_sequence":2,
      "routing_value_summary":{},
      "routing_task_summaries":{},
      "authority_granted":False,
      "evidence_upgraded":False,
      "customer_value_claimed":False,
    }
    return {**core,"receipt_hash":digest(core)}


class LiveLearningObservationTests(unittest.TestCase):
    def setUp(self):
        self.task=load_contract()
        self.verifier_contract=load_verifier_contract()
        self.builder=call_receipt(
          invocation_id="MINV-LIVE-BUILDER",tier=2,model_id="gpt-5.6-terra",
          group="openai-terra",cost=.011,input_tokens=400,output_tokens=80,
          completed_at="2026-09-27T03:44:08Z",
        )
        self.verifier=call_receipt(
          invocation_id="MINV-LIVE-VERIFIER",tier=3,model_id="gpt-5.6-sol",
          group="openai-sol",cost=.026,input_tokens=500,output_tokens=60,
          completed_at="2026-09-27T03:44:10Z",
        )
        self.outcome=value_outcome(self.task,self.builder,self.verifier)
        self.feedback=feedback_receipt(self.outcome,self.task)

    def test_verified_value_creates_search_train_and_model_train_confirm(self):
        rows=make_verified_learning_observations(
          task_contract=self.task,
          verifier_contract=self.verifier_contract,
          outcome=self.outcome,
          feedback_receipt=self.feedback,
          builder_provider_receipt=self.builder,
          verifier_provider_receipt=self.verifier,
        )
        self.assertEqual(len(rows),3)
        search=[x for x in rows if x["domain"]=="SEARCH"]
        model=[x for x in rows if x["domain"]=="MODEL"]
        self.assertEqual(len(search),1)
        self.assertEqual({x["phase"] for x in model},{"TRAIN","CONFIRM"})
        self.assertEqual(len({x["learning_key"] for x in model}),1)
        self.assertTrue(all(x["evidence_state"]=="VERIFIED" for x in rows))
        self.assertTrue(all(x["signal_class"]=="VERIFIED_TECHNICAL" for x in rows))
        self.assertTrue(all(x["reward_signal"]==1.0 for x in rows))
        self.assertEqual(search[0]["resource_usage"]["model_calls"],0)
        self.assertEqual(sum(x["resource_usage"]["model_calls"] for x in model),2)

    def test_state_apply_is_idempotent(self):
        state=load_seed_state()
        first=apply_verified_value_outcome(
          state,
          task_contract=self.task,verifier_contract=self.verifier_contract,
          outcome=self.outcome,feedback_receipt=self.feedback,
          builder_provider_receipt=self.builder,verifier_provider_receipt=self.verifier,
          at="2026-09-27T03:45:00Z",
        )
        second=apply_verified_value_outcome(
          state,
          task_contract=self.task,verifier_contract=self.verifier_contract,
          outcome=self.outcome,feedback_receipt=self.feedback,
          builder_provider_receipt=self.builder,verifier_provider_receipt=self.verifier,
          at="2026-09-27T03:46:00Z",
        )
        self.assertEqual(first["status"],"APPLIED")
        self.assertEqual(first["added_observations"],3)
        self.assertEqual(second["status"],"ALREADY_APPLIED")
        self.assertEqual(state["sequence"],1)
        self.assertEqual(len(state["observations"]),3)
        validate_state(state)

    def test_live_state_feeds_advisory_learner_without_promotion(self):
        state=load_seed_state()
        apply_verified_value_outcome(
          state,
          task_contract=self.task,verifier_contract=self.verifier_contract,
          outcome=self.outcome,feedback_receipt=self.feedback,
          builder_provider_receipt=self.builder,verifier_provider_receipt=self.verifier,
          at="2026-09-27T03:45:00Z",
        )
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"learning.json"
            path.write_text(json.dumps(state))
            rebuilt=rebuild_from_sources(path)
        self.assertEqual(rebuilt["source_mode"],"LIVE_WITH_BASELINE_CONTEXT")
        self.assertEqual(rebuilt["live_observation_count"],3)
        self.assertEqual(rebuilt["source_observation_count"],3)
        self.assertEqual(rebuilt["eligible_record_count"],0)
        model=next(x for x in rebuilt["records"] if x["domain"]=="MODEL")
        self.assertEqual(model["visits"],1)
        self.assertEqual(model["train_support"]["observations"],1)
        self.assertEqual(model["confirm_support"]["observations"],1)
        self.assertFalse(model["eligible_for_policy_consideration"])

    def test_tampered_value_outcome_cannot_enter_learning(self):
        bad=copy.deepcopy(self.outcome)
        bad["useful_outcome"]=False
        body=dict(bad);body.pop("outcome_hash");bad["outcome_hash"]=digest(body)
        state=load_seed_state()
        with self.assertRaises(Exception):
            apply_verified_value_outcome(
              state,
              task_contract=self.task,verifier_contract=self.verifier_contract,
              outcome=bad,feedback_receipt=self.feedback,
              builder_provider_receipt=self.builder,verifier_provider_receipt=self.verifier,
            )
        self.assertEqual(state["observations"],[])


if __name__=="__main__":
    unittest.main()
