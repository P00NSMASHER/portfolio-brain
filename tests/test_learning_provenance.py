import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import load_seed_state
from uncertainty.highest_value_uncertainty import build_snapshot

def observation():
    return {
      "schema_version":"1.0.0","observation_id":"LRN-PROVENANCE-00000001",
      "domain":"SEARCH","learning_key":"hunter-strategy:test","scope":"GLOBAL",
      "project_ids":["PRJ-000"],"objective_id":None,"phase":"TRAIN",
      "measurement_quality":"BENCHMARK","signal_class":"VERIFIED_TECHNICAL",
      "evidence_state":"VERIFIED","reward_signal":1.0,"sample_size":1,
      "measured_numerator":1,"measured_denominator":1,
      "source_event_ids":["EVT-PROVENANCE-00000001"],
      "evidence_ids":["EVD-PROVENANCE-00000001"],
      "resource_usage":{"model_calls":0,"tokens":0,"cost_usd":0.0,"compute_seconds":0.0,"tool_calls":0},
      "observed_at":"2026-09-27T03:44:01Z",
      "provenance_refs":["value-outcome:sha256:"+"a"*64],
    }

class LearningProvenanceTests(unittest.TestCase):
    def test_static_baseline_is_context_only_and_cannot_train(self):
        stale=observation()
        with patch("learning.continuous_learning._checked_in_observations",return_value=[stale]):
            rebuilt=rebuild_from_sources(None)
        self.assertEqual(rebuilt["source_observation_count"],0)
        self.assertEqual(rebuilt["fresh_learning_observation_count"],0)
        self.assertEqual(rebuilt["baseline_or_seed_observation_count"],1)
        self.assertEqual(rebuilt["records"],[])
        classes=rebuilt["provenance_freshness"]
        self.assertEqual(set(classes),{
          "LIVE_OBSERVATION","VERIFIED_OUTCOME","PINNED_UPSTREAM","BASELINE_OR_SEED"
        })
        self.assertFalse(classes["BASELINE_OR_SEED"]["fresh_learning_credit"])
        self.assertFalse(classes["PINNED_UPSTREAM"]["fresh_learning_credit"])

    def test_checked_in_live_seed_is_context_only_even_if_populated(self):
        seeded=load_seed_state()
        seeded["sequence"]=1
        seeded["updated_at"]="2026-09-27T03:44:02Z"
        seeded["applied_source_keys"]=["value-outcome:MVOUT-SEED:sha256:"+"a"*64]
        seeded["observations"]=[observation()]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"LIVE_OBSERVATION_STATE_SEED.json"
            path.write_text(json.dumps(seeded))
            with patch("learning.continuous_learning.LIVE_OBSERVATION_SEED_PATH",path):
                with patch("learning.continuous_learning._checked_in_observations",return_value=[]):
                    rebuilt=rebuild_from_sources(path)
        self.assertEqual(rebuilt["source_mode"],"BASELINE_OR_SEED_ONLY")
        self.assertEqual(rebuilt["source_observation_count"],0)
        self.assertEqual(rebuilt["fresh_learning_observation_count"],0)
        self.assertEqual(rebuilt["baseline_or_seed_observation_count"],1)
        self.assertEqual(rebuilt["records"],[])
        self.assertFalse(
          rebuilt["provenance_freshness"]["BASELINE_OR_SEED"]["fresh_learning_credit"]
        )

    def test_durable_verified_outcome_receives_fresh_credit_separately(self):
        state=load_seed_state()
        state["sequence"]=1
        state["updated_at"]="2026-09-27T03:44:02Z"
        state["applied_source_keys"]=["value-outcome:MVOUT-PROVENANCE:sha256:"+"a"*64]
        state["observations"]=[observation()]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"learning.json"
            path.write_text(json.dumps(state))
            with patch("learning.continuous_learning._checked_in_observations",return_value=[observation()]):
                rebuilt=rebuild_from_sources(path)
        self.assertEqual(rebuilt["source_observation_count"],1)
        self.assertEqual(rebuilt["baseline_or_seed_observation_count"],1)
        self.assertEqual(len(rebuilt["records"]),1)
        self.assertEqual(rebuilt["provenance_freshness"]["VERIFIED_OUTCOME"]["observation_count"],1)

    def test_fresh_live_observation_is_not_mislabeled_verified_outcome(self):
        row=observation()
        row["observation_id"]="LRN-PROVENANCE-LIVE-0001"
        row["provenance_refs"]=["runtime:live-observation:fixture"]
        state=load_seed_state()
        state["sequence"]=1
        state["updated_at"]="2026-09-27T03:44:03Z"
        state["applied_source_keys"]=["runtime-live:fixture"]
        state["observations"]=[row]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"learning.json"
            path.write_text(json.dumps(state))
            rebuilt=rebuild_from_sources(path)
        classes=rebuilt["provenance_freshness"]
        self.assertEqual(rebuilt["fresh_learning_observation_count"],1)
        self.assertEqual(classes["LIVE_OBSERVATION"]["observation_count"],1)
        self.assertEqual(classes["VERIFIED_OUTCOME"]["observation_count"],0)
        self.assertTrue(classes["LIVE_OBSERVATION"]["fresh_learning_credit"])

    def test_static_baseline_cannot_hide_missing_live_learning_gap(self):
        empty=build_snapshot(learning_observation_count=0)
        live=build_snapshot(learning_observation_count=1)
        self.assertIn("UNC-LEARNING-PRJ-000",{x["uncertainty_id"] for x in empty["candidates"]})
        self.assertNotIn("UNC-LEARNING-PRJ-000",{x["uncertainty_id"] for x in live["candidates"]})

if __name__=="__main__":
    unittest.main()
