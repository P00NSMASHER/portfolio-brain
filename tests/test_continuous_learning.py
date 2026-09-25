import copy, json, unittest
from learning.continuous_learning import LearningError, effective_reward, memory_key, rebuild_state, validate_observation

DOMAINS=["SEARCH","ENGINEERING","TEST","REGRESSION","PRODUCT","CUSTOMER","EXPERIMENT","MODEL","RESOURCE"]

def obs(i=1,*,domain="SEARCH",phase="TRAIN",quality="PROSPECTIVE",signal="VERIFIED_TECHNICAL",state="VERIFIED",reward=0.8,sample=4,scope="GLOBAL",project_ids=None):
    return {
      "schema_version":"1.0.0","observation_id":f"LRN-OBS-{i:08d}","domain":domain,
      "learning_key":"action:example","scope":scope,"project_ids":project_ids or ["PRJ-000"],
      "objective_id":"OBJ-000","phase":phase,"measurement_quality":quality,"signal_class":signal,
      "evidence_state":state,"reward_signal":reward,"sample_size":sample,
      "measured_numerator":None,"measured_denominator":None,
      "source_event_ids":[f"EVT-OBS-{i:08d}"],"evidence_ids":[f"EVD-OBS-{i:08d}"],
      "resource_usage":{"model_calls":0,"tokens":0,"cost_usd":0.0,"compute_seconds":1.0,"tool_calls":1},
      "observed_at":f"2026-09-{20+(i%5):02d}T12:00:00Z","provenance_refs":[f"receipt:{i}"]
    }

class ContinuousLearningTests(unittest.TestCase):
    def test_all_required_domains_validate(self):
        for i,d in enumerate(DOMAINS,1):
            o=obs(i,domain=d)
            if d=="CUSTOMER":o["signal_class"]="VERIFIED_EXTERNAL_VALUE"
            if d=="MODEL":o["measurement_quality"]="BENCHMARK"
            if d=="RESOURCE":o["signal_class"]="COST_RESOURCE"
            validate_observation(o)

    def test_internal_activity_has_zero_learning_reward(self):
        o=obs(signal="INTERNAL_ACTIVITY",state="OBSERVED",reward=None,quality="INTERNAL_ACTIVITY")
        self.assertIsNone(effective_reward(o))

    def test_inferred_signal_cannot_train(self):
        o=obs(state="INFERRED",signal="INTERNAL_ACTIVITY",reward=None)
        self.assertIsNone(effective_reward(o))

    def test_confirm_and_evaluation_never_update_q(self):
        self.assertIsNone(effective_reward(obs(1,phase="CONFIRM")))
        self.assertIsNone(effective_reward(obs(2,phase="EVALUATION_ONLY")))

    def test_verified_external_value_outranks_verified_technical(self):
        ext=obs(1,domain="PRODUCT",signal="VERIFIED_EXTERNAL_VALUE",reward=0.8)
        tech=obs(2,domain="ENGINEERING",signal="VERIFIED_TECHNICAL",reward=0.8)
        self.assertGreater(effective_reward(ext),effective_reward(tech))

    def test_customer_value_must_be_verified_external(self):
        with self.assertRaises(LearningError):validate_observation(obs(domain="CUSTOMER",signal="VERIFIED_TECHNICAL"))

    def test_model_train_requires_benchmark_quality(self):
        with self.assertRaises(LearningError):validate_observation(obs(domain="MODEL",quality="PROSPECTIVE"))
        validate_observation(obs(domain="MODEL",quality="BENCHMARK"))

    def test_global_and_project_scopes_do_not_collide(self):
        g=obs(1);p=obs(2,scope="PRJ-000")
        self.assertNotEqual(memory_key(g),memory_key(p))

    def test_five_train_observations_without_confirm_are_not_promoted(self):
        rows=[obs(i,reward=0.8,sample=4) for i in range(1,6)]
        state=rebuild_state(rows);r=state["records"][0]
        self.assertTrue(r["train_evidence_ready"])
        self.assertFalse(r["confirm_evidence_ready"])
        self.assertFalse(r["eligible_for_policy_consideration"])
        self.assertEqual(r["generalization_status"],"awaiting_confirm")

    def test_independent_confirm_closes_generalization_gate_without_training_q(self):
        rows=[obs(i,reward=0.8,sample=4) for i in range(1,6)]
        rows += [obs(10,phase="CONFIRM",reward=0.5,sample=3),obs(11,phase="CONFIRM",reward=0.6,sample=3)]
        state=rebuild_state(rows);r=state["records"][0]
        self.assertTrue(r["eligible_for_policy_consideration"])
        self.assertEqual(r["visits"],5)

    def test_negative_confirm_surfaces_overfit_signal(self):
        rows=[obs(i,reward=0.8,sample=4) for i in range(1,6)]
        rows += [obs(10,phase="CONFIRM",reward=-0.5,sample=3),obs(11,phase="CONFIRM",reward=-0.2,sample=3)]
        r=rebuild_state(rows)["records"][0]
        self.assertFalse(r["eligible_for_policy_consideration"])
        self.assertIn(r["generalization_status"],{"overfit_signal","confirm_regression_signal"})

    def test_retrospective_verified_outcome_does_not_train(self):
        r=rebuild_state([obs(1,quality="RETROSPECTIVE")])["records"][0]
        self.assertEqual(r["visits"],0)
        self.assertEqual(r["q_value"],0.0)

    def test_duplicate_observation_ids_fail_closed(self):
        a=obs(1)
        with self.assertRaises(LearningError):rebuild_state([a,copy.deepcopy(a)])

    def test_unknown_denominator_is_preserved(self):
        o=obs(1);o["measured_numerator"]=None;o["measured_denominator"]=None
        validate_observation(o)
        state=rebuild_state([o])
        self.assertEqual(state["records"][0]["train_support"]["sample_size"],4)

    def test_invalid_ratio_rejected(self):
        o=obs(1);o["measured_numerator"]=5;o["measured_denominator"]=4
        with self.assertRaises(LearningError):validate_observation(o)

if __name__=="__main__":unittest.main()
