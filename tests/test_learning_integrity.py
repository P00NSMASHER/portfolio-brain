import copy
import unittest

from hunting.autonomous_hunter import load_seed_state as load_hunter_seed
from learning.integrity import build_learning_integrity
from learning.live_observations import load_seed_state as load_learning_seed
from model_router.feedback_state import (
    apply_verified_model_feedback,
    load_seed_state as load_model_seed,
    stable_feedback_key,
)
from model_router.model_router import hashv


OUTCOME_ID="MVOUT-INTEGRITY-0001"
OUTCOME_HASH="sha256:"+"a"*64
EVENT_ID="EVT-INTEGRITY-0001"


def call_receipt(*,invocation_id,tier,model_id,group):
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
      "completed_at":"2026-09-27T03:44:01Z",
      "input_tokens":100,
      "output_tokens":20,
      "cost_usd":0.01,
      "cost_basis":"CONFIGURED_RATE",
      "latency_ms":1000,
      "input_hash":"sha256:"+"1"*64,
      "output_hash":"sha256:"+"2"*64,
      "authority_granted":False,
      "evidence_upgraded":False,
      "downstream_outcome_ids":[],
    }
    return {**core,"receipt_hash":hashv(core)}


def observation(i):
    return {
      "schema_version":"1.0.0",
      "observation_id":f"LRN-INTEGRITY-{i:08d}",
      "domain":"SEARCH",
      "learning_key":"hunter-strategy:test",
      "scope":"GLOBAL",
      "project_ids":["PRJ-005"],
      "objective_id":None,
      "phase":"TRAIN",
      "measurement_quality":"BENCHMARK",
      "signal_class":"VERIFIED_TECHNICAL",
      "evidence_state":"VERIFIED",
      "reward_signal":1.0,
      "sample_size":1,
      "measured_numerator":1,
      "measured_denominator":1,
      "source_event_ids":[EVENT_ID],
      "evidence_ids":[f"EVD-INTEGRITY-{i:08d}"],
      "resource_usage":{"model_calls":0,"tokens":0,"cost_usd":0.0,"compute_seconds":0.0,"tool_calls":0},
      "observed_at":"2026-09-27T03:44:01Z",
      "provenance_refs":["value-outcome:"+OUTCOME_HASH,f"test:integrity:{i}"],
    }


def healthy_states():
    hunter=load_hunter_seed()
    hunter["strategy_stats"]["STRAT:capability-conjunction-search-claim-tracing"]["verified_value_outcomes"]=1

    model=load_model_seed()
    builder=call_receipt(invocation_id="MINV-INTEGRITY-B",tier=2,model_id="gpt-5.6-terra",group="openai-terra")
    verifier=call_receipt(invocation_id="MINV-INTEGRITY-V",tier=3,model_id="gpt-5.6-sol",group="openai-sol")
    for role,task,receipt in (
        ("BUILDER","OPPORTUNITY_REASONING",builder),
        ("VERIFIER","PROMOTION_VERIFICATION",verifier),
    ):
        key=stable_feedback_key(
          task_id="MVTASK-INTEGRITY",role=role,
          hunter_finding_id="HFD-INTEGRITY",value_class="TECHNICAL"
        )
        apply_verified_model_feedback(
          model,
          feedback_key=key,
          task_id="MVTASK-INTEGRITY",
          task_kind=task,
          role=role,
          hunter_finding_id="HFD-INTEGRITY",
          call_receipt=receipt,
          outcome_event_id=OUTCOME_ID,
          outcome_value=1.0,
          provenance_refs=["test:integrity"],
          at="2026-09-27T03:44:02Z",
        )

    learning=load_learning_seed()
    learning["sequence"]=1
    learning["updated_at"]="2026-09-27T03:44:03Z"
    learning["applied_source_keys"]=[f"value-outcome:{OUTCOME_ID}:{OUTCOME_HASH}"]
    learning["observations"]=[observation(i) for i in range(1,4)]
    return hunter,model,learning


class LearningIntegrityTests(unittest.TestCase):
    def test_complete_verified_pipeline_is_healthy(self):
        hunter,model,learning=healthy_states()
        result=build_learning_integrity(hunter,model,learning)
        self.assertEqual(result["status"],"HEALTHY")
        self.assertEqual(result["verified_value_event_count"],1)
        self.assertEqual(result["independently_verified_event_count"],1)
        self.assertEqual(result["continuous_learning_event_count"],1)
        self.assertEqual(result["hunter_verified_value_outcomes"],1)
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["policy_promoted"])

    def test_missing_continuous_learning_propagation_degrades(self):
        hunter,model,learning=healthy_states()
        learning["applied_source_keys"]=[]
        learning["observations"]=[]
        result=build_learning_integrity(hunter,model,learning)
        self.assertEqual(result["status"],"DEGRADED")
        self.assertEqual(result["missing_continuous_learning_event_ids"],[OUTCOME_ID])
        self.assertFalse(result["checks"]["all_verified_events_reach_continuous_learning"])

    def test_source_key_without_full_observation_payload_is_not_green(self):
        hunter,model,learning=healthy_states()
        learning["observations"]=learning["observations"][:2]
        result=build_learning_integrity(hunter,model,learning)
        self.assertEqual(result["status"],"DEGRADED")
        self.assertFalse(result["checks"]["continuous_learning_payloads_are_complete"])

    def test_missing_independent_verifier_role_degrades(self):
        hunter,model,learning=healthy_states()
        verifier_feedback=next(x for x in model["outcomes"] if next(
            c for c in model["task_contexts"] if c["feedback_id"]==x["feedback_id"]
        )["role"]=="VERIFIER")
        model["outcomes"].remove(verifier_feedback)
        model["task_contexts"]=[x for x in model["task_contexts"] if x["feedback_id"]!=verifier_feedback["feedback_id"]]
        model["applied_feedback_keys"]=[x for x in model["applied_feedback_keys"] if "VERIFIER" not in x]
        model["calls"]=[x for x in model["calls"] if x["tier"]!=3]
        from model_router.feedback_state import rebuild_summaries
        rebuild_summaries(model)
        result=build_learning_integrity(hunter,model,learning)
        self.assertEqual(result["status"],"DEGRADED")
        self.assertFalse(result["checks"]["all_verified_events_have_builder_and_verifier"])

    def test_empty_verified_value_state_is_neutral_not_fake_green(self):
        result=build_learning_integrity(load_hunter_seed(),load_model_seed(),load_learning_seed())
        self.assertEqual(result["status"],"NO_VERIFIED_VALUE")
        self.assertEqual(result["verified_value_event_count"],0)


if __name__=="__main__":
    unittest.main()
