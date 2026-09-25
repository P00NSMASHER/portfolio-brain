import copy, unittest
from memory.value_memory_adapter import (
    SharedMemoryError, canonical_hash, load_pin, project_upstream_summary,
    upstream_registration_args, validate_credit_conservation, validate_memory,
    validate_outcome, verified_outcome_calls
)

def mem():
    content={"lesson":"cheap decisive experiments beat speculative build activity"}
    return {
      "schema_version":"1.0.0","memory_id":"MEM-PORTFOLIO-0001","memory_key":"experiment-first",
      "version":"v1","memory_kind":"STRATEGY","project_ids":["PRJ-000","PRJ-008"],
      "objective_id":"OBJ-000","scope":"GLOBAL","content":content,"content_hash":canonical_hash(content),
      "provenance_evidence_ids":["EVD-PORTFOLIO-0001"],"truth_state":"VERIFIED",
      "status":"ACTIVE","upstream_memory_id":"portfolio-memory-0001"
    }

def outcome(state="VERIFIED", event="EVT-OUTCOME-0001", fraction=1.0):
    verified=state=="VERIFIED"
    return {
      "schema_version":"1.0.0","outcome_id":"MOUT-PORTFOLIO-0001","memory_id":"MEM-PORTFOLIO-0001",
      "event_id":event,"project_id":"PRJ-000","objective_id":"OBJ-000","reward":0.8,
      "attribution_fraction":fraction,"evidence_ids":["EVD-OUTCOME-0001"],"evidence_state":state,
      "observer_actor_id":"observer","verifier_actor_id":"verifier" if verified else None,
      "verification_report_hash":"sha256:"+"a"*64 if verified else None,
      "observed_at":"2026-09-25T16:00:00Z","verified_at":"2026-09-25T16:01:00Z" if verified else None
    }

class SharedValueMemoryTests(unittest.TestCase):
    def test_pin_reuses_upstream_engine(self):
        pin=load_pin()
        self.assertEqual(pin["source_revision"],"dcca6215f2439bb55391335fe0513f471c762290")
        self.assertEqual(pin["source_blob_sha"],"5e6450087e2fe0402ebe0af9ea0443383964a7a8")
        self.assertFalse(pin["copied_source_code"])

    def test_memory_hash_and_registration_mapping(self):
        m=mem(); validate_memory(m)
        args=upstream_registration_args(m)
        self.assertEqual(args["scope"],"GLOBAL")
        self.assertEqual(args["objective"],"OBJ-000")
        self.assertEqual(args["memory_id"],m["upstream_memory_id"])
        self.assertEqual(args["content"]["project_ids"],["PRJ-000","PRJ-008"])

    def test_only_verified_outcome_can_change_learned_value(self):
        m=mem()
        with self.assertRaises(SharedMemoryError):
            verified_outcome_calls(m,outcome("OBSERVED"))
        with self.assertRaises(SharedMemoryError):
            verified_outcome_calls(m,outcome("INFERRED"))
        calls=verified_outcome_calls(m,outcome("VERIFIED"))
        self.assertTrue(calls["verify"]["accepted"])

    def test_observer_cannot_verify_own_outcome(self):
        o=outcome(); o["verifier_actor_id"]="observer"
        with self.assertRaises(SharedMemoryError): validate_outcome(o)

    def test_verified_outcome_requires_report_hash(self):
        o=outcome(); o["verification_report_hash"]=None
        with self.assertRaises(SharedMemoryError): validate_outcome(o)

    def test_project_attribution_is_preserved(self):
        m=mem(); o=outcome(); o["project_id"]="PRJ-005"
        with self.assertRaises(SharedMemoryError): verified_outcome_calls(m,o)

    def test_objective_scope_is_preserved(self):
        m=mem(); o=outcome(); o["objective_id"]="OBJ-999"
        with self.assertRaises(SharedMemoryError): verified_outcome_calls(m,o)

    def test_verified_credit_is_conserved_across_memories(self):
        a=outcome(event="EVT-OUTCOME-0002",fraction=0.6)
        b=copy.deepcopy(a); b["outcome_id"]="MOUT-PORTFOLIO-0002"; b["memory_id"]="MEM-PORTFOLIO-0002"; b["attribution_fraction"]=0.5
        with self.assertRaises(SharedMemoryError): validate_credit_conservation([a,b])

    def test_unverified_observations_do_not_consume_verified_credit(self):
        a=outcome(event="EVT-OUTCOME-0003",fraction=1.0)
        b=copy.deepcopy(a); b["outcome_id"]="MOUT-PORTFOLIO-0002"; b["evidence_state"]="OBSERVED"; b["verifier_actor_id"]=None; b["verification_report_hash"]=None; b["verified_at"]=None
        validate_credit_conservation([a,b])

    def test_verified_positive_summary_outweighs_neutral_speculation(self):
        neutral=project_upstream_summary({
          "verified_count":0,"rejected_count":0,"unverified_count":10,"unique_events":0,"unique_verifiers":0,
          "effective_weight":0.0,"mean_reward":0.0,"confidence":0.0,"half_life_days":90.0,"as_of":1.0
        })
        verified=project_upstream_summary({
          "verified_count":3,"rejected_count":0,"unverified_count":0,"unique_events":3,"unique_verifiers":2,
          "effective_weight":2.0,"mean_reward":0.8,"confidence":0.63,"half_life_days":90.0,"as_of":1.0
        })
        self.assertEqual(neutral["value_factor"],0.5)
        self.assertGreater(verified["value_factor"],neutral["value_factor"])

    def test_negative_verified_outcomes_can_reduce_value(self):
        summary=project_upstream_summary({
          "verified_count":2,"rejected_count":0,"unverified_count":99,"unique_events":2,"unique_verifiers":2,
          "effective_weight":1.5,"mean_reward":-0.8,"confidence":0.5,"half_life_days":90.0,"as_of":1.0
        })
        self.assertLess(summary["value_factor"],0.5)

if __name__=="__main__": unittest.main()
