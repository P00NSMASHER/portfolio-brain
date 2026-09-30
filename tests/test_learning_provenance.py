import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning.continuous_learning import rebuild_from_sources


def obs(i, *, phase="TRAIN", provenance=None):
    return {
        "schema_version": "1.0.0",
        "observation_id": f"LRN-PROV-{i:08d}",
        "domain": "SEARCH",
        "learning_key": "action:provenance-test",
        "scope": "GLOBAL",
        "project_ids": ["PRJ-000"],
        "objective_id": "OBJ-000",
        "phase": phase,
        "measurement_quality": "PROSPECTIVE",
        "signal_class": "VERIFIED_TECHNICAL",
        "evidence_state": "VERIFIED",
        "reward_signal": 0.8,
        "sample_size": 4,
        "measured_numerator": None,
        "measured_denominator": None,
        "source_event_ids": [f"EVT-PROV-{i:08d}"],
        "evidence_ids": [f"EVD-PROV-{i:08d}"],
        "resource_usage": {
            "model_calls": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "compute_seconds": 1.0,
            "tool_calls": 1,
        },
        "observed_at": f"2026-09-{20 + (i % 5):02d}T12:00:00Z",
        "provenance_refs": provenance or [f"baseline:{i}"],
    }


class LearningProvenanceTests(unittest.TestCase):
    def test_static_baseline_cannot_masquerade_as_fresh_learning(self):
        static = [obs(i) for i in range(1, 6)]
        static += [obs(10, phase="CONFIRM"), obs(11, phase="CONFIRM")]
        with patch("learning.continuous_learning._checked_in_observations", return_value=static):
            state = rebuild_from_sources(None)
        self.assertEqual(state["source_mode"], "BASELINE_CONTEXT_ONLY")
        self.assertEqual(state["fresh_learning_observation_count"], 0)
        self.assertEqual(state["baseline_context_observation_count"], 7)
        self.assertEqual(state["eligible_record_count"], 0)
        self.assertEqual(state["records"], [])
        self.assertFalse(state["baseline_context"]["fresh_learning_credit"])
        self.assertEqual(state["provenance_counts"]["BASELINE_OR_SEED"], 7)

    def test_pinned_upstream_is_context_not_fresh_learning(self):
        static = [obs(1, provenance=["pinned-upstream:value-memory:abc"])]
        with patch("learning.continuous_learning._checked_in_observations", return_value=static):
            state = rebuild_from_sources(None)
        self.assertEqual(state["provenance_counts"]["PINNED_UPSTREAM"], 1)
        self.assertEqual(state["fresh_learning_observation_count"], 0)
        pinned = [x for x in state["context_sources"] if x["provenance_class"] == "PINNED_UPSTREAM"]
        self.assertTrue(pinned)
        self.assertTrue(all(x["fresh_learning_credit"] is False for x in pinned))

    def test_verified_live_outcome_is_fresh_and_classified(self):
        live_obs = obs(20, provenance=["value-outcome:sha256:" + "a" * 64])
        live_state = {
            "schema_version": "1.0.0",
            "state_id": "portfolio-learning-observation-state",
            "sequence": 1,
            "updated_at": "2026-09-30T14:00:00Z",
            "applied_source_keys": ["value-outcome:MVOUT-PROV:sha256:" + "a" * 64],
            "observations": [live_obs],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "learning.json"
            path.write_text(json.dumps(live_state), encoding="utf-8")
            with patch("learning.continuous_learning._checked_in_observations", return_value=[]):
                state = rebuild_from_sources(path)
        self.assertEqual(state["source_mode"], "LIVE_WITH_BASELINE_CONTEXT")
        self.assertEqual(state["provenance_counts"]["VERIFIED_OUTCOME"], 1)
        self.assertEqual(state["fresh_learning_observation_count"], 1)
        self.assertEqual(state["records"][0]["fresh_learning_observation_count"], 1)
        self.assertTrue(state["records"][0]["fresh_learning_credit"])


if __name__ == "__main__":
    unittest.main()
